# Platform SDK map (facade backends)

The game only calls `PLATFORM` (platform.js, the facade). Every public method
delegates to the same-named inner method of `PLATFORM_BACKEND`, defined by one
backend file under `platform/backends/`:

| file | platformId | status |
|---|---|---|
| `local.js` | `local` | default; localStorage storage, no ads; also exposes `LOCAL_PLATFORM_BACKEND` |
| `itch.js` | `itch` | ported (TASK-856), self-contained: init `{environment: 'itch', language}` from `navigator.language`, localStorage saves (in-memory fallback), no ads (going back is free), `onPause` on window blur/focus and `visibilitychange`; the game pauses and mutes (`GAME_AUDIO` reason `host`) while paused; tested in an itch.io-like sandboxed 960x540 iframe by tools/test_itch_backend.py |
| `gamepix.js` | `gamepix` | ported (TASK-857), self-contained: `lifecycle.loading(n)` non-decreasing 0..100, `lifecycle.loaded()` once on `gameReady` (and before any ad call), `lifecycle.gameStart()` once on the first `gameplayStart` after `loaded()`; `events.on('pause'\|'resume')` -> onPause/onAudio (the game pauses and mutes, `GAME_AUDIO` reason `host`); interstitial (`ads.interstitial()`) refused while a run is in play, one in flight, min gap; rewarded via `ads.reward()`; every SDK call guarded with timeouts (`adOpenTimeoutMs` 3 s without a GamePix pause, `adResumeGraceMs` 2 s after the ad's resume, `adPlayingTimeoutMs` 120 s, `loadedTimeoutMs` 3 s); localStorage saves with in-memory fallback; tested by tools/test_gamepix_backend.py (fake SDK recorder + real SDK smoke) |
| `y8.js` | `y8` | ported (TASK-858), self-contained: init waits for the async SDK (`window.y8` present, `y8sdk.ready` or the script tag's load; `readyTimeoutMs` 3 s) then `sdk.init({appId, autoLogin: false}, {gameId})` with `BUILD_CONFIG.y8` ids (`initTimeoutMs` 3 s); missing/throwing/rejecting/never-settling SDK -> environment `disabled`, game plays, no ads; guest play (never logs in; localStorage is the save of record, `loadData` fills locally missing keys and `saveData` mirrors writes, 1 per key per 5 s, only while `sdk.getUser()` is signed in); `isBlacklisted()` asked once (`blacklistTimeoutMs` 6 s), true disables interstitial and rewarded, failure allows ads; interstitial `showAd({type: 'next'})` refused while a run is in play, one in flight, min gap, `adOpenTimeoutMs` 3 s / `adPlayingTimeoutMs` 120 s; window blur / hidden -> onPause + onAudio (pause and mute, `GAME_AUDIO` reason `host`), a blur during our own ad is ignored; no leaderboards/achievements (false); tested by tools/test_y8_backend.py (fake SDK recorder + real SDK smoke) |
| `playgama.js` | `playgama` | ported (TASK-859), self-contained: `bridge.initialize({configFilePath: 'playgama-bridge-config.json', disableLoadingLogo: true})` within `PLATFORM.initTimeoutMs` (missing/throwing/rejecting/never-settling bridge -> environment `disabled`, the game plays, a late initialize still attaches); `sendMessage('game_ready')` once at the first playable frame (only an explicit rejection is retried, 500/1000/2000 ms); lifecycle messages (`level_*`, `gameplay_started`/`gameplay_stopped`, `player_got_achievement`) and the `startup_funnel` wait in a bounded queue until game_ready went out; `PAUSE_STATE_CHANGED` -> onPause (pause and mute, `GAME_AUDIO` reason `host`), `AUDIO_STATE_CHANGED` -> onAudio (mute without pausing; index.html `PLATFORM.onAudio`); interstitial refused while a run is in play, one in flight, min gap, settled on `INTERSTITIAL_STATE_CHANGED` (`adOpenTimeoutMs` 3 s / `adPlayingTimeoutMs` 120 s); rewarded via `REWARDED_STATE_CHANGED`; telemetry only via `bridge.analytics.send`; saves via `bridge.storage` with the published Grapnel Ninja keys (artifacts/TASK-859/save-format.md; values turned back into strings, no write before the first read answered, late reads reconciled via `onRecovery`; localStorage under the same keys without a usable bridge); ships `playgama-bridge-config.json`; tested by tools/test_playgama_backend.py (fake bridge on game_harness LOCAL_BRIDGE only) |

All four portal backends are ported (each self-contained; local.js still loads
first in a build). A port replaced the stub's `// REPLACE: <SDK call>` bodies in
that ONE file; platform.js does not change. The game's only Playgama-driven
addition is index.html's `PLATFORM.onAudio` hook (host audio off mutes).

## Selecting a backend (script-tag swap)

`index.html` loads the backend right before `platform.js`. Default:

```html
<script src = "platform/backends/local.js"></script>
<script src = "platform.js"></script>
```

For a portal build add the portal SDK tag and the portal stub after `local.js`
(the stub reuses `LOCAL_PLATFORM_BACKEND` and redefines `PLATFORM_BACKEND`):

| portal | SDK tag (before the backend) | backend tag |
|---|---|---|
| itch.io | none (no SDK) | `<script src = "platform/backends/itch.js"></script>` |
| GamePix | `<script src="https://integration.gamepix.com/sdk/v3/gamepix.sdk.js"></script>` (sync) | `<script src = "platform/backends/gamepix.js"></script>` |
| Y8 | `<script src="https://cdn.y8.com/minimal-sdk/2-0/y8.min.js" async></script>` (wait for `y8sdk.ready`) | `<script src = "platform/backends/y8.js"></script>` |
| Playgama | `<script src="https://bridge.playgama.com/v2/stable/playgama-bridge.js"></script>` | `<script src = "platform/backends/playgama.js"></script>` |

`tools/test_platform_backends.py` does exactly this swap with a Playwright
route for all five backends.

### Release zips

`python3 tools/build_release.py --portal itch|gamepix|y8|playgama|all [--out DIR]`
builds `DIR/<portal>/grapple-over-<portal>.zip` plus `manifest.json` (default
DIR `artifacts/release-grapple-over`) from the git blobs of HEAD (`--rev`).
It ships index.html at the zip root plus every file index.html references and
every committed file a shipped script names in a string literal
(`leveldata.js`, `art/win-*.svg`); adds the SDK tag and backend tag above
after `local.js` (kept: the stubs build on `LOCAL_PLATFORM_BACKEND`); keeps
`analytics/backends/none.js` except for itch.io and Y8, where it swaps that
tag for the vendored GameAnalytics SDK plus `analytics/backends/gameanalytics.js`
with the keys injected (see "GameAnalytics backend (itch.io, Y8)" below);
rewrites `buildconfig.js` (modes
`['grapple_over']` for itch.io, GamePix and Y8, every mode for Playgama;
`Y8_APP_ID` / `Y8_GAME_ID` from the environment for Y8; `build` =
`<sha12>-<commit date>`). The itch build needs `GA_GAME_KEY` /
`GA_SECRET_KEY` in the environment, the y8 build `Y8_APP_ID` / `Y8_GAME_ID`
(`set -a; . /root/credentials/grapnelninja/credentials.env; set +a`).
Test: `tools/test_build_release.py`.

## Facade method x portal SDK call

| facade method | itch.io | GamePix v3 (`GamePix`) | Y8 minimal SDK 2.x (`sdk = y8.sdk()`) | Playgama Bridge (`bridge`) |
|---|---|---|---|---|
| `now` | `performance.now()` | `performance.now()` | `performance.now()` | `performance.now()` |
| `init` | resolve `{environment:'itch', language}` | `GamePix.lang()` (sync tag) | `await y8sdk.ready; sdk.init({appId, autoLogin:false}, {gameId})` | `await bridge.initialize()`; `bridge.platform.id`, `bridge.platform.language` |
| `isInterstitialSupported` | `false` | `typeof GamePix.ads.interstitial === 'function'` | `!!sdk && !sdk.isBlacklisted()` | `bridge.advertisement.isInterstitialSupported` |
| `isInterstitialDue` | `false` | own min-gap check | own min-gap check | own min-gap check (`setMinimumDelayBetweenInterstitial`) |
| `showInterstitial` | `'skipped'` | `GamePix.ads.interstitial()` -> `{success}`: `'closed'` / `'failed'`; `'skipped'` while a run is in play | `sdk.showAd({type:'next'})` | `bridge.advertisement.showInterstitial(placement)` + `INTERSTITIAL_STATE_CHANGED` |
| `sendMessage` | - | - | - | `bridge.platform.sendMessage(message)` |
| `sendLifecycle` | - | - | - | `bridge.platform.sendMessage(name, data)` |
| `track` | - (GameAnalytics allowed) | - (**no third-party analytics**) | - (GameAnalytics allowed) | `bridge.analytics.send(event, data)` (**no external analytics**) |
| `startup` | - (GameAnalytics progression allowed) | - | - (GameAnalytics allowed) | `bridge.analytics.send('startup_funnel', ...)` |
| `gameReady` | - | `GamePix.lifecycle.loaded()` | - | `bridge.platform.sendMessage('game_ready')` |
| `readiness` | `{state:'local'}` | `{state: 'success'\|'disabled'}` | `{state: 'success'\|'disabled'}` | `{state: 'success'\|'disabled'}` |
| `isAudioEnabled` | `true` | `false` while a GamePix `pause` holds (mute via pause event) | `!document.hidden` | `bridge.platform.isAudioEnabled` |
| `onPause` | window blur/focus | `GamePix.events.on('pause'\|'resume')` | window blur/focus | `bridge.platform.on(PAUSE_STATE_CHANGED)` |
| `onAudio` | - | `GamePix.events.on('pause'\|'resume')` | window blur/focus | `bridge.platform.on(AUDIO_STATE_CHANGED)` |
| `onAdState` | - | wrap `ads.interstitial()/reward()` | wrap `sdk.showAd()` | `bridge.advertisement.on(INTERSTITIAL_/REWARDED_STATE_CHANGED)` |
| `loadingProgress` | - | `GamePix.lifecycle.loading(0..100)` (non-decreasing) | - | - |
| `gameplayStart` | - | `GamePix.lifecycle.gameStart()` | - | `bridge.platform.sendMessage('gameplay_started')` |
| `gameplayStop` | - | - | - | `bridge.platform.sendMessage('gameplay_stopped')` |
| `happyMoment` | - | `GamePix.happyMoment()` | - | - |
| `isRewardedSupported` | `false` | `typeof GamePix.ads.reward === 'function'` | SDK initialized and not blacklisted | `bridge.advertisement.isRewardedSupported` |
| `showRewarded` | `'unavailable'` | `GamePix.ads.reward()` -> `{success}` | `sdk.showAd({type:'reward'})`; reward only when `adViewed` fired | `bridge.advertisement.showRewarded(placement)`; reward only on state `'rewarded'` |
| `showBanner` / `hideBanner` | - | - | - | `bridge.advertisement.showBanner(position)` / `hideBanner()` |
| `submitScore` | `false` | `false` | `false` (no Y8 tables configured) | `bridge.leaderboards.setScore(board, value)` |
| `unlockAchievement` | `false` | `false` | `false` (none configured) | `bridge.achievements.unlock({id})` |
| `getLanguage` | `navigator.language` | `GamePix.lang()` | `navigator.language` | `bridge.platform.language` |
| `getPlatformId` | `'itch'` | `'gamepix'` | `'y8'` | `'playgama'` |
| `storage.remoteKnown` | `true` | `true` | `true` | `true` once `bridge.storage.get` resolved |
| `storage.onRecovery` | - | - | - | late `bridge.storage.get` reconcile |
| `storage.getMany` | `localStorage.getItem` | `localStorage.getItem` | `localStorage.getItem` (+ `sdk.loadData({key})` for locally missing keys, signed in) | `bridge.storage.get(keys)` |
| `storage.setMany` | `localStorage.setItem` | `localStorage.setItem` | `localStorage.setItem` (+ `sdk.saveData`, 1 write/key/5 s) | `bridge.storage.set(keys, values)` |

`-` = no SDK call; keep the local no-op.

## Rewarded go-back

After a long fall in Grapple Over the 'Go back?' dialog offers to return to
the go-back checkpoint (menu.js). With `PLATFORM.isRewardedSupported()` the
Go back button carries the AD marker and calls `PLATFORM.showRewarded('go_back')`;
without it Go back is free. Only `'closed'` (the player closed the ad early)
keeps falling; every other result goes back.

| platform | Go back | isRewardedSupported | showRewarded result mapping |
|---|---|---|---|
| local | free | `false` | `'unavailable'` |
| itch.io | free (no ad SDK) | `false` | `'unavailable'` |
| GamePix | rewarded when `GamePix.ads.reward` exists, else free | `typeof GamePix.ads.reward === 'function'` | `{success: true}` -> `'rewarded'`; `{success: false}` (closed early, no fill) -> `'closed'`; throw / rejection / never settles (timeouts above) / another ad up -> `'failed'`; no `reward()` -> `'unavailable'` |
| Y8 | rewarded when the SDK initialized and the site is not blacklisted, else free | SDK initialized, `isBlacklisted()` not true | `showAd({type: 'reward', name: placement})`, settled on `afterAd` / `adBreakDone`: `adViewed` fired -> `'rewarded'`; `adDismissed` (or breakStatus `dismissed`) -> `'closed'`; no ad (noAdPreloaded, frequencyCapped, timeout, error, ...), throw / rejection / never starts (3 s) or never ends (120 s) / another ad up -> `'failed'`; no SDK or blacklisted -> `'unavailable'` |
| Playgama | rewarded when the bridge initialized and `bridge.advertisement.isRewardedSupported`, else free | bridge initialized and `bridge.advertisement.isRewardedSupported === true` | REWARDED_STATE_CHANGED: `'rewarded'` then `'closed'` -> `'rewarded'`; `'closed'` alone -> `'closed'`; `'failed'`, throw / rejection, no state within 3 s or no end within 120 s (`'rewarded'` if already earned) / another ad up -> `'failed'`; no bridge or unsupported -> `'unavailable'` |

Go-back outcome per result: `'rewarded'`, `'failed'`, `'unavailable'`, any
other value and the 30 s timeout -> go back; `'closed'` -> keep falling.
Without its SDK each portal backend returns the local results (`false` /
`'unavailable'`, free). Tests: tools/test_rewarded_backends.py (GamePix, Y8,
itch.io), tools/test_gamepix_backend.py, tools/test_y8_backend.py, tools/test_playgama_rewarded.py, tools/test_playgama_backend.py, tools/test_go_back_ad.py.

## Publication must-haves per portal

- **itch.io** — zip with `index.html` at the root; no SDK; saves in localStorage
  (works in the itch.io iframe). Docs: https://itch.io/docs/creators/html5
- **GamePix** — `GamePix.lifecycle.loading(n)` 0..100, never decreasing, then
  `GamePix.lifecycle.loaded()` **before any ad call**; `gameStart()` when play
  starts; pause and mute on `GamePix.events.on('pause')`, resume on `'resume'`;
  ads only via `GamePix.ads.interstitial()` / `ads.reward()` at natural breaks
  (death/restart), never during play. Docs: https://partners.gamepix.com/sdk/doc/javascript
- **Y8** — **guest play**: the game must be fully playable without a Y8 login
  (`autoLogin: false`; saveData/loadData/leaderboards only when signed in, the
  local save stays the record); pause **and** mute on window blur; ads via
  `showAd({type:'next'})` at breaks only; respect `isBlacklisted()`.
  Docs: https://docs.y8.com/sdk/intro/
- **Playgama** — `bridge.initialize()` then `sendMessage('game_ready')` when the
  first frame is playable (mandatory); honour `PAUSE_STATE_CHANGED` and
  `AUDIO_STATE_CHANGED`; interstitials only at natural breaks through
  `bridge.advertisement`, rewarded grants only on `'rewarded'`; storage via
  `bridge.storage`. Docs: https://wiki.playgama.com/playgama/bridge-sdk/setup.md

## Analytics bans

- **No GameAnalytics (or any third-party analytics) on GamePix.**
- **No GameAnalytics (or any external analytics) on Playgama** — only
  `bridge.analytics.send`.
- GameAnalytics is allowed on itch.io, Y8 and local builds; it ships on
  **itch.io and Y8** (user decisions), through the analytics backend
  `analytics/backends/gameanalytics.js` (below), never in a platform backend.
  Docs: https://github.com/GameAnalytics/GA-SDK-JAVASCRIPT

## Telemetry facade (GameAnalytics backend)

Telemetry goes through its own facade, `analytics.js` (`ANALYTICS`), over
`ANALYTICS_BACKEND`. index.html loads `analytics/backends/none.js` and then
`analytics.js`, right after `platform.js`. The facade sanitizes every call
the GameAnalytics way (ids of 1-5 `:`-segments, `[A-Za-z0-9_.-]`, <= 32
chars each; progression levels filled in order; unknown status/severity
dropped; error messages <= 8000 chars), records it in `ANALYTICS.debugLog`
(last 500) and never lets a backend throw into the game.

| Facade | Inner method (`// REPLACE:` GameAnalytics call) |
| --- | --- |
| `init({build})` | `initialize(config)` -> `configureBuild` + `initialize(gameKey, secretKey)` |
| `sessionStart()` / `sessionEnd()` | `startSession()` / `endSession()` |
| `progression(status, l1, l2?, l3?, score?)` | `addProgressionEvent(status, p1, p2, p3, score)` |
| `design(id, value?)` | `addDesignEvent(id, value)` |
| `error(severity, message)` | `addErrorEvent(severity, message)` |
| `ad(action, type, placement)` | `addAdEvent(action, type, sdkName, placement)` |

- **GamePix and Playgama: the analytics backend must stay `none`.** Their
  rules forbid third-party analytics (Playgama telemetry goes through
  `bridge.analytics.send` in the platform backend's `track` instead).
- **itch.io and Y8 ship the GameAnalytics backend** (same game key; the
  build is reported as `itch-<build id>` / `y8-<build id>`, so the two stay
  apart in GameAnalytics): see "GameAnalytics backend (itch.io, Y8)" below.
  The dev index.html and the GamePix / Playgama builds stay on `none.js`.
- Call sites: boot sends `init({build: PLATFORM.buildVersion})` +
  `sessionStart()` once after `PLATFORM.init()`; `pagehide` sends one
  `sessionEnd()` per page; a `pageshow` with `persisted` (the page came back
  from the back/forward cache, TASK-907) reopens it: `sessionStart()` (a new
  GameAnalytics session; events wait until it started), progression `Start`
  again for the run and section the pagehide failed, and the next `pagehide`
  sends the quit-time events and `sessionEnd()` again; window `error` / `unhandledrejection` send
  `error('error', '<message> @ <file>:<line>')`, deduplicated, at most 10 per
  session; `PLATFORM.showInterstitial` / `showRewarded` results send
  `ad('show' | 'failed_show' | 'reward_received', 'interstitial' | 'rewarded',
  placement)` for 'closed' / 'failed' / 'rewarded' (nothing for 'skipped' /
  'unavailable').
- Design counters: `design('best_height:<single|double>', bucket * 500)` once
  per 500-unit best height bucket per Grapple Over run (a restored run keeps
  its buckets); `design('fall:<sectionId>')` per counted fall, against the
  section of the last grapple catch; `design('restart:<mode>')` on the Grapple
  Over restart and the Classic/Bad death screen Restart;
  `design('death:<mode>')` when the Classic/Bad death screen opens. Their
  state is never saved (climbStats is unchanged).
  Docs: https://github.com/GameAnalytics/GA-SDK-JAVASCRIPT
- Mode time and quit (telemetry.js): active play seconds per grapnel mode
  (playing frames only) go out as `design('mode_time:<single|double>',
  wholeSeconds)` when `setGrapnelMode` changes the mode and on `pagehide`.
  `TELEMETRY.mark(type, sectionId)` keeps the last fall / grapple / pause /
  restart / death / section / complete. `pagehide` sends, once per page and
  in this order: the mode time flush, `design('quit:<type>:<sectionId>')`,
  `progression('Fail', mode, sectionId)` for a section in progress, then
  `sessionEnd()` last. The session play time events below go out right
  after the mode time flush.

### Session telemetry (TASK-861)

telemetry.js `createSession()`, sent only through `ANALYTICS.design` (so it
is sanitized, recorded in `ANALYTICS.debugLog`, and reaches GameAnalytics on
the itch.io build only). Every id below is already clean (the sanitizer
leaves it unchanged): at most 4 `:`-segments of `[A-Za-z0-9_.-]`, each
<= 32 chars. No user agent string, no free text, no identifiers: the user
agent is parsed in the page into a family name and a major version only.

**Start events**, once per page, after `ANALYTICS.sessionStart()` and once
the game language is applied (`TELEMETRY.sendEnvironment()` in boot), in
this order (7 events):

| Id | Value |
| --- | --- |
| `env:browser:<chrome\|firefox\|safari\|edge\|opera\|samsung\|yandex\|other>` | major version, integer 0..999 (0 = unknown) |
| `env:os:<windows\|macos\|ios\|android\|linux\|chromeos\|other>` | none |
| `env:device:<desktop\|phone\|tablet>` | none (iPad, iPadOS desktop mode = Macintosh UA with touch, Android without `Mobile` -> tablet) |
| `env:input:<touch\|mouse>` | none (`(pointer: coarse)` -> touch) |
| `env:screen:<W>x<H>:dpr<D>` | none. `window.screen` CSS size, each side floored to a bucket: W in 0, 320, 360, 400, 480, 600, 768, 1024, 1280, 1366, 1440, 1600, 1920, 2560, 3840; H in 0, 320, 360, 480, 540, 600, 720, 768, 800, 900, 1080, 1200, 1440, 2160; D (devicePixelRatio) in 1, 1.25, 1.5, 2, 2.5, 3, 4 |
| `env:viewport:<W>x<H>` | none. `innerWidth` x `innerHeight` (the iframe), same buckets |
| `env:lang:<game>:<browser>` | none. Game language (`en`/`ru`), browser primary language subtag (2-3 lower-case letters); anything else -> `other` |

**Per minute of active play** (frames `TELEMETRY.frame` counts as playing;
pauses, ads, hidden tab and the rotate prompt do not count; a single frame
counts as at most 1000 ms of play, so a stall or a sleep without a blur event
cannot inflate play time): every 60 000 ms of active frame time, at most once
per frame, in this order:

| Id | Value |
| --- | --- |
| `perf:fps_p50` | 1000 / median frame time, integer 0..240 |
| `perf:fps_p5` | 5th percentile FPS = 1000 / 95th percentile frame time, integer 0..240 |
| `perf:frame_ms_p95` | 95th percentile frame time in ms, 0.1 ms steps, 0..250 (250 = 250 ms or longer) |
| `perf:freezes` | frames longer than 250 ms in that minute, integer 0..1000 |

then the play time events. Frame times go into a fixed 0.1 ms histogram
(one increment per frame, no allocation); the percentiles are read from it
once a minute. A partial last minute sends no perf events. (The
render/visualsperf.js freeze recorder is opt-in and costs per-frame work,
so it is not used.)

**Play time**, after each perf group and on `pagehide` (after
`mode_time:*`, before `quit:*`), for each grapnel mode with at least one
whole second of total play time:

| Id | Value |
| --- | --- |
| `playtime:session:<single\|double>` | active play seconds this page session, whole seconds (floor), 0..1e8 |
| `playtime:total:<single\|double>` | active play seconds across sessions, whole seconds (floor), 0..1e8 |

The total is saved under the `PROGRESS.keys` key `grapnelninja_playtime_v1`
(`{"single": ms, "double": ms}`) through `PLATFORM.storage` (Bridge storage on
Playgama, localStorage elsewhere): read in the one boot `getMany`, written in
PROGRESS's `setMany` with the other keys after every flush and on pagehide
(TASK-873; telemetry.js never touches localStorage; unreadable storage ->
starts at 0). Rate: 7 events at boot, at most 8 per active minute, at
most 4 on pagehide. Tested by `tools/test_telemetry_session.py` (scripted
3-minute headless run plus a reload).

### Gameplay and UI telemetry (TASK-862)

Grapple Over gameplay and the UI, through `ANALYTICS` only (so it reaches
GameAnalytics on the itch.io build alone). Every id is already clean (the
sanitizer leaves it unchanged); section ids are the level's
(`SEC-baseline`, ..., `SEC-sky-spire`). Nothing here is saved. A **fall**
is the continuous drop `LONG_FALL` measures: from the last grapple catch or
the last apex (a rise resets it), in game units; a teleport (fall recovery,
go back) ends it. Its **section** is the section of the last grapple catch
(`climbFallSection()`; the spawn section when there was none since the
launch or the last recovery), as for `fall:*`.

**Fall buckets** (value = the lower bound the distance reaches): 0, 1000,
2000, 4000, 6000, 10000, 15000, 20000, 30000, 50000, 75000, 100000, 150000.

Existing counters, reused (unchanged): `best_height:<mode>` (best height,
500-unit buckets), `fall:<sectionId>` (every counted fall, i.e. every fall
recovery, with its section), `restart:<mode>` (restarts), `goback:<sectionId>`
(the player was put back at the checkpoint; the checkpoint's section),
`quit:<type>:<sectionId>`, `mode_time:<mode>`.

**Progression** (`addProgressionEvent`):

| Event | When |
| --- | --- |
| `Start` `grapple_over` | the run: its first tracked frame on this page (a new run, a restart, or a restored run after a reload; not for a completed run) |
| `Complete` `grapple_over`, score = active seconds (rounded) | the summit, after the last section's Complete |
| `Fail` `grapple_over` | a restart while the run is open (before `restart:*`), and `pagehide` (after the section's Fail) |
| `Start` / `Complete` / `Fail` `grapple_over` `<sectionId>` | per section reached, unchanged (TASK-751): Start on entering a section not completed in this run, Complete when left upward (once per run) and at the summit, Fail when left downward and on `pagehide` |

**Design events:**

| Id | Value | When |
| --- | --- | --- |
| `section_height:<sectionId>` | highest climb height reached in the section during the visit, floored to 1000-unit buckets (0..202000; negative heights -> 0) | when the player leaves the section, at the summit, on a restart and on `pagehide`; only when the bucket is higher than the one sent for that section earlier in the run |
| `longest_fall:session` | fall bucket of the session's longest single fall | `pagehide`, after `quit:*`; nothing if the player never fell |
| `longest_fall:complete` | fall bucket of the session's longest single fall so far | when the game is beaten (summit), after the run Complete |
| `quit_long_fall:<sectionId>` | fall bucket of that fall | `pagehide` within 30 s (wall clock) after the last moment of a fall longer than `LONG_FALL_THRESHOLD` (4000), with that fall's section; at most once per page |
| `hide:<type>:<sectionId>` | none | the tab goes hidden (`visibilitychange`) during a Grapple Over run: the last run event, same `<type>`/`<sectionId>` as `quit:*` (`:<sectionId>` left out when it has none); see "Hidden tab" below |
| `hide_long_fall:<sectionId>` | fall bucket of that fall | the tab goes hidden within 30 s (wall clock) after the last moment of a fall longer than `LONG_FALL_THRESHOLD`, with that fall's section |
| `longest_fall:hide` | fall bucket of the session's longest single fall so far | the tab goes hidden, after `hide:*` / `hide_long_fall:*`; nothing if the player never fell |
| `goback_offer:<sectionId>` | fall bucket when offered (10000, 20000, ...) | the 'Go back?' dialog opens (every offer, again after Keep falling) |
| `goback_choice:keep:<sectionId>` | none | Keep falling (button, Escape, or a rewarded ad answering `closed`) |
| `goback_choice:back:<sectionId>` | none | Go back pressed |
| `goback_ad:<result>` | none | the go-back rewarded ad's answer: `rewarded`, `closed`, `failed`, `unavailable`, `skipped`, `timeout` (no answer within 30 s), `other`; `unsupported` when the build has no rewarded ads (the player goes back for free). `ad('reward_received' \| 'show' \| 'failed_show', 'rewarded', 'go_back')` still comes from PLATFORM |
| `ui:pause:open:<user\|auto>` | none | a pause screen opens: `user` = pause button or P/Escape key; `auto` = blur, hidden tab, host pause, rotation, a restored run (the go-back dialog and the double offer are not pause screens) |
| `ui:pause:close` | none | the game unpauses after a pause screen (resume, restart, mode change) |
| `ui:grapnel:<single\|double>` | none | the grapnel mode changes (pause toggle, Try double offer, win screen try-default) |
| `ui:lang:<en\|ru>` | none | the language button switches the language |
| `ui:fps:<on\|off>` | none | the fps checkbox (pause or death screen) |
| `tutorial:grapple:shown` | none | the control hint (the one tutorial step, "hold to grapple") is shown, once per page |
| `tutorial:grapple:completed` | none | the step is done: the first grapnel throw of the page while the hint is up |

`pagehide` order: `mode_time:*`, `playtime:*`, `quit:*`,
`longest_fall:session`, `quit_long_fall:*`, `section_height:*`, section
Fail, run Fail, `sessionEnd()`.

**Hidden tab (TASK-908).** A phone player usually leaves by switching app or
tab, and a backgrounded mobile tab is often discarded later with no
`pagehide`, so the quit-time events above would never be sent. On
`visibilitychange` to hidden while a Grapple Over run is in progress (and
the page has not had its `pagehide`), index.html `watchAnalytics` sends,
once per hidden period (visible again re-arms it) and at most 5 times per
page: `hide:<type>:<sectionId>`, `hide_long_fall:<sectionId>` (only within
30 s of a long fall), `longest_fall:hide`, then `ANALYTICS.flush()`. Its
listener runs before the auto pause, so `<type>` is the event before that
pause. `flush()` (none.js: no-op) makes the GameAnalytics backend run the
SDK's queued tasks and send its event store at once by `fetch(keepalive)`
(the pagehide sender, TASK-899) WITHOUT `endSession`: no `session_end`, the
session goes on when the tab is visible again. `pagehide` is unchanged and
still sends `quit:*` etc. once per page. At most 3 events per hidden period,
15 per page.

Cost: one comparison per physics cycle
(`TELEMETRY.falling`, from `LONG_FALL.step`) and one per frame
(`CLIMB_UI.trackSection`). Tested by `tools/test_telemetry_gameplay.py`
(scripted runs, exact expected sequences).

## GameAnalytics backend (itch.io, Y8)

`analytics/backends/gameanalytics.js` (TASK-860) is `none.js` with each
inner method filled from its `// REPLACE:` marker. It talks to the vendored
SDK `analytics/vendor/GameAnalytics.min.js`: GameAnalytics JavaScript SDK
**5.0.0** (npm `gameanalytics` 5.0.0 = GitHub release v5.0.0), unmodified,
**MIT** licence in `analytics/vendor/GameAnalytics.LICENSE.txt` (shipped in
the itch and Y8 zips next to the SDK); source URL and sha256 in
`analytics/vendor/GameAnalytics.VERSION.txt`. No CDN is loaded.

| Inner method | GameAnalytics call |
| --- | --- |
| `initialize({build})` | once per page: `configureBuild(BUILD_CONFIG.build \|\| build)` (the release id `<sha12>-<YYYYMMDD>`, <= 32 chars), then `initialize(GA_KEYS.gameKey, GA_KEYS.secretKey)`. Automatic session handling: GA starts the session itself when its init request answers |
| `startSession()` / `endSession()` | `startSession()` (a no-op until GA's init answered) / `endSession()` (pagehide) |
| `addProgressionEvent(status, p1, p2, p3, score)` | `addProgressionEvent(EGAProgressionStatus[status], p1, p2 \|\| '', p3 \|\| '', score?)` (score only when a number) |
| `addDesignEvent(id, value)` | `addDesignEvent(id, value?)` (value only when a number) |
| `addErrorEvent(severity, message)` | `addErrorEvent(EGAErrorSeverity[Debug..Critical], message)` |
| `addAdEvent(action, type, sdkName, placement)` | `addAdEvent(EGAAdAction[show -> Show, failed_show -> FailedShow, reward_received -> RewardReceived, clicked -> Clicked], EGAAdType[interstitial -> Interstitial, rewarded -> RewardedVideo, ...], sdkName lower-case, placement \|\| 'none')`; other actions/types dropped |

Without both keys or without the SDK every method is a no-op; a throwing SDK
is caught (one `console.warn` per method) and never reaches the game.

**Keys.** The repo file has `var GA_KEYS = {gameKey: '', secretKey: ''}`
and never holds a key. `tools/build_release.py --portal itch` (or `all`)
reads `GA_GAME_KEY` (32 alphanumerics) and `GA_SECRET_KEY` (40) from the
environment (`set -a; . /root/credentials/grapnelninja/credentials.env;
set +a`), refuses to build itch without them, rewrites that one line in the
itch zip's copy only, and swaps the itch index.html tag
`analytics/backends/none.js` for `analytics/vendor/GameAnalytics.min.js` +
`analytics/backends/gameanalytics.js`. The manifest records
`analytics_backend` and `analytics_keys_injected`, never the values. The
keys end up in a public client-side file, which is how GameAnalytics' JS SDK
works; they are kept out of git and of the other portals' zips.

Tests: `tools/test_gameanalytics_backend.py` (built itch zip with a
recording mock SDK: boot order and keys, facade -> GA mapping, throwing and
missing SDK, repo file is a no-op), `tools/scan_ga_keys.py --out FILE` (key
counts per zip / manifest / git, counts only), `tools/smoke_gameanalytics.py
--out FILE` (the real SDK against api.gameanalytics.com, URLs redacted; it
sends one real session). test_itch_backend and test_build_release serve the
SDK as an empty script so they never reach GameAnalytics.
