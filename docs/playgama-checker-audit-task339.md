# Checker audit — TASK-339

The branch is not production-ready. This audit ran every `tools/test_*.py`
module, all 100 of them, one at a time at `6181d60`. Earlier audits ran only the
Playgama checker subset. Each failure was then traced to its first error,
and the runtime and packaging code was reviewed. It changes no runtime or
checker behaviour; findings are appended as TASK-340..350.

## Runtime defects

- **TASK-340, late interstitial plays over live gameplay.** A late ad is never
  recognised as open. `showInterstitial` gives up after 3000 ms
  (`platform.js:301`) and sets `adBusy=false`. The global listener at
  `platform.js:117-118` accepts an interstitial `'opened'` only while `adBusy`
  is set. So when an ad opens after the watchdog, no `adState` event fires:
  physics keeps running and audio stays unmuted underneath the ad. A Node VM
  reproduction drives the real `platform.js`.
- **TASK-341, abandoned run has no terminal lifecycle event.** Pause → "back
  to menu" calls `next()` without `level_failed` (`index.html:368-376`). The
  host therefore sees `level_started → level_paused → level_started`.

## Packaging and release tooling

- **TASK-342, references silently left out of the ZIP.** `bundle()` in
  `tools/build_playgama.py` inlines only `<script src>` tags. It drops other
  local `src`/`href` references from the ZIP without error.
- **TASK-343, documented release procedure cannot pass.** The steps in
  `docs/playgama-release.md` and `tools/verify_playgama_release.py` still
  assume the old builder: the `playgama2` ancestry check, 38 ZIP members and
  `platform.js` as its own member. The current builder inlines everything into
  a 2-member ZIP.
- **TASK-344, `--phone` mislabels desktop cases.** In
  `tools/verify_hosted_playgama.py`, `--phone` overrides `has_touch`, so
  "desktop" cases actually run as touch/mobile.
- **TASK-345, audit passes on empty evidence.**
  `tools/verify_playgama_audit.py` passes vacuously on empty evidence.

## Master-era regression suite

Of the 100 modules, 48 exit 0 and 52 fail. All 36 test modules that this branch
added or changed pass, except two that need configuration (below). Every failure
falls into one of the groups below; `classification.json` holds the first
error of each failing module.

- **22 modules (TASK-346):** they stop at "boot() did not finish under the
  frozen clock". `tools/render_snapshot.py` never advances its manual clock
  during boot, but the Playgama adapter waits for the offline SDK through a
  2900 ms timer.
- **16 modules (TASK-347):** they fail on the
  `Failed to load resource: net::ERR_FAILED` console error from the aborted
  Bridge SDK request, and on readiness timeouts.
- **API drift (TASK-348):** these call removed `continueRun`, the master
  `local` adapter, or other changed globals.
- **Environment-gated (TASK-349):** these modules crash under discovery
  instead of skipping:
  - variables `REAL_BRIDGE_DIR` and `*_BASE_REV`;
  - missing `artifacts/TASK-227` and `artifacts/TASK-230` files;
  - the `--zip`-only `test_playgama_repair_archive`.

  Run as configured, `test_loading_real_sdk` passes in Chromium, Firefox
  and WebKit (`real-sdk.log`).
- **Exact-ZIP checker hangs (TASK-350).** Run against a fresh HEAD build,
  `tools/test_playgama_repair_archive.py` failed `test_three_retries` and
  `test_exhausted_rejection`; both pass headless. The `bad-delayed` start-flow
  case then exceeded its 120 s alarm. That alarm raises inside Playwright's
  event loop (`test_playgama_repair_archive.py:46-49`), and cleanup then spins
  at 100% CPU forever. The run printed nothing for 20 minutes and ended only on
  SIGINT (`repair-archive.log`, EXIT 130). TASK-329's single run of this
  checker had passed.

Until TASK-346..348 are done, rendering and gameplay on this branch are not
covered by the master regression suite. The known release FPS failure (TASK-333)
stays outside this audit's tickets. Evidence is in `artifacts/TASK-339/`:
`run_checkers*.py`, `commands*.json`, `logs/`, `classification.{json,log}`
and `repro/`.
