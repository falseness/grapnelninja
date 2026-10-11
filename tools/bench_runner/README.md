# Grapnel Ninja offline benchmark runner (owner-operated)

Self-contained local measurement package for native desktop / Android Chrome /
iPhone Safari checks of the integrated current game. Nothing in it visits a
public site, loads the Y8 SDK, uploads telemetry or creates identifiers: the
game is served from the owner's own machine and the results stay on that
machine and/or the device.

## Contents

| path | purpose |
|---|---|
| `game/` | committed runtime (34 files, exact bytes of the recorded source revision) with ONE change: the public `cdn.y8.com` SDK `<script>` line of `index.html` is replaced by `<script src="bench.js"></script>` (`game/PATCH.diff`) |
| `game/bench.js` | in-page benchmark panel and frame recorder |
| `game/build.json` | identity of the served bytes: source revision, SHA-256 of every served file, tree hash, build version |
| `benchtool.py` | `serve`, `validate`, `summarize`, `inspect`, `replay`, `build` (Python 3.8+, standard library only) |
| `result-schema.json` | schema of an exported result |
| `OWNER-CHECKLIST.txt` | what to run on which devices and what to return |
| `test_bench_runner.py` | tests (cheap arithmetic/schema tests; optional Playwright smoke) |
| `results/` | results POSTed by the page land here |

## 1. Serve locally

On the machine that holds this folder (Python 3 required):

    python3 benchtool.py serve            # desktop only: http://127.0.0.1:8765/
    python3 benchtool.py serve --lan      # phones on the same Wi-Fi: prints http://<lan-ip>:8765/

The server serves only files below this folder, disables directory listings,
sends `Cache-Control: no-store`, logs to `server.log` without client addresses
and accepts `POST /save` (a result document) into `results/`. Stop it with
Ctrl-C when done. Do not expose the port beyond the local network.

## 2. Open the game with the panel

Open `http://<address>:8765/` on the device and tap the link (or open
`game/index.html` directly). The game boots exactly as shipped: the SDK is
absent, so `PLATFORM.environment` becomes `disabled` after its 2.9 s timeout,
rewarded ads are unsupported and a lethal death restarts instantly (the same
isolation the local harness uses). The benchmark panel appears at the bottom.

Phones: hold the device in landscape, disable auto-lock / keep the screen on,
close other apps. Desktop: a normal maximised window; record the DevTools
state you use (closed first, then docked, then undocked) and keep CPU
throttling disabled unless the checklist row says otherwise.

## 3. Fill in the panel (every run of a session shares these)

* **Device model** (required): the actual hardware, e.g. `Pixel 8`, `iPhone 15`,
  `ThinkPad T14 Gen 3`. An emulated device must be labelled with
  Emulation = `DevTools device emulation`; it is never a native result.
* **Display refresh rate**: Hz if you know it (phone settings / monitor OSD),
  otherwise leave `unknown`. The panel also records a requestAnimationFrame
  cadence estimate, clearly marked as an estimate.
* **DevTools**: closed / docked / undocked. **CPU throttle**: `none (1x)` or
  the DevTools setting. **Emulation**: `none` on a real device.
* **Mode**: Main version (`bad`) or Chill version (`classic`).
* **Replay**: `auto` (default) or `manual`.

## 4. Documented replay

**auto** (default): when you tap *Start run* the panel starts the selected mode
through the game's own `startGame(mode)` and dispatches the harness-style
bounded seeded grapnel throws itself: seed 4, holds of 250–900 ms separated by
80–450 ms, targets inside the 40–85 % × 15–60 % box of the view (away from the
HUD menu button and the left edge), scheduled on the active clock so menu,
pause and hidden gaps do not shift the sequence. Keep your hands off the game
until the panel comes back (about 65 s of active time). Deaths restart the run
instantly and are counted; they are never suppressed.

**manual**: tap *Start run*, then play this script for the whole run: hold the
grapple ~0.5 s towards the upper-right, release, wait ~0.3 s, repeat; keep
playing through deaths; never open the menu. Manual runs are not reproducible
and are recorded as `replay_kind: manual`.

The page's `Math.random` is seeded (mulberry32, seed 4, re-seeded at every run
start) so the obstacle sequence is comparable between devices; `?seed=none`
restores the native generator. This changes nothing about rendering, resolution
or effects.

## 5. Runs: 5 s warmup + 60 s measured, three per mode

A run records every `gameLoop` frame that the game itself treats as active
play: menu, pause, continue offer, hidden tab and ad states are excluded, the
interval after such a gap is dropped, and the warmup ends at the first frame
whose cumulative active time reaches 5 000 ms. The run completes when 60 000 ms
of active intervals have been measured after the warmup. While recording the
panel is hidden; if the game pauses (menu button, Esc/P, focus loss, tab
hidden) the panel reappears so you can resume in the game or abort. Aborted
and short runs are kept in the export as non-complete attempts and never
counted. After each run the panel shows the summary and (by default) sends the
whole session so far to the serving machine (`results/…json`).

Do three complete runs in Main, then switch Mode and do three in Chill. Do not
reset the session between runs of the same device. Changing DevTools state or
throttle is a new session (reload the page).

## 6. Export

* **Send to serving machine**: `POST /save` to the machine serving the page
  (automatic after every run; the newest file holds the whole session).
* **Download results**: saves `bench-<utc>-<model>.json` on the device
  (Android Chrome: Downloads; iPhone Safari: Files/Downloads via the share
  sheet). **Show JSON** reveals the text for copy/paste as a last resort.

Return the JSON files (see `OWNER-CHECKLIST.txt`); do not retype numbers.

## 7. Validate / summarize (on the serving machine)

    python3 benchtool.py validate results/<file>.json          # exit 0 = ACCEPTED
    python3 benchtool.py summarize                             # table of every run

`validate` checks the schema, that the result's build identity equals this
package's `game/build.json` (and that the package still matches it), SDK
isolation, frame arithmetic (increasing timestamps, interval == timestamp
difference, null intervals only after gaps), the seals (`frames_sha256`,
`replay_fractions_sha256` re-derived from the seed), that the page-side
numbers equal an independent recomputation, and that each COMPLETE run holds
≥ 60 000 ms of measured active intervals. It recomputes the verdict inputs
(average FPS, p50/p95/p99/max frame time, every rolling 10 s window and its
minimum FPS, gaps, deaths, backing-store sizes). It never decides PASS/FAIL
against the 60 FPS thresholds: that is the evaluator's job, and
`acceptance_eligible` is false for custom durations or emulated devices.

## 8. What the measurement does and does not change

* Only `gameLoop` and `reStart` are wrapped, and only while a run records;
  both are restored afterwards. The wrapper reads state and the rAF timestamp
  and calls the original loop with the same arguments.
* No drawing, physics, viewport or density function is replaced. Adaptive
  render density (`RENDER_BUDGET`) is NOT pinned: the shipped behaviour runs
  and every backing-store size change is recorded per run
  (`backing.changes`), so a softened run is visible, never hidden.
* No tracing, no pixel readback, no per-call timing wrappers.
* The panel is a DOM overlay hidden (`display:none`) during the whole measured
  period; its inputs stop event propagation so taps on it never reach the game.
* Network: the game requests only same-origin files; the page `fetch`es
  `build.json` and `POST`s to `../save` on the serving machine. Verify with
  `python3 benchtool.py inspect`.
