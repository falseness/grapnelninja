#!/usr/bin/env python3
"""Verify a sealed TASK-266 evidence audit with the tool revision it was sealed with.

`audit_y8_repaired_evidence.py --verify` binds the tool files and every cited
artifact to the bytes recorded in the report's manifest, so it fails permanently
once a later ticket changes those tools or rebuilds the release directory
(TASK-285 did both: AssertionError tools/verify_y8_release.py). This runs the
sealed tool revision from a temporary git worktree against an overlay of the
live artifacts/: cited files that still match are linked in place, drifted ones
are resolved through the saved historical relocations
(artifacts/TASK-270/historical-relocations.json -> artifacts/TASK-270/previous-release/),
and tasks.json is the ticket snapshot the report was built from (tasks-input.json).
Read-only: it writes only the temporary worktree, which it removes again.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TOOL = 'tools/audit_y8_repaired_evidence.py'


def digest(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, text=True, check=True, stdout=subprocess.PIPE).stdout.strip()


def blob_matches(revision, path, expected):
    blob = subprocess.run(['git', 'show', f'{revision}:{path}'], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return blob.returncode == 0 and hashlib.sha256(blob.stdout).hexdigest() == expected


def sealed_revision(manifest, tool_hashes):
    """First commit from the recorded revision forward whose tool blobs all match the manifest."""
    base = manifest['source_revision']
    forward = git('rev-list', '--ancestry-path', f'{base}..HEAD').split()
    for revision in [base] + forward[::-1]:
        if all(blob_matches(revision, p, h) for p, h in tool_hashes.items()):
            return revision
    raise SystemExit(f'FAIL no commit between {base[:12]} and HEAD carries all {len(tool_hashes)} sealed tool files')


def fill(live, overlay):
    """Link every live artifact the overlay does not already provide (drifted files were placed first)."""
    for child in live.iterdir():
        target = overlay / child.name
        if target.is_symlink() or target.exists():
            if child.is_dir() and target.is_dir() and not target.is_symlink():
                fill(child, target)
            continue
        target.symlink_to(child)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', type=Path, default=ROOT / 'artifacts/TASK-266', help='sealed audit directory (manifest.json, tasks-input.json)')
    ap.add_argument('--relocations', type=Path, default=ROOT / 'artifacts/TASK-270/historical-relocations.json')
    ap.add_argument('--revision', help='override the sealed tool revision (default: first commit whose tool blobs match the manifest)')
    args = ap.parse_args()
    out = args.out.resolve()
    manifest = json.loads((out / 'manifest.json').read_text())
    assert (out / 'manifest.sha256').read_text().split()[0] == digest(out / 'manifest.json'), 'manifest.json does not match its detached checksum'
    cited = manifest['evidence_sha256']
    tool_hashes = {p: h for p, h in cited.items() if p.startswith('tools/')}
    assert TOOL in tool_hashes and manifest['auditor_sha256'] == tool_hashes[TOOL], 'manifest does not seal the audit tool itself'
    revision = args.revision or sealed_revision(manifest, tool_hashes)
    for p, h in tool_hashes.items():
        assert blob_matches(revision, p, h), f'{revision[:12]} does not carry the sealed {p}'
    relocations = json.loads(args.relocations.read_text()) if args.relocations.is_file() else {}
    print(f"sealed tool revision {revision} ({git('log', '--oneline', '-1', revision)}); "
          f"recorded source_revision {manifest['source_revision']}; {len(tool_hashes)} tool files match its blobs")
    with tempfile.TemporaryDirectory(prefix='y8-sealed-audit-') as tmp:
        worktree = Path(tmp) / 'worktree'
        git('worktree', 'add', '--detach', str(worktree), revision)
        try:
            overlay = worktree / 'artifacts'
            overlay.mkdir()
            in_place, relocated, unresolved = [], [], []
            for rel, expected in cited.items():
                if not rel.startswith('artifacts/'):
                    continue
                live = ROOT / rel
                source = live if live.is_file() and digest(live) == expected else None
                if source is None:
                    moved = relocations.get(rel)
                    if moved and (ROOT / moved['path']).is_file() and digest(ROOT / moved['path']) == expected:
                        source = ROOT / moved['path']
                        relocated.append((rel, moved['path']))
                if source is None:
                    unresolved.append(rel)
                    continue
                in_place.append(rel) if source == live else None
                target = worktree / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.symlink_to(source)
            # The report compared the 14 audited tickets with the task list of its time; the live list has
            # since dropped them, so the overlay's tasks.json is the snapshot the report itself cites.
            (overlay / 'tasks.json').symlink_to(out / 'tasks-input.json')
            fill(ROOT / 'artifacts', overlay)
            for rel, path in relocated:
                print(f'RELOCATED {rel} <- {path}')
            for rel in unresolved:
                print(f'UNRESOLVED {rel}: neither the live file nor a recorded relocation carries the sealed bytes')
            print(f'overlay: {len(in_place)} cited artifacts unchanged in place, {len(relocated)} resolved via recorded relocations, '
                  f'{len(unresolved)} unresolved; tasks.json -> {out.relative_to(ROOT) / "tasks-input.json"}')
            print(f'COMMAND {sys.executable} {worktree / TOOL} --out {out} --verify')
            run = subprocess.run([sys.executable, str(worktree / TOOL), '--out', str(out), '--verify'],
                                 text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=worktree)
            print(run.stdout, end='' if run.stdout.endswith('\n') else '\n')
            print(f'exit_code={run.returncode}')
        finally:
            subprocess.run(['git', 'worktree', 'remove', '--force', str(worktree)], cwd=ROOT, check=False)
    ok = run.returncode == 0 and not unresolved
    print(('PASS' if ok else 'FAIL') + f' sealed verify of {out.relative_to(ROOT)}: tool revision {revision[:12]}, '
          f'{len(cited)} cited files ({len(relocated)} via recorded relocations, {len(unresolved)} unresolved)')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
