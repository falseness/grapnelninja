"""Capture local Y8 media from an identified release, with reproducible provenance.

Run covers and screenshots separately, then inventory. Console-only media limits
are intentionally not inferred from the locally chosen candidate dimensions.
"""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import sys
import zipfile
from datetime import datetime, timezone

import make_covers as covers
from PIL import Image, ImageDraw


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, data):
    path.write_text(json.dumps(data, indent=2) + '\n')


def identity(candidate, root):
    archive = Path(candidate['zip'])
    assert sha(archive) == candidate['sha256'], 'Archive hash mismatch'
    expected = {f['path']: f['sha256'] for f in candidate['files']}
    with zipfile.ZipFile(archive) as z:
        assert set(z.namelist()) == set(expected), 'Unexpected archive members'
        for name, digest in expected.items():
            assert not Path(name).is_absolute() and '..' not in Path(name).parts
            data = z.read(name)
            assert hashlib.sha256(data).hexdigest() == digest
            source = subprocess.check_output(['git', 'show', candidate['source_revision'] + ':' + name])
            assert data == source, name
        if not root.exists():
            z.extractall(root)
    actual = {str(p.relative_to(root)): sha(p) for p in root.rglob('*') if p.is_file()}
    assert actual == expected, 'Served files differ from archive'
    print(f'PASS archive/source/served identity: {len(actual)} files; {candidate["sha256"]}', flush=True)
    return actual


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage', choices=['covers', 'screenshots', 'inventory'])
    p.add_argument('--candidate', type=Path, required=True)
    p.add_argument('--seeds', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    candidate = json.loads(a.candidate.read_text())
    root = (a.out / 'extracted').resolve()
    files = identity(candidate, root)
    tool_paths = [Path(__file__), Path(covers.__file__), covers.AUTOPILOT,
                  Path(__file__).with_name('browser_test_support.py')]
    source = dict(source_revision=candidate['source_revision'], archive=candidate['zip'],
                  archive_sha256=candidate['sha256'], served_root=str(root), files=files,
                  candidate_sha256=sha(a.candidate), seeds_sha256=sha(a.seeds),
                  tools={str(p.resolve()): sha(p) for p in tool_paths},
                  environment=dict(python=sys.version, platform=platform.platform(),
                                   playwright=importlib.metadata.version('playwright'),
                                   pillow=importlib.metadata.version('Pillow')))
    provenance = a.out / 'capture-source.json'
    if provenance.exists():
        assert json.loads(provenance.read_text()) == source, 'Capture provenance changed'
    else:
        write(provenance, source)
    if a.stage in ('covers', 'screenshots'):
        covers.ROOT = root
        if a.stage == 'covers':
            shots = {'landscape': {'mode': 'bad', 'tick': 180}, 'crop': {'mode': 'bad', 'tick': 180}}
            directory = a.out / 'source-frames'
        else:
            # Keep the actual gameplay HUD; the release default hides FPS.
            covers.CAPTURE_JS = covers.CAPTURE_JS.replace('window.drawUILayer = function() {}', '')
            covers.CAPTURE_JS = covers.CAPTURE_JS.replace('window.drawFpsCounterLayer = function() {}', '')
            shots = {name: {'mode': 'bad', 'tick': tick} for name, tick in
                     [('landscape', 180), ('main240', 240), ('main300', 300)]}
            directory = a.out / 'screenshots'
        errors = covers.capture(a.seeds, directory, shots)
        write(a.out / (a.stage + '-errors.json'), errors)
        assert not any(errors.values()), errors
        metadata = json.loads((directory / 'source-frames.json').read_text())
        for name, frame in metadata['frames'].items():
            assert frame['tick'] == shots[name]['tick'] and frame['deathTick'] is None
            frame['sha256'] = sha(directory / frame['file'])
        metadata.update(archive_sha256=candidate['sha256'], source_revision=candidate['source_revision'],
                        capture_source_sha256=sha(provenance), captured_utc=datetime.now(timezone.utc).isoformat(),
                        method='Main (internal bad): deterministic real physics/draw replay; local network only',
                        hud='suppressed for cover composition' if a.stage == 'covers' else 'release HUD preserved')
        write(directory / 'source-frames.json', metadata)
        if a.stage == 'covers':
            covers.compose(directory, a.out / 'media', {(1280,720), (1920,1080), (512,512),
                                                      (800,1200), (800,600), (800,800)})
        identity(candidate, root)
        print(f'PASS {a.stage}: {len(shots)} live Main frames; source/tool hashes bound; no page/console errors')
        return
    assets = []
    for folder in ['media', 'screenshots']:
        for path in sorted((a.out / folder).glob('*.png')):
            with Image.open(path) as im:
                im.load()
                assert im.format == 'PNG'
                dimensions = list(im.size)
            if folder == 'media':
                expected = list(map(int, path.stem.split('-')[1].split('x')))
                assert dimensions == expected
            assets.append(dict(path=str(path), dimensions=dimensions, format='PNG', bytes=path.stat().st_size,
                               sha256=sha(path), field='thumbnail/cover candidate' if folder == 'media' else 'gameplay screenshot candidate',
                               source=str(a.out / ('source-frames' if folder == 'media' else folder) / 'source-frames.json'),
                               requirements_status='UNKNOWN console dimensions/format/byte/count limits; candidate only'))
            print(f'PASS PNG header/dimensions/bytes/hash: {path} {dimensions} {path.stat().st_size} {sha(path)}')
    assert len(assets) == 9
    write(a.out / 'media-manifest.json', dict(archive_sha256=candidate['sha256'],
          source_revision=candidate['source_revision'], assets=assets,
          video='UNKNOWN whether required in owner console; no video claimed ready',
          composition='Aspect-ratio crop and uniform resize of real Main frames; title added to covers only'))
    sheet = Image.new('RGB', (1200, 900), '#15151c')
    draw = ImageDraw.Draw(sheet)
    for i, asset in enumerate(assets):
        with Image.open(asset['path']) as original:
            preview = original.copy()
            preview.thumbnail((390, 255))
        x, y = (i % 3)*400, (i // 3)*300
        sheet.paste(preview, (x, y))
        draw.text((x, y+258), Path(asset['path']).name, fill='white')
        draw.text((x, y+275), str(asset['dimensions']), fill='white')
    sheet.save(a.out / 'contact-sheet.png')
    print('PASS inventory: 9 selected assets; contact sheet generated; visual review still required')


if __name__ == '__main__':
    main()
