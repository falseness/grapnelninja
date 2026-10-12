# Release checker audit — TASK-334

The branch is not production-ready. This audit found four concrete
defects in release FPS validation and tutorial checker error handling and appended TASK-335 through
TASK-338 to the local task list. It changes no runtime or checker behavior.

- **TASK-335 — incomplete activity states accepted.**
  `tools/playgama_fps_gate.py:26` treats empty state dictionaries as active;
  `tools/playgama_release_fps.py:128-134` does not check the seven boolean flags
  emitted by the real collector. A sealed six-run fixture with every before/after
  state replaced by `{}` evaluates PASS. The release boundary must reject missing
  or malformed activity evidence before calculating FPS.
- **TASK-336 — actual input timing ignored.**
  `tools/playgama_release_fps.py:130` compares scheduled input fields but discards
  the recorded `actual_active_ms` and `t`. Both missing timestamps and timestamps
  set to -1 evaluate PASS. Validation must reconcile actual dispatch against raw
  frames and active time, allowing legitimate slow-frame delays.
- **TASK-337 — tool hashes not bound to source.**
  `tools/playgama_release_fps.py:104-106` checks only revision existence, hash-map
  keys and digest syntax. Replacing all tool hashes with 64 zeroes and resealing
  the manifest still evaluates PASS. Tool identity must be checked against
  recorded source bytes while preserving historical revision compatibility.

The fourth finding is a checker lifecycle failure, **TASK-338**. The tutorial
suite emitted `Task exception was never retrieved` with Playwright
`TargetClosedError`, then reported all six tests OK and exited zero.
`tools/test_playgama2_tutorial.py:91-92,185-188` only asserts page errors and
reports PASS before context cleanup; it does not account for asynchronous runner
errors. The repair must settle fixture work across reload/close and make unexpected
runner exceptions fail the checker. The exact pending operation is not identified;
this is not evidence of an application runtime failure. The original traceback is
retained in `test_playgama2_tutorial.log`.

The three release-validator reproductions are synthetic validator counterexamples, never performance
measurements. They do not show that historical captures were malformed. A real
TASK-330 trace contains the expected seven state flags and actual input timing.
The existing twelve-run FPS failure remains recorded in
[release admission](playgama-release-admission.md); unchanged performance captures
were not repeated, and no upload or publication was attempted.

The audit started at `9a12310`. Local evidence is under `artifacts/TASK-334/`:
`source.json` pins all tracked input bytes, `commands.json` records checker
commands/exits/durations, and individual module logs retain original output.
`reproduce_confirmed.py`, `reproduce-confirmed.log` and `repro-confirmed/` retain
complete sealed fixtures for the three FPS defects, including a positive control.
`audit.log` and `manifest.json` record evidence inspection and file hashes.
No other task's evidence was copied.

`artifacts/prd.txt` is absent. Scope came from the current task list, progress
history, checked-in requirements and direct source inspection. The selected
checks cover packaging, rendering/FPS validators, browser selection, mode labels,
clipping, profiling, Bridge, readiness, startup flow/telemetry and trusted input, audio, play time,
storage, tutorial and ads. This is bounded local coverage, not exhaustive native
mobile, hosted-platform or production performance certification. New tickets
address the reproduced defects; they do not defer another review or concern git
publication state.

All 20 selected modules completed: 83 unittest methods and zero command exits.
The tutorial runner exception above remains a finding despite unittest OK.
Evidence inspection verified every selected log's actual `Ran …`/`OK` lines,
all synthetic defect markers, sealed fixture hashes, unchanged tracked source
bytes and preservation of other existing tasks. Artifacts totaled 1.44 GiB.
