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
