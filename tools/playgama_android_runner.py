"""Build an offline Android receipt runner; validate exports without trusting summaries."""
import argparse
import ast
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import statistics
import zipfile

ROOT = Path(__file__).resolve().parents[1]

def sha(data):
    return hashlib.sha256(data).hexdigest()

def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')

def constant(file, name):
    for node in ast.parse(file.read_text()).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError(name)

def schedule():
    return [(mode, pair, arm) for mode in ('classic', 'bad') for pair in range(3)
            for arm in (('baseline', 'repair') if pair % 2 == 0 else ('repair', 'baseline'))]

def metrics(frames):
    if not isinstance(frames, list) or len(frames) < 2:
        raise ValueError('missing frames')
    active = warmup = 0
    intervals, gaps = [], []
    for row in frames:
        if not isinstance(row['t'], (int, float)) or isinstance(row['t'], bool) or not math.isfinite(row['t']):
            raise ValueError('invalid timestamp')
        for side in ('before', 'after'):
            if set(row[side]) != {'menu','pause','death','ad','host','portrait','hidden'} or any(type(v) is not bool for v in row[side].values()):
                raise ValueError('invalid active state')
    for prev, row in zip(frames, frames[1:]):
        dt = row['t'] - prev['t']
        if dt <= 0:
            raise ValueError('nonmonotonic timestamp')
        if not any(prev['after'].values()) and not any(row['before'].values()):
            if active < 5000:
                warmup += dt
            else:
                intervals.append(dt)
            active += dt
        else:
            gaps.append({'start': prev['t'], 'end': row['t'], 'ms': dt})
    if sum(intervals) < 30000:
        raise ValueError('insufficient active duration after 5-second warmup')
    ordered = sorted(intervals)
    return {'mean_frame_ms': statistics.mean(intervals), 'p95_frame_ms': ordered[math.ceil(.95*len(ordered))-1],
            'average_fps': 1000/statistics.mean(intervals), 'measured_ms': sum(intervals),
            'warmup_ms': warmup, 'excluded_gaps': gaps}

def validate(data, package):
    try:
        if data['schema'] != 1 or len(data['runs']) != 12:
            raise ValueError('expected twelve alternating runs')
        env = data['environment']
        if not all(isinstance(env[k], str) and env[k].strip() for k in ('device_model','android_version','firefox_version','user_agent','platform')):
            raise ValueError('missing device identity')
        if data['quality'] != 'unchanged':
            raise ValueError('quality changed')
        layouts, results = [], []
        for run, (mode, pair, arm) in zip(data['runs'], schedule()):
            if (run['mode'], run['pair'], run['arm']) != (mode, pair, arm):
                raise ValueError('pair order mismatch')
            if run['build_sha256'] != package['builds'][arm]['zip_sha256']:
                raise ValueError('build mismatch')
            layout = run['layout']
            dimensions = [layout['dpr'], *layout['backing'], *layout['viewport']]
            if len(layout['backing']) != 2 or len(layout['viewport']) != 2 or any(type(v) not in (int,float) or not math.isfinite(v) or v <= 0 for v in dimensions):
                raise ValueError('invalid backing dimensions')
            if layout != run['end_layout'] or layout['orientation'] != 'landscape' or layout['dpr'] <= 0 or any(v <= 0 for v in layout['backing']):
                raise ValueError('invalid or changed backing/orientation')
            layouts.append(layout)
            if any(item != layout for item in run.get('layout_changes', [])):
                raise ValueError('backing changed during run')
            if not isinstance(run['visibility'], list):
                raise ValueError('missing visibility interruptions')
            results.append(metrics(run['frames']))
        if any(x != layouts[0] for x in layouts):
            raise ValueError('mismatched backings')
        pairs = []
        for i in range(0, 12, 2):
            a,b = (results[i],results[i+1]) if data['runs'][i]['arm']=='baseline' else (results[i+1],results[i])
            pairs.append({'mode':data['runs'][i]['mode'],'pair':data['runs'][i]['pair'],
                          'reduction':1-b['mean_frame_ms']/a['mean_frame_ms'], 'baseline':a,'repair':b})
        reductions = {m:statistics.median(p['reduction'] for p in pairs if p['mode']==m) for m in ('classic','bad')}
        native = (data['provenance']=='native-device' and env['owner_attested_native'] is True
                  and env['webdriver'] is False and 'Android' in env['user_agent']
                  and re.search(r'Firefox/\d+',env['user_agent']) is not None
                  and 'Linux' in env['platform'] and 'x86' not in env['platform'])
        return {'status':'NATIVE_RECORDED' if native else 'UNVERIFIED', 'pairs':pairs,
                'environment':env, 'quality':data['quality'], 'provenance':data['provenance'],
                'builds':{arm:package['builds'][arm]['zip_sha256'] for arm in ('baseline','repair')},
                'median_paired_reduction': reductions,
                'native_performance_accept':native and max(reductions.values())>=.10 and min(reductions.values())>=-.05,
                'rule':'>=10% median paired mean-frame reduction in targeted mode; <=5% regression in either mode; p95 reported; native Firefox only, no other-engine claim',
                'limitation':'Owner identity/quality attestation required; UA alone cannot prove native hardware. No Chromium or production claim.'}
    except (KeyError, TypeError, IndexError, ZeroDivisionError) as exc:
        raise ValueError('malformed export') from exc

def prepare(out):
    runner = out/'runner'; runner.mkdir(parents=True, exist_ok=True)
    builds = {}
    for arm, task, archive in [('baseline','TASK-292','baseline.zip'),('repair','TASK-294','control.zip')]:
        source = ROOT/'artifacts'/task
        build = json.loads((source/'build.json').read_text())
        raw = (source/archive).read_bytes()
        assert sha(raw) == build['zip_sha256']
        (runner/(arm+'.zip')).write_bytes(raw)
        dest = runner/arm; dest.mkdir(exist_ok=True)
        with zipfile.ZipFile(source/archive) as z:
            for name in z.namelist():
                assert name in ('index.html','playgama-bridge-config.json')
                payload = z.read(name)
                assert sha(payload)==build['served_sha256'][name]
                (dest/name).write_bytes(payload)
        html = (dest/'index.html').read_text()
        sdk = 'https://bridge.playgama.com/v2/stable/playgama-bridge.js'
        assert sdk in html
        html = html.replace(sdk,'../sdk.js')
        csp = "default-src 'none'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; media-src 'self' data:"
        html = html.replace('<head>', '<head><meta http-equiv="Content-Security-Policy" content="'+csp+'">', 1)
        (dest/'index.html').write_text(html)
        builds[arm] = {**build, 'offline_entry_sha256':sha((dest/'index.html').read_bytes()),
                       'adaptation':'Only local SDK URL and restrictive CSP; original exact ZIP included. No rendering/gameplay changes.'}
    fake = constant(ROOT/'tools/test_playgama2_bridge.py','FAKE')
    (runner/'sdk.js').write_text("const SAVED_LANGUAGE='en', FAULT='';\n"+fake)
    probe = constant(ROOT/'tools/playgama_firefox_perf.py','PROBE')
    probe = probe.replace('if (p.activeMs >= 35000) p.done = true;', '''if (p.warmupEnd === undefined && p.activeMs >= 5000) p.warmupEnd = p.activeMs;
        if (p.warmupEnd !== undefined && p.activeMs - p.warmupEnd >= 30000) p.done = true;''')
    (runner/'probe.js').write_text('window.installProbe = '+probe+';\n')
    for f in (ROOT/'tools/android_runner').iterdir():
        shutil.copyfile(f,runner/f.name)
    write(runner/'builds.json',builds)
    package = {'builds':builds, 'repair_identity':'TASK-294 frozen repair control; no supported optimization candidate',
        'serve':'python3 -m http.server 8765 --bind 0.0.0.0 --directory artifacts/TASK-295/runner',
        'steps': ['Use a trusted local LAN; no public deployment. Open http://<computer-LAN-IP>:8765 in actual Firefox Android.',
                  'Keep landscape orientation and fixed zoom; enter model and actual Android Settings / Firefox About versions (UA may be reduced).',
                  'Attest native device only on actual hardware. Press Start once; twelve runs alternate AB, BA, AB per mode with 5 active seconds warmup + 30 active seconds.',
                  'Leave tab visible. Automatic fixed-seed input and restart buttons preserve quality. Interruptions are exported; timeout/failure cannot pass validation.',
                  'Download JSON; validate with python3 tools/playgama_android_runner.py validate EXPORT.json --out artifacts/TASK-295. Export tests never prove hardware performance.'],
        'files':{str(p.relative_to(runner)):sha(p.read_bytes()) for p in sorted(runner.rglob('*')) if p.is_file()}}
    write(out/'package.json', package)
    write(out/'native-status.json', {'status':'UNVERIFIED','native_performance_accept':False,'reason':'No actual-device export supplied; preparation and synthetic tests are not hardware evidence.'})
    print('PASS package: exact published baseline and frozen repair ZIP hashes; local SDK and restrictive CSP; twelve alternating unchanged-quality runs')

def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('command',choices=['prepare','validate']); p.add_argument('export',nargs='?',type=Path); p.add_argument('--out',type=Path,default=ROOT/'artifacts/TASK-295'); a=p.parse_args()
    if a.command=='prepare': prepare(a.out)
    else:
        result=validate(json.loads(a.export.read_text()),json.loads((a.out/'package.json').read_text()))
        result['export_sha256']=sha(a.export.read_bytes())
        write(a.out/'validated-export.json',result)
        print('PASS export validation; native status:',result['status'])
        if result['status']=='NATIVE_RECORDED': write(a.out/'native-status.json',result)

if __name__=='__main__': main()
