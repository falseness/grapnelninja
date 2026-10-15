"""Test-only encounter setup and lossless attempt recording through production physics.

No keyboard/teleport controls are installed. Call spawn only before stepping/input.
All attempts (including exceptions) are retained in a unique task-local directory.
"""
from contextlib import contextmanager
import hashlib
import json
import uuid

from grapple_over_test_support import ROOT, EvidenceWriter


def install_recorder(page):
    page.evaluate('cancelAnimationFrame(game); window.requestAnimationFrame=()=>0')
    page.add_script_tag(path=str(ROOT / 'tools/grapple_over_injector.js'))


def state_hash(state):
    return hashlib.sha256(json.dumps(state, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def export_recording(page):
    attempts = page.evaluate('GRAPPLE_OVER_TEST.attempts')
    for attempt in attempts:
        for row in attempt['snapshots']:
            row['sha256'] = state_hash(row['state'])
    return attempts


@contextmanager
def recorded_attempt(page, name, evidence=None):
    evidence = evidence or EvidenceWriter('TASK-461')
    prefix = 'attempts/' + uuid.uuid4().hex
    page.evaluate('name=>GRAPPLE_OVER_TEST.begin(name)', name)
    outcome = 'failed'
    try:
        yield
        outcome = 'passed'
    finally:
        page.evaluate('outcome=>GRAPPLE_OVER_TEST.finish(outcome)', outcome)
        evidence.write(prefix + '/recording.json', export_recording(page)[-1])
        page.evaluate('draw()')
        page.screenshot(path=str(evidence.path(prefix + '/final.png')))
