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
