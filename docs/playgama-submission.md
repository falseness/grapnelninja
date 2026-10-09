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
