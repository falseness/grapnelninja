"""Independently inspect saved release evidence without repeating browser tests."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zipfile
from PIL import Image


def digest(data): return hashlib.sha256(data).hexdigest()
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True)
    out=p.parse_args().out
    def read(name): return json.loads((out/name).read_text())
    source=read('source.json'); inventory=read('inventory.json'); manifest=read('manifest.json'); smoke=read('smoke.json')
    revision=source['revision']
    assert source['branch']=='playgama2' and manifest['application_revision']==revision
    subprocess.run(['git','merge-base','--is-ancestor',revision,'playgama2'],check=True)
    print(f'PASS source.json pinned committed playgama2 revision {revision}')
    release=(out/'grapnelninja-playgama.zip').read_bytes(); sha=digest(release)
    assert len(release)<=300*1024*1024
    assert (out/'sha256.txt').read_text().split()[0]==sha==smoke['zip_sha256']
    assert release==(out/'rebuild/grapnelninja-playgama.zip').read_bytes()
    with zipfile.ZipFile(out/'grapnelninja-playgama.zip') as z:
        assert z.testzip() is None
        names=z.namelist(); assert len(set(names))==len(names)==len(inventory)
        assert {'index.html','platform.js','playgama-bridge-config.json'}<=set(names)
        assert set(names)=={row['path'] for row in inventory}
        for row in inventory:
            name=row['path']; assert re.fullmatch(r'[A-Za-z0-9_./-]+',name)
            assert name in ('index.html','playgama-bridge-config.json') or re.fullmatch(r'(?:(?:collision|elements|render|sprites)/)?[A-Za-z0-9_-]+\.js',name)
            data=z.read(name);blob=subprocess.check_output(['git','show',revision+':'+name])
            blob_id=subprocess.check_output(['git','rev-parse',revision+':'+name],text=True).strip()
            assert data==blob and len(data)==row['size'] and digest(data)==row['sha256']==smoke['extracted_files'][name]
            assert row['source_blob']==blob_id and row['source_blob_equivalent'] is True
    print(f'PASS inventory.json {len(names)} runtime files: sizes/SHA256/Git source blobs independently equal; ASCII Latin paths; exclusions; index.html root')
    print(f'PASS grapnelninja-playgama.zip integrity; {len(release)} bytes <=300MB; deterministic rebuild; sha256.txt {sha}')
    build=(out/'build.log').read_text()
    assert 'No errors detected in compressed data' in build and 'PASS deterministic rebuild byte comparison' in build and revision in build
    print('PASS build.log exact pinned builder command, unzip integrity and deterministic rebuild markers')
    expected={f'{device}-{mode}-{fault}' for device in ('desktop','touch') for mode in ('classic','bad') for fault in ('normal','init_rejected')}
    assert {c['case'] for c in smoke['cases']}==expected
    log=(out/'smoke.log').read_text()
    assert Path(smoke['extracted_root']).is_relative_to(Path(smoke['server_root']))
    assert not Path(smoke['server_root']).is_relative_to(Path.cwd())
    for case in smoke['cases']:
        name=case['case'];assert f'PASS {name}:' in log and case['verdict']=='PASS' and case['errors']==[]
        assert case['state']['grapple'] and not case['state']['menu'] and any(i['trusted'] for i in case['inputs'])
        assert case['readiness']['complete'] and case['readiness']['loading']
        assert case['audio'][0]['rms']>.001 and case['audio'][1]['rms']<.00001 and case['audio'][2]['rms']>.001
        if name.endswith('init_rejected'):
            assert case['readiness']['environment']=='disabled' and any('initialize failed' in s for s in case['console'])
        else:
            assert sum(c['name']=='game_ready' for c in case['readiness']['calls'])==1
        for req in case['network']:
            assert req['status']==200
            assert req['url']=='https://bridge.playgama.com/v2/stable/playgama-bridge.js' or re.fullmatch(r'http://127\.0\.0\.1:\d+/nested/game/release/[A-Za-z0-9_./-]+',req['url'])
        path=Path(case['capture']);assert digest(path.read_bytes())==case['capture_sha256']
        with Image.open(path) as im:
            assert im.format=='PNG' and im.size==((960,540) if name.startswith('touch') else (1280,720))
        print(f'PASS capture {path.name}: native PNG hash/dimensions; {name} input/audio/readiness/network/errors')
    assert set(smoke['extracted_files'])==set(names)
    print('PASS smoke.log/smoke.json eight cases, extracted-only server root, nested requests, readiness traces, errors empty')
    for path, sha in manifest['tool_source_hashes'].items():
        assert digest(Path(path).read_bytes())==sha,path
    for path, sha in manifest['evidence_sha256'].items():
        assert digest((out/path).read_bytes())==sha,path
    assert manifest['commands'] and manifest['environment'] and manifest['limitations'] and manifest['later_ticket_prerequisites']==[]
    if (out/'preserved-archives.txt').stat().st_size:
        subprocess.run(['sha256sum','-c',str(out/'preserved-archives.txt')],check=True)
    print('PASS manifest.json commands/environment/evidence/tool hashes/limitations; no later-ticket prerequisite; existing archives preserved')
if __name__=='__main__':main()
