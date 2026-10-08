"""Archive continuous, interactive phone play for visual release review.

Run: python3 tools/record_release_play.py --out artifacts/TASK-195
The recordings are evidence for human review, not an automatic visual verdict.
"""
import argparse
from contextlib import ExitStack, redirect_stdout
import hashlib
import json
from pathlib import Path
import subprocess
import time

from browser_test_support import start_browser_test
from game_harness import click_canvas


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(root, out):
    play = out / 'play'
    play.mkdir(parents=True, exist_ok=True)
    manifest_path = play / 'manifest.json'
    # A failed rerun must not leave an old successful manifest behind.
    manifest_path.unlink(missing_ok=True)
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root,
                                   text=True).strip()
    manifest = {'rev': head, 'viewport': {'width': 844, 'height': 390},
                'dpr': 3, 'sessions': {}}
    log_path = out / 'play.log'
    with log_path.open('w', buffering=1) as log, redirect_stdout(log), ExitStack() as stack:
        print('HEAD', head, flush=True)
        url, browser = start_browser_test(root, stack.callback)
        for mode in ('bad', 'classic'):
            context = browser.new_context(
                viewport=manifest['viewport'], device_scale_factor=3,
                is_mobile=True, has_touch=True, record_video_dir=str(play),
                record_video_size={'width': 844, 'height': 844})
            try:
                page = context.new_page()
                video = page.video
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(url + 'index.html')
                page.wait_for_function('menu.visible && document.getElementById("loading").hidden')
                page.evaluate('fpsCounter.toggle()')
                page.screenshot(path=str(play / f'{mode}-menu.png'))
                page.evaluate('mode => startGame(mode)', mode)
                start = time.monotonic()
                taps = 0
                while time.monotonic() - start < 65:
                    if page.evaluate('menu.visible'):
                        page.evaluate('mode => startGame(mode)', mode)
                    point = page.evaluate('({x:width*0.62,y:height*0.22})')
                    click_canvas(page, point['x'], point['y'])
                    taps += 1
                    page.wait_for_timeout(1300)
                    print(json.dumps({'mode': mode, 'elapsed': time.monotonic() - start,
                                      'inputs': taps, 'state': page.evaluate(
                                          '({mode:version,menu:menu.visible,score:scoreText.count[version],x:ninja.x,y:ninja.y})')}),
                          flush=True)
                seconds = time.monotonic() - start
                page.screenshot(path=str(play / f'{mode}-landscape.png'))
                page.set_viewport_size({'width': 390, 'height': 844})
                page.wait_for_timeout(2000)
                page.screenshot(path=str(play / f'{mode}-portrait.png'))
                page.evaluate('menu.startPause()')
                page.screenshot(path=str(play / f'{mode}-pause.png'))
            finally:
                context.close()  # Flush the entire recording before hashing it.
            recording = play / f'{mode}-session.webm'
            video.save_as(str(recording))
            video.delete()
            assert seconds >= 60 and taps > 1 and not errors, (seconds, taps, errors)
            manifest['sessions'][mode] = {
                'file': recording.name, 'sha256': sha256(recording),
                'interaction_seconds': seconds, 'inputs': taps, 'page_errors': errors}
            print(f'PASS mode={mode} live_browser_seconds={seconds:.2f} inputs={taps} page_errors={errors}', flush=True)
        assert head == subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root,
                                               text=True).strip(), 'HEAD changed during capture'
        print('exit=0', flush=True)
    manifest['log'] = {'file': '../play.log', 'sha256': sha256(log_path)}
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    record(Path(__file__).resolve().parents[1], args.out.resolve())
