"""Tests for the collision broad phase (collision/broadphase.js).

Helper cases run the real script in a page. The world-state test plays 1200
seeded ticks (render_snapshot's frozen clock and scripted input) on the base
revision and on the candidate and requires equal state hashes for bad and
classic. Candidate: the worktree if game files are dirty, else HEAD; base: the
parent of the commit that added collision/broadphase.js (HEAD if it is not
committed yet). Override with BROADPHASE_BASE / BROADPHASE_REV.
"""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import subprocess
import unittest

from browser_test_support import start_browser_test
from perf_mobile import SEED_SCRIPT, export_rev
import render_snapshot

ROOT = Path(__file__).resolve().parent.parent
TICKS = 1200
CHECKPOINT = 60
VIEWPORT = render_snapshot.VIEWPORTS[0]

# Every number that drives physics, serialized exactly (JSON numbers round-trip).
STATE_SCRIPT = '''() => JSON.stringify({
    tick: __snap.tick,
    ninja: [ninja.x, ninja.y, ninja.speedX, ninja.speedY],
    grapnel: [grapnel.throwed, grapnel.grappled, grapnel.pos.map(p => [p[0], p[1]])],
    screen: [screen.x, screen.y],
    floors: floors.map(f => f.elements.map(e =>
        [e.constructor.name, e.x, e.y, e.speedX, e.speedY, e.dx, e.dy]))
})'''


def default_revs():
    dirty = subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'],
                                    cwd=ROOT, text=True).strip()
    added = subprocess.check_output(['git', 'log', '--diff-filter=A', '--format=%H', '--', 'collision/broadphase.js'],
                                    cwd=ROOT, text=True).split()
    base = added[-1] + '~1' if added else 'HEAD'
    rev = 'worktree' if dirty else 'HEAD'
    return os.environ.get('BROADPHASE_BASE', base), os.environ.get('BROADPHASE_REV', rev)


def world_states(rev, modes):
    """{mode: {'rev', 'hash', 'checkpoints', 'final', 'broadphase'}} after TICKS ticks."""
    out = {}
    with ExitStack() as stack:
        root, rev_id = export_rev(rev, stack.callback)
        url, browser = start_browser_test(root, stack.callback)
        script = render_snapshot.input_script(render_snapshot.SEED, TICKS,
                                              VIEWPORT['width'], VIEWPORT['height'])
        for mode in modes:
            context = browser.new_context(viewport={'width': VIEWPORT['width'], 'height': VIEWPORT['height']},
                                          device_scale_factor=VIEWPORT['dpr'],
                                          is_mobile=True, has_touch=True)
            context.add_init_script(SEED_SCRIPT % render_snapshot.SEED)
            context.add_init_script(render_snapshot.CLOCK_SCRIPT)
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(url + 'index.html', wait_until='load')
            page.evaluate(render_snapshot.SETUP_SCRIPT, [script, True])
            page.evaluate('mode => startGame(mode)', mode)
            digest, checkpoints = hashlib.sha256(), []
            for tick in range(CHECKPOINT, TICKS + 1, CHECKPOINT):
                page.evaluate(render_snapshot.ADVANCE_SCRIPT, tick)
                state = page.evaluate(STATE_SCRIPT)
                checkpoints.append(hashlib.sha256(state.encode()).hexdigest())
                digest.update(state.encode())
            out[mode] = {'rev': rev_id, 'hash': digest.hexdigest(), 'checkpoints': checkpoints,
                         'final': json.loads(state), 'page_errors': errors,
                         'broadphase': page.evaluate('() => typeof pointsBounds == "function"')}
            context.close()
    return out


class BroadphaseHelperTest(unittest.TestCase):
    CASES = '''() => {
        const box = (l, t, r, b) => ({left: l, top: t, right: r, bottom: b})
        const square = [{x: 0, y: 0}, {x: 10, y: 0}, {x: 10, y: 10}, {x: 0, y: 10}]
        const tri = [{x: 5, y: -2}, {x: 9, y: 4}, {x: 1, y: 3}]
        const eps = defaultEqualityTolerance
        return {
            square: pointsBounds(square),
            triangle: pointsBounds(tri),
            padded: pointsBounds(square, 2),
            segment: segmentBounds(10, 5, 2, -3, 1),
            circle: circleBounds(5, 6, 2, 1),
            touching: boundsOverlap(box(0, 0, 10, 10), box(10, 0, 20, 10)),
            touchingCorner: boundsOverlap(box(0, 0, 10, 10), box(10, 10, 20, 20)),
            overlapping: boundsOverlap(box(0, 0, 10, 10), box(5, 5, 15, 15)),
            contained: boundsOverlap(box(0, 0, 10, 10), box(2, 2, 3, 3)),
            separatedX: boundsOverlap(box(0, 0, 10, 10), box(10.5, 0, 20, 10)),
            separatedY: boundsOverlap(box(0, 0, 10, 10), box(0, 10.5, 10, 20)),
            // Circle 0.5 short of the square: rejected bare, kept within tolerance.
            gapBare: boundsOverlap(circleBounds(12.5, 5, 2), pointsBounds(square)),
            gapTolerance: boundsOverlap(circleBounds(12.5, 5, 2, eps), pointsBounds(square)),
            gapBeyondTolerance: boundsOverlap(circleBounds(13.5 + eps, 5, 2, eps), pointsBounds(square)),
            // Exact test accepts a circle touching an edge: the broad phase must too.
            exactAccepts: collisionCircleWithLine(lineFormula(0, 0, 10, 0), 5, -1.9, 2),
            exactAcceptsKept: boundsOverlap(circleBounds(5, -1.9, 2, eps), pointsBounds(square)),
            eps
        }
    }'''

    @classmethod
    def setUpClass(cls):
        with ExitStack() as stack:
            url, browser = start_browser_test(ROOT, stack.callback)
            page = browser.new_page()
            page.goto(url + 'index.html', wait_until='load')
            cls.r = page.evaluate(cls.CASES)

    def test_bounds(self):
        r = self.r
        self.assertEqual(r['square'], {'left': 0, 'right': 10, 'top': 0, 'bottom': 10})
        self.assertEqual(r['triangle'], {'left': 1, 'right': 9, 'top': -2, 'bottom': 4})
        self.assertEqual(r['padded'], {'left': -2, 'right': 12, 'top': -2, 'bottom': 12})
        self.assertEqual(r['segment'], {'left': 1, 'right': 11, 'top': -4, 'bottom': 6})
        self.assertEqual(r['circle'], {'left': 2, 'right': 8, 'top': 3, 'bottom': 9})

    def test_touching_and_overlapping(self):
        for key in ('touching', 'touchingCorner', 'overlapping', 'contained'):
            self.assertTrue(self.r[key], key)

    def test_separated(self):
        for key in ('separatedX', 'separatedY', 'gapBare', 'gapBeyondTolerance'):
            self.assertFalse(self.r[key], key)

    def test_within_tolerance(self):
        self.assertEqual(self.r['eps'], 1)
        self.assertTrue(self.r['gapTolerance'])
        self.assertTrue(self.r['exactAccepts'])
        self.assertTrue(self.r['exactAcceptsKept'])


class WorldStateHashTest(unittest.TestCase):
    def test_world_state_equal_after_1200_ticks(self):
        base, rev = default_revs()
        modes = ['bad', 'classic']
        before, after = world_states(base, modes), world_states(rev, modes)
        for mode in modes:
            b, a = before[mode], after[mode]
            print(f'STATE_HASH mode={mode} ticks={TICKS} base={b["rev"]} hash={b["hash"]}', flush=True)
            print(f'STATE_HASH mode={mode} ticks={TICKS} head={a["rev"]} hash={a["hash"]}', flush=True)
            print(f'STATE_HASH mode={mode} equal={a["hash"] == b["hash"]} '
                  f'elements={sum(map(len, a["final"]["floors"]))} ninja={a["final"]["ninja"]}', flush=True)
            self.assertEqual(b['page_errors'], [])
            self.assertEqual(a['page_errors'], [])
            self.assertFalse(b['broadphase'], 'base revision already has the broad phase')
            self.assertTrue(a['broadphase'], 'candidate revision lacks the broad phase')
            self.assertEqual(a['final']['tick'], TICKS)
            self.assertGreater(sum(map(len, a['final']['floors'])), 0)
            self.assertEqual(b['checkpoints'], a['checkpoints'], mode)
            self.assertEqual(b['hash'], a['hash'], mode)


if __name__ == '__main__':
    unittest.main()
