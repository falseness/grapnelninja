"""Check active-time accounting against a controlled clock, without a browser."""
from pathlib import Path
import subprocess
import unittest


class PlayTimeTests(unittest.TestCase):
    def test_pause_is_idempotent_and_resume_excludes_waiting(self):
        result = subprocess.run(['node', '-e', r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
let now = 100000, saved = 0;
const context = vm.createContext({time: undefined,
    Date: class {getTime() {return now;}},
    PROGRESS: {getTime: () => saved, setTime: n => {saved = n;}}});
// Execute the actual timer functions; the remaining file defines canvas UI.
const source = fs.readFileSync('menu.js', 'utf8').split('// Test hook:')[0];
vm.runInContext(source, context);
context.pauseTimeInGame();
assert.equal(saved, 0, 'pause before a run');
context.reuseTimeInGame(); now += 12000; context.pauseTimeInGame();
assert.equal(saved, 12, 'first active segment');
now += 60000; context.pauseTimeInGame();
assert.equal(saved, 12, 'duplicate host pause must not count waiting');
context.reuseTimeInGame(); now += 7000; context.pauseTimeInGame();
assert.equal(saved, 19, 'restart/resume adds only its active segment');
now += 180000; context.pauseTimeInGame();
assert.equal(saved, 19, 'death offer/ad/menu waiting excluded');
console.log('PASS play-time: active segments 12+7=19; duplicate pauses and 240s waiting excluded');
'''], cwd=Path(__file__).resolve().parents[1], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout, end='', flush=True)


if __name__ == '__main__':
    unittest.main()
