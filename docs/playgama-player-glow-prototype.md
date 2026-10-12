# Isolated player-glow prototype

TASK-310 adds a builder and deterministic diagnostic for cropping player-glow
intermediate canvases. Production rendering is unchanged. The input is the
immutable TASK-309 accepted runtime; the candidate lives only under artifacts.

```sh
python3 tools/playgama_player_glow_prototype.py --source artifacts/TASK-309/accepted-runtime --out artifacts/TASK-310
python3 tools/playgama_render_compare.py visuals --control artifacts/TASK-310/control --candidate artifacts/TASK-310/candidate --out artifacts/TASK-310/visuals
python3 tools/playgama_player_glow_check.py --out artifacts/TASK-310
python3 artifacts/TASK-310/audit.py
```

Use fresh output paths when reproducing; preserve previous attempts. The builder
copies both runtimes, emits the candidate patch, and records source/build hashes.
The diagnostic uses the existing SDK stub and blocks other external requests.

The prototype bounds the player ring, trail and sparks, adds four coarsest-level
texels of padding, and places each cropped surface at an integer origin on its
original sampling grid. Downsampling and final compositing retain the original
full-surface ratios, including odd dimensions. Ring exclusion and blend order
are retained. Sixteen-texel capacity buckets reuse the four canvas objects;
capacity changes still reset backing stores. This reduces intermediate fill
and downsample area beyond the existing final-composite ring exclusion.

TASK-310 evidence contains 20 standard and 48 extended image pairs, plus eight
camera-motion pairs. All have equal gameplay state. Recorded visual review
accepts maximum channel changes of 3/255 as negligible rasterization, with no
visible clipping, seams, missing particles or layout change. Both browsers pass
functional checks and repeated-frame surface checks. Sixty one-pixel camera
translations retain four canvas objects, with two level resizes in classic and
none in bad. The candidate is eligible for performance testing, not production
integration. No speedup or native Android Firefox result is claimed.

The local `manifest.json` hashes raw images, states, logs and tools; `audit.py`
recomputes hashes, pixel differences, geometry and allocation counts. Consult
`review.json`, `decision.json` and original command logs for the recorded
eligibility decision. Artifact files and screenshots must never be committed.
