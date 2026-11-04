"""TASK-893: the release zips' one game bundle (tools/build_release.py bundle_scripts).

Builds the four zips of REV (default HEAD) and of BEFORE (a revision before
the bundle, default the parent of the commit that added it) into a temp dir,
then:

- zips: per zip the <script> tags of index.html (exactly one local game
  bundle, plus the portal SDK and the vendored GameAnalytics SDK where the
  portal has them), the bundle bytes raw and gzipped, the zip bytes before
  and after, file counts;
- switches: in every zip ?visualsPerf=1 defines window.visualsPerf (and its
  canvas creators map back to source files, not game-*.js), without the flag
  it stays undefined; ?off=ui replaces drawUILayer with the empty function;
- globals: every top-level name the bundled source files declare has the
  same typeof (and a function the same .name) in the zip as in the same
  portal's unbundled build (runtime_files(bundle=False)) booted the same way;
- climb: a scripted climb of CLIMB_S seconds per zip (default 60): real
  grapple presses alternating up-left / up-right for 3/4 of the time, then a
  camera flight along every route transfer for the rest, so every region of
  the level is drawn; page errors and ReferenceErrors (page or console) are
  recorded and must be empty. After the climb, on the same page (ui_flow,
  TASK-894): the pause menu (Escape, or P on Playgama) and Resume, the
  go-back dialog (Keep falling by ArrowRight+Enter, Go back by
  ArrowLeft+Enter), a death (onLethalDeath) and the death screen's Restart,
  and Pause > Restart climb > Yes; each step's state is checked;
- modes (TASK-894): every zip's BUILD_CONFIG.modes is build_release.MODES;
  the single-mode zips' bundle has other-mode-stubs.js and none of
  build_release.OTHER_MODE_SCRIPTS, Playgama's has all of them and no stub.

    python3 tools/test_release_bundle.py --out-dir DIR [--rev REV] [--before REV] [--climb-s 60]
writes DIR/zips.json, switches.json, globals.json, climb-errors.json and
bundle-report.json (all checks). With no arguments (unittest) it runs every
check with a 10 s climb on the itch and playgama zips.
"""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
import unittest
import zipfile

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import build_release  # noqa: E402
from browser_test_support import start_browser_test, wait_for_boot_run  # noqa: E402
from test_build_release import y8_env  # noqa: E402

ROOT = TOOLS.parent
PORTALS = build_release.PORTALS
VIEWPORT = {'width': 1366, 'height': 768}
DECLARATION = re.compile(r'^(?:async\s+)?(?:function\*?|let|const|var|class)\s+([A-Za-z_$][\w$]*)', re.M)
EXTERNAL = re.compile(r'^(https?:)?//')

GLOBALS_JS = r'''names => Object.fromEntries(names.map(name => {
    try {
        const t = (0, eval)('typeof ' + name)
        const fname = t === 'function' ? (0, eval)(name).name : null
        return [name, [t, fname]]
    } catch (e) { return [name, ['throws ' + e.name, null]] }
}))'''

FLIGHT_JS = r'''seconds => {
    const transfers = floors[0].level.svgFormat.transfers.filter(t => t.guide)
    const points = transfers.map(t => [(t.guide[0][0] + t.guide[3][0]) / 2, (t.guide[0][1] + t.guide[3][1]) / 2])
    const halfW = width / scale[version] / 2, halfH = height / scale[version] / 2
    const path = [[halfW - screen.x, halfH - screen.y], ...points]
    const lengths = [0]
    for (let i = 1; i < path.length; ++i)
        lengths.push(lengths[i - 1] + Math.hypot(path[i][0] - path[i - 1][0], path[i][1] - path[i - 1][1]))
    const total = lengths[lengths.length - 1], t0 = performance.now()
    const flight = window.__flight = {frames: 0, done: false, transfers: transfers.length}
    const original = window.draw
    window.draw = function()
    {
        const f = Math.min(1, (performance.now() - t0) / (seconds * 1000))
        const at = f * total
        let i = 1
        while (i < path.length - 1 && lengths[i] < at) ++i
        const a = path[i - 1], b = path[i], seg = lengths[i] - lengths[i - 1] || 1
        const k = Math.min(1, Math.max(0, (at - lengths[i - 1]) / seg))
        const sx = screen.x, sy = screen.y
        screen.x = halfW - (a[0] + (b[0] - a[0]) * k)
        screen.y = halfH - (a[1] + (b[1] - a[1]) * k)
        ++flight.frames
        flight.done = f >= 1
        try { return original() }
        finally { screen.x = sx; screen.y = sy }
    }
    return {transfers: transfers.length, pathLength: total}
}'''


def zip_files(path):
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n) for n in z.namelist() if not n.endswith('/')}


def script_tags(html):
    """[(src or '<inline>', async)] of index.html's <script> elements in order."""
    tags = []
    for m in build_release.SCRIPT_ELEMENT.finditer(html):
        src = build_release.SCRIPT_SRC.search(m.group(1))
        tags.append([src.group(2).strip() if src else '<inline>', bool(re.search(r'\basync\b', m.group(1)))])
    return tags


def gzip_size(data):
    import gzip
    return len(gzip.compress(data, 9, mtime=0))


def build_all(tree, out, env):
    for portal in PORTALS:
        build_release.build(portal, out, env=env, tree=tree)
    return {p: out / p / f'grapple-over-{p}.zip' for p in PORTALS}


def zips_report(after, before, drops=False):
    """drops: REV leaves OTHER_MODE_SCRIPTS out of the single-mode zips (TASK-894)."""
    report = {}
    for portal in PORTALS:
        a, b = zip_files(after[portal]), zip_files(before[portal])
        bundle = build_release.bundle_path(a)
        tags = script_tags(a['index.html'].decode('utf-8'))
        local = [s for s, _ in tags if s != '<inline>' and not EXTERNAL.match(s)]
        game = [s for s in local if s != build_release.GA_SDK]
        sdk = [s for s, _ in tags if EXTERNAL.match(s)]
        before_scripts = [s for s, _ in script_tags(b['index.html'].decode('utf-8'))
                          if s != '<inline>' and not EXTERNAL.match(s)]
        before_js = sum(len(b[s]) for s in before_scripts)
        expected_sdk = [build_release.SDK_TAGS[portal]] if build_release.SDK_TAGS[portal] else []
        parts = [row['path'] for row in build_release.bundle_table(a[bundle])]
        config = build_release.bundle_part(a, 'buildconfig.js').decode('utf-8')
        modes = re.findall(r"'([a-z_]+)'", re.search(r'^const BUILD_CONFIG = .*modes: \[([^\]]*)\]', config, re.M).group(1))
        single = build_release.MODES[portal] == ['grapple_over']
        dropped = [p for p in build_release.OTHER_MODE_SCRIPTS if p not in parts]
        checks = {
            'modes': modes == build_release.MODES[portal],
            'other_mode_scripts': (dropped == list(build_release.OTHER_MODE_SCRIPTS)
                                   and build_release.OTHER_MODE_STUBS in parts) if single and drops
                                  else (not dropped and build_release.OTHER_MODE_STUBS not in parts),
            'one_game_bundle_script': game == [bundle] and bool(bundle),
            'sdk_tags_kept': sdk == [re.search(r'src="([^"]+)"', t).group(1) for t in expected_sdk],
            'vendor_tag': (build_release.GA_SDK in local) == (portal in build_release.GA_PORTALS),
            'no_separate_game_scripts': not [p for p in a if p.endswith('.js') and p not in
                                             (bundle, 'leveldata.js', build_release.GA_SDK)],
        }
        report[portal] = {
            'modes': modes, 'dropped_scripts': dropped,
            'stub_bytes': len(build_release.bundle_part(a, build_release.OTHER_MODE_STUBS))
                          if build_release.OTHER_MODE_STUBS in parts else 0,
            'script_tags': tags,
            'game_scripts': game,
            'bundle': bundle,
            'bundle_parts': len(build_release.bundle_table(a[bundle])),
            'bundle_bytes': len(a[bundle]),
            'bundle_gzip_bytes': gzip_size(a[bundle]),
            'before_script_tags_local': len(before_scripts),
            'before_scripts_bytes': before_js,
            'before_scripts_gzip_bytes_sum': sum(gzip_size(b[s]) for s in before_scripts),
            'zip_bytes_before': after_size(before[portal]),
            'zip_bytes_after': after_size(after[portal]),
            'files_before': len(b), 'files_after': len(a),
            'checks': checks, 'pass': all(checks.values()),
        }
    return report


def after_size(path):
    return Path(path).stat().st_size


class Booter:
    """One browser; boots extracted zips (or unbundled sites) served over http, external requests blocked."""
    def __init__(self, stack):
        self.stack = stack
        self.base = Path(tempfile.mkdtemp(prefix='release-bundle-'))
        stack.callback(shutil.rmtree, self.base, True)
        self.url, self.browser = start_browser_test(self.base, stack.callback)

    def site(self, name, files):
        site = self.base / name
        for path, data in files.items():
            (site / path).parent.mkdir(parents=True, exist_ok=True)
            (site / path).write_bytes(data)
        return self.url + name + '/'

    def open(self, url, query=''):
        context = self.browser.new_context(viewport=VIEWPORT, locale='en-US')
        context.route('**/' + build_release.GA_SDK, lambda r: r.fulfill(
            content_type='application/javascript', body='// GameAnalytics stub\n'))
        page = context.new_page()
        errors = {'page': [], 'console': []}
        page.on('pageerror', lambda e: errors['page'].append(str(e)))
        page.on('console', lambda m: m.type == 'error' and errors['console'].append(m.text))
        page.goto(url + 'index.html' + query)
        wait_for_boot_run(page)
        return context, page, errors


def reference_errors(errors):
    return [e for e in errors['page'] + errors['console'] if 'ReferenceError' in e or 'is not defined' in e]


def switches(booter, url):
    out = {}
    context, page, errors = booter.open(url, '?visualsPerf=1')
    page.wait_for_timeout(500)
    out['visualsPerf'] = page.evaluate('''() => {
        const vp = window.visualsPerf
        if (!vp) return {defined: false}
        vp.start({meta: 'TASK-893'})
        return new Promise(resolve => setTimeout(() => {
            const r = vp.stop()
            const creators = Object.keys((r && r.canvasSnapshot && r.canvasSnapshot.liveCanvasByCreator) || {})
            resolve({defined: true, type: typeof vp, methods: Object.keys(vp).filter(k => typeof vp[k] === 'function').sort(),
                     panel: !!document.getElementById('visuals-perf-controls'), samples: r ? r.samples.length : null,
                     buildIdMethod: r && r.buildIdMethod, creators: creators.sort(),
                     bundleCreators: creators.filter(c => /game-[0-9a-f]+\.js/.test(c))})
        }, 1500))
    }''')
    out['visualsPerf']['page_errors'] = errors['page']
    context.close()
    context, page, errors = booter.open(url)
    out['visualsPerf_without_flag'] = page.evaluate('() => typeof window.visualsPerf')
    out['ui_layer_default'] = page.evaluate("() => drawUILayer.toString().replace(/\\s/g, '') !== 'function(){}'")
    context.close()
    context, page, errors = booter.open(url, '?off=ui')
    page.wait_for_timeout(300)
    out['off_ui'] = page.evaluate("""() => ({noop: drawUILayer.toString().replace(/\\s/g, '') === 'function(){}',
        sameAsWindow: drawUILayer === window.drawUILayer, otherLayerKept: drawWorldLayer.toString().length > 20})""")
    out['off_ui']['page_errors'] = errors['page']
    context.close()
    v, o = out['visualsPerf'], out['off_ui']
    out['checks'] = {
        'visualsPerf_defined': v.get('defined') is True and v.get('type') == 'object',
        'visualsPerf_panel': v.get('panel') is True,
        'visualsPerf_records': (v.get('samples') or 0) > 0,
        'visualsPerf_creators_mapped': bool(v.get('creators')) and not v.get('bundleCreators'),
        'visualsPerf_undefined_without_flag': out['visualsPerf_without_flag'] == 'undefined',
        'ui_layer_drawn_by_default': out['ui_layer_default'] is True,
        'off_ui_disables_ui_layer': o['noop'] and o['sameAsWindow'] and o['otherLayerKept'],
        'no_page_errors': not v['page_errors'] and not o['page_errors'],
    }
    out['pass'] = all(out['checks'].values())
    return out


def globals_compare(booter, bundled_url, plain_url, names):
    seen = {}
    for label, url in (('unbundled', plain_url), ('bundle', bundled_url)):
        context, page, errors = booter.open(url)
        seen[label] = page.evaluate(GLOBALS_JS, names)
        seen[label + '_page_errors'] = errors['page']
        context.close()
    diff = {n: [seen['unbundled'][n], seen['bundle'][n]] for n in names if seen['unbundled'][n] != seen['bundle'][n]}
    return {'names': len(names), 'defined_in_bundle': sum(1 for n in names if seen['bundle'][n][0] != 'undefined'),
            'functions': sum(1 for n in names if seen['bundle'][n][0] == 'function'),
            'differences': diff, 'page_errors': {'unbundled': seen['unbundled_page_errors'], 'bundle': seen['bundle_page_errors']},
            'pass': not diff and not seen['bundle_page_errors']}


# Presses the CLIMB_UI button labelled I18N.t(key) (as a click on it would); returns its label or null
PRESS_JS = r'''key => {
    redrawOverlays()
    const label = I18N.t(key)
    const button = CLIMB_UI.buttons.find(b => b.text && b.text.text === label)
    if (!button) return null
    button.click()
    return label
}'''
UI_STATE_JS = r'''() => ({paused: menu.gamePaused, confirming: CLIMB_UI.confirming, goingBack: CLIMB_UI.goingBack,
    offerVisible: continueOffer.visible, runInProgress, version, ninjaY: ninja.y,
    deaths: window.__deaths || 0})'''


def ui_flow(page):
    """TASK-894: pause menu, go-back dialog, a death and the restarts, after the climb (same page)."""
    page.evaluate('''() => { const real = window.onLethalDeath
        window.onLethalDeath = function() { window.__deaths = (window.__deaths || 0) + 1; return real.apply(this, arguments) } }''')
    steps = {}
    def step(name, wait=400):
        page.wait_for_timeout(wait)
        steps[name] = page.evaluate(UI_STATE_JS)
    # Pause menu (Escape; P where Escape is the browser's), then Resume
    page.keyboard.press('Escape' if page.evaluate('buildUsesEscape()') else 'p')
    step('pause_open')
    steps['pause_open']['resume'] = page.evaluate(PRESS_JS, 'pause.resume')
    step('pause_resumed')
    # Go-back dialog: offered as after a long fall, Keep falling by keys, offered again, Go back by Enter
    page.evaluate('() => CLIMB_UI.offerGoBack()')
    step('goback_open')
    page.keyboard.press('ArrowRight')
    page.keyboard.press('Enter')
    step('goback_keep_falling')
    page.evaluate('() => CLIMB_UI.offerGoBack()')
    page.keyboard.press('ArrowLeft')
    page.keyboard.press('Enter')
    step('goback_back', 1500)
    # A death (the lethal path every mode shares), then the death screen's Restart
    page.evaluate('() => onLethalDeath()')
    step('death', 1000)
    page.evaluate('() => { if (!continueOffer.visible) continueOffer.show() }')
    step('offer_open')
    page.evaluate('() => restartFromOffer()')
    step('offer_restarted', 2000)
    # Pause > Restart climb > Yes
    page.keyboard.press('Escape' if page.evaluate('buildUsesEscape()') else 'p')
    steps['restart_confirm'] = {'restart': page.evaluate(PRESS_JS, 'climb.restart'),
                                'confirming': page.evaluate('CLIMB_UI.confirming')}
    steps['restart_confirm']['yes'] = page.evaluate(PRESS_JS, 'climb.yes')
    step('restart_done', 2000)
    s = steps
    checks = {
        'pause_opens': s['pause_open']['paused'] is True and s['pause_open']['resume'] is not None,
        'pause_resumes': s['pause_resumed']['paused'] is False,
        'goback_opens': s['goback_open']['goingBack'] is True and s['goback_open']['paused'] is True,
        'goback_keep_falling': s['goback_keep_falling']['goingBack'] is False and s['goback_keep_falling']['paused'] is False,
        'goback_back': s['goback_back']['goingBack'] is False and s['goback_back']['paused'] is False,
        'death_counted': s['death']['deaths'] >= 1,
        'offer_restart': s['offer_open']['offerVisible'] is True and s['offer_restarted']['offerVisible'] is False
                         and s['offer_restarted']['runInProgress'] is True,
        'restart_climb': s['restart_confirm']['restart'] is not None and s['restart_confirm']['confirming'] is True
                         and s['restart_confirm']['yes'] is not None and s['restart_done']['paused'] is False
                         and s['restart_done']['runInProgress'] is True,
        'still_grapple_over': all(v.get('version', 'grapple_over') == 'grapple_over' for v in s.values()),
    }
    return {'steps': steps, 'checks': checks, 'pass': all(checks.values())}


def climb(booter, url, seconds, ui=True):
    context, page, errors = booter.open(url)
    box = page.locator('#canvas').bounding_box()
    play_s = seconds * 0.75
    t0 = time.monotonic()
    presses, top = 0, None
    start_y = page.evaluate('() => ninja.y')
    while time.monotonic() - t0 < play_s:
        x = box['x'] + box['width'] * (0.68 if presses % 2 == 0 else 0.32)
        page.mouse.move(x, box['y'] + box['height'] * 0.22)
        page.mouse.down()
        page.wait_for_timeout(650)
        page.mouse.up()
        page.wait_for_timeout(250)
        presses += 1
        y = page.evaluate('() => ninja.y')
        top = y if top is None else min(top, y)
    flight_s = max(1.0, seconds - (time.monotonic() - t0))
    setup = page.evaluate(FLIGHT_JS, flight_s)
    page.wait_for_function('() => window.__flight.done', timeout=int(flight_s * 1000) + 60000)
    page.wait_for_timeout(300)
    state = page.evaluate('() => ({version, runInProgress, flightFrames: window.__flight.frames})')
    elapsed = time.monotonic() - t0
    flow = ui_flow(page) if ui else None
    context.close()
    return {'seconds': round(elapsed, 1), 'presses': presses, 'ninja_start_y': start_y, 'ninja_min_y': top,
            'flight': dict(setup, frames=state['flightFrames'], seconds=round(flight_s, 1)),
            'state_after': {'version': state['version'], 'runInProgress': state['runInProgress']},
            'ui_flow': flow,
            'page_errors': errors['page'], 'reference_errors': reference_errors(errors),
            'console_errors': errors['console']}


def run(out_dir=None, rev='HEAD', before=None, climb_s=60.0, portals=PORTALS):
    env = y8_env()
    if not all(env.values()):
        raise SystemExit('Y8_APP_ID / Y8_GAME_ID / GA_GAME_KEY / GA_SECRET_KEY unavailable')
    tree = build_release.CommittedTree(rev)
    if not build_release.bundles_scripts(tree):
        raise SystemExit(f'{rev} does not bundle (render/visualsperf.js has no GAME_BUNDLE_FILES)')
    before_tree = build_release.CommittedTree(before or default_before(tree))
    report = {'revision': tree.revision, 'build_id': tree.build_id(), 'before_revision': before_tree.revision,
              'viewport': VIEWPORT, 'climb_s': climb_s}
    with ExitStack() as stack:
        tmp = Path(tempfile.mkdtemp(prefix='release-bundle-zips-'))
        stack.callback(shutil.rmtree, tmp, True)
        after = build_all(tree, tmp / 'after', env)
        before_zips = build_all(before_tree, tmp / 'before', env)
        report['zips'] = zips_report(after, before_zips, build_release.drops_other_modes(tree, 'itch'))
        booter = Booter(stack)
        report['switches'], report['globals'], report['climb'] = {}, {}, {}
        for portal in portals:
            files = zip_files(after[portal])
            url = booter.site(portal, files)
            plain = build_release.runtime_files(tree, portal, build_release.y8_ids_for(portal, env),
                                                build_release.ga_keys_for(portal, env), bundle=False)
            plain_url = booter.site(portal + '-unbundled', plain)
            names = sorted({n for path in build_release.bundle_table(files[build_release.bundle_path(files)])
                            if not path['path'].startswith('index.html#')
                            for n in DECLARATION.findall(plain[path['path']].decode('utf-8'))})
            report['switches'][portal] = switches(booter, url)
            report['globals'][portal] = globals_compare(booter, url, plain_url, names)
            report['climb'][portal] = climb(booter, url, climb_s)
            print(f"{portal}: zips {report['zips'][portal]['pass']} switches {report['switches'][portal]['pass']} "
                  f"globals {report['globals'][portal]['pass']} climb errors "
                  f"{len(report['climb'][portal]['page_errors'])}/{len(report['climb'][portal]['reference_errors'])}",
                  flush=True)
    climb_errors = {p: {'page_errors': c['page_errors'], 'reference_errors': c['reference_errors'],
                        'console_errors': c['console_errors'], 'ui_flow': c['ui_flow']['checks'],
                        'modes': build_release.MODES[p]}
                    for p, c in report['climb'].items()}
    report['checks'] = {
        'zips': all(z['pass'] for z in report['zips'].values()),
        'switches': all(s['pass'] for s in report['switches'].values()),
        'globals': all(g['pass'] for g in report['globals'].values()),
        'climb_no_errors': all(not v['page_errors'] and not v['reference_errors'] for v in climb_errors.values()),
        'ui_flow': all(c['ui_flow']['pass'] for c in report['climb'].values()),
        'climb_ran': all(c['seconds'] >= climb_s * 0.95 and c['presses'] > 0 and c['flight']['frames'] > 0
                         and c['state_after']['runInProgress'] for c in report['climb'].values()),
        'all_portals': sorted(report['climb']) == sorted(portals),
    }
    report['pass'] = all(report['checks'].values())
    if out_dir:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        meta = {'revision': tree.revision, 'build_id': tree.build_id()}
        write(out / 'zips.json', dict(meta, before_revision=before_tree.revision, zips=report['zips'],
                                      pass_=report['checks']['zips']))
        write(out / 'switches.json', dict(meta, switches=report['switches'], pass_=report['checks']['switches']))
        write(out / 'globals.json', dict(meta, globals=report['globals'], pass_=report['checks']['globals']))
        write(out / 'climb-errors.json', dict(meta, climb_s=climb_s, errors=climb_errors,
                                              pass_=report['checks']['climb_no_errors'] and report['checks']['ui_flow']))
        write(out / 'bundle-report.json', report)
    return report


def write(path, data):
    if 'pass_' in data:
        data['pass'] = data.pop('pass_')
    path.write_text(json.dumps(data, indent=1) + '\n')


def default_before(tree):
    """The newest ancestor of tree whose build does not bundle yet."""
    rev = tree.revision
    for _ in range(50):
        rev = build_release.git('rev-parse', rev + '^').decode().strip()
        if not build_release.bundles_scripts(build_release.CommittedTree(rev)):
            return rev
    raise SystemExit('no pre-bundle ancestor in the last 50 commits')


class ReleaseBundleTest(unittest.TestCase):
    def test_bundle_switches_globals_climb(self):
        report = run(rev=os.environ.get('BUILD_RELEASE_REV', 'HEAD'), climb_s=10.0, portals=('itch', 'playgama'))
        self.assertTrue(report['pass'], json.dumps({'checks': report['checks'],
                                                    'climb': report['climb'], 'globals': {
                                                        p: g['differences'] for p, g in report['globals'].items()}})[:4000])


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--out-dir', required=True)
    parser.add_argument('--rev', default='HEAD')
    parser.add_argument('--before')
    parser.add_argument('--climb-s', type=float, default=60.0)
    parser.add_argument('--portals', default=','.join(PORTALS))
    args = parser.parse_args(argv)
    report = run(args.out_dir, args.rev, args.before, args.climb_s, tuple(args.portals.split(',')))
    print(json.dumps(report['checks']))
    print('PASS' if report['pass'] else 'FAIL')
    return 0 if report['pass'] else 1


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] not in ('-v', '--verbose'):
        sys.exit(main(sys.argv[1:]))
    unittest.main()
