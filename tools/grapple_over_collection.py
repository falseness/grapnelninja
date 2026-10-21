"""Cheap exact test selection and bounded, task-local redesign exports.

No browser launches during collection. Historical suites remain independently runnable.
"""
import argparse
import importlib
import json
import os
from pathlib import Path
import re
import unittest

from grapple_over_test_support import EvidenceWriter, ROOT


def exact_suite(module, name):
    if not re.fullmatch(r'Task[0-9]+Tests', name):
        raise ValueError('Expected exact TaskNNNTests class name')
    classes = [v for v in vars(module).values() if isinstance(v, type)
               and issubclass(v, unittest.TestCase) and v.__name__ == name]
    if len(classes) != 1:
        raise ValueError(f'Expected one class {name}; found {len(classes)} (duplicate aliases rejected)')
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(classes[0])
    ids = [test.id() for test in suite]
    if not ids or len(ids) != len(set(ids)) or any(i.split('.')[-2] != name for i in ids):
        raise ValueError('Empty, duplicate or substring-matched collection')
    return suite, ids


def export_encounter(section, encounter, filename):
    """Export only the requested planned encounter; never imply playable coverage."""
    blueprint = json.loads((ROOT/'docs/grapple-over-blueprint.json').read_text())
    s = next(s for s in blueprint['sections'] if s['id'] == section)
    e = next(e for e in s['encounters'] if e['id'] == encounter)
    writer = EvidenceWriter()
    writer.write(filename, dict(section=section, encounter=e, scope='planned reservation, not gameplay'))
    return writer.path(filename)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--module', default='test_grapple_over_redesign')
    parser.add_argument('--class', dest='name', required=True)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--export', nargs=2, metavar=('SECTION', 'ENCOUNTER'))
    args = parser.parse_args()
    try:
        suite, ids = exact_suite(importlib.import_module(args.module), args.name)
        print('\n'.join(ids)); print(f'COLLECTED {len(ids)} exact {args.name}')
        if args.export:
            if not os.environ.get('GRAPPLE_OVER_EVIDENCE_DIR'):
                raise ValueError('Declare GRAPPLE_OVER_EVIDENCE_DIR for export')
            print('EXPORTED', export_encounter(*args.export, 'encounter.json'))
    except (ValueError, StopIteration) as error:
        parser.error(str(error))
    if args.run:
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() and result.testsRun else 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
