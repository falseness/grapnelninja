# Playgama repair audit — TASK-298

The current repair has a reproduced startup telemetry defect. TASK-299 tracks
its fix; this audit does not declare the branch production-ready.

TASK-300 tracks a separate checker defect at
`tools/test_playgama2_mobile.py:60`: the iPhone 13 emulation timed out waiting for
the intentionally hidden portrait canvas during `Locator.bounding_box`. The
iPhone SE and Pixel 7 emulations passed. Portrait capture should collect geometry
without waiting for visibility and assert the rotate overlay and inert state.
The original failing log is retained; it is not counted as a successful suite.

At `index.html:232–237`, portrait touch boot makes the stage inert and displays
the rotate prompt, then unconditionally emits `menu_interactive`. That stage is
once per page, so rotating to landscape cannot replace the premature event.
The existing telemetry suite uses landscape contexts and misses this condition.
The fix should defer this diagnostic milestone until the unobstructed menu is
interactive, while keeping SDK `game_ready` independent of orientation.

TASK-301 tracks stale tutorial storage-fault assertions at
`tools/test_playgama2_tutorial.py:106`. Both rejection cases demand the removed
direct application `localStorage` cache. The current contract retains unsaved
changes in memory until Bridge Storage succeeds; tests must cover recovery and
reload after confirmed remote save. All four normal language/device tutorial
cases passed. Neither checker failure warrants restoring obsolete runtime behavior.

The reviewed runtime is commit `6757d75cedf75ea276a00b2cee7eb3cbc9780f66`, build
`2026-10-11-start-firefox`. Its rebuilt ZIP is 91,541 bytes, SHA-256
`bbbdfcc236f1c2377e16e962e7c4366616dfb2ec484e1f81ad956e7679f73836`, identical to
the TASK-296 archive. CRC, member names and member hashes were checked.

Local evidence is retained under `artifacts/TASK-298/`: `inventory.json` records
checker selection, `commands.json` records individual suite commands and exits,
`source.json` pins tested bytes, and `review.txt` records the code review.
`portrait.json`, `portrait.log` and the visually inspected `portrait.png` prove
the defect using Chromium touch emulation. The initial probe's Python viewport
API error is preserved separately; its corrected run reached all assertions.

`artifacts/prd.txt` is absent. Requirements were taken from TASK-287 through
TASK-297 and the repair documentation. Native Android Firefox and native Safari
remain unverified; this audit makes no performance improvement or release claim.
No publication-state or further-review tickets were created.

Nineteen offline checker modules were executed: seventeen have passing coverage,
while the mobile and tutorial suites retain the failures assigned to TASK-300
and TASK-301. The desktop suite hit the audit driver's six-minute overall limit
after three passes; the five unfinished cases passed individual runs with the
same assertions. Chromium and Firefox passed the browser matrix; WebKit initially
failed host dependency validation, then passed after isolated library extraction.
The system dependency installer failed on existing package inconsistencies; no
kernel/package repair was attempted. Edge and Opera were unavailable.

`audit.log` contains the evidence existence checks, actual grep output, source
hash checks and case coverage reconciliation. `manifest.json` seals the retained
evidence. The wrapper command receipts identify this run; historical task labels
embedded by older checker modules do not identify its invocation.

## Readiness review — TASK-302

The branch is not production-ready: rotating a touch viewport to portrait leaves
music audible behind the rotate prompt. `index.html:615` requests an `orientation`
mute, but `audio.js:9,33` does not register that source and `setMute` ignores it.
TASK-303 tracks the focused fix and an audio regression covering rotation and
overlapping mute reasons.

The offline reproduction used the unmodified page and trusted Chromium touch.
With the rotate prompt visible and the stage inert, WebAudio remained running at
master gain 1; measured portrait PCM RMS was 0.0242008. The trace, actual sampled
WAV files and original console output are in `artifacts/TASK-302/orientation/`
and `orientation.log`. This is desktop touch emulation, not native-device proof.

The review used `git diff master...HEAD`, every nonblocked task's requirements,
and the existing repair documentation. `artifacts/prd.txt` is absent. The reviewed
source is `33cedcd311be01c4e92dfca615bf50e9241b9320`; `source.json` pins its bytes.
`branch.diff`, `tasks-before.json` and `review.txt` preserve review scope, while
`commands.json`, test logs and `manifest.json` retain execution and evidence
identity. The readiness finding concerns current code, not publication state.

The readiness checker also needs repair (TASK-304). Its frame fixture holds the
first animation-frame request after the loading overlay hides. TASK-299 added an
orientation frame before boot's readiness frame, so the fixture now holds the
wrong callback. Four cases fail their pre-release zero-attempt assertion.
`ready-gate/gate.json` records the callback stack through `updateOrientation`,
with the gate unreleased and readiness already successful. The natural scheduler
case and all 13 isolated lifecycle scenarios pass; the failing suite is retained
as evidence, not reported as a successful check.

TASK-305 tracks a second runtime defect: starting a mode while the host is already
paused starts the saved play-time clock although physics stays frozen.
`index.html:252` starts the segment unconditionally; `menu.js:927` uses the same
clock entry for resume. With trusted mode input and Escape, and a controlled
60-second Date offset, saved time increased from 120 to 184 while the ninja's
position remained unchanged. `paused-time/paused-time.json` and `paused-time.log`
retain the reproduction. The fix must exclude frozen time and retain correct
accounting after host release and player resume.

Mobile checks are also incomplete (TASK-306). Both iPhone profiles passed before
the combined command reached its eight-minute budget. An isolated Pixel 7 run
then failed at `tools/test_playgama2_mobile.py:61` during portrait geometry
capture, with `Locator.evaluate` timing out and zero completed captures.
`pixel-7.log` retains the full traceback. The locator requests attachment, so its
hidden-canvas message alone does not establish a visibility wait or a production
bug. TASK-306 calls for a single DOM snapshot, capture-stage timing diagnostics
and passing separate profile runs while preserving the existing assertions.
