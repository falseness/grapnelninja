"""Cheap content/hash audit of archived exact-candidate smoke evidence."""
import argparse
import hashlib
import json
import pathlib
from PIL import Image


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(out):
    result=json.loads((out/'release-smoke.json').read_text())
    manifest=json.loads((out/'manifest.json').read_text())
    log=(out/'release-smoke.log').read_text()
    # Integrity is meaningful even for a failed or incomplete run. Do not confuse
    # intact diagnostics with successful gameplay acceptance.
    for file,digest in manifest['evidence_sha256'].items():
        assert sha(pathlib.Path(file))==digest,file
    captures=0
    for row in result['results']:
        for capture in row['captures']:
            path=pathlib.Path(capture['path'])
            assert sha(path)==capture['sha256'],str(path)
            with Image.open(path) as image: image.verify()
            captures+=1
    print(f'PASS diagnostic integrity: {len(manifest["evidence_sha256"])} hashes; {captures} PNG captures',flush=True)
    print(f'OBSERVED {len(result["results"])} cases; '+str(sum(r['verdict']=='PASS' for r in result['results']))+' passed',flush=True)
    for row in result['results']:
        if row['verdict']!='PASS':
            print('FAIL case '+'-'.join(row[k] for k in ('engine','profile','mode','sdk'))+'; '+row.get('error','').strip().splitlines()[-1],flush=True)
    assert manifest['exit_code']==0, 'Smoke run failed; task must remain pending'
    assert 'EXIT_CODE=0' in log and 'PASS smoke matrix: 18 cases; served hashes unchanged' in log
    assert result['archive_sha256'] in log and result['source'] in log and result['served_root'] in log
    assert 'COMMAND ' in log and 'START_UTC ' in log and 'END_UTC ' in log
    assert manifest['archive_sha256']==result['archive_sha256']
    assert sha(pathlib.Path(manifest['archive']))==result['archive_sha256']
    root=pathlib.Path(result['served_root'])
    assert {str(p.relative_to(root)):sha(p) for p in root.rglob('*') if p.is_file()}==result['file_hashes']
    expected={(e,p,m,s) for e in ['chromium','firefox','webkit']
              for p,s in [('desktop','immediate'),('portrait','unavailable'),('landscape','delayed')]
              for m in ['bad','classic']}
    rows=result['results']
    assert len(rows)==18
    assert {(r['engine'],r['profile'],r['mode'],r['sdk']) for r in rows}==expected
    captures=0
    for r in rows:
        name='-'.join(r[k] for k in ('engine','profile','mode','sdk'))
        assert r['verdict']=='PASS' and 'PASS '+name in log
        assert r['archive_sha256']==result['archive_sha256'] and r['source']==result['source']
        assert r['trusted_input'] and all(e['trusted'] for e in r['trusted_input'])
        for check in ('first_menu','sdk_startup','grapple','gameplay','pause_resume','natural_death','restart','save_reload','http_js_errors'):
            assert r['checks'][check]['result']=='PASS',(name,check)
        assert r['checks']['tutorial']['result']=='NOT_APPLICABLE'
        assert r['checks']['mute']['result']=='NOT_APPLICABLE'
        assert all(not present for present in result['feature_inventory'].values())
        assert r['checks']['natural_death']['deaths']
        assert all('physics' in d['stack'] for d in r['checks']['natural_death']['deaths'])
        assert not r['errors'] and not r['request_failures'] and not r['external_blocked']
        assert not any(m['type']=='error' for m in r['console'])
        assert r['responses'] and all(q['status']<400 for q in r['responses'])
        for name in result['file_hashes']:
            assert any(q['url'].endswith('/'+name) or (name=='index.html' and q['url'].endswith('/')) for q in r['responses']),name
        if r['sdk']=='delayed': assert r['checks']['late_sdk']['result']=='PASS'
        assert {c['stage'] for c in r['captures']}=={'menu','gameplay','pause','death','restart','reload'}
        for c in r['captures']:
            p=pathlib.Path(c['path']);assert sha(p)==c['sha256']
            with Image.open(p) as image:
                assert image.width>0 and image.height>0
                image.verify()
            captures+=1
        print('PASS case '+name+': trusted grapple, motion, pause/resume, natural collision/restart, save/reload, clean HTTP/JS; 6 hashed captures')
    for file,digest in manifest['evidence_sha256'].items():
        assert sha(pathlib.Path(file))==digest,file
    assert sha(pathlib.Path('tools/smoke_y8_candidate.py'))==manifest['harness_sha256']
    print(f'PASS archive/source/served identity: {len(result["file_hashes"])} files')
    print(f'PASS evidence hashes and PNG integrity: {captures} captures; 18 complete cases')
    print('LIMITATION tutorial and mute NOT_APPLICABLE: absent from exact Y8 candidate; physical phones and real SDK untested')


if __name__=='__main__':
    ap=argparse.ArgumentParser(__doc__);ap.add_argument('out',type=pathlib.Path)
    audit(ap.parse_args().out)
