# Playgama checker audit — TASK-315

The branch is not production-ready. This audit found three reproducible defects
in rendering evidence validation and reporting. The previously recorded absolute Firefox
FPS failure also remains unresolved; a passing unit test or integrity audit does
not satisfy that performance requirement.

TASK-316 covers the missing full-backing constraint in
`tools/playgama_render_compare.py:87-91` and
`tools/playgama_fps_gate.py:66-67`. Both validators compare backing dimensions
between runs without requiring the protocol's full 1688×780 backing at
844×390 DPR 2. The complete FPS evaluator accepted six synthetic runs with
844×390 backing and again with 1×1 backing. These are negative validator
fixtures, not measured browser performance. The fix must reject reduced backing
without changing the rendering quality or the strict greater-than-30 threshold.

TASK-317 covers incomplete manifest validation in
`tools/playgama_render_compare.py:125-158`. The audit hashes only files listed in
`evidence_sha256`; it does not require that consumed evidence is listed. It
accepted an altered, unsealed `results.json`, then accepted an empty hash map
while printing that snapshot hashes passed. Execution identity is also optional.
The repair must validate coverage and execution provenance before claiming full
integrity, with positive and negative capture and visual fixtures.

TASK-318 covers reversed display-mode reporting in
`tools/playgama_render_compare.py:37` and benchmark documentation. The menu
starts `classic` from Chill and `bad` from Main, while the historical protocol
labeled them Main and Chill respectively. TASK-318 corrects current reporting to Chill/classic
and Main/bad and explicitly recognizes that legacy metadata without rewriting
sealed evidence or relaxing any other protocol field. The browser-rendered
landscape screenshot and `labels.log` confirm the mismatch. Correct reporting must preserve gameplay,
saved mode IDs, raw measurements, and explicit compatibility with historical
protocol metadata.

The reviewed working tree started at
`cc890290685c0fd365c46aae4abb7939ad6ec5e8`. Local evidence under
`artifacts/TASK-315/` records source hashes, checker selection, exact commands,
original stdout/stderr and exits, reproduction scripts, synthetic fixtures,
review notes, and an audited SHA-256 inventory. `backing-repro.log` and
`manifest-repro.log` contain the concrete defect markers. Follow-up tickets are
local entries in `artifacts/tasks.json`; they repair validators and do not waive
or reschedule earlier unresolved performance requirements.

`artifacts/prd.txt` is absent. Scope came from TASK-287 through TASK-314,
repository documentation, and inspection of the current runtime and checker
code. Local browser tests isolate SDK calls at the network boundary. Native
mobile devices, production FPS, and hosted release behavior are not established
by this audit. The historical failed FPS captures were not rerun unchanged.

An initial unittest-discovery invocation of the archive CLI was interrupted:
that module needs its `--zip`/`--out` entry point to configure extracted runtime
and expected build metadata. Its retained log is an audit invocation mistake,
not a passing package check or an application defect. Existing immutable package
proof was not regenerated for this source/checker audit.

All 21 selected checker modules passed (108 unittest methods), including
Chromium/Firefox input, startup recovery and telemetry, readiness, Bridge, audio,
play-time, storage, tutorial, ads, progression, and both 120-second navigation
soaks. Both progression and history browser-error logs are present and empty.
The standalone desktop/mobile matrices were outside this selection; these
results do not establish exhaustive browser/device coverage.
