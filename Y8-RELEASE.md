# Y8 local release handoff

Current package: `artifacts/y8-release/`, rebuilt and audited by
`tools/y8_package.py` (`--task` labels the evidence directory; the kit's
`artifacts/y8-release/manifest.json` names it in `task`); see
[Y8-SUBMISSION-KIT.md](Y8-SUBMISSION-KIT.md). TASK-285 was the first kit built
this way; later rebuilds replace it in place. The notes below are historical
(TASK-265/269/270 era).

Current candidate owner/media instructions: [Y8-MEDIA-HANDOFF.md](Y8-MEDIA-HANDOFF.md)
and [Y8-OWNER-CHECKLIST.md](Y8-OWNER-CHECKLIST.md). These supersede the older
release-directory copy below; TASK-269 reuses historical TASK-263 media with
its original provenance and does not rebuild or promote the old package.

The locally assembled package is in `artifacts/y8-release/`. Upload only
`grapnelninja-y8.zip`, not the directory. Its manifest identifies the committed
runtime, archive and media hashes, executed commands and evidence. The owner
handles console access, private preview, actual phones, hosted ads and submission.

**The package is prepared for inspection but is not ready for resubmission.**
TASK-257's matched-density software measurements regressed in all six candidate
runs: approximately 4.9–5.4 FPS versus 15.5–16.6 FPS for the baseline. The measured
runtime matches the packaged runtime. This is an unresolved local performance
gate, separate from unavailable physical-device checks. `package_ready`,
`submission_ready` and `moderation_approved` remain false. Completing TASK-257
certified its diagnostic evidence, not performance recovery.

The old 1688×780 versus 633×293 benchmark does not establish equal-quality gains.
Adaptive pixel density can soften output. Neither local browser emulation nor
synthetic visibility events certify phone performance or native OS suspension.

TASK-265 rebuilds the archive with the visibility-change progress flush and
checks its extracted bytes with the full smoke and lifecycle suites. Current
media is reused only after matching its capture archive and runtime hashes.
See `artifacts/TASK-265/final-checks.log`, `manifest.json`, `release-smoke.json`,
`mobile-lifecycle.json` and `performance-audit.json`. Requirements and the owner
handoff are in the release directory. No live gameplay, ads or upload is needed
for these local checks.

`python3 tools/assemble_y8_release.py` assembles the package from the completed
TASK-265 command records and final-byte evidence. It invalidates any old ready
claim before checking the inputs. `--audit` checks a sealed evidence manifest,
package hashes, readiness claims and staged paths without running browsers.
A changed runtime requires rebuilding and rerunning affected checks; a new
performance result requires reassessing the explicit performance gate.

`tools/profile_y8_compositing.py` captures and audits offline, 30-second glow
ablations against an extracted release. Its control retains the packaged
visuals; the other cases remove ambient glow, player glow, or both. All retain
DPR 2 and a 1560×780 backing canvas. These cases diagnose rendering cost but
cannot establish an equal-quality improvement or satisfy the performance gate.
Use a new output directory for each capture to preserve failed experiments.
TASK-265 repair diagnostics are under `artifacts/TASK-265/repair/`; the original
failed performance results remain authoritative until a real fix is retested.

`tools/profile_y8_glow_bounds.py` tests clipping additive glow to nonblack
source bounds on isolated copies of the release ZIP. The recorded experiment in
`artifacts/TASK-265/bounds-repair/retry/` preserved all pixels at ticks 60 and 150
in both modes, with unchanged DPR 2 and 1560×780 output. Its single 30-second
software sample improved from 5.24 to 7.61 FPS, still below the archived baseline
of 15.5–16.6 FPS. These sampled pixels do not prove universal equivalence, and
this diagnostic does not satisfy the six-run gate. No renderer change shipped.
Run `capture` or `audit` with `--archive` and `--out`; use a fresh directory for
capture. The source patch, raw frames, matched simulation states, captures,
offline network logs, environment and dependency hashes are retained. The first
capture failed because two initialization scripts lacked a separating semicolon;
its failure is preserved separately from the successful retry.

`tools/profile_y8_readback_oracle.py` isolates readback cost on the same committed
release bytes. It records bounds outside measurement, verifies every replayed
frame's state, glow-source SHA256 and final RGBA SHA256, then rotates full
compositing, readback-and-clip and recorded-bound clipping through three timed
repetitions in each mode. The oracle is valid only for that replay, never for
live moving content. Use `capture --archive PATH --out NEW_DIRECTORY`, followed
by `audit` with the same arguments. The default replay has 120 frames per mode,
seed 1, DPR 2 and 1560×780 backing; adaptive density is disabled.

Evidence is under `artifacts/TASK-265/readback-oracle/`, including interrupted
and failed harness attempts. Readback removal did not consistently improve
frame wall time: bad-mode repetition 2 took 16.31 seconds with oracle bounds
versus 16.07 seconds with readback. The specified stopping rule rejects this
hypothesis; averaging repetitions must not hide that counterexample. This is
not a shipping fix or an acceptance FPS result. Timings include instrumentation
and a double real-rAF barrier. Canvas API durations cover synchronous calls;
native Skia trace spans are partial. Neither measures complete GPU raster time.
The six inherited local regressions and false readiness flags remain binding.

`tools/profile_y8_live_geometry.py --out NEW_DIRECTORY` constructs a separate
live geometry candidate from the current archive and checks the archive against
committed runtime source. `tools/y8_live_geometry.js` bounds emitted rectangles,
player ribbon envelopes and ring strokes under their actual transforms. It
expands support through the unchanged blur chain and clips only the destination;
unknown drawing support falls back to the full viewport. It has no pixel scanning
or recorded-bounds cache. The supported helper and renderer bodies are concatenated into render/effects.js
for integration, preserving the 34-file runtime inventory. The standalone tools
remain outside the package.

Validation uses both modes and three seeds, full serialized states, full source
and final RGBA hashes, moving cameras, long trails, edge sparks, actual shake,
menu/start, debounced resize, odd backing sizes and empty geometry. Only matching
validation proceeds to three alternating untraced 30-second pairs per mode, at
780×390 CSS / DPR2 with fresh contexts. Whole-frame intervals and zero-readback
counts are retained; pixel hashing and geometry observations stay outside timing.
`tools/audit_y8_live_geometry.py --out DIRECTORY` independently verifies hashes,
coverage, comparisons and every paired result. Its exit zero means evidence
integrity, including an honest rejection; it does not satisfy the release gate.
The recorded experiment passed 138 full-state/source/final-pixel comparisons
and all six untraced timing pairs, with candidate FPS of 6.92–7.56. This is a
partial recovery, not proof that the historical 15.5–16.6 FPS deficit is resolved.
Final-byte TASK-257 results and current readiness must be read from the evidence
manifests; the experiment alone cannot mark the package ready.
The attempt directories also preserve interrupted harness captures and their
specific coverage/synchronization defects. Never promote their partial checks.

The separate full-source CanvasPattern candidate in
`artifacts/TASK-265/glow-pattern/attempt1/` is rejected. It retained the live
destination bounds, source textures, level order, alpha and blend operation,
but all 23 checked cases had different final pixels despite matching state and
source pixels. The fail-fast identity gate stopped before timing or remaining
seeds/modes; there is no performance result or shipping change from this probe.
`tools/profile_y8_glow_pattern.py --out NEW_DIRECTORY` records this experiment;
`tools/audit_y8_glow_pattern.py --out DIRECTORY` checks its evidence and rejection.
Do not rerun the rejected candidate unchanged or weaken pixel equality to ship
it. The six final-byte regressions still block package readiness.

`tools/profile_y8_glow_winding.py --out NEW_DIRECTORY` isolates another
candidate: reverse the player exclusion circle and use the nonzero winding
rule instead of even-odd clipping. It shares the pattern probe's exact
state/source/pixel gate and alternating live timing protocol, while retaining
the current full-image sampling, geometry bounds, alpha and blending. The
driver and shared harness hashes are recorded with the candidate patch.
`tools/audit_y8_glow_pattern.py --out DIRECTORY` audits either experiment,
including actual resize, moving-camera, shake and long-trail coverage.
Neither an identity pass nor an experiment's timing benefit substitutes for
the six final-byte release gates.
The winding experiment passed all 138 exact identity cases but failed its
consistent-benefit condition: at least one paired control was faster. It is
not integrated into production. Preserve its per-run results under
`artifacts/TASK-265/glow-winding/`; do not rerun this candidate unchanged.

Do not send the draft reviewer response until the local regression is resolved
and the owner has completed `OWNER-CHECKLIST.txt`. Keep all artifacts, screenshots
and unrelated `output/` files out of commits.

TASK-267's reproducible candidate is `artifacts/TASK-267/grapnelninja-y8.zip`,
with build tag `2026-10-10-y8-candidate267`. Its `candidate.json` records the
full committed source revision, both build hashes, packed inventory and actual
previous release identity. `build.log`, `archive-check.log` and `manifest.json`
record local build/test commands and evidence integrity. The extraction is
`artifacts/TASK-267/extracted/`. The previous release is preserved in place;
this candidate does not replace its validation or certify submission readiness.
Later verification must use this exact archive; phones, console and hosted ads
remain owner checks. The existing measured performance failures remain open.

For an exact-candidate offline check, run `tools/verify_y8_candidate.py` with
`--archive`, its matching extracted `--root`, a fresh `--out`, and each of
`--suite release`, `embed`, `mobile-embed`, `lifecycle`, and `ads`. The wrapper
checks every extracted runtime hash before/after each suite and records browser
versions, context profiles, route actions, request failures and trusted input
observations. The release suite now explicitly resumes moving gameplay through
the Resume control in every engine/profile/mode. Document-local input traces
reset on reload; release/lifecycle input proof also uses the suite's trusted
Playwright calls and asserted gameplay effects. SDK callbacks, seeded deaths,
visibility and blur remain local fixtures, not native or hosted certification.

TASK-268 stores the combined case report in `release-checks.json`, with raw
suite outputs/captures, command logs and a hashed `manifest.json` under
`artifacts/TASK-268/`. `python3 tools/audit_y8_candidate.py --out artifacts/TASK-268`
checks the saved results and hashes without repeating the browser suites.
Candidate verification does not clear inherited performance failures or replace
owner phone, hosted SDK/ad, console and moderation checks.
