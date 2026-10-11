#!/usr/bin/env python3
"""60-FPS readiness evaluator over owner benchmark exports (TASK-284).

Reads every result file exported by the TASK-283 runner (bench.js ->
benchtool.py serve, results/*.json or downloads), validates each one with
benchtool.validate_result against the built package, recomputes every metric
from the raw frame intervals and fills the required acceptance matrix:

  desktop  x DevTools closed / docked / undocked   (CPU throttle none)
  android-chrome, iphone-safari                     (native, no emulation)
  each in both runtime modes (bad = Main, classic = Chill)

Per row the verdict is PASS only when three valid repetitions each satisfy
  average FPS >= 58, every full rolling 10 s window >= 55 FPS, p95 frame
  time <= 33.3 ms, >= 60 000 ms measured active after the 5 s warmup,
at unchanged rendering quality (adaptive density never reduced the backing,
page DPR equal to the display DPR, no emulation, standard protocol).
FAIL when valid repetitions exist and any threshold is missed; UNVERIFIED when
fewer than three valid repetitions exist for the row (missing owner data,
rejected evidence). Metrics are normalised only by the recorded frame
timestamps: an interval must equal its timestamp difference, slow frames are
never dropped, and a null interval (gap) is accepted only when the page
recorded an inactive state (menu/pause/offer/hidden/ad or a visibility/blur
interruption) that explains it; an unexplained gap rejects the repetition.

Outputs acceptance.json (rows, repetitions, metrics, evidence files, reasons)
and decision.json (evaluation_completed vs 60fps_achieved, the latter true only
when every required actual-device row is PASS). Nothing here produces
measurements: the files are the owner's; this tool only judges them.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import benchtool as bt  # noqa: E402

THRESHOLDS = {'average_fps_min': 58.0, 'rolling_10s_window_fps_min': 55.0, 'p95_frame_ms_max': 33.3,
              'measured_active_ms_min': 60000, 'repetitions_required': 3, 'warmup_ms': 5000, 'rolling_window_ms': 10000}
TARGETS = ['desktop', 'android-chrome', 'iphone-safari']
DEVTOOLS_STATES = {'desktop': ['closed', 'docked', 'undocked'], 'android-chrome': ['closed'], 'iphone-safari': ['closed']}
MODES = ['bad', 'classic']
GAP_TOLERANCE_MS = 250.0  # an inactive-state sample must fall inside the gap, with this slack at either edge


def rolling_windows(frames, window_ms=THRESHOLDS['rolling_window_ms']):
    """Every window of >= window_ms contiguous active intervals starting at each
    frame (a gap breaks it), like benchtool.rolling_windows, but the window length
    is the timestamp difference frames[j][0] - frames[i][0] (equal to the interval
    sum within the 1e-6 ms enforced by check_frames) found with a monotone sweep:
    O(n) instead of O(n * window)."""
    out = []
    n = len(frames)
    j = 0
    for i in range(n):
        if j < i:
            j = i
        while j + 1 < n and frames[j + 1][1] is not None and frames[j][0] - frames[i][0] < window_ms:
            j += 1
        span = frames[j][0] - frames[i][0]
        if j > i and span >= window_ms:
            out.append({'start': i, 'end': j, 'intervals': j - i, 'active_ms': span, 'fps': (j - i) * 1000 / span})
    return out


def row_key(target, devtools, mode):
    return f'{target}/{devtools}/{mode}'


def required_rows():
    return [row_key(t, d, m) for t in TARGETS for d in DEVTOOLS_STATES[t] for m in MODES]


def classify_target(data):
    """Target device class from the recorded user agent; None when unrecognised.

    Phone rows are selected only by the Android / iOS user-agent tokens (Chrome on
    Android, Safari on iOS; other browsers on those systems are rejected). Every
    other recognised desktop OS token (Windows NT, Macintosh, X11 / Linux without
    Android, CrOS) is the desktop class regardless of navigator.maxTouchPoints:
    Chrome on a touchscreen laptop (Surface, XPS, Yoga; maxTouchPoints 10) is a
    desktop export, the touch count is only recorded in the row (TASK-299). An
    iPad (its own token, or the Macintosh desktop-mode UA with touch points) is
    neither the iPhone row nor a desktop and stays unassigned."""
    ua = data['device']['user_agent']
    os_fam = (data['device'].get('os_family_detected') or '')
    browser = (data['device'].get('browser_family_detected') or '')
    if re.search(r'Android', ua) or os_fam == 'Android':
        return 'android-chrome' if (re.search(r'Chrome/', ua) and not re.search(r'OPR/|SamsungBrowser|EdgA/|Firefox', ua)) else None
    touch = touch_points(data)
    if re.search(r'iPad', ua) or os_fam == 'iPadOS':
        return None  # a tablet is neither the iPhone row nor a desktop
    if re.search(r'iPhone|iPod', ua) or os_fam in ('iOS', 'iPhone'):
        # every iOS browser uses WebKit; only Safari itself is the required row
        return 'iphone-safari' if (re.search(r'Safari/', ua) and not re.search(r'CriOS|FxiOS|EdgiOS|OPT/', ua)) else None
    if re.search(r'Macintosh', ua) and touch:
        return None  # iPadOS Safari in desktop mode reports a Macintosh UA; real Macs have no touch points
    if re.search(r'Windows NT|Macintosh|X11|Linux|CrOS', ua) or os_fam in ('Windows', 'macOS', 'Linux', 'ChromeOS'):
        return 'desktop'
    if browser:
        return 'desktop'
    return None


def touch_points(data):
    """navigator.maxTouchPoints as recorded by the page (None when the export does not carry it)."""
    try:
        t = data['device'].get('max_touch_points')
    except (KeyError, TypeError, AttributeError):
        return None
    return t if isinstance(t, int) and not isinstance(t, bool) else None


def gap_explained(run, gap_frame_index):
    """A null interval inside the measured region must be covered by a recorded
    inactive-state sample or an interruption between the previous frame and this one."""
    frames = run['frames']
    t1 = frames[gap_frame_index][0]
    t0 = frames[gap_frame_index - 1][0]
    lo, hi = t0 - GAP_TOLERANCE_MS, t1 + GAP_TOLERANCE_MS
    for s in run.get('excluded_samples') or []:
        t = s.get('t')
        if isinstance(t, (int, float)) and lo <= t <= hi:
            return True
    for s in run.get('interruptions') or []:
        t = s.get('t') if isinstance(s.get('t'), (int, float)) else s.get('t_ms')
        if isinstance(t, (int, float)) and lo <= t <= hi:
            return True
    return False


def evaluate_run(run, settings, display):
    """Independent recomputation + threshold verdict for one COMPLETE run.
    Returns {valid, reasons, metrics, verdict, thresholds_failed}."""
    out = {'index': run['index'], 'mode': run['mode'], 'result': run['result'], 'valid': False, 'reasons': [],
           'metrics': None, 'verdict': None, 'thresholds_failed': []}
    if run['result'] != 'COMPLETE':
        out['reasons'].append(f'non-complete attempt preserved, not counted: {run["result"]}')
        return out
    try:
        bt.check_frames(run['frames'])
        start, region = bt.measured_region(run['frames'], THRESHOLDS['warmup_ms'])
        if region is None:
            raise bt.Rejected('warmup never completed')
        m = bt.metrics(region)
        windows = rolling_windows(region, THRESHOLDS['rolling_window_ms'])
    except bt.Rejected as e:
        out['reasons'].append(f'frame evidence rejected: {e}')
        return out
    gaps = [i for i in range(start + 1, len(run['frames'])) if run['frames'][i][1] is None]
    unexplained = [i for i in gaps if not gap_explained(run, i)]
    metrics = {'measured_start_frame': start, 'frames': m['frames'], 'intervals': m['intervals'], 'gaps': len(gaps),
               'unexplained_gaps': len(unexplained), 'active_ms': m['active_ms'], 'wall_ms': m['wall_ms'],
               'average_fps': m['average_fps'], 'frame_ms': m['frame_ms'],
               'rolling_10s_windows': len(windows), 'rolling_10s_min_fps': min(w['fps'] for w in windows) if windows else None,
               'rolling_10s_windows_below_min': sum(1 for w in windows if w['fps'] < THRESHOLDS['rolling_10s_window_fps_min']),
               'backing_sizes': [run['backing']['initial']] + [c['backing'] for c in run['backing']['changes']],
               'backing_constant': not run['backing']['changes'],
               'density_limit_at_start': run['dimensions_at_start'].get('density_limit'),
               'page_dpr': run['dimensions_at_start'].get('dpr'), 'display_dpr': display.get('dpr'),
               'viewport': run['dimensions_at_start'].get('viewport'), 'deaths': len(run['deaths']),
               'inactive_frames_excluded': run['excluded'], 'dispatched_inputs': len(run['dispatched'])}
    out['metrics'] = metrics
    if unexplained:
        out['reasons'].append(f'{len(unexplained)} gap(s) in the measured region without a recorded inactive state at frames {unexplained[:5]}: '
                              'dropped frames are not accepted')
        return out
    if m['active_ms'] < THRESHOLDS['measured_active_ms_min']:
        out['reasons'].append(f'insufficient duration: measured active {m["active_ms"]:.0f} ms < {THRESHOLDS["measured_active_ms_min"]} ms')
        return out
    if not windows:
        out['reasons'].append('no full rolling 10 s window inside the measured region')
        return out
    out['valid'] = True
    failed = []
    if m['average_fps'] < THRESHOLDS['average_fps_min']:
        failed.append(f'average_fps {m["average_fps"]:.2f} < {THRESHOLDS["average_fps_min"]}')
    if metrics['rolling_10s_windows_below_min']:
        failed.append(f'{metrics["rolling_10s_windows_below_min"]} rolling 10 s window(s) below {THRESHOLDS["rolling_10s_window_fps_min"]} FPS '
                      f'(minimum {metrics["rolling_10s_min_fps"]:.2f})')
    if m['frame_ms']['p95'] > THRESHOLDS['p95_frame_ms_max']:
        failed.append(f'p95 frame time {m["frame_ms"]["p95"]:.2f} ms > {THRESHOLDS["p95_frame_ms_max"]} ms')
    dl = metrics['density_limit_at_start']
    if not metrics['backing_constant'] or (dl not in (None, 'Infinity') and dl != float('inf')):
        failed.append(f'rendering quality reduced by adaptive density (density_limit {dl}, backing {metrics["backing_sizes"]}): '
                      'not a pass at normal quality')
    if isinstance(metrics['page_dpr'], (int, float)) and isinstance(metrics['display_dpr'], (int, float)) \
            and abs(metrics['page_dpr'] - metrics['display_dpr']) > 1e-9:
        failed.append(f'page DPR {metrics["page_dpr"]} != display DPR {metrics["display_dpr"]}')
    out['thresholds_failed'] = failed
    out['verdict'] = 'PASS' if not failed else 'FAIL'
    return out


def evaluate_file(path, package_root):
    """One export -> {file, sha256, validation, target, devtools, eligible, runs: [evaluate_run...]}"""
    entry = {'file': str(path), 'sha256': bt.sha_file(path), 'validation': None, 'target': None, 'devtools': None,
             'model_supplied': None, 'touch_points': None, 'eligible': False, 'ineligible_reasons': [], 'runs': [], 'display': None}
    try:
        data = json.loads(Path(path).read_text())
    except ValueError as e:
        entry['ineligible_reasons'].append(f'unreadable JSON: {e}')
        return entry
    if not isinstance(data, dict) or data.get('schema') != bt.SCHEMA_ID:
        entry['ineligible_reasons'].append(f'not a {bt.SCHEMA_ID} result document (schema field '
                                           f'{data.get("schema") if isinstance(data, dict) else type(data).__name__!r}); skipped')
        return entry
    report = bt.validate_result(data, package_root, allow_custom=False)
    entry['validation'] = {'status': report['status'], 'reasons': report['reasons'], 'warnings': report['warnings'],
                           'acceptance_eligible': report['acceptance_eligible'], 'package': report.get('package')}
    if report['status'] != 'ACCEPTED':
        entry['ineligible_reasons'].extend('validator: ' + r for r in report['reasons'])
        # still record what the file says about itself, so wrong-build / rejected files appear in the audit trail
        try:
            entry['model_supplied'] = data['device']['model_supplied']
            entry['touch_points'] = touch_points(data)
            entry['target'] = classify_target(data)
            entry['devtools'] = data['settings']['devtools']
        except (KeyError, TypeError):
            pass
        return entry
    entry['model_supplied'] = data['device']['model_supplied']
    entry['touch_points'] = touch_points(data)
    entry['display'] = data['display']
    entry['target'] = classify_target(data)
    entry['devtools'] = data['settings']['devtools']
    s = data['settings']
    if not report['acceptance_eligible']:
        entry['ineligible_reasons'].append('not eligible: custom protocol or emulation (validator)')
    if s['emulation'] != 'none':
        entry['ineligible_reasons'].append(f'emulation={s["emulation"]}: not a native device')
    if not re.match(r'^\s*none', s['cpu_throttle'].lower()) and '1x' not in s['cpu_throttle']:
        entry['ineligible_reasons'].append(f'CPU throttling {s["cpu_throttle"]!r}: rows require throttling disabled')
    if entry['target'] is None:
        entry['ineligible_reasons'].append('device class not recognised from the user agent (not desktop / Android Chrome / iPhone Safari)')
    if entry['devtools'] not in ('closed', 'docked', 'undocked'):
        entry['ineligible_reasons'].append(f'devtools state {entry["devtools"]!r} unknown: row cannot be assigned')
    if entry['target'] in ('android-chrome', 'iphone-safari') and entry['devtools'] not in (None, 'closed'):
        entry['ineligible_reasons'].append('native phone rows are DevTools closed only')
    entry['eligible'] = not entry['ineligible_reasons']
    for run in data['runs']:
        entry['runs'].append(evaluate_run(run, s, data['display']))
    return entry


def build_matrix(entries):
    rows = {k: {'row': k, 'target': k.split('/')[0], 'devtools': k.split('/')[1], 'mode': k.split('/')[2],
                'verdict': 'UNVERIFIED', 'repetitions_required': THRESHOLDS['repetitions_required'],
                'valid_repetitions': 0, 'repetitions': [], 'rejected_attempts': [], 'non_complete_attempts': [], 'devices': [], 'viewports': [], 'dprs': [],
                'touch_points': [], 'note': None,
                'reason': 'no eligible native result file for this row'} for k in required_rows()}
    for e in entries:
        if not e['eligible']:
            continue
        for r in e['runs']:
            key = row_key(e['target'], e['devtools'], r['mode'])
            if key not in rows:
                continue
            row = rows[key]
            rec = {'file': e['file'], 'sha256': e['sha256'], 'run_index': r['index'], 'model_supplied': e['model_supplied'],
                   'touch_points': e['touch_points'], 'valid': r['valid'], 'verdict': r['verdict'], 'reasons': r['reasons'], 'thresholds_failed': r['thresholds_failed'],
                   'metrics': r['metrics']}
            if r['valid']:
                row['repetitions'].append(rec)
                row['valid_repetitions'] += 1
            elif r['result'] != 'COMPLETE':
                row['non_complete_attempts'].append(rec)  # aborted / short: preserved in the file, never counted either way
            else:
                row['rejected_attempts'].append(rec)
            if e['model_supplied'] not in row['devices']:
                row['devices'].append(e['model_supplied'])
            if e['touch_points'] not in row['touch_points']:
                row['touch_points'].append(e['touch_points'])
            if r['metrics'] and r['metrics']['viewport'] not in row['viewports']:
                row['viewports'].append(r['metrics']['viewport'])
            if r['metrics'] and r['metrics']['page_dpr'] not in row['dprs']:
                row['dprs'].append(r['metrics']['page_dpr'])
    for row in rows.values():
        if row['touch_points']:
            row['note'] = ('navigator.maxTouchPoints recorded per contributing export: '
                           + ', '.join(str(t) for t in row['touch_points'])
                           + ('; a touchscreen desktop (touch points > 0) still fills the desktop rows, the class comes from the UA OS token'
                              if row['target'] == 'desktop' and any(t for t in row['touch_points'] if t) else ''))
        n = row['valid_repetitions']
        if n < THRESHOLDS['repetitions_required']:
            row['verdict'] = 'UNVERIFIED'
            row['reason'] = (f'{n} valid repetition(s) < {THRESHOLDS["repetitions_required"]} required'
                             + (f'; {len(row["rejected_attempts"])} attempt(s) rejected' if row['rejected_attempts'] else '')
                             + (f'; {len(row["non_complete_attempts"])} non-complete attempt(s) preserved, not counted' if row['non_complete_attempts'] else '')
                             + ('' if n or row['rejected_attempts'] or row['non_complete_attempts'] else ' (no eligible native result file for this row)'))
            continue
        failing = [r for r in row['repetitions'] if r['verdict'] != 'PASS']
        if failing:
            row['verdict'] = 'FAIL'
            row['reason'] = f'{len(failing)} of {n} valid repetition(s) miss a threshold: ' + ' | '.join(
                f'run {r["run_index"]}: ' + '; '.join(r['thresholds_failed']) for r in failing)
        else:
            row['verdict'] = 'PASS'
            row['reason'] = f'all {n} valid repetitions meet every threshold'
    return rows


def docking_comparison(rows):
    """Docked/undocked vs closed at matched viewport (per mode); only attributes a cost when the viewports match."""
    out = {}
    for mode in MODES:
        closed = rows[row_key('desktop', 'closed', mode)]
        for state in ('docked', 'undocked'):
            other = rows[row_key('desktop', state, mode)]
            key = f'desktop/{state}-vs-closed/{mode}'
            if closed['verdict'] == 'UNVERIFIED' or other['verdict'] == 'UNVERIFIED':
                out[key] = {'comparable': False, 'reason': 'one or both rows UNVERIFIED'}
                continue
            if closed['viewports'] != other['viewports'] or len(closed['viewports']) != 1:
                out[key] = {'comparable': False, 'reason': f'viewports differ (closed {closed["viewports"]}, {state} {other["viewports"]}): '
                            'docking cost not attributed at unmatched viewport'}
                continue
            a = sum(r['metrics']['average_fps'] for r in closed['repetitions']) / len(closed['repetitions'])
            b = sum(r['metrics']['average_fps'] for r in other['repetitions']) / len(other['repetitions'])
            out[key] = {'comparable': True, 'viewport': closed['viewports'][0], 'closed_mean_fps': a, f'{state}_mean_fps': b,
                        'docking_cost_fps': a - b}
    return out


def evaluate(result_paths, package_root, notes=None):
    entries = [evaluate_file(Path(p), package_root) for p in result_paths]
    rows = build_matrix(entries)
    required = required_rows()
    verdicts = {k: rows[k]['verdict'] for k in required}
    counts = {v: sum(1 for x in verdicts.values() if x == v) for v in ('PASS', 'FAIL', 'UNVERIFIED')}
    package = None
    if package_root is not None and (Path(package_root) / 'game' / 'build.json').exists():
        b = json.loads((Path(package_root) / 'game' / 'build.json').read_text())
        package = {'source_revision': b['source_revision'], 'served_tree_sha256': b['served_tree_sha256'], 'build_version': b['build_version']}
    acceptance = {
        'task': 'TASK-284', 'generated_utc': bt.utc(), 'package': package, 'thresholds': THRESHOLDS,
        'normalisation': 'metrics come only from the recorded frame timestamps (interval == timestamp difference, enforced); '
                         'slow frames are never dropped; a gap is accepted only when the page recorded an inactive state covering it; '
                         'resolution/effects are never lowered by the evaluator and a run whose adaptive density reduced the backing cannot PASS',
        'required_rows': required, 'rows': [rows[k] for k in required], 'row_verdicts': verdicts, 'counts': counts,
        'docking_comparison': docking_comparison(rows),
        'result_files': entries,
        'unassigned_or_ineligible_files': [{'file': e['file'], 'sha256': e['sha256'], 'reasons': e['ineligible_reasons'],
                                            'model_supplied': e['model_supplied'], 'target': e['target'], 'touch_points': e['touch_points']}
                                           for e in entries if not e['eligible']],
    }
    all_pass = bool(required) and all(v == 'PASS' for v in verdicts.values())
    decision = {
        'task': 'TASK-284', 'generated_utc': acceptance['generated_utc'], 'package': package,
        'evaluation_completed': True,
        'evaluation_completed_meaning': 'every supplied export was validated and recomputed and every required row has a finite verdict '
                                        '(PASS / FAIL / UNVERIFIED); this is independent of the performance result',
        '60fps_achieved': all_pass,
        '60fps_achieved_rule': 'true only when every required actual-device row (desktop closed/docked/undocked, Android Chrome, iPhone Safari; '
                               'both modes) is PASS from three valid native repetitions each; server/headless results and fixture tests never fill native rows',
        'row_verdicts': verdicts, 'counts': counts,
        'unverified_rows': [k for k, v in verdicts.items() if v == 'UNVERIFIED'],
        'failed_rows': [k for k, v in verdicts.items() if v == 'FAIL'],
        'release_readiness_claimed': False,
    }
    if notes is not None:
        decision['residual_local_deficit'] = notes
    return acceptance, decision


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--package', default=str(HERE), help='built package root (game/build.json) the results must match')
    p.add_argument('--results', action='append', default=[], help='directory of exported result JSON files (repeatable)')
    p.add_argument('--file', action='append', default=[], help='single result file (repeatable)')
    p.add_argument('--acceptance', required=True)
    p.add_argument('--decision', required=True)
    p.add_argument('--notes', help='JSON file with the quantified local bottleneck / next hypothesis (embedded verbatim '
                                   'as decision.residual_local_deficit; never changes a verdict)')
    args = p.parse_args(argv)
    notes = json.loads(Path(args.notes).read_text()) if args.notes else None
    paths = list(args.file)
    for d in args.results:
        paths.extend(str(x) for x in sorted(Path(d).glob('*.json')))
    acceptance, decision = evaluate(paths, args.package, notes)
    Path(args.acceptance).write_text(json.dumps(acceptance, indent=1, sort_keys=True) + '\n')
    Path(args.decision).write_text(json.dumps(decision, indent=1, sort_keys=True) + '\n')
    print(json.dumps({'files': len(paths), 'row_verdicts': decision['row_verdicts'], 'counts': decision['counts'],
                      '60fps_achieved': decision['60fps_achieved'], 'evaluation_completed': decision['evaluation_completed']}, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
