"""Bind existing offline suites to immutable archive bytes and record transport/input.

Each invocation needs a fresh output directory. Captures are native browser PNGs,
not physical-device evidence. Fixture routes remain owned by the selected suite.
"""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import traceback
import zipfile

from playwright.sync_api import Browser, Route

SUITES = {'release': 'verify_y8_release', 'embed': 'verify_y8_embed',
          'mobile-embed': 'verify_y8_mobile_embed',
          'lifecycle': 'verify_y8_mobile_lifecycle', 'ads': 'verify_y8_ads'}
INPUT = '''window.__candidateInput=[];
for(const type of ['touchstart','touchend','touchcancel','mousedown','mouseup','keydown'])
 document.addEventListener(type,e=>__candidateInput.push({type,trusted:e.isTrusted}),true);'''


def digest(data):
    return hashlib.sha256(data).hexdigest()


def identity(archive, root):
    with zipfile.ZipFile(archive) as z:
        expected = {n: digest(z.read(n)) for n in z.namelist() if not n.endswith('/')}
    actual = {str(p.relative_to(root)): digest(p.read_bytes()) for p in root.rglob('*') if p.is_file()}
    assert actual == expected, 'extracted runtime differs from archive'
    return {'archive': str(archive.resolve()), 'sha256': digest(archive.read_bytes()),
            'root': str(root.resolve()), 'runtime_sha256': actual}


def run(args):
    args.out.mkdir(parents=True, exist_ok=False)
    report = {'candidate': identity(args.archive, args.root), 'suite': args.suite,
              'contexts': [], 'verdict': 'FAIL',
              'boundaries': ['Offline SDK fixture or deliberate blocked SDK only; no production transport.',
                             'Trusted browser input; synthetic visibility/blur, seeded deaths and callback fixtures.',
                             'Linux browser emulation; native devices, Y8 host and real ads NOT RUN.']}
    original_context = Browser.new_context
    originals = {name: getattr(Route, name) for name in ('fulfill', 'abort', 'continue_')}
    owners = {}

    def new_context(browser, **kwargs):
        context = original_context(browser, **kwargs)
        row = {'engine': browser.browser_type.name, 'version': browser.version,
               'profile': kwargs, 'transport': [], 'failures': [], 'errors': [], 'inputs': []}
        report['contexts'].append(row)
        owners[id(context)] = row
        context.add_init_script(INPUT)
        context.on('requestfailed', lambda r: row['failures'].append({'url': r.url, 'failure': r.failure}))
        def page_open(page):
            page.on('pageerror', lambda e: row['errors'].append(str(e)))
        context.on('page', page_open)
        close = context.close
        def recorded_close(*a, **kw):
            for page in context.pages:
                for frame in page.frames:
                    try:
                        row['inputs'].append({'url': frame.url, 'events': frame.evaluate('window.__candidateInput || []')})
                    except Exception as e:
                        row.setdefault('input_capture_errors', []).append(str(e))
            return close(*a, **kw)
        context.close = recorded_close
        return context

    def wrapped(name):
        def action(route, *a, **kw):
            row = owners.get(id(route.request.frame.page.context))
            url = route.request.url
            if row is not None:
                row['transport'].append({'url': url, 'action': name,
                    **({'body_sha256': digest(kw['body'].encode() if isinstance(kw['body'], str) else kw['body'])}
                       if name == 'fulfill' and 'body' in kw else {})})
            if name == 'continue_':
                assert url.startswith('http://127.0.0.1:'), 'external network continuation forbidden'
            return originals[name](route, *a, **kw)
        return action

    Browser.new_context = new_context
    for name in originals:
        setattr(Route, name, wrapped(name))
    try:
        module = importlib.import_module(SUITES[args.suite])
        result = module.run(args.archive if args.suite == 'ads' else args.root, args.out)
        assert result is not False, 'suite failed'
        assert identity(args.archive, args.root) == report['candidate'], 'runtime changed during suite'
        assert report['contexts'] and all(not c['errors'] for c in report['contexts'])
        assert all(c['transport'] for c in report['contexts']), 'missing transport evidence'
        report['verdict'] = 'PASS'
    except Exception:
        report['error'] = traceback.format_exc()
        raise
    finally:
        Browser.new_context = original_context
        for name, original in originals.items():
            setattr(Route, name, original)
        (args.out/'instrumentation.json').write_text(json.dumps(report, indent=2)+'\n')
    print('PASS candidate identity, offline transport and context instrumentation', report['candidate']['sha256'])


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--suite', choices=SUITES, required=True)
    ap.add_argument('--root', type=Path, required=True)
    ap.add_argument('--archive', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    run(ap.parse_args())
