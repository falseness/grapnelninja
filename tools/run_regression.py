#!/usr/bin/env python3
"""One regression runner for the browser/unit suites (TASK-811).

    python3 tools/run_regression.py --out DIR [--only NAME ...] [--skip-slow] [--timeout S]

Runs every suite below with cwd tools/, one after another. Each suite's evidence
env vars (*_EVIDENCE_DIR, GRAPPLE_OVER_EVIDENCE_DIR, RESIZE_SCREENS_DIR,
PAUSE_TIME_SHOTS, ... scanned from the suite source) point at the ABSOLUTE path
DIR/ev/<suite>, so nothing lands in tools/artifacts. Writes DIR/<suite>.log and one
JSON line per suite to DIR/summary.jsonl:
    {suite, exit, ran, failures, errors, skipped, seconds}
Screenshots/videos under DIR/ev/<suite> are deleted after a passing suite.
NAME may be a dotted unittest name (module.Class). Each suite runs in its own session;
on timeout the whole process group (plus any descendant that left it, e.g. browsers)
gets SIGTERM, then SIGKILL after KILL_GRACE s, so no workers/browsers outlive it (TASK-851).
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

# artifacts/TASK-797/run_checks.sh, run_checks2.sh, then the suites they missed.
SUITES = [
    'test_grapple_over_save', 'test_imported_level_runtime', 'test_climb_fall_recovery', 'test_platform',
    'test_analytics_wiring', 'test_analytics_facade', 'test_platform_backends', 'test_playgama_rewarded',
    'test_rewarded_backends', 'test_go_back', 'test_go_back_dialog', 'test_go_back_ad', 'test_hud_glyphs',
    'test_play_time', 'test_i18n', 'test_grapple_over_completion', 'test_grapple_over_visuals',
    'test_analytics_progression', 'test_analytics_quit', 'test_analytics_design', 'test_platform_facade',
    'test_progress', 'test_double_offer', 'test_fall_hint', 'test_long_fall_messages',
    'test_grapnel_menu_toggle', 'test_menu_fps_checkbox', 'test_climb_tutorial_legend', 'test_double_grapnel',
    'test_spawn_launch', 'test_safe_respawn', 'test_pause_time', 'test_continue', 'test_input', 'test_resize',
    'test_rotate_landscape', 'test_ab_switches', 'test_adaptive_quality', 'test_perf_overlay',
    'test_visualsperf_attribution', 'test_freeze_report', 'test_spire_route',
    'test_no_grapple_render', 'test_fast_restart',
]
SLOW = {'test_grapple_over_visuals'}  # about 25 min
TIMEOUT = 3600
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
            try:
                code = proc.wait(timeout=TIMEOUT)
            except subprocess.TimeoutExpired:
                kill_tree(proc)
                log.flush()
                log.write(f'\nTIMEOUT after {TIMEOUT}s\n')
                code = 124
    row = dict(suite=suite, exit=code, **counts((out / f'{suite}.log').read_text(errors='replace')),
               seconds=round(time.monotonic() - start, 1))
    if code == 0:
        for path in ev.rglob('*'):
            if path.suffix.lower() in MEDIA and path.is_file():
                path.unlink()
    return row


def main():
    global TIMEOUT
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--out', required=True, help='output dir (logs, summary.jsonl, ev/<suite>)')
    parser.add_argument('--only', nargs='+', metavar='NAME', help='run only these suites')
    parser.add_argument('--skip-slow', action='store_true', help='leave out ' + ', '.join(sorted(SLOW)))
    parser.add_argument('--timeout', type=int, default=TIMEOUT, help=f'per-suite timeout in s (default {TIMEOUT})')
    args = parser.parse_args()
    TIMEOUT = args.timeout
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
