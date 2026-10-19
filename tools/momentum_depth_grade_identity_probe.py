"""Momentum audit 6/14: graded pixels of the depth grade by score (TASK-093).

Per revision, viewport (844x390@3, 1280x720@1) and score (each depth stage
boundary and MID_SCORES inside the blends), two captures of the momentum
start scene (frozen clock, seeded course):
- cold: the score set, one draw() (the graded tiles built at once);
- ramped: RAMP_POINTS points up to the score, DRAWS_PER_POINT draw() calls
  per point, then the capture (on a tree with ahead-of-time rotation a
  step's tiles come from the job rotated over the earlier frames:
  stepChanges counts the draws reaching a new step, prepared those whose
  HueRotateJob was complete before it).
Each capture keeps the decoded frame and an FNV-1a hash of the graded far and
near tiles' pixels (getImageData; null at hue 0). Per REV:BASE pair the report
compares every capture of REV with the same capture of BASE: decoded maxDelta
and tile hash equality.

Usage: python3 momentum_depth_grade_identity_probe.py OUT.json REV:BASE...
(revisions 'worktree' or git revisions)
"""
import io
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import momentum_fx_support as fx
import render_snapshot
from momentum_depth_grade_perf_probe import open_page, VIEWPORTS

MID_SCORES = (100, 120, 380)
RAMP_POINTS = 12
DRAWS_PER_POINT = 16

CAPTURE = r'''([score, ramp, drawsPerPoint]) => {
    const bg = visualEffects.background, grade = bg.depthGrade
    let stepChanges = 0, prepared = 0
    const drawAt = s => {
        const hue = bg.getDepthHue(s)
        if (hue && hue !== grade.hue) {
            ++stepChanges
            if (grade.next && grade.next.hue === hue && grade.next.done) ++prepared
        }
        scoreText.count.momentum = s
        draw()
    }
    for (let s = Math.max(0, score - ramp); s < score; ++s)
        for (let k = 0; k < drawsPerPoint; ++k)
            drawAt(s)
    const hue = bg.getDepthHue(score)
    drawAt(score)
    const hash = tile => {
        const c = tile.canvas, data = c.getContext('2d').getImageData(0, 0, c.width, c.height).data
        let h = 0x811c9dc5
        for (let i = 0; i < data.length; ++i)
            h = Math.imul(h ^ data[i], 16777619)
        return [c.width, c.height, (h >>> 0).toString(16)].join(':')
    }
    const tiles = hue && grade.tiles ? {far: hash(grade.tiles.far), near: hash(grade.tiles.near)} : null
    return {score, hue, rebuilds: grade.rebuilds, stepChanges, prepared, tiles}
}'''


def captures(rev, scores):
    tree = fx.harness(rev)
    out = {}
    for w, h, dpr in VIEWPORTS:
        for score in scores:
            for mode, ramp in (('cold', 0), ('ramped', RAMP_POINTS)):
                context, page = open_page(tree, w, h, dpr)
                try:
                    info = page.evaluate(CAPTURE, [score, ramp, DRAWS_PER_POINT])
                    png = render_snapshot.png_bytes(page.evaluate('() => __snap.capture()'))
                    if page.errors:
                        raise RuntimeError(f'page errors: {page.errors}')
                finally:
                    context.close()
                frame = np.asarray(Image.open(io.BytesIO(png)).convert('RGBA'), np.int16)
                key = (f'{w}x{h}@{dpr}', score, mode)
                out[key] = (info, frame)
                print(rev, key, info)
    return tree.rev, out


def main(out, pairs):
    stages = [0, 150, 400]
    scores = stages + list(MID_SCORES)
    taken = {}
    try:
        for pair in pairs:
            for rev in pair.split(':'):
                if rev not in taken:
                    taken[rev] = captures(rev, scores)
    finally:
        fx.close()
    reports = []
    for pair in pairs:
        rev, base = pair.split(':')
        (rev_sha, mine), (base_sha, theirs) = taken[rev], taken[base]
        rows = []
        for key, (info, frame) in mine.items():
            base_info, base_frame = theirs[key]
            rows.append({'viewport': key[0], 'score': key[1], 'mode': key[2], 'hue': info['hue'],
                         'stageBoundary': key[1] in stages, 'stepChanges': info['stepChanges'],
                         'prepared': info['prepared'],
                         'maxDelta': int(np.abs(frame - base_frame).max()) if frame.shape == base_frame.shape else None,
                         'tiles': info['tiles'], 'baseTiles': base_info['tiles'],
                         'tilesEqual': info['tiles'] == base_info['tiles']})
        report = {'rev': rev_sha, 'base': base_sha, 'captures': len(rows),
                  'maxDelta': max(r['maxDelta'] if r['maxDelta'] is not None else 999 for r in rows),
                  'allTilesEqual': all(r['tilesEqual'] for r in rows),
                  'rampStepChanges': sum(r['stepChanges'] for r in rows if r['mode'] == 'ramped'),
                  'rampPrepared': sum(r['prepared'] for r in rows if r['mode'] == 'ramped'), 'rows': rows}
        print({k: v for k, v in report.items() if k != 'rows'})
        reports.append(report)
    result = {'scores': scores, 'stageScores': stages, 'midScores': list(MID_SCORES), 'rampPoints': RAMP_POINTS,
              'drawsPerPoint': DRAWS_PER_POINT, 'pairs': reports}
    Path(out).write_text(json.dumps(result, separators=(',', ':')))
    return result


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2:])
