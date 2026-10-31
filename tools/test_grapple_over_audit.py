"""TASK-500 delivery audit of Grapple Over: the live runtime manifest and repository hygiene.

Task500Tests reads the live mountain manifest and mode constants, checks that no evidence is tracked or staged, and writes
audit.json / delivery.json. All evidence goes under GRAPPLE_OVER_EVIDENCE_DIR (default artifacts/TASK-500). The archived
TASK-444..499 prerequisite check and the TASK-496/497 completion replays were retired by TASK-840 (artifacts/TASK-840/retired.md).
"""
import hashlib
import json
import subprocess
import unittest

from browser_test_support import start_browser_test, wait_for_boot
from grapple_over_test_support import ROOT, VIEWPORT, EvidenceWriter

FIRST_SCOPE_COMMIT = '9de4a6c'  # TASK-444
DELIVERY_JS = '''() => { const m = GRAPPLE_OVER_MOUNTAIN, d = MODE_DEFINITIONS.grapple_over;
    let validation = 'ok'; try { validateMountainManifest(m) } catch (e) { validation = String(e.message) }
    const keys = []; const walk = (v, p) => { if (!v || typeof v !== 'object') return;
        for (const [k, x] of Object.entries(v)) { if (/checkpoint|respawn|highestProgress/i.test(k)) keys.push(p + '.' + k); walk(x, p + '.' + k) } };
    walk(m, 'mountain');
    const roles = {}; for (const e of m.geometry.elements) roles[e.role] = (roles[e.role] || 0) + 1;
    return {sections: m.sections.map(s => ({id: s.id, status: s.status, designVersion: s.designVersion,
            landmark: s.landmark ? {id: s.landmark.id, name: s.landmark.name} : null})),
        encounters: m.encounters.map(e => ({id: e.id, section: e.section})),
        shortcuts: m.shortcuts.map(s => ({id: s.id, from: s.from, to: s.to, status: s.status, optional: s.optional})),
        recoveries: m.recoveries.map(r => ({id: r.id, from: r.from, to: r.to, status: r.status})),
        roles, movers: m.geometry.movers.length, range: m.range, validation, checkpoint_keys: keys,
        definition: {cameraScale: d.cameraScale, acquisitionRadius: d.acquisitionRadius,
            upgradedAcquisitionRadius: d.upgradedAcquisitionRadius, rangeUpgradeSection: d.rangeUpgradeSection},
        old_modes: {classic: MODE_DEFINITIONS.classic.cameraScale, bad: MODE_DEFINITIONS.bad.cameraScale},
        difficulty: m.difficulty, recoveryPolicy: m.recoveryPolicy, completion: m.completion, finish: m.finish,
        boot: {mode: version, run: runInProgress, paused: !!menu.gamePaused}} }'''


def sha(data):
    return hashlib.sha256(data).hexdigest()


def tested_hashes():
    from grapple_over_verify import hashes
    result = hashes()
    for name in ('test_grapple_over_completion.py', 'test_grapple_over_integration.py', 'test_grapple_over_audit.py',
                 'test_grapple_over_regression.py'):
        result['tools/' + name] = sha((ROOT / 'tools' / name).read_bytes())
    return dict(sorted(result.items()))


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True)


class Task500Tests(unittest.TestCase):
    """Final Grapple Over delivery audit (TASK-444..499 plus this ticket)."""
    task_id = 'TASK-500'

    @classmethod
    def setUpClass(cls):
        cls.evidence = EvidenceWriter(cls.task_id)
        cls.url, browser = start_browser_test(ROOT, cls.addClassCleanup)
        cls.chromium = browser
        cls.hashes = tested_hashes()
        cls.revision = git('rev-parse', 'HEAD').strip()
        cls.dirty = git('status', '--porcelain', '--', '.', ':!artifacts').splitlines()
        cls.config = dict(browser=browser.version, browser_name='chromium (Playwright, headless)', desktop_viewport=VIEWPORT,
                          device_scale_factor=1, hz=60, seed=1, revision=cls.revision,
                          dirty_paths=cls.dirty, source_hashes=cls.hashes)
        cls.evidence.log('CONFIG ' + json.dumps(cls.config, sort_keys=True, separators=(',', ':')))

    # ---- cases ----------------------------------------------------------------------------------
    # TASK-840 retired test_01_prerequisites, test_03_desktop_completion, test_04_touch_completion and
    # test_05_replay_audit_and_media (see artifacts/TASK-840/retired.md): the runtime changed after 419e0ba from daca189
    # (TASK-558) on, and the TASK-496/497 base-start routes they replay were replaced by the imported level in ba5ca11
    # (TASK-650), off-screen at camera 0.25 since c2a6743 (TASK-688).
    def test_02_runtime_delivery(self):
        """The live runtime: manifest counts, rules and constants, and the boot state."""
        page = self.chromium.new_page(viewport=VIEWPORT); page.goto(self.url); wait_for_boot(page)
        live = page.evaluate(DELIVERY_JS)
        page.close()
        sections, encounters = live['sections'], live['encounters']
        self.assertEqual([s['id'] for s in sections], ['S0%d' % i for i in range(1, 9)])
        self.assertTrue(all(s['status'] == 'built' and s['designVersion'] == 3 for s in sections))
        names = [s['landmark']['name'] for s in sections]
        self.assertEqual(len(set(names)), 8)
        self.assertEqual(len(encounters), 32)
        self.assertEqual({s['id']: sum(e['section'] == s['id'] for e in encounters) for s in sections}, {s['id']: 4 for s in sections})
        self.assertEqual(len(live['shortcuts']), 2)
        self.assertTrue(all(s['status'] == 'built' and s['optional'] for s in live['shortcuts']))
        self.assertEqual(live['validation'], 'ok')
        self.assertEqual(live['checkpoint_keys'], [])
        self.assertEqual(live['recoveryPolicy'], 'Physical falls, nonlethal hazards, current-state saves; no automatic relocation')
        self.assertEqual(live['definition'], dict(cameraScale=0.25, acquisitionRadius=1080, upgradedAcquisitionRadius=1620, rangeUpgradeSection='S05'))
        self.assertEqual(live['range'], dict(base=1080, upgraded=1620, upgradeBand='S05'))
        self.assertEqual(live['old_modes'], dict(classic=1, bad=1/2.2))
        self.assertEqual(live['boot'], dict(mode='grapple_over', run=True, paused=False))
        self.assertIs(live['difficulty']['validated'], False)
        self.assertTrue(all(r['status'] == 'built' for r in live['recoveries']), live['recoveries'])
        # The Chromium smoke (completion.smoke) is not run here since TASK-840: its attachment step replays the TASK-496
        # v3 base-start route, replaced by the imported level in ba5ca11 (TASK-650) and off-screen at camera 0.25 (c2a6743).
        self.evidence.write('parts/runtime.json', dict(live=live, landmark_names=names))
        print('PASS runtime delivery: 8 built v3 sections, %d distinct landmarks, 32 encounters (4 per section), 2 optional built '
              'shortcuts, %d built recoveries, validateMountainManifest ok, 0 checkpoint keys, range %d/%d at cameraScale %.3f, boots '
              'into grapple_over' % (len(set(names)), len(live['recoveries']), live['definition']['acquisitionRadius'],
              live['definition']['upgradedAcquisitionRadius'], live['definition']['cameraScale']), flush=True)

    def test_06_delivery_and_audit(self):
        """delivery.json and audit.json from the runtime part; repository hygiene; unchanged hashes during the run.
        TASK-840: the prerequisites/desktop/touch/media parts and their requirements were retired with test_01/03/04/05."""
        path = self.evidence.path('parts/runtime.json')
        self.assertTrue(path.exists(), 'missing part runtime')
        live = json.loads(path.read_text())
        self.assertEqual(tested_hashes(), self.hashes, 'tested files changed during the run')
        staged = git('diff', '--cached', '--name-only').split()
        status = git('status', '--short').splitlines()
        forbidden = [p for p in staged + [l[3:] for l in status] if p.startswith(('artifacts', 'screenshots'))]
        self.assertEqual(forbidden, [])
        ignored = subprocess.run(['git', 'check-ignore', 'artifacts/TASK-500/x', 'screenshots/x'], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(ignored.returncode, 0)
        # No tracked evidence, and no commit since TASK-444 touched artifacts/ or screenshots/. 38 screenshots/ files committed by
        # TASK-001..017 (June, before the ignore rule) remain tracked; they predate this scope and are reported, not removed.
        tracked = git('ls-files', 'artifacts').split()
        self.assertEqual(tracked, [])
        legacy_screenshots = git('ls-files', 'screenshots').split()
        scope_touched = git('log', '--format=', '--name-only', FIRST_SCOPE_COMMIT + '^..HEAD', '--', 'artifacts', 'screenshots').split()
        self.assertEqual(scope_touched, [])
        legacy_added = git('log', '--format=%h %s', '--diff-filter=A', FIRST_SCOPE_COMMIT + '^..HEAD', '--', 'screenshots').split()
        self.assertEqual(legacy_added, [])
        d = live['live']['definition']
        runtime_only = {k: v for k, v in self.hashes.items() if not k.startswith('tools/')}
        delivery = dict(revision=self.revision, dirty_paths=self.dirty,
            sections=len(live['live']['sections']), landmarks=live['landmark_names'], distinct_landmarks=len(set(live['landmark_names'])),
            encounters=len(live['live']['encounters']), shortcuts=[s['id'] for s in live['live']['shortcuts']], shortcut_count=len(live['live']['shortcuts']),
            checkpoints=len(live['live']['checkpoint_keys']), checkpoint_keys=live['live']['checkpoint_keys'],
            recovery_policy=live['live']['recoveryPolicy'], recoveries=len(live['live']['recoveries']), startup=live['live']['boot'],
            acquisition=dict(units=d['acquisitionRadius'], camera_scale=d['cameraScale'], upgraded_units=d['upgradedAcquisitionRadius'],
                             upgrade_section=d['rangeUpgradeSection']),
            scale=dict(grapple_over=d['cameraScale'], classic=live['live']['old_modes']['classic'], bad=live['live']['old_modes']['bad']),
            runtime_hashes=runtime_only, level_sha256=self.hashes['fixedlevel.js'], mountain_sha256=self.hashes['mountain.js'])
        self.evidence.write('delivery.json', delivery)
        requirements = {
            '32 authored encounters': (delivery['encounters'] == 32, ['parts/runtime.json']),
            'eight distinct landmarks': (delivery['distinct_landmarks'] == 8, ['parts/runtime.json']),
            'two optional shortcuts': (delivery['shortcut_count'] == 2, ['parts/runtime.json']),
            'recovery routes': (all(r['status'] == 'built' for r in live['live']['recoveries']), ['parts/runtime.json']),
            'startup': (live['live']['boot']['mode'] == 'grapple_over', ['parts/runtime.json']),
            'no checkpoints': (delivery['checkpoints'] == 0, ['parts/runtime.json']),
            'evidence untracked and nothing staged': (forbidden == [] and tracked == [] and scope_touched == [], ['commands.log', 'audit.json']),
        }
        audit = dict(revision=self.revision, scope='TASK-500 runtime delivery and repository hygiene (TASK-840 scope)',
            requirements={k: dict(passed=bool(v[0]), artifacts=v[1]) for k, v in requirements.items()},
            staged=staged, status_short=status, tracked_artifacts=tracked, scope_commits_touching_artifacts_or_screenshots=scope_touched,
            legacy_tracked_screenshots=dict(count=len(legacy_screenshots), files=legacy_screenshots,
                note='committed by TASK-001..017 before the ignore rule; outside TASK-444..500; left for the user to untrack'),
            failed=[k for k, v in requirements.items() if not v[0]])
        audit['passed'] = audit['failed'] == []
        self.evidence.write('audit.json', audit)
        self.evidence.log('GIT staged=%r status_short=%r tracked_artifacts=%r scope_touched=%r legacy_tracked_screenshots=%d'
                          % (staged, status, tracked, scope_touched, len(legacy_screenshots)))
        self.assertEqual(audit['failed'], [])
        print('PASS delivery audit: %d/%d requirements; 8 sections, 32 encounters, 2 shortcuts, 0 checkpoints, %d units at %.3f; '
              'nothing under artifacts/ or screenshots/ staged or tracked' % (sum(v[0] for v in requirements.values()), len(requirements),
              d['acquisitionRadius'], d['cameraScale']), flush=True)


if __name__ == '__main__':
    unittest.main()
