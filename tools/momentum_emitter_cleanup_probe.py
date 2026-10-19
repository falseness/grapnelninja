"""TASK-096: the dead emitter list / extra-pass removal leaves every frame equal.

Usage: python3 momentum_emitter_cleanup_probe.py OUT NEW:OLD [NEW:OLD ...]
Each pair captures the 4 momentum_fx_support scenes at both viewports with
MOMENTUM_FX on and off, plus 'blue-touched' (the blue-hit scene with its blue
touched this frame: MomentumBlue.onNinjaPass, so the pop is drawn and the blue
light gone), in NEW and OLD (git revs or 'worktree') and records the decoded
maxDelta per capture. OUT gets compact JSON with allEqual.
"""
import json
import sys

import momentum_fx_support as fx

TOUCH_JS = """() => {
    for (const floor of floors)
        for (const element of floor.elements)
            if (element instanceof MomentumBlue)
                element.onNinjaPass(ninja)
}"""

CASES = [(scene, None, fx_on) for scene in fx.SCENES for fx_on in (True, False)] \
    + [('blue-hit', 'blue-touched', True)]


def main(out, pairs):
    results = []
    try:
        for pair in pairs:
            new, old = pair.split(':')
            for scene, label, fx_on in CASES:
                extra = TOUCH_JS if label else None
                for viewport in fx.VIEWPORTS:
                    a = fx.capture(scene, viewport, fx_on, extra, rev=new)
                    b = fx.capture(scene, viewport, fx_on, extra, rev=old)
                    results.append({'new': a.info['rev'], 'old': b.info['rev'],
                                    'scene': label or scene, 'viewport': list(viewport),
                                    'fx': fx_on, 'maxDelta': int(fx.max_delta(a, b))})
                    print(results[-1], flush=True)
    finally:
        fx.close()
    report = {'captures': len(results), 'allEqual': all(r['maxDelta'] == 0 for r in results),
              'results': results}
    with open(out, 'w') as f:
        json.dump(report, f, separators=(',', ':'))
    print('allEqual', report['allEqual'], 'captures', len(results))
    return 0 if report['allEqual'] else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1], sys.argv[2:]))
