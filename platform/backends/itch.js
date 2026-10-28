// itch.io platform backend stub.
// itch.io has no SDK: the game runs in an itch.io iframe and keeps saves in
// localStorage, so most REPLACE lines say "nothing" and this stub is the port.
// Docs: https://itch.io/docs/creators/html5
// Script tag: none: itch.io has no SDK; upload the zip with index.html at its root (no extra <script> tag)
// For now every inner method behaves like local.js (localStorage storage,
// no-op ads/lifecycle/leaderboards) by calling LOCAL_PLATFORM_BACKEND, which
// must be loaded first; to port, replace each body with its REPLACE line.
// See docs/platform-sdk.md.
var PLATFORM_BACKEND = (function()
{
    const base = LOCAL_PLATFORM_BACKEND

    return {
        platformId: 'itch',

        // REPLACE: nothing: performance.now()
        // https://itch.io/docs/creators/html5
        now()
        {
            return base.now()
        },

        // REPLACE: nothing: resolve {environment: 'itch', language: navigator.language 2-letter code}
        // https://itch.io/docs/creators/html5
        init()
        {
            return base.init()
        },

        // REPLACE: nothing: no ads on itch.io, return false
        // https://itch.io/docs/creators/html5
        isInterstitialSupported()
        {
            return base.isInterstitialSupported()
        },

        // REPLACE: nothing: return false
        // https://itch.io/docs/creators/html5
        isInterstitialDue(...args)
        {
            return base.isInterstitialDue(...args)
        },

        // REPLACE: nothing: resolve 'skipped'
        // https://itch.io/docs/creators/html5
        showInterstitial(...args)
        {
            return base.showInterstitial(...args)
        },

        // REPLACE: nothing
        // https://itch.io/docs/creators/html5
        sendMessage(...args)
        {
            return base.sendMessage(...args)
        },

        // REPLACE: nothing
        // https://itch.io/docs/creators/html5
        sendLifecycle(...args)
        {
            return base.sendLifecycle(...args)
        },

        // REPLACE: nothing (or gameanalytics.GameAnalytics.addDesignEvent(id, value) when GameAnalytics is on)
        // https://itch.io/docs/creators/html5
        track(...args)
        {
            return base.track(...args)
        },

        // REPLACE: nothing (or gameanalytics.GameAnalytics.addProgressionEvent(Start, stage) when GameAnalytics is on)
        // https://itch.io/docs/creators/html5
        startup(...args)
        {
            return base.startup(...args)
        },

        // REPLACE: nothing
        // https://itch.io/docs/creators/html5
        gameReady()
        {
            return base.gameReady()
        },

        // REPLACE: nothing: return {state: 'local'}
        // https://itch.io/docs/creators/html5
        readiness()
        {
            return base.readiness()
        },

        // REPLACE: nothing: return true
        // https://itch.io/docs/creators/html5
        isAudioEnabled()
        {
            return base.isAudioEnabled()
        },

        // REPLACE: window.addEventListener('blur'/'focus') or document 'visibilitychange' -> fn(paused)
        // https://itch.io/docs/creators/html5
        onPause(fn)
        {
            return base.onPause(fn)
        },

        // REPLACE: nothing: itch.io has no host mute
        // https://itch.io/docs/creators/html5
        onAudio(fn)
        {
            return base.onAudio(fn)
        },

        // REPLACE: nothing: no ads
        // https://itch.io/docs/creators/html5
        onAdState(fn)
        {
            return base.onAdState(fn)
        },

        // REPLACE: nothing
        // https://itch.io/docs/creators/html5
        loadingProgress(percent)
        {
            return base.loadingProgress(percent)
        },

        // REPLACE: nothing
        // https://itch.io/docs/creators/html5
        gameplayStart(level)
        {
            return base.gameplayStart(level)
        },

        // REPLACE: nothing
        // https://itch.io/docs/creators/html5
        gameplayStop(reason, level)
        {
            return base.gameplayStop(reason, level)
        },

        // REPLACE: nothing
        // https://itch.io/docs/creators/html5
        happyMoment()
        {
            return base.happyMoment()
        },

        // REPLACE: nothing: return false
        // https://itch.io/docs/creators/html5
        isRewardedSupported()
        {
            return base.isRewardedSupported()
        },

        // REPLACE: nothing: resolve 'unavailable'
        // https://itch.io/docs/creators/html5
        showRewarded(placement)
        {
            return base.showRewarded(placement)
        },

        // REPLACE: nothing
        // https://itch.io/docs/creators/html5
        showBanner(position)
        {
            return base.showBanner(position)
        },

        // REPLACE: nothing
        // https://itch.io/docs/creators/html5
        hideBanner()
        {
            return base.hideBanner()
        },

        // REPLACE: nothing: no leaderboards, resolve false
        // https://itch.io/docs/creators/html5
        submitScore(board, value)
        {
            return base.submitScore(board, value)
        },

        // REPLACE: nothing: resolve false
        // https://itch.io/docs/creators/html5
        unlockAchievement(id)
        {
            return base.unlockAchievement(id)
        },

        // REPLACE: nothing: navigator.language 2-letter code
        // https://itch.io/docs/creators/html5
        getLanguage()
        {
            return base.getLanguage()
        },

        // REPLACE: nothing: 'itch'
        // https://itch.io/docs/creators/html5
        getPlatformId()
        {
            return this.platformId
        },

        storage:
        {
            // REPLACE: nothing: return true
            // https://itch.io/docs/creators/html5
            remoteKnown()
            {
                return base.storage.remoteKnown()
            },

            // REPLACE: nothing
            // https://itch.io/docs/creators/html5
            onRecovery(fn)
            {
                return base.storage.onRecovery(fn)
            },

            // REPLACE: localStorage.getItem(key) for each key (as local.js)
            // https://itch.io/docs/creators/html5
            getMany(keys)
            {
                return base.storage.getMany(keys)
            },

            // REPLACE: localStorage.setItem(key, value) for each key (as local.js)
            // https://itch.io/docs/creators/html5
            setMany(obj)
            {
                return base.storage.setMany(obj)
            }
        }
    }
})()
