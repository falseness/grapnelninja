"""Y8 callback ordering and bounded startup, without browser/network traffic."""
import pathlib,subprocess,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class Y8ReleasePlatform(unittest.TestCase):
 def test_contract(self):
  r=subprocess.run(['node','tools/y8_platform_contract.cjs'],cwd=ROOT,text=True,capture_output=True)
  print(r.stdout,end='');self.assertEqual(r.returncode,0,r.stderr)
if __name__=='__main__':unittest.main()
