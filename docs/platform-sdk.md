# Platform SDK map (facade backends)

The game only calls `PLATFORM` (platform.js, the facade). Every public method
delegates to the same-named inner method of `PLATFORM_BACKEND`, defined by one
backend file under `platform/backends/`:

| file | platformId | status |
|---|---|---|
| `local.js` | `local` | default; localStorage storage, no ads; also exposes `LOCAL_PLATFORM_BACKEND` |
| `itch.js` | `itch` | stub, behaves like local |
| `gamepix.js` | `gamepix` | stub, behaves like local |
| `y8.js` | `y8` | stub, behaves like local |
| `playgama.js` | `playgama` | stub, behaves like local |

Each portal stub calls `LOCAL_PLATFORM_BACKEND` for every inner method (so the
storage code exists once) and carries a `// REPLACE: <SDK call>` line plus the
portal docs URL above every inner method. Porting = replacing those bodies in
that ONE file; platform.js and the game do not change.

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

## Facade method x portal SDK call

| facade method | itch.io | GamePix v3 (`GamePix`) | Y8 minimal SDK 2.x (`sdk = y8.sdk()`) | Playgama Bridge (`bridge`) |
|---|---|---|---|---|
| `now` | `performance.now()` | `performance.now()` | `performance.now()` | `performance.now()` |
| `init` | resolve `{environment:'itch', language}` | `GamePix.lang()` (sync tag) | `await y8sdk.ready; sdk.init({appId, autoLogin:false}, {gameId})` | `await bridge.initialize()`; `bridge.platform.id`, `bridge.platform.language` |
| `isInterstitialSupported` | `false` | `!!window.GamePix` | `!!sdk && !sdk.isBlacklisted()` | `bridge.advertisement.isInterstitialSupported` |
| `isInterstitialDue` | `false` | own min-gap check | own min-gap check | own min-gap check (`setMinimumDelayBetweenInterstitial`) |
| `showInterstitial` | `'skipped'` | `GamePix.ads.interstitial()` -> `{success}` | `sdk.showAd({type:'next'})` | `bridge.advertisement.showInterstitial(placement)` + `INTERSTITIAL_STATE_CHANGED` |
| `sendMessage` | - | - | - | `bridge.platform.sendMessage(message)` |
| `sendLifecycle` | - | - | - | `bridge.platform.sendMessage(name, data)` |
| `track` | - (GameAnalytics allowed) | - (**no third-party analytics**) | - (GameAnalytics allowed) | `bridge.analytics.send(event, data)` (**no external analytics**) |
| `startup` | - (GameAnalytics progression allowed) | - | - (GameAnalytics allowed) | `bridge.analytics.send('startup_funnel', ...)` |
| `gameReady` | - | `GamePix.lifecycle.loaded()` | - | `bridge.platform.sendMessage('game_ready')` |
| `readiness` | `{state:'local'}` | `{state: 'success'\|'disabled'}` | `{state: 'success'\|'disabled'}` | `{state: 'success'\|'disabled'}` |
| `isAudioEnabled` | `true` | `true` (mute via pause event) | `!document.hidden` | `bridge.platform.isAudioEnabled` |
| `onPause` | window blur/focus | `GamePix.events.on('pause'\|'resume')` | window blur/focus | `bridge.platform.on(PAUSE_STATE_CHANGED)` |
| `onAudio` | - | `GamePix.events.on('pause'\|'resume')` | window blur/focus | `bridge.platform.on(AUDIO_STATE_CHANGED)` |
| `onAdState` | - | wrap `ads.interstitial()/reward()` | wrap `sdk.showAd()` | `bridge.advertisement.on(INTERSTITIAL_/REWARDED_STATE_CHANGED)` |
| `loadingProgress` | - | `GamePix.lifecycle.loading(0..100)` (non-decreasing) | - | - |
| `gameplayStart` | - | `GamePix.lifecycle.gameStart()` | - | `bridge.platform.sendMessage('gameplay_started')` |
| `gameplayStop` | - | - | - | `bridge.platform.sendMessage('gameplay_stopped')` |
| `happyMoment` | - | `GamePix.happyMoment()` | - | - |
| `isRewardedSupported` | `false` | `!!window.GamePix` | `!!sdk && !sdk.isBlacklisted()` | `bridge.advertisement.isRewardedSupported` |
| `showRewarded` | `'unavailable'` | `GamePix.ads.reward()` -> `{success}` | `sdk.showAd({type:'reward'})` | `bridge.advertisement.showRewarded(placement)`; reward only on state `'rewarded'` |
| `showBanner` / `hideBanner` | - | - | - | `bridge.advertisement.showBanner(position)` / `hideBanner()` |
| `submitScore` | `false` | `false` | `sdk.saveLeaderboardScore(...)` (signed in) | `bridge.leaderboards.setScore(board, value)` |
| `unlockAchievement` | `false` | `false` | `sdk.awardAchievement(...)` (signed in) | `bridge.achievements.unlock({id})` |
| `getLanguage` | `navigator.language` | `GamePix.lang()` | `navigator.language` | `bridge.platform.language` |
| `getPlatformId` | `'itch'` | `'gamepix'` | `'y8'` | `'playgama'` |
| `storage.remoteKnown` | `true` | `true` | `true` | `true` once `bridge.storage.get` resolved |
| `storage.onRecovery` | - | - | - | late `bridge.storage.get` reconcile |
| `storage.getMany` | `localStorage.getItem` | `localStorage.getItem` | `localStorage.getItem` (+ `sdk.loadData` signed in) | `bridge.storage.get(keys)` |
| `storage.setMany` | `localStorage.setItem` | `localStorage.setItem` | `localStorage.setItem` (+ `sdk.saveData`, 1 write/key/5 s) | `bridge.storage.set(keys, values)` |

`-` = no SDK call; keep the local no-op.

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
- GameAnalytics is allowed on itch.io, Y8 and local builds: put
  `gameanalytics.GameAnalytics.initialize(gameKey, secretKey)`,
  `addProgressionEvent` / `addDesignEvent` / `addErrorEvent` / `addAdEvent`
  inside that backend's `track` / `startup` inner methods only.
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
- **itch.io and Y8 may swap in a GameAnalytics backend**: copy `none.js` to
  e.g. `analytics/backends/gameanalytics.js`, fill each inner method from its
  `// REPLACE:` marker, load the GameAnalytics SDK and swap the
  `analytics/backends/none.js` script tag. Nothing else changes.
- Call sites: boot sends `init({build: PLATFORM.buildVersion})` +
  `sessionStart()` once after `PLATFORM.init()`; `pagehide` sends one
  `sessionEnd()` per page; window `error` / `unhandledrejection` send
  `error('error', '<message> @ <file>:<line>')`, deduplicated, at most 10 per
  session; `PLATFORM.showInterstitial` / `showRewarded` results send
  `ad('show' | 'failed_show' | 'reward_received', 'interstitial' | 'rewarded',
  placement)` for 'closed' / 'failed' / 'rewarded' (nothing for 'skipped' /
  'unavailable').
  Docs: https://github.com/GameAnalytics/GA-SDK-JAVASCRIPT
