"""Read-only TASK-324 audit: hashes, committed bytes, scope and geometry oracle."""
import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(subprocess.check_output(['git','rev-parse','--show-toplevel'],text=True).strip())
sys.path.insert(0,str(ROOT/'tools'))
from playgama_combined_clip import candidate
from build_playgama import runtime


def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(ticket):
    manifest=json.loads((ticket/'manifest.json').read_text())
    for name, expected in manifest['sha256'].items():
        assert digest(ROOT/name)==expected,name
    for binary in ('node','python3'):
        identity=manifest[binary+'_identity']
        assert digest(Path(identity['path']))==identity['sha256'],binary
    print('PASS original logs, consumed prior evidence, source/tool identities SHA256')
    for command in manifest['commands']:
        assert command['exit']==0,command
        assert command['cwd']==str(ROOT)
        assert command['duration_seconds']>=0 and command['ended_utc']>=command['started_utc']
    revision,original=runtime(manifest['revision'],manifest['revision'])
    members={}
    for arm in ('control','candidate'):
        base=ticket/arm
        source=json.loads((base/'source.json').read_text())
        assert source['revision']==revision
        assert set(source['members'])==set(original)
        assert {p.relative_to(base).as_posix() for p in base.rglob('*') if p.is_file()}==set(original)|{'source.json'}
        members[arm]={name:(base/name).read_bytes() for name in original}
        for name,data in members[arm].items():
            assert hashlib.sha256(data).hexdigest()==source['members'][name]
            assert not (base/name).stat().st_mode & 0o222
    assert members['control']==original
    assert all((ROOT/p).read_bytes()==b for p,b in original.items())
    print(f'PASS preserved control bytes and no accepted runtime modification; revision={revision}; members={len(original)}')
    changed=[p for p in original if members['candidate'][p]!=original[p]]
    assert changed==['render/effects.js'],changed
    produced=candidate(original['render/effects.js'])
    assert members['candidate']['render/effects.js']==produced
    expected=''.join(difflib.unified_diff(original['render/effects.js'].decode().splitlines(True),produced.decode().splitlines(True),fromfile='control/render/effects.js',tofile='candidate/render/effects.js'))
    assert (ticket/'candidate.diff').read_text()==expected
    # Independent scope check, apart from reproducing the builder: strip the
    # two renderer classes and normalize the single known callback annotation.
    def outside(data):
        s=data.decode().replace('this.drawAmbientMotes(view), true)', 'this.drawAmbientMotes(view))')
        for start,end in [('class LightmapRenderer','\nfunction positiveModulo'),('class AmbientGlowRenderer','\n// Player-only glow')]:
            i=s.index(start);j=s.index(end,i);s=s[:i]+s[j:]
        return s
    assert outside(original['render/effects.js'])==outside(produced)
    # Menu's method is byte identical, not merely semantically similar.
    def menu(b):
        s=b.decode();return s[s.index('    drawMenu(controls)'):s.index('    drawWorldLights(floors)')]
    assert menu(original['render/effects.js'])==menu(produced)
    print('PASS reproducible candidate generation; only two support clips and explicit ambient callback; menu unchanged')
    geometry=(ticket/'geometry.log').read_text()
    for marker in ['Ran 7 tests','OK','EXIT_CODE=0','independent pixel oracle overlapping','independent pixel oracle disjoint','independent pixel oracle empty','independent pixel oracle offscreen','all four ambient levels rounding/filter padding','unsupported/radial emitter fallback']:
        assert marker in geometry,marker
    # Execute JS again and recompute the independently enumerated pixel sets.
    result=subprocess.run([sys.executable,'-m','unittest','test_playgama_combined_clip','test_playgama_light_profile','-v'],cwd=ROOT/'tools',env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'},capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
    assert 'Ran 7 tests' in result.stderr
    print('PASS independent geometry oracle recomputed: seven tests; all four ambient levels; world-light coverage, reset and fallback')
    size=sum(p.stat().st_size for p in (ROOT/'artifacts').rglob('*') if p.is_file() and not p.is_symlink())
    assert size<20*1024**3
    print(f'PASS artifacts under 20.0 GiB ({size} bytes at audit)')
    assert manifest['browser_identity']=='NOT_RUN: geometry-only Node VM; no browser or FPS measurement'
    print('PASS no FPS claim; no browser/build/timing jobs required or run')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('ticket',type=Path)
    audit(p.parse_args().ticket)
