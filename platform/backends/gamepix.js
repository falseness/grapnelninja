// GamePix platform backend stub.
// GamePix SDK v3 (window.GamePix). GamePix.lifecycle.loaded() must run before
// any ad call. NO third-party analytics (no GameAnalytics) on GamePix.
// Docs: https://partners.gamepix.com/sdk/doc/javascript
// Script tag: <script src="https://integration.gamepix.com/sdk/v3/gamepix.sdk.js"></script> (synchronous, before platform/backends/gamepix.js)
// For now every inner method behaves like local.js (localStorage storage,
// no-op ads/lifecycle/leaderboards) by calling LOCAL_PLATFORM_BACKEND, which
// must be loaded first; to port, replace each body with its REPLACE line.
// See docs/platform-sdk.md.
var PLATFORM_BACKEND = (function()
{
    const base = LOCAL_PLATFORM_BACKEND

    return {
        platformId: 'gamepix',

        // REPLACE: nothing: performance.now()
        // https://partners.gamepix.com/sdk/doc/javascript
        now()
        {
            return base.now()
        },

        // REPLACE: nothing to await (sync tag); resolve {environment: 'gamepix', language: GamePix.lang()}
        // https://partners.gamepix.com/sdk/doc/javascript
        init()
        {
            return base.init()
        },

        // REPLACE: return !!window.GamePix (GamePix.ads.interstitial exists)
        // https://partners.gamepix.com/sdk/doc/javascript
        isInterstitialSupported()
        {
            return base.isInterstitialSupported()
        },

        // REPLACE: nothing: own min-gap check; GamePix paces ads itself
        // https://partners.gamepix.com/sdk/doc/javascript
        isInterstitialDue(...args)
        {
            return base.isInterstitialDue(...args)
        },

        // REPLACE: await GamePix.ads.interstitial() -> {success}; resolve 'closed' | 'failed'
        // https://partners.gamepix.com/sdk/doc/javascript
        showInterstitial(...args)
        {
            return base.showInterstitial(...args)
        },

        // REPLACE: nothing
        // https://partners.gamepix.com/sdk/doc/javascript
        sendMessage(...args)
        {
            return base.sendMessage(...args)
        },

        // REPLACE: nothing
        // https://partners.gamepix.com/sdk/doc/javascript
        sendLifecycle(...args)
        {
            return base.sendLifecycle(...args)
        },

        // REPLACE: nothing: third-party analytics are banned on GamePix
        // https://partners.gamepix.com/sdk/doc/javascript
        track(...args)
        {
            return base.track(...args)
        },

        // REPLACE: nothing: third-party analytics are banned on GamePix
        // https://partners.gamepix.com/sdk/doc/javascript
        startup(...args)
        {
            return base.startup(...args)
        },

        // REPLACE: GamePix.lifecycle.loaded()  (before any ad call)
        // https://partners.gamepix.com/sdk/doc/javascript
        gameReady()
        {
            return base.gameReady()
        },

        // REPLACE: nothing: return {state: window.GamePix ? 'success' : 'disabled'}
        // https://partners.gamepix.com/sdk/doc/javascript
        readiness()
        {
            return base.readiness()
        },

        // REPLACE: nothing: return true (mute comes through the pause event)
        // https://partners.gamepix.com/sdk/doc/javascript
        isAudioEnabled()
        {
            return base.isAudioEnabled()
        },

        // REPLACE: GamePix.events.on('pause', () => fn(true)); GamePix.events.on('resume', () => fn(false))
        // https://partners.gamepix.com/sdk/doc/javascript
        onPause(fn)
        {
            return base.onPause(fn)
        },

        // REPLACE: GamePix.events.on('pause'/'resume') -> fn(false/true)
        // https://partners.gamepix.com/sdk/doc/javascript
        onAudio(fn)
        {
            return base.onAudio(fn)
        },

        // REPLACE: wrap GamePix.ads.interstitial()/reward(): fn('opened') before, fn('closed'|'failed') after
        // https://partners.gamepix.com/sdk/doc/javascript
        onAdState(fn)
        {
            return base.onAdState(fn)
        },

        // REPLACE: GamePix.lifecycle.loading(percent)  (0..100, never decreasing)
        // https://partners.gamepix.com/sdk/doc/javascript
        loadingProgress(percent)
        {
            return base.loadingProgress(percent)
        },

        // REPLACE: GamePix.lifecycle.gameStart()
        // https://partners.gamepix.com/sdk/doc/javascript
        gameplayStart(level)
        {
            return base.gameplayStart(level)
        },

        // REPLACE: nothing: v3 has no gameplay-stop call
        // https://partners.gamepix.com/sdk/doc/javascript
        gameplayStop(reason, level)
        {
            return base.gameplayStop(reason, level)
        },

        // REPLACE: GamePix.happyMoment()
        // https://partners.gamepix.com/sdk/doc/javascript
        happyMoment()
        {
            return base.happyMoment()
        },

        // REPLACE: return !!window.GamePix
        // https://partners.gamepix.com/sdk/doc/javascript
        isRewardedSupported()
        {
            return base.isRewardedSupported()
        },

        // REPLACE: await GamePix.ads.reward() -> {success}; resolve success ? 'rewarded' : 'closed'
        // https://partners.gamepix.com/sdk/doc/javascript
        showRewarded(placement)
        {
            return base.showRewarded(placement)
        },

        // REPLACE: nothing: GamePix owns banner placement
        // https://partners.gamepix.com/sdk/doc/javascript
        showBanner(position)
        {
            return base.showBanner(position)
        },

        // REPLACE: nothing
        // https://partners.gamepix.com/sdk/doc/javascript
        hideBanner()
        {
            return base.hideBanner()
        },

        // REPLACE: nothing: no leaderboard in GamePix v3, resolve false
        // https://partners.gamepix.com/sdk/doc/javascript
        submitScore(board, value)
        {
            return base.submitScore(board, value)
        },

        // REPLACE: nothing: resolve false
        // https://partners.gamepix.com/sdk/doc/javascript
        unlockAchievement(id)
        {
            return base.unlockAchievement(id)
        },

        // REPLACE: GamePix.lang()
        // https://partners.gamepix.com/sdk/doc/javascript
        getLanguage()
        {
            return base.getLanguage()
        },

        // REPLACE: nothing: 'gamepix'
        // https://partners.gamepix.com/sdk/doc/javascript
        getPlatformId()
        {
            return this.platformId
        },

        storage:
        {
            // REPLACE: nothing: return true
            // https://partners.gamepix.com/sdk/doc/javascript
            remoteKnown()
            {
                return base.storage.remoteKnown()
            },

            // REPLACE: nothing
            // https://partners.gamepix.com/sdk/doc/javascript
            onRecovery(fn)
            {
                return base.storage.onRecovery(fn)
            },

            // REPLACE: localStorage.getItem(key) for each key (plain localStorage on GamePix)
            // https://partners.gamepix.com/sdk/doc/javascript
            getMany(keys)
            {
                return base.storage.getMany(keys)
            },

            // REPLACE: localStorage.setItem(key, value) for each key
            // https://partners.gamepix.com/sdk/doc/javascript
            setMany(obj)
            {
                return base.storage.setMany(obj)
            }
        }
    }
})()
