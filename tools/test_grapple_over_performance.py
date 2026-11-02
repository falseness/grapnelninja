"""TASK-499: full-mountain runtime cost, measured and bounded.

Task499Tests:
  * test_01: matched old-mode comparison against the immutable TASK-444 baseline revision. For each of classic and bad,
    PAIRS pairs of warmed tools/perf_mobile.py runs (20 s window, 3 s warmup, seed 1, --no-trace); the two runs of a
    pair (baseline and final) run at the same time so both see the same host load, the launch order alternates and the
    modes interleave pair by pair (ABAB...). Each pair gives a ratio final/baseline of the frame-interval p95; the
    median of those per-pair ratios must stay within 1.10x. TASK-877: the old gate (median of 3 sequential p95s per
    revision, minutes apart) failed at 1.50 under host load 15.7 and passed alone. One extra grapple_over run proves
    the harness selects all three modes under the menu-less boot.
  * test_04: summary.json and source hashes of the tested worktree.

TASK-840 retired test_02_climb_scenes and test_03_soak (artifacts/TASK-840/retired.md): both replayed the TASK-496 v3
base-start route, replaced by the imported level in ba5ca11 (TASK-650) and off-screen at camera 0.25 since c2a6743 (TASK-688).

All timings here are headless Chromium on a shared host. Frame intervals come only from perf_mobile's real rAF loop, and even those
are only meaningful as baseline/final ratios on the same host.
"""
import hashlib
import json
import shlex
import statistics
import subprocess
import sys
import time
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

from grapple_over_test_support import ROOT, EvidenceWriter

BASELINE_REV = '9639e07'          # TASK-444's pre-change revision (artifacts/TASK-444/pre-change.json)
FINAL_REV = 'worktree'
OLD_MODES = ('classic', 'bad')
PAIRS = 6                         # concurrent baseline/final pairs per old mode (TASK-877)
RATIO_LIMIT = 1.10
HASHED_TOOLS = ['tools/perf_mobile.py', 'tools/browser_test_support.py', 'tools/grapple_over_test_support.py',
                'tools/test_grapple_over_performance.py', 'tools/test_grapple_over_completion.py',
                'tools/test_grapple_over_integration.py', 'tools/test_grapple_over_sections.py']


def source_hashes():
    names = subprocess.check_output(['git', 'ls-files'], cwd=ROOT, text=True).splitlines()
    names = [n for n in names if (n.endswith('.js') and not n.startswith('tools/')) or n == 'index.html'] + HASHED_TOOLS
    return {n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest() for n in sorted(names)}


class Task499Tests(unittest.TestCase):
    task_id = 'TASK-499'

    @classmethod
    def setUpClass(cls):
        cls.evidence = EvidenceWriter(cls.task_id)
        cls.hashes = source_hashes()
        cls.revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        cls.dirty = subprocess.check_output(['git', 'status', '--porcelain', '--', '.', ':!artifacts'],
                                            cwd=ROOT, text=True).splitlines()
        cls.evidence.log('CONFIG ' + json.dumps(dict(case='setUpClass', revision=cls.revision, dirty_paths=cls.dirty,
                                                     source_hashes=cls.hashes), sort_keys=True))

    # ---- cases ---------------------------------------------------------------------------------------------------
    def test_01_old_mode_matched_comparison(self):
        perf = self.evidence.path('perf/.keep').parent
        baseline_sha = subprocess.check_output(['git', 'rev-parse', BASELINE_REV], cwd=ROOT, text=True).strip()
        archived = json.loads((ROOT / 'artifacts/TASK-444/perf/classic-1.json').read_text())
        runs = {}

        def launch(rev, mode, repeat):
            out = perf / f'{rev}-{mode}-{repeat}.json'
            cmd = ['python3', 'tools/perf_mobile.py', '--rev', rev, '--mode', mode, '--seconds', '20', '--warmup', '3',
                   '--seed', '1', '--no-trace', '--out', str(out.relative_to(ROOT))]
            self.evidence.log('COMMAND ' + shlex.join(cmd))
            log = out.with_suffix('.log').open('w')
            return out, log, subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)

        def collect(rev, mode, repeat, launched, started):
            out, log, proc = launched
            code = proc.wait()
            log.close()
            self.evidence.log(f'EXIT {code} {out.name} wall_s={time.time() - started:.1f}')
            self.assertEqual(code, 0, out.with_suffix('.log').read_text()[-2000:])
            result = json.loads(out.read_text())
            self.assertEqual(result['page_errors'], [])
            self.assertEqual(result['selected']['mode'], mode)
            self.assertFalse(result['selected']['paused'])
            runs[rev, mode, repeat] = result
            return result

        def run_pair(mode, repeat):
            # Baseline and final run at the same time, so both see the same host load; the launch order alternates.
            pair = (BASELINE_REV, FINAL_REV) if repeat % 2 else (FINAL_REV, BASELINE_REV)
            started = time.time()
            launched = {rev: launch(rev, mode, repeat) for rev in pair}
            for rev in pair:
                collect(rev, mode, repeat, launched[rev], started)
            order.append('+'.join(f'{rev}-{mode}-{repeat}' for rev in pair))

        order = []
        for repeat in range(1, PAIRS + 1):          # ABAB...: the modes interleave pair by pair
            for mode in OLD_MODES:
                run_pair(mode, repeat)
        go_started = time.time()
        go = collect(FINAL_REV, 'grapple_over', 1, launch(FINAL_REV, 'grapple_over', 1), go_started)
        self.assertGreater(go['frames'], 0)
        self.assertEqual(go['selected']['flow'], 'boot run + menu.selectMode')

        results = list(runs.values())
        configs = {json.dumps([r['provenance']['browser_version'], r['emulation'], r['seconds'], r['seed'],
                               r['warmup_seconds'], r['provenance']['trace'], r['provenance']['harness_files_sha256'],
                               r['provenance']['runtime_scripts_sha256']], sort_keys=True) for r in results}
        self.assertEqual(len(configs), 1, 'every run must share browser and harness configuration')
        self.assertTrue(all(r['rev'] == baseline_sha for (rev, *_), r in runs.items() if rev == BASELINE_REV))
        final_revs = {r['rev'] for (rev, *_), r in runs.items() if rev == FINAL_REV}
        self.assertEqual(len(final_revs), 1, final_revs)
        reusable = (archived['provenance']['browser_version'] == results[0]['provenance']['browser_version'] and
                    archived['provenance']['harness_files_sha256'] == results[0]['provenance']['harness_files_sha256'])
        modes = {}
        for mode in OLD_MODES:
            row = {}
            for metric in ('frame_interval_ms_after_warmup', 'physics_ms', 'draw_ms'):
                base = [runs[BASELINE_REV, mode, i][metric]['p95'] for i in range(1, PAIRS + 1)]
                final = [runs[FINAL_REV, mode, i][metric]['p95'] for i in range(1, PAIRS + 1)]
                pair_ratios = [round(f / b, 4) for f, b in zip(final, base)]
                row[metric] = dict(baseline_p95=base, final_p95=final, pair_ratios=pair_ratios,
                                   ratio=round(statistics.median(pair_ratios), 4),
                                   ratio_of_medians=round(statistics.median(final) / statistics.median(base), 4))
            row['frames'] = dict(baseline=[runs[BASELINE_REV, mode, i]['frames'] for i in range(1, PAIRS + 1)],
                                 final=[runs[FINAL_REV, mode, i]['frames'] for i in range(1, PAIRS + 1)])
            modes[mode] = row
        comparison = dict(baseline_rev=baseline_sha, final_rev=final_revs.pop(), order=order, pairs=PAIRS,
                          gated_metric=f'median over {PAIRS} concurrent baseline/final pairs of the per-pair ratio '
                                       'frame_interval_ms_after_warmup.p95 final/baseline',
                          limit=RATIO_LIMIT, modes=modes,
                          archived_task444=dict(browser=archived['provenance']['browser_version'],
                                                harness_files_sha256=archived['provenance']['harness_files_sha256'],
                                                reused=False, reusable=reusable,
                                                reason='fresh paired baseline runs: the TASK-444 archive was made by an older perf_mobile.py '
                                                       '(different harness hash), so only fresh matched runs are compared'),
                          config=json.loads(configs.pop()),
                          grapple_over=dict(file=f'{FINAL_REV}-grapple_over-1.json', selected=go['selected'],
                                            frames=go['frames'], page_errors=go['page_errors']),
                          page_errors=sum(len(r['page_errors']) for r in runs.values()),
                          note='perf_mobile frame intervals are headless Chromium under a 4x CPU throttle on a shared '
                               'host; only the baseline/final ratio of runs made at the same time is meaningful, '
                               'not the absolute FPS')
        self.evidence.write('perf/comparison.json', comparison)
        for mode in OLD_MODES:
            self.assertLessEqual(modes[mode]['frame_interval_ms_after_warmup']['ratio'], RATIO_LIMIT, (mode, modes[mode]))

    def test_04_summary(self):
        comparison = json.loads(self.evidence.path('perf/comparison.json').read_text())
        now = source_hashes()
        self.assertEqual(now, self.hashes, 'sources changed during the run')
        gated = 'frame_interval_ms_after_warmup'
        ratios = {mode: row[gated]['ratio'] for mode, row in comparison['modes'].items()}
        # physics()/draw() wall time per call: reported for diagnosis, not the frame cost a player sees
        components = {mode: {k: row[k]['ratio'] for k in ('physics_ms', 'draw_ms')} for mode, row in comparison['modes'].items()}
        summary = dict(revision=self.revision, dirty_paths=self.dirty, source_hashes=now,
                       old_mode_p95_ratios=ratios, gated_metric=comparison['gated_metric'], limit=RATIO_LIMIT,
                       old_modes_pass=all(r <= RATIO_LIMIT for r in ratios.values()),
                       diagnostic_component_p95_ratios=components,
                       diagnostic_note='median per-pair p95 ratio of per-call physics()/draw() ms, not gated; see review.md',
                       browser_errors=comparison['page_errors'],
                       retired='climb scenes and soak (test_02/test_03) retired by TASK-840')
        self.evidence.write('perf/summary.json', summary)
        self.assertTrue(summary['old_modes_pass'])
        self.assertEqual(summary['browser_errors'], 0)


if __name__ == '__main__':
    unittest.main()
