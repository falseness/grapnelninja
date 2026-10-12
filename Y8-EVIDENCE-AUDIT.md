# Repaired Y8 evidence audit

Run `python3 tools/audit_y8_repaired_evidence.py --out artifacts/TASK-266`
from the repository. It refuses to overwrite a completed report. For a fresh
review, choose another empty directory.

`--verify` binds the tool versions at seal time: the manifest hashes the audit
tool itself, the Y8 verify tools it cites (`tools/verify_y8_release.py`,
`tools/browser_test_support.py`, ...) and every cited artifact, so
`python3 tools/audit_y8_repaired_evidence.py --out artifacts/TASK-266 --verify`
passes on the current tree only while none of them changed. TASK-285 rewrote
those tools and rebuilt `artifacts/y8-release/`, so that command now fails
permanently with an `AssertionError` naming the first changed tool
(`tools/verify_y8_release.py` in TASK-286's log, `tools/browser_test_support.py`
since TASK-291). The failure records drift after sealing, not a defect in the
sealed report. Verify the
TASK-266 report against the sealed tool revision instead:

    python3 tools/verify_sealed_y8_evidence_audit.py --out artifacts/TASK-266

It finds the first commit after the recorded `source_revision` whose tool blobs
match the manifest (`be66c63`, the TASK-266 commit; `c3daa29^`, the tree before
TASK-285, already carries the TASK-284 tool changes and does not match), checks
that revision out in a temporary git worktree, overlays the live `artifacts/`
on it with the drifted `artifacts/y8-release/` files resolved through
`artifacts/TASK-270/historical-relocations.json` (saved bytes under
`artifacts/TASK-270/previous-release/`) and `tasks.json` replaced by the
report's own `tasks-input.json` snapshot (TASK-252 through TASK-266 no longer
exist in the live task list), then runs that revision's `--verify` and removes
the worktree. Pass `--revision <commit>` to pin the tool revision explicitly.
The manual equivalent is `git worktree add --detach /tmp/y8-266 be66c63`, the
same artifact links, then
`python3 /tmp/y8-266/tools/audit_y8_repaired_evidence.py --out artifacts/TASK-266 --verify`.

The audit reconciles TASK-252 through TASK-265 with `artifacts/tasks.json`,
retains the complete verifier feedback, maps rejected evidence to repaired
files, checks recorded hashes and source ancestry, and compares the current
release ZIP with HEAD and the workspace. It reads saved evidence without
running browsers, rebuilding archives, or changing earlier tasks. The report
records current verification, not invented historical execution.

TASK-266's report confirms historical repairs for TASK-252–264. Their captures
remain scoped to the recorded source; subsequent source changes and replaced
archive paths are listed separately. In particular, the TASK-264 checklist's
old root-ZIP description is historical. Use the current release manifest for
current package identity. No earlier historical PASS certifies changed bytes.

TASK-265 is `autoskip` in the task list and remains unresolved. The current
0055eb5 runtime retains six `FAIL_MEASURED_REGRESSION` results and
`package_ready=false`. Audit integrity does not constitute performance recovery.
The 12.9-to-42.1 FPS comparison changed backing resolution from 1688×780 to
633×293; it cannot isolate glow compositing or establish equal-quality gains.
Fixed-density CPU submission profiles, matched-density presentation samples,
and adaptive-resolution results are separated in `performance-claims.json`.
Native phones, hardware GPU/interactive DevTools, hosted ads, console upload and
moderation remain untested owner work. There are no later-task dependencies.

Required outputs are `evidence-audit.json`, `audit.log`,
`performance-claims.json`, and `manifest.json` under the selected directory.
The manifest hashes cited evidence and the audit tool; its detached checksum
avoids a self-referential hash. The verification command fails on changed
files, changed task statuses/feedback, or unresolved entries labeled PASS;
after later tickets change the tools or cited files, only the sealed-revision
command above can still pass, and it passes only when every drifted file is
recoverable byte-for-byte from a recorded relocation.
