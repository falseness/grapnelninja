# TASK-332: release admission assessment

**NOT_READY.** All twelve required desktop FPS runs fail the strict >30 FPS
threshold. The exact package, functional evidence, browser identities and sealed
captures pass validation. This assessment does not authorize upload; no upload
was performed.

The assessed ZIP is `grapnelninja-playgama-2026-10-12-selected-release.zip`
(93107 bytes), SHA256
`99f3e1bbd1f67cabfde853f25ede07cd850b52a8baed52297d1e71b3cdbac227`,
from runtime revision `ade0043b42a2f182d8584dc63cdcf11a4a197816`.
Its two member hashes match the extracted runtime and both captures. The
reproducibility audit reconstructs the archive from committed source in memory
and compares both retained builds. Functional evidence passes all 10 tests,
including raw readiness, lifecycle, recovery, input and telemetry checks.

| Engine | Mode | Run | FPS | p95 ms |
| --- | --- | --- | --- | --- |
| firefox | classic | 1 | 6.774154299450504 | 200.02000000000407 |
| firefox | classic | 2 | 6.563524307581335 | 200.4800000000032 |
| firefox | classic | 3 | 6.77559621941562 | 216.09999999999854 |
| firefox | bad | 1 | 7.053120260667431 | 183.84000000000015 |
| firefox | bad | 2 | 7.020366900700665 | 199.55999999999767 |
| firefox | bad | 3 | 6.699479816744475 | 200.5199999999968 |
| chrome | classic | 1 | 6.300428165222955 | 199.90000000000146 |
| chrome | classic | 2 | 6.016611078412138 | 200.0 |
| chrome | classic | 3 | 5.806667497752787 | 216.59999999999854 |
| chrome | bad | 1 | 6.316069410278573 | 183.40000000000146 |
| chrome | bad | 2 | 6.153232109893399 | 183.40000000000146 |
| chrome | bad | 3 | 6.380418396762847 | 183.3000000000029 |

The unchanged protocol uses viewport 844×390, DPR 2, backing 1688×780,
logical size 2337×1080, seed 292, at least 5 active seconds warmup and
30 measured active seconds. Inactive gaps are excluded; slow active intervals
are retained. FPS uses interval count / summed interval seconds; p95 uses
nearest rank and has no separate admission threshold. Actual Google Chrome
155.0.8059.39 and Firefox 150.0.2 identities, executable hashes and original
launch logs were checked. No browser timing was repeated.

Local evidence is in `artifacts/TASK-332/`: `preflight.json` lists all twelve
metrics, thresholds, functional result and full release identity; `receipt.json`
lists each failure; `combine.log` retains original evaluator output and exit 1.
`manifest.json` records command/cwd/UTC/duration/exit, source/tool/browser
identities and SHA256 of 320 consumed files and seven outputs. Original stdout
and empty stderr remain in the fresh attempt directory. `audit.log` records
successful independent validation (exit 0), including recalculated FPS/p95.
Earlier artifacts are referenced in place and were not copied or modified.

The read-only audit can be repeated with:

```sh
python3 artifacts/TASK-332/audit.py
```

The historical TASK-329 audit expects HEAD to equal its package revision.
The admission audit resolves that one historical query to the verified package
ancestor, retaining all source/blob, reproducibility and raw functional checks.
Later documentation commits do not change the assessed runtime identity.

Production FPS remains `NOT_MEASURED`; native Android remains `UNVERIFIED`.
A new admission attempt requires materially changed runtime or a verified
changed graphics environment and new applicable evidence. Status edits, later
publication tasks and TASK-312/313/314 are not prerequisites for this decision.
