# TASK-330: exact release Firefox measurement

Six real sequential Firefox runs measured the exact TASK-329 release ZIP.
The measurement is complete; the desktop Firefox FPS gate is **FAIL**.
This result does not authorize release. Production FPS is `NOT_MEASURED`;
native Android is `UNVERIFIED`.

- ZIP: `grapnelninja-playgama-2026-10-12-selected-release.zip`
- Size: 93107 bytes; SHA256: `99f3e1bbd1f67cabfde853f25ede07cd850b52a8baed52297d1e71b3cdbac227`
- Runtime revision: `ade0043b42a2f182d8584dc63cdcf11a4a197816`
- Firefox: 150.0.2; executable SHA256: `239e76665a080259bf1e68205f4086c3b469e5eb4844f1a487384592d8404d4d`
- Viewport 844×390, DPR 2, backing 1688×780, logical 2337×1080, seed 292.
- Original headless launch environment; no CPU throttling or backend overrides.
- At least 5 active seconds warmup and 30 measured active seconds per run.
- FPS = measured interval count / summed interval seconds; nearest-rank p95.
  Inactive gaps are excluded; slow active and death-ending intervals are retained.
  Every run must be strictly above 30 FPS; results are not averaged across runs.

| Mode | Run | Average FPS (unrounded) | p95 ms | Measured ms | Gate |
| --- | --- | --- | --- | --- | --- |
| Chill (classic) | 1 | 6.774154299450504 | 200.02000000000407 | 30409.7 | FAIL |
| Chill (classic) | 2 | 6.563524307581335 | 200.4800000000032 | 30166.719999999998 | FAIL |
| Chill (classic) | 3 | 6.77559621941562 | 216.09999999999854 | 30255.64 | FAIL |
| Main (bad) | 1 | 7.053120260667431 | 183.84000000000015 | 30199.399999999998 | FAIL |
| Main (bad) | 2 | 7.020366900700665 | 199.55999999999767 | 30625.18 | FAIL |
| Main (bad) | 3 | 6.699479816744475 | 200.5199999999968 | 30300.86 | FAIL |

Evidence remains local under `artifacts/TASK-330/`: sealed `capture/` contains
raw intervals and input/state traces; `results.json` contains all metrics and
ZIP/member hashes; `manifest.json` binds original command logs, exit codes,
UTC times, durations, environment and tool identities. `handoff.json` separates
measurement completeness from FPS acceptance. The original capture and evaluate
commands both returned 1 (valid FPS failure). `audit.py` independently recomputes every metric,
checks the exact ZIP/extracted members and validates the sealed collector proof;
`audit.log` records its passing assertions. Correctly empty stderr logs are retained.

Recheck without launching a browser:

```sh
python3 artifacts/TASK-330/audit.py
```

No runtime, ZIP, effect resolution, density, sampling or gameplay changes were made.
No repeated capture, device-performance claim or upload is included.
