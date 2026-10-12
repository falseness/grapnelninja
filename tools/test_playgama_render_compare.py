"""Synthetic arithmetic/validation tests only: never FPS evidence."""
import copy
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from playgama_render_compare import PROTOCOL, summarize, aggregate, audit, write, sha, FIXTURE, SEED, INPUT


def raw():
    off = {'pause': False}
    frames = [{'t': t, 'before': dict(off), 'after': dict(off)} for t in (0, 5000, 5100, 6100, 8100, 38100)]
    frames[2]['after']['pause'] = True
    # 1000ms inactive gap excluded; 2000ms and death-ending 30000ms retained.
    frames[-1]['after']['pause'] = True
    return {'frames': frames}


def runs():
    layout = {'viewport': [844,390], 'dpr':2, 'backing':[1688,780], 'logical':[844,390], 'css':[844,390]}
    return [dict(engine=e, mode=m, pair=n, arm=a, layout=copy.deepcopy(layout),
                 metrics={'mean_ms':10, 'p95_ms':20, 'warmup_ms':5000, 'measured_ms':30000})
            for e in PROTOCOL['engines'] for m in PROTOCOL['modes']
            for n, order in enumerate(PROTOCOL['orders']) for a in order]


class HarnessTests(unittest.TestCase):
    def test_raw_metric_recomputation_inactive_gap_and_death_ending(self):
        m = summarize(raw())
        self.assertEqual(m['intervals_ms'], [100,2000,30000])
        self.assertEqual(m['mean_ms'], 10700)
        self.assertEqual(m['p95_ms'], 30000)
        self.assertEqual(m['excluded_gaps'], [{'start':5100,'end':6100,'ms':1000}])
        print('PASS raw metric recomputation; inactive-gap exclusion; slow death-ending interval retained')

    def test_duration_order_backing_rejection(self):
        for field in ('warmup_ms','measured_ms'):
            r = runs(); r[0]['metrics'][field] = 0
            with self.assertRaisesRegex(AssertionError, 'duration'): aggregate(r)
        r = runs(); r[0],r[1] = r[1],r[0]
        with self.assertRaisesRegex(AssertionError, 'order'): aggregate(r)
        r = runs(); r[1]['layout']['backing'][0] += 1
        with self.assertRaisesRegex(AssertionError, 'backing'): aggregate(r)
        print('PASS duration/order/backing mismatch rejection')

    def test_acceptance_boundary_cases(self):
        r = runs()
        self.assertFalse(aggregate(r)['performance_accepted'])
        for a in r:
            if a['arm']=='candidate':
                a['metrics']['mean_ms'] *= .90 if a['engine']=='firefox' and a['mode']=='classic' else 1.05
                a['metrics']['p95_ms'] *= 1.05
        self.assertTrue(aggregate(r)['performance_accepted'])
        for a in r:
            if a['arm']=='candidate' and a['engine']=='chromium': a['metrics']['p95_ms'] = 21.0001
        self.assertFalse(aggregate(r)['performance_accepted'])
        r = runs()
        for a in r:
            if a['arm']=='candidate': a['metrics']['mean_ms'] = 9.0001
        self.assertFalse(aggregate(r)['performance_accepted'])
        print('PASS acceptance boundary cases: inclusive 10% gain / 5% mean and p95 regression; just outside rejected; no gain rejected')

    def test_timestamp_sample_rejection(self):
        r = raw(); r['frames'][2]['t'] = 0
        with self.assertRaisesRegex(AssertionError, 'timestamp'): summarize(r)
        print('PASS tampered timestamp sample rejected')

    def test_audit_hash_and_rehashed_metric_layout_tampering(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            rs = runs()
            sample = dict(raw(),layout=rs[0]['layout'],source_sha256={},seed=SEED,input_policy=INPUT,inputs=[{}],transitions=[{}])
            rs[0].update(raw='raw.json',metrics=summarize(sample))
            data = dict(kind='capture', roots={},sources={'control':{}},fixture_sha256=sha(FIXTURE.encode()),errors=[],runs=[rs[0]],smoke=False)
            write(out/'results.json',data); write(out/'raw.json',sample)
            write(out/'network.json',[{'action':'SDK_STUB','url':__import__('playgama_render_compare').SDK}])
            def receipt():
                write(out/'manifest.json',dict(exit_code=0,evidence_sha256={p.name:sha(p.read_bytes()) for p in out.iterdir() if p.name!='manifest.json'}))
            receipt()
            sample['frames'][2]['t'] += 1; write(out/'raw.json',sample)
            with self.assertRaisesRegex(AssertionError,'hash mismatch'): audit(out)
            receipt()
            with self.assertRaisesRegex(AssertionError,'raw metric mismatch'): audit(out)
            sample['frames'][2]['t'] -= 1
            sample['layout'] = copy.deepcopy(sample['layout']); sample['layout']['backing'][0] += 1
            write(out/'raw.json',sample); receipt()
            with self.assertRaisesRegex(AssertionError,'raw layout mismatch'): audit(out)
        print('PASS audit rejects tampered sample/hash/layout fixtures, including recomputed receipt hashes')


if __name__ == '__main__': unittest.main()
