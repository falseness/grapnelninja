"""Capture privileged Firefox graphics diagnostics, never an FPS acceptance run.

Uses the same Playwright Firefox launcher as the rendering harness, with an
additional local Marionette endpoint for read-only chrome diagnostics. Explicit
feature status, not WebGL renderer strings or requested prefs, is the evidence.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import socket
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright


SCRIPT = r'''
const gfx = Cc["@mozilla.org/gfx/info;1"].getService(Ci.nsIGfxInfo);
const indices = {};
const prefs = {};
for (const name of Services.prefs.getChildList("")) {
  if (!/^(gfx\.|layers\.|webgl\.|widget\.|marionette\.)/.test(name)) continue;
  const type = Services.prefs.getPrefType(name);
  prefs[name] = {user: Services.prefs.prefHasUserValue(name), value:
    type === Services.prefs.PREF_BOOL ? Services.prefs.getBoolPref(name) :
    type === Services.prefs.PREF_INT ? Services.prefs.getIntPref(name) :
    Services.prefs.getStringPref(name)};
}
return {info:gfx.getInfo(), featureLog:gfx.getFeatureLog(),
        failures:gfx.getFailures(indices), failureIndices:indices.value,
        windows:Array.from(Services.wm.getEnumerator(null), w => ({
          layerManagerType:w.windowUtils.layerManagerType,
          layerManagerRemote:w.windowUtils.layerManagerRemote})), prefs};
'''


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat()


def write(path, data):
    path.write_text(json.dumps(data, indent=2) + '\n')


class Marionette:
    """Minimal length-prefixed protocol client; retain all request/response bytes."""
    def __init__(self, sock, transcript):
        self.sock = sock
        self.transcript = transcript
        self.serial = 0
        self.receive()

    def receive(self):
        size = b''
        while True:
            byte = self.sock.recv(1)
            if not byte:
                raise EOFError('Marionette closed before message length')
            if byte == b':':
                break
            size += byte
        remaining = int(size)
        chunks = []
        while remaining:
            chunk = self.sock.recv(remaining)
            if not chunk:
                raise EOFError('Marionette truncated message')
            chunks.append(chunk)
            remaining -= len(chunk)
        message = json.loads(b''.join(chunks))
        self.transcript.write(json.dumps({'received': message}) + '\n')
        self.transcript.flush()
        return message

    def call(self, name, params):
        self.serial += 1
        message = [0, self.serial, name, params]
        self.transcript.write(json.dumps({'sent': message}) + '\n')
        self.transcript.flush()
        data = json.dumps(message).encode()
        self.sock.sendall(str(len(data)).encode() + b':' + data)
        reply = self.receive()
        if reply[:2] != [1, self.serial] or reply[2] is not None:
            raise RuntimeError(reply)
        return reply[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--prefs', type=Path, help='Explicit candidate graphics prefs JSON')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    prefs = json.loads(args.prefs.read_text()) if args.prefs else {}
    if any(not key.startswith(('gfx.', 'layers.')) for key in prefs):
        parser.error('Only graphics prefs may vary in this diagnostic')
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    launch_prefs = prefs
    diagnostic_env = {'MOZ_MARIONETTE_PREF_STATE_ACROSS_RESTARTS': json.dumps({**prefs, 'marionette.port': port})}
    launch_args = ['-marionette', '-remote-allow-system-access']
    manifest = {'scope': 'privileged backend prerequisite, NOT FPS proof',
                'command': [sys.executable, *sys.argv], 'cwd': str(Path.cwd()),
                'started_utc': utc(), 'os': platform.platform(),
                'revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                'tool_sha256': sha(__file__), 'requested_graphics_prefs': prefs,
                'launch': {'headless': True, 'args': launch_args, 'firefox_user_prefs': launch_prefs},
                'env_override': diagnostic_env,
                'diagnostic_difference': 'Marionette and system-access flags; no gameplay timing collected'}
    start = time.monotonic()
    exit_code = 1
    try:
        with sync_playwright() as pw:
            manifest['executable'] = pw.firefox.executable_path
            manifest['executable_sha256'] = sha(pw.firefox.executable_path)
            with pw.firefox.launch(headless=True, args=launch_args, firefox_user_prefs=launch_prefs, env={**os.environ, **diagnostic_env}, timeout=20000) as browser:
                manifest['browser_version'] = browser.version
                page = browser.new_page(viewport={'width': 844, 'height': 390}, device_scale_factor=2)
                # Exercise a full-backing Canvas2D context without a performance claim.
                canvas = page.evaluate('''() => {const c=document.createElement('canvas');
                  c.width=1688;c.height=780;document.body.appendChild(c);
                  const x=c.getContext('2d',{alpha:false});x.fillRect(0,0,c.width,c.height);
                  return {backing:[c.width,c.height],dpr:devicePixelRatio,attributes:x.getContextAttributes()};}''')
                write(args.out/'canvas.json', canvas)
                deadline = time.monotonic() + 15
                while True:
                    try:
                        connection = socket.create_connection(('127.0.0.1', port), timeout=20)
                        break
                    except ConnectionRefusedError:
                        if time.monotonic() >= deadline:
                            raise
                        time.sleep(.1)
                with connection as sock, (args.out/'protocol.jsonl').open('w') as transcript:
                    client = Marionette(sock, transcript)
                    manifest['session'] = client.call('WebDriver:NewSession', {'capabilities': {'alwaysMatch': {'acceptInsecureCerts': True}}})
                    client.call('Marionette:SetContext', {'value': 'chrome'})
                    result = client.call('WebDriver:ExecuteScript', {'script': SCRIPT, 'args': [], 'newSandbox': True})
                    write(args.out/'graphics.json', result['value'])
                    print(json.dumps(result['value']['info'], indent=2))
                    for feature in result['value']['featureLog']['features']:
                        if any(s in feature['name'] for s in ('CANVAS', 'WEBRENDER', 'HW_COMPOSITING', 'OPENGL_COMPOSITING')):
                            print(json.dumps(feature))
        print('PASS privileged graphics capture; NOT FPS acceptance')
        exit_code = 0
    except Exception:
        traceback.print_exc()
        (args.out/'error.log').write_text(traceback.format_exc())
    finally:
        manifest.update(ended_utc=utc(), duration_seconds=time.monotonic()-start, exit=exit_code)
        manifest['evidence_sha256'] = {p.name: sha(p) for p in args.out.iterdir() if p.is_file()}
        write(args.out/'manifest.json', manifest)
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
