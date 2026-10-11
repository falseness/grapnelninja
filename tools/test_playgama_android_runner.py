"""Synthetic arithmetic/schema fixtures; never native device acceptance."""
import copy
import json
from pathlib import Path
import unittest
from playgama_android_runner import metrics, schedule, validate


def fixture():
    state={k:False for k in ('menu','pause','death','ad','host','portrait','hidden')}
    frames=[{'t':t,'before':state.copy(),'after':state.copy()} for t in range(0,35101,20)]
    layout={'dpr':2,'backing':[1600,800],'viewport':[800,400],'orientation':'landscape'}
    package={'builds':{a:{'zip_sha256':a*8} for a in ('baseline','repair')}}
    data={'schema':1,'provenance':'synthetic','quality':'unchanged',
          'environment':{'device_model':'SYNTHETIC ONLY','android_version':'synthetic','firefox_version':'synthetic',
                         'user_agent':'Mozilla Android Firefox/140.0','platform':'Linux armv8l','webdriver':False,'owner_attested_native':True},
          'runs':[{'mode':m,'pair':p,'arm':a,'build_sha256':package['builds'][a]['zip_sha256'],
                   'layout':copy.deepcopy(layout),'end_layout':copy.deepcopy(layout),'visibility':[],
                   'frames':copy.deepcopy(frames)} for m,p,a in schedule()]}
    return data,package

class AndroidRunnerTests(unittest.TestCase):
    def test_timestamp_derived_arithmetic(self):
        d,p=fixture();m=metrics(d['runs'][0]['frames'])
        self.assertEqual((m['mean_frame_ms'],m['p95_frame_ms'],m['average_fps']),(20,20,50))
        self.assertEqual(m['measured_ms'],30100)
    def test_pause_gaps(self):
        d,p=fixture();f=d['runs'][0]['frames'];f[10]['after']['pause']=True
        m=metrics(f);self.assertEqual(m['excluded_gaps'],[{'start':200,'end':220,'ms':20}]);self.assertEqual(m['measured_ms'],30080)
    def test_insufficient_active_duration(self):
        d,p=fixture()
        with self.assertRaisesRegex(ValueError,'insufficient'): metrics(d['runs'][0]['frames'][:1000])
    def test_mismatched_builds(self):
        d,p=fixture();d['runs'][1]['build_sha256']='wrong'
        with self.assertRaisesRegex(ValueError,'build mismatch'): validate(d,p)
    def test_mismatched_backings(self):
        d,p=fixture();d['runs'][1]['layout']['dpr']=3;d['runs'][1]['end_layout']['dpr']=3
        with self.assertRaisesRegex(ValueError,'mismatched backings'):validate(d,p)
    def test_midrun_resize_rejected(self):
        d,p=fixture();changed=copy.deepcopy(d['runs'][0]['layout']);changed['backing']=[800,1600]
        d['runs'][0]['layout_changes']=[changed]
        with self.assertRaisesRegex(ValueError,'during run'):validate(d,p)
    def test_malformed_exports(self):
        for value in ({},None,{'schema':1,'runs':None}):
            with self.assertRaises(ValueError):validate(value,{})
        d,p=fixture();d['runs'][0]['frames'][1]['t']=float('nan')
        with self.assertRaisesRegex(ValueError,'invalid timestamp'):validate(d,p)
    def test_paired_comparison(self):
        d,p=fixture();r=validate(d,p)
        self.assertEqual(len(r['pairs']),6);self.assertEqual(r['median_paired_reduction'],{'classic':0,'bad':0})
        for run in d['runs']:
            if run['arm']=='baseline':
                for frame in run['frames']:frame['t']*=1.2
        r=validate(d,p);self.assertAlmostEqual(r['median_paired_reduction']['classic'],1/6)
        self.assertFalse(r['native_performance_accept'])
    def test_fixture_and_desktop_never_native(self):
        d,p=fixture();self.assertEqual(validate(d,p)['status'],'UNVERIFIED')
        d['provenance']='native-device';d['environment']['webdriver']=True
        self.assertEqual(validate(d,p)['status'],'UNVERIFIED')
        d['environment']['webdriver']=False;d['environment']['user_agent']='Mozilla Linux x86_64 Firefox/140.0'
        self.assertEqual(validate(d,p)['status'],'UNVERIFIED')
    def test_native_rules_and_regression(self):
        d,p=fixture();d['provenance']='native-device'
        # Schema-only exercise, explicitly synthetic data; not saved as native evidence.
        for run in d['runs']:
            if run['arm']=='baseline' and run['mode']=='classic':
                for frame in run['frames']:frame['t']*=1.2
            if run['arm']=='repair' and run['mode']=='bad':
                for frame in run['frames']:frame['t']*=1.1
        self.assertFalse(validate(d,p)['native_performance_accept'])
    def test_order_quality_and_rotation(self):
        d,p=fixture();d['runs'].reverse()
        with self.assertRaisesRegex(ValueError,'order'):validate(d,p)
        d,p=fixture();d['quality']='reduced'
        with self.assertRaisesRegex(ValueError,'quality'):validate(d,p)
        d,p=fixture();d['runs'][0]['end_layout']['orientation']='portrait'
        with self.assertRaisesRegex(ValueError,'orientation'):validate(d,p)

if __name__=='__main__':unittest.main()
