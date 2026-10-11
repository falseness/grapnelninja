# Published baseline performance

Run from the repository root (requires installed Playwright Firefox and Chromium):

```sh
python3 tools/playgama_firefox_perf.py baseline --revision a570592a1a52b9af0278efa7583874ae25419d0d --out artifacts/TASK-292
python3 tools/playgama_firefox_perf.py audit --input artifacts/TASK-292
```

Use a fresh output directory for subsequent attempts. The runner reconstructs the
historical bundled release and requires its known published ZIP SHA256. It serves
those bytes unchanged. The SDK is stubbed at the request boundary; all other
external requests are aborted, and service workers are blocked. No analytics or
advertising requests are sent to production.

Firefox and Chromium run sequentially, headless, with no CPU throttling. Desktop
1280×720 DPR1 and mobile-sized portrait/landscape DPR2 probes record layout and
orientation. Every mobile-sized run is **desktop emulation**, not native Android.
The Android Firefox report remains poor gameplay performance despite successful
loading; these measurements cannot confirm or dismiss that report.

Each mode has two landscape 844×390 DPR2 repetitions. A fixed seed is installed
before boot and reset before the start input. Identical synthetic mouse events
alternate down/up at (650,100) every 500 ms of active gameplay. Normal restart
button events recover from death; their actual times and state transitions are
recorded. This fixed input policy is a reproducible workload, not a human skill
or native touch test. Browser timing can produce different trajectories/deaths;
raw evidence retains those differences rather than disabling collisions.

The gameLoop wrapper records actual RAF timestamps and before/after state without
changing rendering, physics, effect density, or quality. Intervals following an
inactive state are explicitly excluded. Slow active intervals remain in the
sample, including intervals ending in death. Warmup consumes at least five active
seconds, preserving its whole boundary interval; the measured sample contains at
least thirty additional active seconds. FPS is interval count / elapsed interval
time, and p50/p95 use nearest-rank frame-time percentiles. Portrait contributes
no sustained FPS. Interactive-menu timing is an observed-ready upper bound from
navigation; accepted start input and first active frame have separate timings.
The first active frame uses the browser RAF timestamp, which can precede the
accepted-input observation by one refresh interval (the callback runs later).
It must not be interpreted as negative input latency.

`audit` recomputes metrics from every raw frame, verifies repetition inventory,
input identity, durations, backing sizes, build hashes and network isolation.
Different backing dimensions fail the comparison instead of being normalized.
The receipt distinguishes experiment completion from performance success: there
is no performance threshold and no improvement claimed. Graphics information is
reported when exposed; unavailable renderer information remains explicit.

The baseline command archives its worker's original merged stdout/stderr live in
`baseline-command.log`, including tracebacks on failure. Its execution header and
exit footer share an execution ID with `manifest.json`; the manifest hashes the
closed log alongside the raw evidence. Both the invoked command and worker command,
working directories, UTC times, harness hash and source HEAD are recorded. Audit
checks that identity, the published build marker and all eight recording markers.
Never reconstruct console output from JSON or a later audit. Existing nonempty
output directories are refused; preserve rejected or interrupted attempts before
rerunning. Host graphics package versions are collected during the same run.

TASK-293 adds a bounded diagnostic profile of that same published bundle:

```sh
python3 tools/playgama_firefox_perf.py profile --baseline artifacts/TASK-292 --out artifacts/TASK-293
python3 tools/playgama_firefox_perf.py audit --input artifacts/TASK-293
```

The baseline audit must pass first. A Firefox pilot instruments every drawing
layer in both modes and ranks their mean synchronous submission time. Only the
largest three are suppressed, in disposable browser contexts. Each browser/mode
has two fresh-context matched control/suppression pairs per selected layer, with
reversed order in the second pair. Each arm has eight warmup draws and 24 measured
draws. Initial gameplay geometry is frozen; physics is not stepped. Effects use a
fixed clock and seeded randomness; raw before/after geometry, RNG counts and
transforms must match at every draw. This deliberately bounded scene is not a
sustained gameplay benchmark or a proof about other gameplay states.

Suppression intercepts paint calls within the selected layer; layer functions,
updates, random calls, clears and canvas state changes still execute. No served
or production file changes. RAF intervals include deferred work and scheduling;
layer timings measure synchronous work only. Savings are nonadditive and may
include downstream effects of altered pixels. A saving is labelled repeatable
only if both pairs exceed the greater of 1 ms and the control-to-control spread.
This conservative descriptive rule is not a statistical significance test.

The audit independently recomputes pilot ranking, every raw metric, matched
states, pair savings, noise and dominant repeatable costs. Archived historical
rejections inform the hypothesis; `no-supported-candidate` is a valid result when
cost attribution does not establish a new quality-preserving mechanism. The
manifest preserves the original worker output, failed attempts, exact commands,
build identity, browser executables, environment and evidence hashes. A nonempty
output directory cannot be reused. Native Android remains UNVERIFIED.

TASK-294 records the profile's no-supported-candidate outcome on the repaired
`playgama-start-firefox` branch:

```sh
python3 tools/playgama_firefox_perf.py compare --profile artifacts/TASK-293 --start-evidence artifacts/TASK-291 --out artifacts/TASK-294
python3 tools/playgama_firefox_perf.py audit --input artifacts/TASK-294
python3 -m unittest discover -s tools -p test_playgama_firefox_perf.py -v
```

This compare path requires the audited profile to say `no-supported-candidate`.
It freezes the current committed runtime (including the start/telemetry repairs),
checks it against TASK-291's source receipt, and archives both the source and its
deterministic bundle. It copies the profile evidence for independent recomputation.
`decision.json` reports `NO_SUPPORTED_CANDIDATE`, a control SHA256, and null candidate
hash and hypothesis: no candidate exists and no hypothesis was tested.
`candidate.diff` is intentionally empty. `paired-metrics.json` and
`visual-state.json` explicitly mark timing, screenshots, state and resize checks
not applicable; they are not fabricated successful comparisons. Browsers are not
launched and there is no network activity in this path. Audit checks current runtime
bytes, committed control bytes, preserved repair hashes and the rebuilt bundle.

A future supported hypothesis requires implementing its bounded experiment before
this command can evaluate it; this path refuses supported candidates. Such an
experiment must record three alternating pairs per mode/engine, 5 seconds warmup
and 30 active seconds per arm, all mean/p95 results, >=10% median paired mean-frame
improvement in the targeted Firefox case and <=5% regression in every case. Exact
same-engine decoded pixels and state must match at deterministic checkpoints,
including resize. These conditional checks are not claimed by a no-candidate run.
