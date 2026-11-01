#!/usr/bin/env python3
"""One regression runner for the browser/unit suites (TASK-811).

    python3 tools/run_regression.py --out DIR [--only NAME ...] [--skip-slow] [--timeout S]

Runs every tools/test_*.py (sorted, minus EXCLUDE) with cwd tools/, one after another. Each suite's evidence
env vars (*_EVIDENCE_DIR, GRAPPLE_OVER_EVIDENCE_DIR, RESIZE_SCREENS_DIR,
PAUSE_TIME_SHOTS, ... scanned from the suite source) point at the ABSOLUTE path
DIR/ev/<suite>, so nothing lands in tools/artifacts. Writes DIR/<suite>.log and one
JSON line per suite to DIR/summary.jsonl:
    {suite, exit, ran, failures, errors, skipped, seconds}
Screenshots/videos under DIR/ev/<suite> are deleted after a passing suite.
NAME may be a dotted unittest name (module.Class). Each suite runs in its own session;
on timeout the whole process group (plus any descendant that left it, e.g. browsers)
gets SIGTERM, then SIGKILL after KILL_GRACE s, so no workers/browsers outlive it (TASK-851).
Per-suite timeout: TIMEOUTS[suite], else TIMEOUT; --timeout S sets it for every suite.
Exits 1 when any suite fails.
"""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

TOOLS = Path(__file__).resolve().parent

# Every tools/test_*.py runs (TASK-852); the hand-picked TASK-811 list missed 112 suites and they rotted.
# EXCLUDE = {suite: reason}; a reason is never just "fails": a red suite gets fixed, not excluded.
EXCLUDE = {}


def discover():
    """sorted tools/test_*.py module names minus EXCLUDE."""
    return [p.stem for p in sorted(TOOLS.glob('test_*.py')) if p.stem not in EXCLUDE]


SUITES = discover()
# Suites that take more than 10 min each (TASK-812 timings); --skip-slow leaves them out.
SLOW = {
    'test_grapple_over_visuals', 'test_grapple_over_redesign', 'test_grapple_over_sections',
    'test_grapple_over_regression', 'test_route_shortcuts', 'test_opening_jump_variety', 'test_extended_opening',
    'test_level_route_arrows', 'test_purple_route',
}
TIMEOUT = 3600  # default per-suite timeout in s
# Per-suite overrides. test_route_shortcuts' full matrix took 5092 s (TASK-773) and 9600 s (TASK-774);
# test_grapple_over_sections took 21409 s (131 tests) and runs 190 tests at about 100 s each (TASK-852);
# test_grapple_over_redesign 3109 s, test_opening_jump_variety 2045 s, test_grapple_over_visuals 2031 s.
TIMEOUTS = {
    'test_route_shortcuts': 6 * 3600,
    'test_grapple_over_regression': 6 * 3600,  # Task498 re-runs Task444..497 and the shared-system suites
    'test_grapple_over_redesign': 3 * 3600,
    'test_grapple_over_sections': 8 * 3600,
    'test_opening_jump_variety': 2 * 3600,
    'test_grapple_over_visuals': 2 * 3600,
}
TIMEOUT_FORCED = False  # set by --timeout
KILL_GRACE = 10  # seconds between SIGTERM and SIGKILL of a timed-out suite
EVIDENCE_VAR = re.compile(r"\b([A-Z0-9_]+_(?:EVIDENCE_DIR|SCREENS_DIR|SHOTS))\b")
MEDIA = {'.png', '.jpg', '.jpeg', '.webp', '.webm', '.mp4', '.gif'}


def evidence_env(suite, ev):
    source = TOOLS / f"{suite.split('.')[0]}.py"
    names = set(EVIDENCE_VAR.findall(source.read_text()) if source.exists() else []) | {'GRAPPLE_OVER_EVIDENCE_DIR'}
    return {name: str(ev / name.lower()) if name in ('RESIZE_SCREENS_DIR', 'PAUSE_TIME_SHOTS') else str(ev)
            for name in sorted(names)}


def counts(text):
    ran = re.findall(r'^Ran (\d+) tests?', text, re.M)
    tail = re.findall(r'^(?:OK|FAILED)(?: \((.*)\))?$', text, re.M)
    out = dict(ran=int(ran[-1]) if ran else 0, failures=0, errors=0, skipped=0)
    for key, value in re.findall(r'(failures|errors|skipped)=(\d+)', (tail[-1] if tail else '') or ''):
        out[key] = int(value)
    return out


def descendants(root):
    """pids of every live descendant of root (from /proc), deepest last."""
    children = {}
    for stat in Path('/proc').glob('[0-9]*/stat'):
        try:
            fields = stat.read_text().rsplit(')', 1)[1].split()
        except OSError:
            continue
        children.setdefault(int(fields[1]), []).append(int(stat.parent.name))
    out, todo = [], [root]
    while todo:
        for pid in children.get(todo.pop(), []):
            out.append(pid)
            todo.append(pid)
    return out


def signal_all(pgid, pids, sig):
    for target, send in [(pgid, os.killpg)] + [(pid, os.kill) for pid in pids]:
        try:
            send(target, sig)
        except (ProcessLookupError, PermissionError):
            pass


def alive(pgid, pids):
    for target, send in [(pgid, os.killpg)] + [(pid, os.kill) for pid in pids]:
        try:
            send(target, 0)
            return True
        except ProcessLookupError:
            pass
        except PermissionError:
            return True
    return False


def kill_tree(proc):
    """SIGTERM the suite's process group and descendants, wait KILL_GRACE s, then SIGKILL them."""
    pids = descendants(proc.pid)
    signal_all(proc.pid, pids, signal.SIGTERM)
    deadline = time.monotonic() + KILL_GRACE
    while time.monotonic() < deadline:
        proc.poll()
        pids += [pid for pid in descendants(proc.pid) if pid not in pids]
        if proc.returncode is not None and not alive(proc.pid, pids):
            break
        time.sleep(0.1)
    signal_all(proc.pid, pids, signal.SIGKILL)
    proc.wait()


def suite_timeout(suite):
    """TIMEOUTS[module] when set, else TIMEOUT (--timeout overrides both)."""
    return TIMEOUT if TIMEOUT_FORCED else TIMEOUTS.get(suite.split('.')[0], TIMEOUT)


def run_suite(suite, out):
    ev = (out / 'ev' / suite).resolve()
    ev.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, **evidence_env(suite, ev)}
    start = time.monotonic()
    with open(out / f'{suite}.log', 'w') as log:
        module = suite.split('.')[0]
        if not (TOOLS / f'{module}.py').exists():
            log.write(f'missing suite tools/{module}.py\n')
            code = 2
        else:
            proc = subprocess.Popen([sys.executable, '-m', 'unittest', '-v', suite], cwd=TOOLS, env=env,
                                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            limit = suite_timeout(suite)
            try:
                code = proc.wait(timeout=limit)
            except subprocess.TimeoutExpired:
                kill_tree(proc)
                log.flush()
                log.write(f'\nTIMEOUT after {limit}s\n')
                code = 124
    row = dict(suite=suite, exit=code, **counts((out / f'{suite}.log').read_text(errors='replace')),
               seconds=round(time.monotonic() - start, 1))
    if code == 0:
        for path in ev.rglob('*'):
            if path.suffix.lower() in MEDIA and path.is_file():
                path.unlink()
    return row


def main():
    global TIMEOUT, TIMEOUT_FORCED
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--out', required=True, help='output dir (logs, summary.jsonl, ev/<suite>)')
    parser.add_argument('--only', nargs='+', metavar='NAME', help='run only these suites')
    parser.add_argument('--skip-slow', action='store_true', help='leave out ' + ', '.join(sorted(SLOW)))
    parser.add_argument('--timeout', type=int, help=f'per-suite timeout in s for every suite '
                        f'(default {TIMEOUT}, longer for ' + ', '.join(sorted(TIMEOUTS)) + ')')
    args = parser.parse_args()
    if args.timeout is not None:
        TIMEOUT, TIMEOUT_FORCED = args.timeout, True
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    suites = args.only or [s for s in SUITES if not (args.skip_slow and s in SLOW)]
    summary = out / 'summary.jsonl'
    summary.write_text('')
    failed = []
    for suite in suites:
        row = run_suite(suite, out)
        with open(summary, 'a') as f:
            f.write(json.dumps(row, separators=(',', ':')) + '\n')
        print(json.dumps(row, separators=(',', ':')), flush=True)
        if row['exit'] != 0:
            failed.append(suite)
    code = 1 if failed else 0
    print(f'run_regression: {len(suites)} suites, {len(failed)} failed{": " + " ".join(failed) if failed else ""}; exit {code}',
          flush=True)
    return code


if __name__ == '__main__':
    sys.exit(main())
