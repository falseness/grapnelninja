"""TASK-500 delivery audit of Grapple Over: TASK-444..499 evidence, the final runtime and fresh full-completion proof.

Task500Tests reads the archived evidence of every prerequisite, re-plays the archived desktop (TASK-496) and touch (TASK-497)
completion routes on the final runtime, re-runs the replay auditor on the regenerated manifests, decodes the clips and stills,
and writes audit.json / delivery.json. All evidence goes under GRAPPLE_OVER_EVIDENCE_DIR (default artifacts/TASK-500).
"""
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from browser_test_support import start_browser_test, wait_for_boot
from grapple_over_test_support import ROOT, VIEWPORT, EvidenceWriter, source_hashes
from grapple_over_support import state_hash
import test_grapple_over_completion as completion
import test_grapple_over_integration as integration

ART = ROOT / 'artifacts'
PREREQUISITES = range(444, 500)
# TASK-498 re-ran every Task444..497 class (PASS or SUPERSEDED with its recorded signature) on the runtime it committed.
REGRESSION_TASK = 498
REGRESSION_COMMIT = '419e0ba'
FIRST_SCOPE_COMMIT = '9de4a6c'  # TASK-444
# Files whose hashes differ between the archived TASK-496/497 completion manifests and the final tree. render/roledetail.js
# (TASK-498 guard for elements without local points; display only) and tools/perf_mobile.py (TASK-499 test tooling; the
# SEED_SCRIPT the replays use is unchanged). The completions are regenerated here regardless.
COMPLETION_HASH_DRIFT = {'render/roledetail.js', 'tools/perf_mobile.py'}
COMPLETIONS = {'desktop': dict(task=496, manifest='manifest.json', stills='filmstrip', video='completion.webm'),
               'touch': dict(task=497, manifest='touch-manifest.json', stills='touch-frames', video='touch-completion.webm')}
DELIVERY_JS = '''() => { const m = GRAPPLE_OVER_MOUNTAIN, d = MODE_DEFINITIONS.grapple_over;
    let validation = 'ok'; try { validateMountainManifest(m) } catch (e) { validation = String(e.message) }
    const keys = []; const walk = (v, p) => { if (!v || typeof v !== 'object') return;
        for (const [k, x] of Object.entries(v)) { if (/checkpoint|respawn|highestProgress/i.test(k)) keys.push(p + '.' + k); walk(x, p + '.' + k) } };
    walk(m, 'mountain');
    const roles = {}; for (const e of m.geometry.elements) roles[e.role] = (roles[e.role] || 0) + 1;
    return {sections: m.sections.map(s => ({id: s.id, status: s.status, designVersion: s.designVersion,
            landmark: s.landmark ? {id: s.landmark.id, name: s.landmark.name} : null})),
        encounters: m.encounters.map(e => ({id: e.id, section: e.section})),
        shortcuts: m.shortcuts.map(s => ({id: s.id, from: s.from, to: s.to, status: s.status, optional: s.optional})),
        recoveries: m.recoveries.map(r => ({id: r.id, from: r.from, to: r.to, status: r.status})),
        roles, movers: m.geometry.movers.length, range: m.range, validation, checkpoint_keys: keys,
        definition: {cameraScale: d.cameraScale, acquisitionRadius: d.acquisitionRadius,
            upgradedAcquisitionRadius: d.upgradedAcquisitionRadius, rangeUpgradeSection: d.rangeUpgradeSection},
        old_modes: {classic: MODE_DEFINITIONS.classic.cameraScale, bad: MODE_DEFINITIONS.bad.cameraScale},
        difficulty: m.difficulty, recoveryPolicy: m.recoveryPolicy, completion: m.completion, finish: m.finish,
        boot: {mode: version, run: runInProgress, paused: !!menu.gamePaused}} }'''


def sha(data):
    return hashlib.sha256(data).hexdigest()


def tested_hashes():
    from grapple_over_verify import hashes
    result = hashes()
    for name in ('test_grapple_over_completion.py', 'test_grapple_over_integration.py', 'test_grapple_over_audit.py',
                 'test_grapple_over_regression.py'):
        result['tools/' + name] = sha((ROOT / 'tools' / name).read_bytes())
    return dict(sorted(result.items()))


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True)


def task_statuses():
    statuses = {}
    for path in (ART / 'old_tasks_do_not_touch' / 'tasks.json', ART / 'tasks.json'):
        for t in json.loads(path.read_text()):
            statuses[t['id']] = (t['status'], str(path.relative_to(ROOT)))
    return statuses


def unittest_result(text):
    """(tests ran, final status line) of the last unittest summary in a log."""
    ran = re.findall(r'^Ran (\d+) tests? in ([0-9.]+)s$', text, re.M)
    status = re.findall(r'^(OK(?: \(.*\))?|FAILED \(.*\))$', text, re.M)
    return (int(ran[-1][0]) if ran else 0, status[-1] if status else None)


def sub_evidence(name):
    evidence = EvidenceWriter('TASK-500')
    evidence.root = evidence.root / name
    evidence.root.mkdir(parents=True, exist_ok=True)
    return evidence


def image_stats(path):
    from PIL import Image, ImageStat
    with Image.open(path) as img:
        img.load()
        rgb = img.convert('RGB')
        stat = ImageStat.Stat(rgb)
        return dict(size=list(rgb.size), mean=[round(v, 2) for v in stat.mean], stddev=round(max(stat.stddev), 2))


def image_difference(a, b):
    from PIL import Image, ImageChops, ImageStat
    with Image.open(a) as x, Image.open(b) as y:
        diff = ImageChops.difference(x.convert('RGB'), y.convert('RGB'))
        return dict(max=max(hi for _, hi in diff.getextrema()), mean=round(max(ImageStat.Stat(diff).mean), 4))


class Task500Tests(unittest.TestCase):
    """Final Grapple Over delivery audit (TASK-444..499 plus this ticket)."""
    task_id = 'TASK-500'

    @classmethod
    def setUpClass(cls):
        import test_grapple_over_sections as sections
        cls.S = sections
        cls.evidence = EvidenceWriter(cls.task_id)
        cls.url, browser = start_browser_test(ROOT, cls.addClassCleanup)
        cls.chromium = browser
        cls.browser = completion.EvidenceBrowser(browser)
        page = browser.new_page(viewport=VIEWPORT); page.goto(cls.url); wait_for_boot(page)
        cls.mountain = page.evaluate(completion.MOUNTAIN_JS)
        page.close()
        cls.hashes = tested_hashes()
        cls.revision = git('rev-parse', 'HEAD').strip()
        cls.dirty = git('status', '--porcelain', '--', '.', ':!artifacts').splitlines()
        cls.config = dict(browser=browser.version, browser_name='chromium (Playwright, headless)', desktop_viewport=VIEWPORT,
                          touch_viewport=completion.TOUCH_VIEWPORT, device_scale_factor=1, hz=60, seed=1, revision=cls.revision,
                          dirty_paths=cls.dirty, source_hashes=cls.hashes)
        cls.evidence.log('CONFIG ' + json.dumps(cls.config, sort_keys=True, separators=(',', ':')))

    def helper(self, base, sub, **attrs):
        """A Task496Tests/Task497Tests instance on the final runtime whose evidence goes to TASK-500/<sub>."""
        proof = dict(browser=self.chromium.version, browser_name='chromium (Playwright, headless)', hz=60, seed=1,
                     revision=self.revision, dirty_paths=self.dirty, source_hashes=self.hashes,
                     level_sha256=self.hashes['fixedlevel.js'], mountain_sha256=self.hashes['mountain.js'],
                     regenerated_by='TASK-500 Task500Tests on the final runtime', archived_route='TASK-%d' % COMPLETIONS[sub]['task'])
        cls = type(base.__name__ + 'Final', (base,), dict(S=self.S, evidence=sub_evidence(sub), url=self.url, browser=self.browser,
                                                          mountain=self.mountain, hashes=self.hashes, proof=proof, **attrs))
        return cls(next(n for n in dir(cls) if n.endswith('_source_hashes')))

    def archived(self, sub):
        """The archived completion manifest and its recorded trace (sha256-checked), read in place."""
        c = COMPLETIONS[sub]
        root = ART / ('TASK-%d' % c['task'])
        manifest = json.loads((root / c['manifest']).read_text())
        raw = gzip.decompress((root / manifest['trace_file']['name']).read_bytes())
        self.assertEqual(sha(raw), manifest['trace_file']['sha256'], 'archived trace corrupt')
        return manifest, raw

    def compare_manifest(self, sub, fresh):
        archived, raw = self.archived(sub)
        for key in ('ticks', 'inputs', 'expected_exit', 'required_events'):
            self.assertEqual(fresh[key], archived[key], key)
        old, new = archived['metadata'], fresh['metadata']
        self.assertEqual({k: v for k, v in old.items() if k not in ('source_hashes', 'level_sha256')},
                         {k: v for k, v in new.items() if k not in ('source_hashes', 'level_sha256')})
        drift = sorted(k for k in set(old['source_hashes']) | set(new['source_hashes'])
                       if old['source_hashes'].get(k) != new['source_hashes'].get(k))
        self.assertEqual(set(drift), COMPLETION_HASH_DRIFT)
        self.assertEqual(old['level_sha256'], new['level_sha256'])
        return archived, raw, drift

    def compare_stills(self, sub, names):
        c = COMPLETIONS[sub]
        old_dir = ART / ('TASK-%d' % c['task']) / c['stills']
        new_dir = self.evidence.path(sub + '/' + c['stills'] + '/.keep').parent
        old = sorted(p.name for p in old_dir.glob('*.jpg')); new = sorted(p.name for p in new_dir.glob('*.jpg'))
        self.assertEqual(new, old)
        self.assertEqual(sorted(names), new)
        rows = []
        for name in new:
            stats = image_stats(new_dir / name)
            self.assertGreater(stats['stddev'], 5, name)  # a decoded, non-blank render
            rows.append(dict(name=name, **stats, vs_archived=image_difference(old_dir / name, new_dir / name)))
        worst = max(r['vs_archived']['mean'] for r in rows)
        # Same production render of an identical state: the ambient motes/embers animate on the wall clock (they are not
        # simulation state), so a few hundred small particle pixels move between runs; geometry, HUD and player match.
        self.assertLess(worst, 5.0)
        return dict(stills=len(rows), archived_dir=str(old_dir.relative_to(ROOT)), max_mean_abs_difference=worst,
                    max_pixel_difference=max(r['vs_archived']['max'] for r in rows), rows=rows)

    # ---- cases ----------------------------------------------------------------------------------
    def test_01_prerequisites(self):
        """Every TASK-444..499 is done, has a non-empty passing tests.log without skips, parseable top-level evidence, and was
        re-run (or superseded with its recorded signature) on a runtime identical to the final one."""
        statuses = task_statuses()
        regression = json.loads((ART / 'TASK-498' / 'regression.json').read_text())
        logged = [l for l in (ART / 'TASK-498' / 'commands.log').read_text().splitlines() if l.startswith('SOURCE_HASHES ')]
        regression_hashes = json.loads(logged[-1].split(' ', 1)[1])
        runtime = sorted(source_hashes())
        current = source_hashes()
        changed_since = git('diff', '--name-only', REGRESSION_COMMIT, 'HEAD').split()
        runtime_changed = sorted(set(changed_since) & {n for n in runtime if not n.startswith('tools/')})
        self.assertEqual(runtime_changed, [])
        stale_runtime = sorted(n for n in runtime if not n.startswith('tools/') and regression_hashes.get(n) != current[n])
        self.assertEqual(stale_runtime, [])
        perf = json.loads((ART / 'TASK-499' / 'perf' / 'summary.json').read_text())
        perf_stale = sorted(k for k, v in perf['source_hashes'].items() if sha((ROOT / k).read_bytes()) != v)
        self.assertEqual(perf_stale, [])
        rows, failures = {}, []
        for n in PREREQUISITES:
            tid = 'TASK-%d' % n
            d = ART / tid
            row = dict(status=statuses.get(tid, (None, None))[0], status_source=statuses.get(tid, (None, None))[1])
            log = d / 'tests.log'
            ran, final = unittest_result(log.read_text(errors='replace')) if log.exists() else (0, None)
            row.update(evidence_dir=str(d.relative_to(ROOT)), tests_log=log.exists(), tests_ran=ran, final_status=final,
                       commands_log=(d / 'commands.log').exists())
            corrupt, parsed = [], 0
            for f in sorted(d.iterdir()) if d.is_dir() else []:
                if f.is_file() and f.suffix in ('.json', '.gz'):
                    try:
                        data = gzip.decompress(f.read_bytes()) if f.suffix == '.gz' else f.read_bytes()
                        if f.suffix == '.json' or f.name.endswith('.json.gz'): json.loads(data)
                        parsed += 1
                    except Exception as error:  # noqa: BLE001 - any decode error is corrupt evidence
                        corrupt.append('%s: %s' % (f.name, type(error).__name__))
            row.update(top_level_json_gz_checked=parsed, corrupt=corrupt)
            cls = regression['classes'].get('Task%dTests' % n)
            if n <= 497:
                row['regression'] = dict(cls, log='artifacts/TASK-498/' + cls['log']) if cls else None
                ok_cls = bool(cls) and (cls['status'] == 'PASS' and cls['exit'] == 0 or
                                        cls['status'] == 'SUPERSEDED' and cls['signature_mismatch'] is None) and cls['ran'] > 0 \
                    and cls['skipped'] == 0 and (ART / 'TASK-498' / cls['log']).exists()
                row['freshness'] = ('re-run by TASK-498 at %s; runtime files unchanged %s..HEAD (dependency proof)'
                                    % (REGRESSION_COMMIT, REGRESSION_COMMIT))
            elif n == 498:
                ok_cls = regression['totals']['nonzero_exits'] == 0 and regression['totals']['skipped'] == 0
                row['freshness'] = 'its runtime hashes equal the final runtime'
            else:
                ok_cls = perf['old_modes_pass'] and perf_stale == []
                row['freshness'] = 'all %d recorded source hashes equal the final tree' % len(perf['source_hashes'])
            if n in (496, 497):
                row['freshness'] += '; full-completion evidence stale by hash (%s) -> regenerated in TASK-500/%s' % (
                    ', '.join(sorted(COMPLETION_HASH_DRIFT)), 'desktop' if n == 496 else 'touch')
            row['passed'] = (row['status'] == 'done' and row['tests_log'] and ran > 0 and final == 'OK'
                             and row['commands_log'] and not corrupt and ok_cls)
            if not row['passed']: failures.append(tid)
            rows[tid] = row
        self.evidence.write('parts/prerequisites.json', dict(tasks=rows, failures=failures,
            dependency_proof=dict(regression_commit=REGRESSION_COMMIT, files_changed_since=changed_since,
                                  runtime_files_changed_since=runtime_changed, runtime_files=len([n for n in runtime if not n.startswith('tools/')]),
                                  task498_runtime_hashes_stale=stale_runtime, task499_hashes_stale=perf_stale),
            regression_totals=regression['totals']))
        self.assertEqual(failures, [])
        print('PASS prerequisites: %d/%d tasks done with passing non-empty tests.log (0 skips), no corrupt top-level evidence; '
              'TASK-498 classes %d PASS / %d SUPERSEDED; runtime files changed %s..HEAD: %d; TASK-499 hashes stale: %d'
              % (len(rows), len(PREREQUISITES), regression['totals']['passed_classes'], regression['totals']['superseded_classes'],
                 REGRESSION_COMMIT, len(runtime_changed), len(perf_stale)), flush=True)

    def test_02_runtime_delivery(self):
        """The final runtime: manifest counts, rules and constants, plus the Chromium desktop smoke (startup, pause, save/reload
        restore, three-mode navigation, camera, range miss, wrap, nonlethal hazard)."""
        page = self.chromium.new_page(viewport=VIEWPORT); page.goto(self.url); wait_for_boot(page)
        live = page.evaluate(DELIVERY_JS)
        page.close()
        sections, encounters = live['sections'], live['encounters']
        self.assertEqual([s['id'] for s in sections], ['S0%d' % i for i in range(1, 9)])
        self.assertTrue(all(s['status'] == 'built' and s['designVersion'] == 3 for s in sections))
        names = [s['landmark']['name'] for s in sections]
        self.assertEqual(len(set(names)), 8)
        self.assertEqual(len(encounters), 32)
        self.assertEqual({s['id']: sum(e['section'] == s['id'] for e in encounters) for s in sections}, {s['id']: 4 for s in sections})
        self.assertEqual(len(live['shortcuts']), 2)
        self.assertTrue(all(s['status'] == 'built' and s['optional'] for s in live['shortcuts']))
        self.assertEqual(live['validation'], 'ok')
        self.assertEqual(live['checkpoint_keys'], [])
        self.assertEqual(live['recoveryPolicy'], 'Physical falls, nonlethal hazards, current-state saves; no automatic relocation')
        self.assertEqual(live['definition'], dict(cameraScale=0.375, acquisitionRadius=1080, upgradedAcquisitionRadius=1620, rangeUpgradeSection='S05'))
        self.assertEqual(live['range'], dict(base=1080, upgraded=1620, upgradeBand='S05'))
        self.assertEqual(live['old_modes'], dict(classic=1, bad=1/2.2))
        self.assertEqual(live['boot'], dict(mode='grapple_over', run=True, paused=False))
        self.assertIs(live['difficulty']['validated'], False)
        self.assertTrue(all(r['status'] == 'built' for r in live['recoveries']), live['recoveries'])
        route = [r for r in type(self.helper(completion.Task496Tests, 'desktop')).route() if r[0] < 340]
        failures = []
        def check(cond, msg):
            if not cond: failures.append(msg)
            self.assertTrue(cond, msg)
        smoke = completion.smoke('chromium', self.url, self.chromium, route, sub_evidence('smoke'), check)
        self.assertEqual(failures, [])
        self.assertEqual((smoke['page_errors'], smoke['console_errors']), ([], []))
        self.assertTrue(all(v['passed'] for v in smoke['scenarios'].values()))
        self.assertTrue(smoke['scenarios']['hazard_knockback']['nonlethal_run_continues'])
        shots = sorted(sub_evidence('smoke').path('browsers/.keep').parent.glob('*.png'))
        decoded = {p.name: image_stats(p) for p in shots}
        self.assertTrue(len(decoded) >= 8 and all(v['stddev'] > 5 for v in decoded.values()), decoded)
        self.evidence.write('parts/runtime.json', dict(live=live, landmark_names=names, smoke=smoke, smoke_screenshots=decoded))
        print('PASS runtime delivery: 8 built v3 sections, %d distinct landmarks, 32 encounters (4 per section), 2 optional built '
              'shortcuts, %d built recoveries, validateMountainManifest ok, 0 checkpoint keys, range %d/%d at cameraScale %.3f, boots '
              'into grapple_over; chromium smoke %s; 0 page/console errors' % (len(set(names)), len(live['recoveries']),
              live['definition']['acquisitionRadius'], live['definition']['upgradedAcquisitionRadius'], live['definition']['cameraScale'],
              ', '.join(k + ' ok' for k, v in smoke['scenarios'].items() if v['passed'])), flush=True)

    def test_03_desktop_completion(self):
        """TASK-496's desktop route from a fresh base start on the final runtime: identical trace, all Task496 assertions."""
        from grapple_over_verify import execute, check_trace
        d = self.helper(completion.Task496Tests, 'desktop')
        m = d.manifest()
        archived, raw_archived, drift = self.compare_manifest('desktop', m)
        boxes = [dict(id=e['id'], seen=False, **{k: integration.exit_box(e['exit'])[k] for k in ('left', 'right', 'top', 'bottom')})
                 for e in self.mountain['encounters']]
        frames = []
        def on_frame(page, tick):
            seen = page.evaluate(completion.FRAME_JS, boxes)
            for name in seen['hit'] + (['finish'] if seen['completed'] and all(n != 'finish' for _, n in frames) else []):
                for b in boxes:
                    if b['id'] == name: b['seen'] = True
                page.evaluate('draw()')
                page.screenshot(path=str(d.evidence.path('filmstrip/%05d-%s.jpg' % (tick, name))), type='jpeg', quality=70)
                frames.append((tick, name))
        self.browser.calls.clear(); self.browser.console_errors.clear()
        trace = execute(m, self.browser, self.url, str(d.evidence.path('runs/completion')), on_frame=on_frame)
        lifecycle, console_errors = list(self.browser.calls), list(self.browser.console_errors)
        check_trace(m, trace)
        raw = json.dumps(trace, separators=(',', ':')).encode()
        identical = trace == json.loads(raw_archived)
        self.assertTrue(identical, 'final-runtime trace differs from the archived TASK-496 recording')
        d.evidence.path('manifest-trace.json.gz').write_bytes(gzip.compress(raw, 6, mtime=0))
        d.evidence.write('manifest.json', dict(m, trace_file=dict(name='manifest-trace.json.gz', sha256=sha(raw))))
        shutil.rmtree(d.evidence.path('runs'))
        d.analyse(m, trace, state_hash(json.loads(raw_archived)), state_hash(trace), lifecycle, lifecycle, console_errors, frames)
        stills = self.compare_stills('desktop', ['%05d-%s.jpg' % f for f in frames])
        result = json.loads(d.evidence.path('trace.json').read_text())
        self.evidence.write('parts/desktop.json', dict(identical_to_archived=identical, archived_trace_sha256=archived['trace_file']['sha256'],
            final_trace_sha256=sha(raw), hash_drift_vs_archived=drift, counts=result['counts'], finish=result['finish'],
            encounter_exit_ticks=result['encounter_exit_ticks'], shortcuts=result['shortcuts'], upgrade_tick=result['upgrade']['upgrade_tick'],
            stills=stills, manifest='desktop/manifest.json', trace='desktop/trace.json'))
        print('PASS desktop completion on the final runtime: %d trusted mouse inputs, 32/32 encounters in order, 0/2 shortcuts, finish at '
              'tick %d, one level_completed, 0 errors; trace identical to TASK-496 (%s); %d filmstrip stills decode, max mean diff %.3f vs '
              'TASK-496' % (result['counts']['trusted_inputs'], result['finish']['completion_tick'], sha(raw)[:12], stills['stills'],
              stills['max_mean_abs_difference']), flush=True)

    def test_04_touch_completion(self):
        """TASK-497's 844x390 CDP-touch route from a fresh base start on the final runtime (Task497Tests.test_01 without a clip)."""
        t = self.helper(completion.Task497Tests, 'touch', CLIP=False, ENGINES=('chromium',))
        archived, raw_archived, drift = self.compare_manifest('touch', t.manifest())
        t.test_01_touch_completion()
        raw = gzip.decompress(t.evidence.path('touch-manifest-trace.json.gz').read_bytes())
        identical = json.loads(raw) == json.loads(raw_archived)
        self.assertTrue(identical, 'final-runtime touch trace differs from the archived TASK-497 recording')
        result = json.loads(t.evidence.path('touch-trace.json').read_text())
        stills = self.compare_stills('touch', [f['file'].split('/')[-1] for f in result['frames']])
        self.evidence.write('parts/touch.json', dict(identical_to_archived=identical, archived_trace_sha256=archived['trace_file']['sha256'],
            final_trace_sha256=sha(raw), hash_drift_vs_archived=drift, counts=result['counts'], finish=result['finish'],
            encounter_exit_ticks=result['encounter_exit_ticks'], shortcuts=result['shortcuts'], camera_framing=result['camera_framing'],
            stills=stills, manifest='touch/touch-manifest.json', trace='touch/touch-trace.json'))
        print('PASS touch completion on the final runtime: %d trusted touch inputs, 32/32 encounters, finish at tick %d, player on screen '
              '%d/%d samples; trace identical to TASK-497 (%s); %d stills decode, max mean diff %.3f vs TASK-497'
              % (result['counts']['trusted_touch_inputs'], result['finish']['completion_tick'], result['camera_framing']['samples'],
                 result['camera_framing']['samples'], sha(raw)[:12], stills['stills'], stills['max_mean_abs_difference']), flush=True)

    def test_05_replay_audit_and_media(self):
        """grapple_over_verify.py audit on the regenerated manifests; decode the archived completion clips."""
        import imageio_ffmpeg
        out = {}
        for sub, c in COMPLETIONS.items():
            root = self.evidence.path(sub + '/.keep').parent
            manifest = root / c['manifest']
            self.assertTrue(manifest.exists(), manifest)
            command = [sys.executable, 'tools/grapple_over_verify.py', 'audit', '--manifest', str(manifest.relative_to(ROOT)),
                       '--out', str((root / 'audit').relative_to(ROOT))]
            env = dict(os.environ, GRAPPLE_OVER_EVIDENCE_DIR=str(root.relative_to(ROOT)))
            run = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
            (root / 'auditor.log').write_text('$ GRAPPLE_OVER_EVIDENCE_DIR=%s %s\n%s%sexit=%d\n' % (
                env['GRAPPLE_OVER_EVIDENCE_DIR'], ' '.join(command), run.stdout, run.stderr, run.returncode))
            self.evidence.log('AUDITOR %s exit=%d %s' % (sub, run.returncode, run.stdout.strip()[:300]))
            self.assertEqual(run.returncode, 0, run.stderr)
            audit = json.loads(run.stdout.strip().split('PASS audit: ', 1)[1])
            fresh = json.loads(manifest.read_text())['trace_file']['sha256']
            raw = gzip.decompress(next((root / 'audit').glob('trace.json.gz')).read_bytes())
            self.assertEqual(sha(raw.rstrip(b'\n')), fresh)  # EvidenceWriter.write appends one newline
            self.assertTrue(audit['matching_traces'] and audit['recorded_sha256'] == audit['replayed_sha256'])
            (root / 'audit' / 'trace.json.gz').unlink()  # identical to the manifest trace (sha256 checked above)
            video = ART / ('TASK-%d' % c['task']) / c['video']
            frames, secs = imageio_ffmpeg.count_frames_and_secs(str(video))
            self.assertAlmostEqual(secs, 11507 / 60, delta=2)
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            samples = {}
            for at in (5, 95, secs - 2):
                png = self.evidence.path('media/%s-%03d.png' % (sub, int(at)))
                subprocess.run([ffmpeg, '-y', '-loglevel', 'error', '-ss', '%.2f' % at, '-i', str(video), '-frames:v', '1', str(png)], check=True)
                samples[png.name] = image_stats(png)
                self.assertGreater(samples[png.name]['stddev'], 5, png)
            sheet = ART / ('TASK-%d' % c['task']) / (c['stills'] + '.jpg')
            out[sub] = dict(auditor=audit, auditor_log=sub + '/auditor.log', manifest_trace_sha256=fresh,
                            video=dict(file=str(video.relative_to(ROOT)), sha256=sha(video.read_bytes()), frames=frames, seconds=secs,
                                       decoded_samples=samples), contact_sheet=dict(file=str(sheet.relative_to(ROOT)), **image_stats(sheet)))
            print('PASS replay auditor %s: matching_traces, %d ticks, %s; %s decodes %d frames / %.1f s, sampled frames non-blank'
                  % (sub, audit['ticks'], audit['replayed_sha256'][:12], video.name, frames, secs), flush=True)
        self.evidence.write('parts/media.json', out)

    def test_06_delivery_and_audit(self):
        """delivery.json and audit.json from the case outputs; repository hygiene; unchanged hashes during the run."""
        parts = {}
        for name in ('prerequisites', 'runtime', 'desktop', 'touch', 'media'):
            path = self.evidence.path('parts/%s.json' % name)
            self.assertTrue(path.exists(), 'missing part ' + name)
            parts[name] = json.loads(path.read_text())
        self.assertEqual(tested_hashes(), self.hashes, 'tested files changed during the run')
        staged = git('diff', '--cached', '--name-only').split()
        status = git('status', '--short').splitlines()
        forbidden = [p for p in staged + [l[3:] for l in status] if p.startswith(('artifacts', 'screenshots'))]
        self.assertEqual(forbidden, [])
        ignored = subprocess.run(['git', 'check-ignore', 'artifacts/TASK-500/x', 'screenshots/x'], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(ignored.returncode, 0)
        # No tracked evidence, and no TASK-444..500 commit touched artifacts/ or screenshots/. 38 screenshots/ files committed by
        # TASK-001..017 (June, before the ignore rule) remain tracked; they predate this scope and are reported, not removed.
        tracked = git('ls-files', 'artifacts').split()
        self.assertEqual(tracked, [])
        legacy_screenshots = git('ls-files', 'screenshots').split()
        scope_touched = git('log', '--format=', '--name-only', FIRST_SCOPE_COMMIT + '^..HEAD', '--', 'artifacts', 'screenshots').split()
        self.assertEqual(scope_touched, [])
        legacy_added = git('log', '--format=%h %s', '--diff-filter=A', FIRST_SCOPE_COMMIT + '^..HEAD', '--', 'screenshots').split()
        self.assertEqual(legacy_added, [])
        live, pre, desk, touch, media = (parts[k] for k in ('runtime', 'prerequisites', 'desktop', 'touch', 'media'))
        runtime_only = {k: v for k, v in self.hashes.items() if not k.startswith('tools/')}
        delivery = dict(revision=self.revision, dirty_paths=self.dirty,
            sections=len(live['live']['sections']), landmarks=live['landmark_names'], distinct_landmarks=len(set(live['landmark_names'])),
            encounters=len(live['live']['encounters']), shortcuts=[s['id'] for s in live['live']['shortcuts']], shortcut_count=len(live['live']['shortcuts']),
            checkpoints=len(live['live']['checkpoint_keys']), checkpoint_keys=live['live']['checkpoint_keys'],
            hazards=dict(nonlethal=live['smoke']['scenarios']['hazard_knockback']['nonlethal_run_continues'],
                         knockback_cooldown_ms=live['smoke']['scenarios']['hazard_knockback']['first']['cooldown_ms'], policy=live['live']['recoveryPolicy']),
            acquisition=dict(spec_units=540, spec_camera_scale=0.75, spec_screen_reach_px_at_1080=540*0.75,
                             final_units=live['live']['definition']['acquisitionRadius'], final_camera_scale=live['live']['definition']['cameraScale'],
                             final_screen_reach_px_at_1080=live['live']['definition']['acquisitionRadius']*live['live']['definition']['cameraScale'],
                             upgraded_units=live['live']['definition']['upgradedAcquisitionRadius'], upgrade_section=live['live']['definition']['rangeUpgradeSection'],
                             note='The original 540-unit range at 0.75 camera scale was doubled to 1080 units at 0.375 by TASK-543 (layout v3, '
                                  'done); the on-screen reach is the same 405 px at the 1080 px reference height.'),
            scale=dict(grapple_over=live['live']['definition']['cameraScale'], classic=live['live']['old_modes']['classic'], bad=live['live']['old_modes']['bad']),
            recoveries=len(live['live']['recoveries']), startup=live['live']['boot'], smoke=list(live['smoke']['scenarios']),
            completions=dict(desktop=dict(passed=True, **{k: desk[k] for k in ('counts', 'finish', 'identical_to_archived', 'final_trace_sha256')},
                                          auditor=media['desktop']['auditor'], manifest=desk['manifest']),
                             touch=dict(passed=True, **{k: touch[k] for k in ('counts', 'finish', 'identical_to_archived', 'final_trace_sha256')},
                                        auditor=media['touch']['auditor'], manifest=touch['manifest'])),
            difficulty=dict(target_first_success_minutes=[30, 60], validated=False, human_feedback=None,
                            note='No human playtest feedback is available; the 30-60 minute first-success target remains unvalidated.'),
            runtime_hashes=runtime_only, level_sha256=self.hashes['fixedlevel.js'], mountain_sha256=self.hashes['mountain.js'])
        self.evidence.write('delivery.json', delivery)
        requirements = {
            '32 authored encounters': (delivery['encounters'] == 32 and desk['counts']['encounters_exited_in_order'] == 32
                                       and touch['counts']['encounters_exited_in_order'] == 32,
                                       ['parts/runtime.json', 'desktop/trace.json', 'touch/touch-trace.json']),
            'eight distinct landmarks': (delivery['distinct_landmarks'] == 8, ['parts/runtime.json', 'artifacts/TASK-493/gallery.json']),
            'two optional shortcuts': (delivery['shortcut_count'] == 2, ['parts/runtime.json', 'artifacts/TASK-492/shortcuts.json']),
            'recovery routes': (all(r['status'] == 'built' for r in live['live']['recoveries']) and pre['tasks']['TASK-491']['passed'],
                                ['parts/runtime.json', 'artifacts/TASK-491/recovery-map.json', 'tools/grapple_over_recovery_routes.json']),
            'startup and navigation': (live['live']['boot']['mode'] == 'grapple_over' and live['smoke']['scenarios']['mode_switching']['passed'],
                                       ['parts/runtime.json', 'smoke/browsers/', 'artifacts/TASK-498/regression.json']),
            'persistent current-state saves': (live['smoke']['scenarios']['save_restore']['passed'] and pre['tasks']['TASK-495']['passed'],
                                               ['parts/runtime.json', 'artifacts/TASK-495/persistence.json', 'artifacts/TASK-495/mode-isolation.json']),
            'summit ending': (desk['counts']['level_completed_calls'] == 1 and touch['counts']['level_completed_calls'] == 1,
                              ['desktop/trace.json', 'touch/touch-trace.json']),
            'no checkpoints, physical falls, nonlethal hazards': (delivery['checkpoints'] == 0 and delivery['hazards']['nonlethal'],
                                                                  ['parts/runtime.json', 'artifacts/TASK-491/recovery-map.json']),
            'desktop continuous completion on final runtime': (desk['identical_to_archived'] and media['desktop']['auditor']['matching_traces'],
                                                               ['desktop/manifest.json', 'desktop/auditor.log', 'parts/desktop.json']),
            'touch continuous completion on final runtime': (touch['identical_to_archived'] and media['touch']['auditor']['matching_traces'],
                                                             ['touch/touch-manifest.json', 'touch/auditor.log', 'parts/touch.json']),
            'media decodes': (all(v['video']['frames'] > 0 for v in media.values()), ['parts/media.json', 'media/']),
            'classic/bad preserved and runtime cost bounded': (pre['tasks']['TASK-498']['passed'] and pre['tasks']['TASK-499']['passed'],
                                                               ['artifacts/TASK-498/old-mode-traces.json', 'artifacts/TASK-499/perf/summary.json']),
            'evidence untracked and nothing staged': (forbidden == [] and tracked == [] and scope_touched == [], ['commands.log', 'audit.json']),
        }
        audit = dict(revision=self.revision, scope='TASK-444..TASK-499 and TASK-500',
            requirements={k: dict(passed=bool(v[0]), artifacts=v[1]) for k, v in requirements.items()},
            tasks={k: dict(passed=v['passed'], status=v['status'], tests_ran=v['tests_ran'], final_status=v['final_status'],
                           evidence=v['evidence_dir'], freshness=v['freshness'], regression=(v.get('regression') or {}).get('status'))
                   for k, v in pre['tasks'].items()},
            dependency_proof=pre['dependency_proof'], staged=staged, status_short=status, tracked_artifacts=tracked,
            scope_commits_touching_artifacts_or_screenshots=scope_touched,
            legacy_tracked_screenshots=dict(count=len(legacy_screenshots), files=legacy_screenshots,
                note='committed by TASK-001..017 before the ignore rule; outside TASK-444..500; left for the user to untrack'), failed=[k for k, v in requirements.items() if not v[0]]
                                                                                              + pre['failures'])
        audit['passed'] = audit['failed'] == []
        self.evidence.write('audit.json', audit)
        self.evidence.log('GIT staged=%r status_short=%r tracked_artifacts=%r scope_touched=%r legacy_tracked_screenshots=%d'
                          % (staged, status, tracked, scope_touched, len(legacy_screenshots)))
        self.assertEqual(audit['failed'], [])
        print('PASS delivery audit: %d/%d requirements, %d/%d tasks; 8 sections, 32 encounters, 2 shortcuts, 0 checkpoints, nonlethal '
              'hazards, %d units at %.3f (spec 540 at 0.75, same 405 px reach), desktop+touch completions identical on the final runtime; '
              'nothing under artifacts/ or screenshots/ staged or tracked' % (sum(v[0] for v in requirements.values()), len(requirements),
              sum(v['passed'] for v in pre['tasks'].values()), len(pre['tasks']), delivery['acquisition']['final_units'],
              delivery['acquisition']['final_camera_scale']), flush=True)


if __name__ == '__main__':
    unittest.main()
