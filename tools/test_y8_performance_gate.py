"""Reject interrupted/inactive evidence and detect sustained slow windows."""
import unittest
from y8_performance_gate import metrics


def frames(intervals):
    result = [{'t':0, 'dt':None, 'state':{'menu':False}}]
    for dt in intervals:
        result.append({'t':result[-1]['t']+dt, 'dt':dt, 'state':{'menu':False}})
    return result


class GateTests(unittest.TestCase):
    def test_constant_rate(self):
        m = metrics(frames([20]*1500))
        self.assertEqual(m['average_fps'], 50)
        self.assertEqual(m['minimum_10s_fps'], 50)
        self.assertEqual(m['windows_below_30'], 0)

    def test_sustained_dip_not_hidden_by_average(self):
        m = metrics(frames([10]*2000+[50]*200))
        self.assertGreater(m['average_fps'],55)
        self.assertEqual(m['minimum_10s_fps'],20)
        self.assertGreater(m['windows_below_30'],0)

    def test_inactive_interrupted_short_or_inconsistent_rejected(self):
        for defect in ('inactive','interrupted','short','inconsistent'):
            with self.subTest(defect=defect):
                f = frames([20]*1500)
                if defect=='inactive': f[2]['state']['menu']=True
                if defect=='interrupted': f[2]['dt']=None
                if defect=='short': f.pop()
                if defect=='inconsistent': f[2]['dt']=30
                with self.assertRaises(AssertionError): metrics(f)


if __name__=='__main__':
    unittest.main()
