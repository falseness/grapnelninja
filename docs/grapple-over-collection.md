# Redesign proof collection

Historical calibration suites remain independently runnable. These helpers are test-only;
the default mountain, preview selector, input, camera, physics and saves are unchanged.

Collect exact test identifiers without starting Chromium:

```sh
python3 tools/grapple_over_collection.py --class Task565Tests
```

Add `--run` to execute that exact class. Unlike unittest's substring `-k`, this
selector rejects partial names, missing/empty classes and duplicate class aliases.
To export one planned encounter, add `--export S01 S01-E01` and set
`GRAPPLE_OVER_EVIDENCE_DIR=artifacts/TASK-NNN`. Children inherit this directory;
exports reject paths escaping it. Exported reservations are not playable proof.

For isolated production movement scenarios, load `grapple_over_metrics.js` then
`grapple_over_collector.js` in the existing offline browser fixture. Call
`REDESIGN_COLLECTOR.collect(pattern, variants)` for one encounter at a time.
Each variant has a label and optional release tick `offset`, horizontal CSS-pixel
`aim` offset, or `held` control. The collector limits batches to 16 variants and
300 ticks each. Simulation runs in-page; capture is separate and optional.
It keeps input records, attachment/shot transitions, contact events and every
15th route position, with initial clearance recorded once. That clearance is
an initial vertical measurement, not a swept obstacle guarantee. Synthetic batch
inputs are labelled untrusted; use real browser input and `compact()` for trusted
confirmation. These fixture transfers are not continuous gameplay.

`Task565Tests` checks a passing tolerance batch against an intentionally failing
held-shot control, confirms trusted mouse input, exports a child encounter and
checks collection failures. Its coverage map names legacy geometry assertions,
replacement assertions and preserved behavioral checks. Geometry-dependent v3
section fixtures remain legacy coverage. Planned blueprint checks do not replace
future playable encounter proofs. No skip or expected-failure wrapper is added.
Reuse archived successful calibration logs when relevant source hashes match;
a new HEAD alone does not invalidate evidence. Retain compact task-local logs
and JSON, with no repeated full geometry or unnecessary screenshots.

### Preview save compatibility (TASK-566)

The local `?grapplePreview=replacement-v1` fixture persists to
`grapnelninja.grappleOver.preview.replacement-v1`. The shipped mountain continues
using `grapnelninja.grappleOver`. Save serialization remains version 1; `layoutId`
separately identifies geometry. Replacement restores require an exact identity
before any coordinates or live objects are changed. Historical saves without an
identity remain accepted only by the original legacy layout (or the historical
identity-less fixed-level fixtures). Incompatible preview saves show a localized
explanation and leave the fresh replacement base intact. Reset clears the upgrade
and restores range 360; valid saves preserve current state and range 540 upgrades.

`Task566Tests` covers the minimal preview, including a test-only mover on its
existing anchor. These are isolated continuation fixtures, not earned gameplay.
TASK-558's historical statement that preview persistence is disabled is superseded
by this isolated storage key; its legacy-save isolation remains required. No full
mountain geometry, old coordinate coverage, or historical capture is regenerated.
