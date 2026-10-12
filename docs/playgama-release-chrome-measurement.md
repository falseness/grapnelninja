# TASK-331: exact release Chrome measurement

Six sequential runs in actual Google Chrome completed against the exact TASK-329
release ZIP. The measurement is complete; the desktop Chrome FPS gate is **FAIL**.
This result does not authorize release. Production FPS is `NOT_MEASURED`;
native Android is `UNVERIFIED`.

- ZIP: `grapnelninja-playgama-2026-10-12-selected-release.zip`
- Size: 93107 bytes; SHA256: `99f3e1bbd1f67cabfde853f25ede07cd850b52a8baed52297d1e71b3cdbac227`
- Runtime revision: `ade0043b42a2f182d8584dc63cdcf11a4a197816`
- Google Chrome: 155.0.8059.39; executable: `/opt/google/chrome/chrome`
- Executable SHA256: `9bfb381296dffe75f3419d07b6cc64525105ed117d1453a4ef3b291cb97d2b58`
- Viewport 844×390, DPR 2, backing 1688×780, logical 2337×1080, seed 292.
- Original headless launch environment; no CPU throttling or backend overrides.
- At least 5 active seconds warmup and 30 measured active seconds per run.
- FPS = interval count / summed interval seconds; nearest-rank p95.
  Inactive gaps excluded; slow active and death-ending intervals retained.
  Each run must be strictly above 30 FPS; no averaging across failures.

| Mode | Run | Average FPS (unrounded) | p95 ms | Measured ms | Gate |
| --- | --- | --- | --- | --- | --- |
| Chill (classic) | 1 | 6.300428165222955 | 199.90000000000146 | 30315.400000000005 | FAIL |
| Chill (classic) | 2 | 6.016611078412138 | 200.0 | 30581.999999999996 | FAIL |
| Chill (classic) | 3 | 5.806667497752787 | 216.59999999999854 | 30482.2 | FAIL |
| Main (bad) | 1 | 6.316069410278573 | 183.40000000000146 | 30081.999999999996 | FAIL |
| Main (bad) | 2 | 6.153232109893399 | 183.40000000000146 | 30065.5 | FAIL |
| Main (bad) | 3 | 6.380418396762847 | 183.3000000000029 | 30248.8 | FAIL |

Evidence remains local under `artifacts/TASK-331/`. Sealed `capture/` contains
the raw intervals, input/state traces, protocol, browser identity and launch log.
`results.json` records metrics and ZIP/member identities. `manifest.json` retains
command/cwd/UTC/duration/exit receipts, launch environment and original log hashes.
`handoff.json` distinguishes measurement completeness from FPS acceptance.
Both required commands returned 1, meaning valid measurements with a failed FPS
gate. The read-only `audit.py` independently recomputes every metric and checks
ZIP/member hashes and sealed evidence; `audit.log` records passing assertions.

The local receipt runner initially failed to parse an informational line before
the evaluation JSON. Postprocessing was corrected while retaining original logs;
the browser capture was not repeated. Empty stderr files are preserved.

Recheck without launching a browser:

```sh
python3 artifacts/TASK-331/audit.py
```

The release ZIP, runtime, effects and gameplay remain unchanged.
