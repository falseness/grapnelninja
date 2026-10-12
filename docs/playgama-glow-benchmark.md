# Smaller player-glow targets: TASK-311

TASK-318 label correction: the English menu starts Chill as `classic` and
Main as `bad`. Historical protocol metadata reversed these display labels.
Values below remain attributed to their original internal mode IDs; no FPS
values, raw runs, or sealed evidence were rewritten. The validator explicitly
recognizes only that known legacy label mapping; all other protocol fields
remain strict. Earlier unresolved absolute-FPS requirements remain unresolved.

Outcome: **ACCEPTED**. Adopted the exact TASK-310 candidate bytes.

One full desktop headless comparison used Firefox and Chromium sequentially,
Chill/classic and Main/bad, 844×390 at DPR 2, identical backing dimensions,
fixed seed and active-time input policy. Each engine/mode used AB, BA, AB:
three paired runs, at least five active seconds warmup and thirty measured
active seconds per arm. Inactive gaps were excluded; slow active intervals,
including death-ending intervals, were retained. p95 is nearest-rank.

Median of paired candidate/control changes (negative is faster):

| Engine/mode | Mean frame time | p95 frame time |
| --- | ---: | ---: |
| firefox/classic | -24.60% | -14.48% |
| firefox/bad | -30.79% | -20.28% |
| chromium/classic | -24.43% | -18.75% |
| chromium/bad | -24.70% | -24.98% |

Firefox ≥10% median mean reduction gate: **PASS**.
Every engine/mode ≤5% median mean and p95 regression gate: **PASS**.

Individual pairs (candidate/control percentage change):

| Engine/mode | Pair | Order | Mean | p95 |
| --- | ---: | --- | ---: | ---: |
| firefox/classic | 1 | AB | -24.60% | -14.48% |
| firefox/classic | 2 | BA | -22.43% | -7.20% |
| firefox/classic | 3 | AB | -26.82% | -19.78% |
| firefox/bad | 1 | AB | -27.67% | -26.37% |
| firefox/bad | 2 | BA | -30.79% | -20.28% |
| firefox/bad | 3 | AB | -31.52% | -20.02% |
| chromium/classic | 1 | AB | -25.81% | -25.01% |
| chromium/classic | 2 | BA | -24.43% | -18.75% |
| chromium/classic | 3 | AB | -22.03% | -13.35% |
| chromium/bad | 1 | AB | -13.06% | -6.72% |
| chromium/bad | 2 | BA | -24.70% | -24.98% |
| chromium/bad | 3 | AB | -27.04% | -24.98% |

TASK-310’s 76 equal-state visual pairs passed recorded review with negligible
rasterization differences. Its source, image, geometry and functional evidence
were checked again by a read-only audit. Original per-level sampling grids,
effect resolution, ring clearance, trail and spark effects are preserved.
The selected runtime passed startup, both gameplay modes, pause/death and
portrait/landscape/resize smoke checks in both browsers, with production
analytics and ads isolated behind the local SDK fixture.

The prior evidence audit overlapped part of the first Firefox Chill/classic pair.
This environmental limitation remains recorded; no pairs were discarded or
rerun to seek a favorable result. These measurements do not establish a
guaranteed device FPS target. Native Android Firefox remains unverified.

Reproduce the benchmark and inspect its raw evidence:

```sh
python3 tools/playgama_render_compare.py capture --control artifacts/TASK-310/control --candidate artifacts/TASK-310/candidate --out artifacts/TASK-311/benchmark
python3 tools/playgama_render_compare.py audit --input artifacts/TASK-311/benchmark
python3 artifacts/TASK-311/audit.py
```

Existing output directories must be preserved; use a fresh directory for a new
experiment. Local evidence is in `artifacts/TASK-311/`: raw RAF intervals and
input/state traces in `benchmark/`, independently recomputed arm/pair metrics
in `independent-metrics.json`, gate results in `decision.json`, immutable
selected source in `accepted-runtime/`, committed identity in `source.json`,
integration output in `integration.log`, and hashes/commands/environment in
`manifest.json`. Evidence and screenshots are deliberately uncommitted.
