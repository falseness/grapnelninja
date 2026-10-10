# Repaired Y8 evidence audit

Run `python3 tools/audit_y8_repaired_evidence.py --out artifacts/TASK-266`
from the repository. It refuses to overwrite a completed report. For a fresh
review, choose another empty directory. Validate a report with the same
`--out` and `--verify`.

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
files, changed task statuses/feedback, or unresolved entries labeled PASS.
