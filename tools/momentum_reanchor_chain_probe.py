"""Which commits change the depth-grade and wall-veins parent checks (TASK-100).

For each rev (argv, oldest first, 'worktree' allowed) captures the
test_momentum_depth_grade score 0 frame (run-right, 1280x720) and runs the
test_momentum_wall_veins TASK-050 collision run (1200 ticks), and records
per rev the frame sha / maxDelta and the cycles / line log sha / differing
cycles against the previous rev and against --ref (default 9174492). Writes
compact JSON to --out.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import momentum_fx_support as fx
from test_momentum_depth_grade import score_frame
from test_momentum_wall_veins import collision_run

ROOT = Path(__file__).resolve().parents[1]


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else json.dumps(value).encode()).hexdigest()


def subject(rev):
    if rev == 'worktree':
        return 'worktree'
    return subprocess.check_output(['git', 'log', '-1', '--format=%h %s', rev], cwd=ROOT, text=True).strip()[:72]


def sample(rev):
    h = fx.harness(rev)
    frame = score_frame(h, 0)
    run = collision_run(h)
    return {'rev': h.rev, 'subject': subject(rev), 'frame': frame, 'cycles': run['cycles'],
            'lineLog': run['lineLog'], 'borderTouches': run['borderTouches'], 'veinFrames': run['veinFrames']}


def compare(a, b):
    return {'depthMaxDelta': fx.max_delta(a['frame'], b['frame']),
            'cyclesIdentical': a['cycles'] == b['cycles'], 'linesEqual': a['lineLog'] == b['lineLog'],
            'differingCycles': sum(1 for p, q in zip(a['cycles'], b['cycles']) if p != q)
            + abs(len(a['cycles']) - len(b['cycles']))}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('revs', nargs='+')
    parser.add_argument('--ref', default='9174492')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    try:
        ref = sample(args.ref)
        rows, prev = [], None
        for rev in args.revs:
            s = sample(rev)
            row = {'rev': s['rev'], 'subject': s['subject'], 'frameSha': sha(s['frame'].tobytes()),
                   'cyclesSha': sha(s['cycles']), 'linesSha': sha(s['lineLog']), 'cycles': len(s['cycles']),
                   'borderTouches': s['borderTouches'], 'veinFrames': s['veinFrames'],
                   'vsPrev': compare(s, prev) if prev else None, 'vsRef': compare(s, ref)}
            print(json.dumps(row, separators=(',', ':')), flush=True)
            rows.append(row)
            prev = s
    finally:
        fx.close()
    Path(args.out).write_text(json.dumps({'ref': ref['rev'], 'rows': rows}, separators=(',', ':')))


if __name__ == '__main__':
    main()
