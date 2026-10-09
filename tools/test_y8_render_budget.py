import pathlib,subprocess,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class BudgetTest(unittest.TestCase):
 def test_sustained_slow_frames_only(self):
  script="""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const box={window:{innerWidth:844,innerHeight:390,devicePixelRatio:3,matchMedia:()=>({matches:true})}};vm.createContext(box);
vm.runInContext(fs.readFileSync('gameoptions.js','utf8')+';globalThis.b=RENDER_BUDGET;globalThis.d=getRenderDensity',box);
assert.equal(box.d(),2);
for(let t=0;t<10000;t+=16.67)box.b.observe(t,true);
assert.equal(box.d(),2,'fast frames retain sharpness');
box.b.observe(20000,false);
for(let t=20000;t<40000;t+=100)box.b.observe(t,true);
assert.equal(box.d(),.75,'slow frames reach bounded floor');
box.b.densityLimit=Infinity;box.b.observe(50000,false);box.b.observe(100000,true);
assert.equal(box.d(),2,'background gap cannot lower density');
console.log('PASS native cap, fast frames, bounded adaptation, background exclusion');
"""
  r=subprocess.run(['node','-e',script],cwd=ROOT,text=True,capture_output=True);print(r.stdout,end='');self.assertEqual(r.returncode,0,r.stderr)
