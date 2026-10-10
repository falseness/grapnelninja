# Y8 local release handoff

The locally assembled package is in `artifacts/y8-release/`. Upload only
`grapnelninja-y8.zip`, not the directory. Its manifest identifies the committed
runtime, archive and media hashes, executed commands and evidence. The owner
handles console access, private preview, actual phones, hosted ads and submission.

**The package is prepared for inspection but is not ready for resubmission.**
TASK-257's matched-density software measurements regressed in all six candidate
runs: approximately 4.9–5.4 FPS versus 15.5–16.6 FPS for the baseline. The measured
runtime matches the packaged runtime. This is an unresolved local performance
gate, separate from unavailable physical-device checks. `package_ready`,
`submission_ready` and `moderation_approved` remain false. Completing TASK-257
certified its diagnostic evidence, not performance recovery.

The old 1688×780 versus 633×293 benchmark does not establish equal-quality gains.
Adaptive pixel density can soften output. Neither local browser emulation nor
synthetic visibility events certify phone performance or native OS suspension.

TASK-265 rebuilds the archive with the visibility-change progress flush and
checks its extracted bytes with the full smoke and lifecycle suites. Current
media is reused only after matching its capture archive and runtime hashes.
See `artifacts/TASK-265/final-checks.log`, `manifest.json`, `release-smoke.json`,
`mobile-lifecycle.json` and `performance-audit.json`. Requirements and the owner
handoff are in the release directory. No live gameplay, ads or upload is needed
for these local checks.

`python3 tools/assemble_y8_release.py` assembles the package from the completed
TASK-265 command records and final-byte evidence. It invalidates any old ready
claim before checking the inputs. `--audit` checks a sealed evidence manifest,
package hashes, readiness claims and staged paths without running browsers.
A changed runtime requires rebuilding and rerunning affected checks; a new
performance result requires reassessing the explicit performance gate.

`tools/profile_y8_compositing.py` captures and audits offline, 30-second glow
ablations against an extracted release. Its control retains the packaged
visuals; the other cases remove ambient glow, player glow, or both. All retain
DPR 2 and a 1560×780 backing canvas. These cases diagnose rendering cost but
cannot establish an equal-quality improvement or satisfy the performance gate.
Use a new output directory for each capture to preserve failed experiments.
TASK-265 repair diagnostics are under `artifacts/TASK-265/repair/`; the original
failed performance results remain authoritative until a real fix is retested.

Do not send the draft reviewer response until the local regression is resolved
and the owner has completed `OWNER-CHECKLIST.txt`. Keep all artifacts, screenshots
and unrelated `output/` files out of commits.
