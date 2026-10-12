# Playgama readiness review — TASK-319

The branch is **not production-ready**. Two reproduced checker defects prevent
valid rendering evidence from reaching the FPS gate. TASK-320 and TASK-321 track
the repairs. The previously unmet absolute Firefox FPS requirement also remains
unresolved; correcting these validators does not establish a performance pass.

At `tools/playgama_render_compare.py:104`, the layout validator requires logical
game coordinates to equal the CSS viewport. A real offline Chromium page at
844×390, DPR 2 reports the required 1688×780 backing and 844×390 CSS box, but its
logical coordinates are 2337×1080. This follows the game's fixed 1080-unit height
and touch aspect calculation in `gameoptions.js`. Validation rejects this valid
geometry with `capture logical dimensions`. The synthetic regression fixtures
use the same incorrect 844×390 logical dimensions and therefore miss the defect.
TASK-320 preserves backing resolution while correcting logical validation and
adding real-page geometry coverage.

At `tools/playgama_fps_gate.py:50`, a second exact protocol comparison bypasses
the shared legacy-label normalization. A complete sealed synthetic capture
passes the rendering audit with recognized historical labels, then fails FPS
evaluation with `protocol differs`. The same fixture with current labels reaches
all six FPS results. TASK-321 applies the shared strict compatibility policy to
the FPS evaluator and tests both passing and failing metric outcomes. The
synthetic reproduction establishes validator behavior only, not browser FPS.

Review scope was `git diff master...HEAD`, the current working tree, and every
nonblocked task through TASK-319, including the unresolved `autoskip` entries.
`artifacts/prd.txt` is absent. Reviewed source began at
`8e072ffc71771f0c1dc2f632bb009dda95430d79`; local source fingerprints bind the
runtime and tools used in this review. Runtime inspection covered startup and
SDK recovery, readiness/lifecycle delivery, storage reconciliation, input,
orientation/audio, active play time, progression, and the adopted cropped glow
renderer. Neither publication state nor another review is a repair deliverable.

Local evidence is retained under `artifacts/TASK-319/`: `branch.diff`,
`tasks-before.json`, `source.json`, `commands.json`, original checker logs,
`actual-layout.json`, `layout.log`, `legacy-gate.log`, reproduction scripts and
the complete sealed synthetic fixture. `audit.log` and `manifest.json` record
evidence checks and hashes. Artifacts and screenshots are deliberately excluded
from the commit. Existing task requirements and historical evidence stay intact;
the new tickets do not add prerequisites to earlier performance tasks.

The selected checks passed 117 unittest methods across 23 modules, covering
build/validator arithmetic, browser support, startup input/recovery/telemetry,
readiness, Bridge, audio, active time, storage, tutorial, ads, progression,
both 120-second history cases, and English mode labels. The progression and
history browser-error logs exist and are empty. These passing regressions
coexist with the separately reproduced validator defects described above.

One archive-check invocation mistakenly used unittest discovery instead of its
required ZIP CLI setup. It was interrupted and is excluded from passing counts;
the original log and exit remain in the evidence. This review makes no new
package acceptance, absolute FPS, hosted release, or native-device claim. The
standalone desktop/mobile/browser matrices were not rerun.
