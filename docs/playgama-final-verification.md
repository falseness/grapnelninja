# Final runtime verification: TASK-312

Status: **pending**. The accepted TASK-311 runtime passes its relative
comparison and visual gates, but fails TASK-312's independent desktop Firefox
requirement of average active-gameplay FPS strictly greater than 30 in every
one of three runs in each mode.

| Mode | Run 1 FPS | Run 2 FPS | Run 3 FPS |
| --- | ---: | ---: | ---: |
| Main/classic | 6.839765343 | 6.518943851 | 6.659410956 |
| Chill/bad | 7.153882316 | 7.116209011 | 7.187158943 |

The original TASK-307/TASK-309 control also fails all six absolute FPS checks
(4.87–5.17 FPS). No rollback offers a passing result. Runtime bytes remain
unchanged; there is no additional FPS improvement from this verification.

A bounded diagnostic with Firefox 150.0.2 under Xvfb measured 7.478046826 FPS
in Main, using the same seed, input policy, 844×390 viewport, DPR 2 and
1688×780 backing dimensions. Its WebGL renderer reported “llvmpipe, or
similar” (Mesa). That string does not identify the Canvas2D backend. This
single headed run is diagnostic only, not a replacement for the six-run
gate. A 1.54-second read-only evidence audit overlapped this diagnostic.
Do not repeat unchanged runs seeking a favorable result.

All eight required functional modules and the three individually bounded
180-second mobile profiles have passing original evidence. Reuse requires
matching runtime and tool hashes, verified by the read-only audit. Production
analytics and ads are isolated during local browser checks. Production FPS
is **NOT_MEASURED**; native Android Firefox is **UNVERIFIED**.

Local evidence (deliberately uncommitted) is in `artifacts/TASK-312/`:
`functional/`, `comparison/`, `firefox-fps/`, `environment-check/`,
`decision.json`, `handoff.json`, and `manifest.json`. The manifest binds
original commands, exits, raw data and source/build identities. Recompute
the evidence and absolute gate with:

```sh
python3 artifacts/TASK-312/audit.py
```

An exit of 1 with `FAIL TASK-312 acceptance` is the expected current result,
even when evidence integrity passes. A valid new six-run capture passing
the unchanged protocol is still required before marking the task to-verify.
Later packaging and upload do not resolve this failure.

The subsequent read-only recheck reproduced all six failures and verified
the original functional, mobile and visual evidence against unchanged
source, build and tool hashes. Its local receipts are in
`artifacts/TASK-312/recheck/`. The host exposes `/dev/dri/renderD128` through
`virtio_gpu` (PCI vendor `0x1af4`, device `0x0010`); device-node presence
alone does not prove Firefox Canvas2D acceleration. The software-renderer
diagnostic is therefore not evidence that no graphics device exists.

Before spending another six-run capture, identify a concrete runtime or
graphics-environment change and record it with the new commands and hashes.
Preserve the failed captures. A changed runtime also invalidates reuse of
its old functional and visual proof; rerun the affected checks and the
required baseline comparison. An environment change still requires all six
FPS runs to pass the same protocol. Neither a new environment nor an
integrity-only audit is a passing FPS result.

Privileged backend diagnostics now have a separate collector:

```sh
python3 tools/playgama_firefox_backend.py --out /tmp/firefox-backend-new
```

It uses the harness's Playwright Firefox executable and headless launcher,
adding a local Marionette endpoint and system-access flag to query
`nsIGfxInfo`. The output records effective graphics preferences, feature
histories, canvas backend, compositor, raw protocol responses, browser hash,
command, elapsed time and exit. Output directories must be new. Optional
`--prefs <json>` applies explicit `gfx.*`/`layers.*` overrides at startup;
requested or force-enabled preferences do not establish a working backend.
These diagnostic flags differ from the timing harness, and the collector
makes no gameplay performance claim.

The local `backend-01` investigation reports Skia canvas and software
WebRender. Default accelerated Canvas2D is blocklisted with
`FEATURE_FAILURE_GLXTEST_FAILED`; hardware compositing is blocked with
`FEATURE_FAILURE_COMP_HEADLESSMODE`. A startup acceleration override reports
Canvas2D `force_enabled`, but actual full-backing context initialization logs
`CanvasTranslator failed creating WebGL shared context`. The compositor
remains software. Therefore no functioning alternative backend was verified,
and no backend ABBA or unchanged final FPS capture was run. This establishes
a concrete diagnostic limitation, not an external-only cause or proof that
30 FPS is impossible. Runtime, quality, final-gate thresholds and pending
status remain unchanged. Preserve these results and do not repeat this same
force-pref attempt without a distinct mechanism addressing the context failure.
