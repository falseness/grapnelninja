# Moderation submission handoff (TASK-251)

Submission is incomplete as of 2026-10-09. The read-only developer MCP
initialization returned `401 Unauthorized`; no authenticated Playgama tool is
exposed in this session. No submission or moderation readback was performed.
Keep TASK-251 pending until all required checks and actual submission succeed.

Preserve existing application `cmuu1nvs30d00hj0h49c07spq`. The historical package
is `artifacts/TASK-248/grapnelninja-playgama.zip`, 104539 bytes, SHA256
`4180a9c142b441fae256aa4b5ea281c122a2bc25a7354d38142668a0c35f1b98`, built from
revision `9c56950591c6dfa26554f2a80cbc2689ab4382e5`. Independent package
inspection passed and resolves release-gap T9/T10. Three covers and ten
gameplay screenshot candidates match their recorded local hashes. Remote
archive/media identity and intended-release hosted QA remain unverified.

The submission checklist retains all 28 other release requirements as
unresolved, including the recorded U4 difficulty-progression failure, native
device/browser certification, live advertising,
listing agreement and visual/provenance review. The earlier local audit is
not release certification. Restore supported authenticated developer access
and obtain the required environments/reviews; do not treat these gaps as PASS.

After resolving those requirements, upload/read back the intended archive and
selected media, complete hosted QA against that exact archive, then use the
existing application's supported reconsideration control. Record the actual
UTC submission time, archive/media IDs, authenticated console screenshot and
read-back moderation status. A prepared build does not prove submission.
Record any actual cooldown or human-only action verbatim if encountered.

Untracked evidence lives in `artifacts/TASK-251/`: `submission-checklist.json`,
`access-check.json`, `package-inspection.log`, `manifest.json`, `verifier.log`
and `evidence-audit.log`. `submission-receipt.json` explicitly records failure
to submit; it is not a successful receipt. The required console capture is
missing. The historical `inspect.py` asserts non-submission and overwrites
failed-snapshot logs; do not run it against new success evidence or use its exit
status as acceptance. No later ticket is a prerequisite.


## Current desktop coverage

The unchanged `tools/test_playgama2_desktop.py` passed all eight cases on
2026-10-09 in 350.456 seconds (exit 0), using Linux Chromium 148.0.7778.96
and Playwright 1.60.0. Tested revision: `c5fab1ae6c03a8ca0963afb29cc661d3cfbad71b`.
Evidence: `artifacts/TASK-251/desktop-20261009T033329Z/`.
The test harness is identical to the historical TASK-243 harness; this run
refreshes coverage after TASK-244's input/orientation changes.

Both modes passed at 800x600, 925x925, 1920x1080 and 2560x1080. The evidence
contains menu, tutorial, settings, gameplay, natural-death and resize captures;
56 PNG hashes and native dimensions were independently checked. Trusted
mouse/keyboard controls, unchanged progress through resize, layout bounds,
aspect ratios and error checks passed. `browser-errors.log` exists and is empty.

This resolves the stale local four-size resize evidence for T4.2.3 and supplies
current local coverage for T4.2, T5, T5.1, T5.3 and S10. Required target-browser
and physical-device coverage remains unverified. All 28 original unresolved
requirements are reconciled individually in this attempt's checklist; U4 still
fails and remote archive/media/hosted-QA identity remains absent. No runtime or
package change was needed for the desktop experiment.

Use the attempt's `submission-checklist.json`, `coverage.md`, `manifest.json`
and `verifier.log` alongside its full `tests.log`, `layout.json`, captures and
source hashes. Original TASK-251 snapshots are preserved. The existing
`input-handoff-20261009T032845Z.md` remains the account-owner handoff; working
supported authenticated lookup is sufficient to resume remote work. Do not
repeat anonymous access probes or require a manufactured reconnect failure.
TASK-251 remains pending until the required local/native/review inputs and
actual same-release submission receipt are available.

## Play time and history navigation

The TASK-251 history experiment exposed lost play time in death/restart loops:
Chill completed nine natural deaths in two minutes while saved time stayed at
zero. Death now records the current interval before saving progress; restart
begins a new interval. Stopping an interval is idempotent, so a subsequent host
pause cannot count time spent in the death offer or advertisement.

`tools/test_play_time.py` checks interval accounting with a controlled clock.
`tools/test_playgama2_history.py` uses real mouse input for 120 seconds per mode,
then exercises three actual Back/Forward/Back cycles. SDK storage persists
across documents at the fixture boundary. The test checks movement, bounded
obstacle counts, accumulated time, exact progress/preferences after navigation,
and working grapnel input in the restored document. It does not replace physics,
inject scores, or represent a human difficulty playtest.

Evidence is under `artifacts/TASK-251/history-20261009T034204Z/`. The interrupted
first harness run and the pre-fix failing Chill run are preserved. Use the
`desktop-fixed`, `history-fixed`, `timer`, `storage`, and `ads` results for the
changed runtime, along with the attempt's manifest, checklist and independent
verifier. These checks add bounded local coverage for T6/S7/S9; native OS
interactions and target-browser certification remain unresolved.

The time-accounting fix changes runtime source, so the historical TASK-248 ZIP
is stale. The replacement local archive and its isolated smoke evidence belong
in this attempt's `release` and `release-smoke` directories, bound to the task
commit. Neither archive is evidence of upload or moderation. U4 progression,
native environments, reviews and authenticated release receipts are still
required; keep TASK-251 pending.

## Score-based encounter pacing

TASK-251 adds a bounded spacing ramp in both modes. The opening five cleared
groups retain the original pacing. Each subsequent point reduces the spacing
for newly generated groups by one percent of the original interval, capped at
20 percent at score 25. Main's inter-group interval therefore moves from
20–30 percent of viewport width to 16–24 percent; Chill's spawn-anchor interval
moves from 35–45 percent to 28–36 percent. This shortens the travel time between
encounters at a given speed while preserving the authored shapes, selection
weights, physics and already generated groups. Queued groups retain their
original spacing, so the effect reaches the player after the queue advances.

Progression uses the current run's score. Pause cannot advance it, a restart or
mode switch resets it, and a saved record cannot increase a new run's difficulty.
The cap preserves clearance and prevents indefinitely increasing density.

`tools/test_playgama2_progression.py` checks all templates at three desktop
sizes, score boundaries and the cap, immutable existing groups, actual group
scoring, restart, mode switching and width rescaling. Short input sessions use
explicitly injected starting scores 0/15/25 with production physics and trusted
mouse input. These are automated integration checks, not evidence of naturally
reaching a high score or a human balance verdict.

Evidence for this change belongs in the unique `progression-*` attempt under
`artifacts/TASK-251/`, including the full desktop rerun and rebuilt archive.
U4 still requires a balance review: play both modes from score zero through
the ramp and assess recovery space, perceived challenge and fairness at the
cap. Reduced spacing can also make grappling targets easier to reach, so a
monotonic spacing measurement alone cannot establish perceived difficulty.
Native certification, provenance/quality review and authenticated same-release
upload, hosted QA and moderation receipt remain required. Keep TASK-251 pending.
