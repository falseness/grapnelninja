"""Host-pause timing on the real page; only SDK storage/events and Date are fixtures."""
import json
import os
from pathlib import Path
import unittest

from browser_test_support import start_browser_test, wait_for_boot
import test_playgama2_bridge as support


class HostPauseTimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(os.environ.get('PLAYGAMA2_EVIDENCE_DIR', 'artifacts/TASK-305'))
        cls.out.mkdir(parents=True, exist_ok=True)
        cls.url, cls.browser = start_browser_test(support.ROOT, cls.addClassCleanup)

    def test_host_paused_time_excluded(self):
        evidence = {'browser': self.browser.version, 'fixture': 'SDK events/storage and fixed Date.getTime boundary only; real RAF, physics, timer and state functions', 'cases': {}}
        self.addCleanup(lambda: (self.out / 'paused-time.json').write_text(json.dumps(evidence, indent=2) + '\n'))
        for initial in (True, False):
            with self.subTest(initial_host_pause=initial):
                context = self.browser.new_context(viewport={'width': 1280, 'height': 720})
                self.addCleanup(context.close)
                remote = {'grapnelninja.time': '120', 'grapnelninja.lang': 'en', 'grapnelninja.tutorialDone': 'true'}
                storage = []
                def get(keys):
                    values = [remote.get(k) for k in keys]
                    storage.append({'op': 'get', 'keys': keys, 'values': values})
                    return values
                def put(keys, values):
                    remote.update(zip(keys, values))
                    storage.append({'op': 'set', 'keys': keys, 'values': values})
                context.expose_function('fixtureGet', get)
                context.expose_function('fixtureSet', put)
                context.add_init_script('''window.clockOffset=0;
                    Date.prototype.getTime=function(){return 1000000+clockOffset};
                    window.inputs=[];
                    for(const name of ['mousedown','mouseup','keydown','click'])
                        addEventListener(name,e=>inputs.push({name,key:e.key,trusted:e.isTrusted,clockOffset}),true);''')
                context.route(support.SDK, lambda r: r.fulfill(content_type='application/javascript', body=
                    'const FAULT="normal", SAVED_LANGUAGE="en";\n' + support.FAKE +
                    '\nbridge.platform.isPaused=' + json.dumps(initial) + ''';
                    bridge.storage.get=keys=>fixtureGet(keys);
                    bridge.storage.set=(keys,values)=>fixtureSet(keys,values);
                    window.hostEvents=[{paused:bridge.platform.isPaused,clockOffset,initial:true}];
                    const originalEmit=emitHost;
                    window.emitHost=(event,value)=>{hostEvents.push({event,paused:value,clockOffset});originalEmit(event,value)};'''))
                p = context.new_page()
                errors = []
                p.on('pageerror', lambda e: errors.append(str(e)))
                p.goto(self.url + 'index.html')
                wait_for_boot(p)
                support.Playgama2BridgeTests.click_mode(self, p, 'classic')
                def snap():
                    return p.evaluate('({hostPaused,menu:menu.visible,paused:menu.gamePaused,segment:time,saved:PROGRESS.getTime(),ninja:{x:ninja.x,y:ninja.y},clockOffset})')
                row = evidence['cases']['initial' if initial else 'resume'] = {'started': snap()}
                if not initial:
                    p.evaluate('clockOffset+=12000')
                    p.wait_for_timeout(100)
                    p.evaluate("emitHost('pause',true)")
                    row['host_pause'] = snap()
                    self.assertEqual(row['host_pause']['saved'], 132)
                else:
                    # The pause switch starts the run paused while the host holds pause (TASK-403)
                    self.assertTrue(row['started']['paused'])
                p.keyboard.press('Escape')
                row['before'] = snap()
                self.assertTrue(row['before']['hostPaused'])
                self.assertFalse(row['before']['paused'])
                self.assertIsNone(row['before']['segment'])
                p.evaluate('clockOffset+=60000')
                p.wait_for_timeout(250)
                row['during'] = snap()
                p.keyboard.press('Escape')
                row['accounted'] = snap()
                self.assertEqual(row['during']['ninja'], row['before']['ninja'])
                self.assertEqual(row['accounted']['saved'], row['before']['saved'])
                # A real preference click forces a Bridge write even if time is unchanged.
                p.locator('#mute-button').click()
                p.wait_for_function("probe.calls.some(c=>c.name==='game_ready')")
                for _ in range(40):
                    if remote.get('grapnelninja.muted') == 'true':
                        break
                    p.wait_for_timeout(100)
                self.assertEqual(remote.get('grapnelninja.muted'), 'true')
                row['frozen_remote'] = dict(remote)
                row['frozen_storage'] = list(storage)
                # Return focus from the native mute button to the canvas.
                p.mouse.click(10, 10)
                # Resume is attempted while the host still holds pause.
                p.keyboard.press('Escape')
                row['resume_attempt'] = snap()
                self.assertIsNone(row['resume_attempt']['segment'])
                self.assertFalse(row['resume_attempt']['paused'])
                p.evaluate("emitHost('pause',false)")
                row['released'] = snap()
                self.assertEqual(row['released']['segment'], (1000000 + row['released']['clockOffset']) // 1000)
                p.evaluate('clockOffset+=7000')
                p.wait_for_timeout(100)
                row['active'] = snap()
                self.assertNotEqual(row['active']['ninja'], row['released']['ninja'])
                # Duplicate release must not reset the already running segment.
                p.evaluate("emitHost('pause',false)")
                p.keyboard.press('Escape')
                row['after'] = snap()
                self.assertEqual(row['after']['saved'] - row['accounted']['saved'], 7)
                p.evaluate("emitHost('pause',true);emitHost('pause',true);emitHost('pause',false)")
                row['duplicate_pause'] = snap()
                self.assertTrue(row['duplicate_pause']['paused'])
                self.assertIsNone(row['duplicate_pause']['segment'])
                self.assertEqual(row['duplicate_pause']['saved'], row['after']['saved'])
                for _ in range(40):
                    if int(remote['grapnelninja.time']) == row['after']['saved']:
                        break
                    p.wait_for_timeout(100)
                self.assertEqual(int(remote['grapnelninja.time']), row['after']['saved'])
                row.update(inputs=p.evaluate('inputs'), host_events=p.evaluate('hostEvents'), remote=dict(remote))
                self.assertTrue(row['inputs'] and all(e['trusted'] for e in row['inputs']))
                p.reload()
                wait_for_boot(p)
                row['reloaded'] = p.evaluate('PROGRESS.getTime()')
                row['storage'] = list(storage)
                self.assertEqual(row['reloaded'], row['after']['saved'])
                self.assertEqual(errors, [])
                p.close()
        if all('reloaded' in row for row in evidence['cases'].values()):
            print('PASS host-paused time excluded', flush=True)


if __name__ == '__main__':
    unittest.main()
