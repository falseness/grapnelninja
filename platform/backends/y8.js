// Y8 platform backend stub.
// Y8 minimal SDK 2.x (window.y8.sdk()). Guest play must work: never require a
// Y8 login; saveData/loadData only work signed in (1 write per key per 5 s),
// so localStorage stays the save of record. Pause and mute on blur.
// Docs: https://docs.y8.com/sdk/intro/
// Script tag: <script src="https://cdn.y8.com/minimal-sdk/2-0/y8.min.js" async></script> (before platform/backends/y8.js; wait for the y8sdk.ready event)
// For now every inner method behaves like local.js (localStorage storage,
// no-op ads/lifecycle/leaderboards) by calling LOCAL_PLATFORM_BACKEND, which
// must be loaded first; to port, replace each body with its REPLACE line.
// See docs/platform-sdk.md.
var PLATFORM_BACKEND = (function()
{
    const base = LOCAL_PLATFORM_BACKEND

    return {
        platformId: 'y8',

        // REPLACE: nothing: performance.now()
        // https://docs.y8.com/sdk/intro/
        now()
        {
            return base.now()
        },

        // REPLACE: await y8sdk.ready; sdk = window.y8.sdk(); await sdk.init({appId, autoLogin: false}, {gameId}); resolve {environment: 'y8', language}
        // https://docs.y8.com/sdk/intro/
        init()
        {
            return base.init()
        },

        // REPLACE: return !!sdk && !sdk.isBlacklisted()
        // https://docs.y8.com/sdk/intro/
        isInterstitialSupported()
        {
            return base.isInterstitialSupported()
        },

        // REPLACE: nothing: own min-gap check
        // https://docs.y8.com/sdk/intro/
        isInterstitialDue(...args)
        {
            return base.isInterstitialDue(...args)
        },

        // REPLACE: await sdk.showAd({type: 'next'}); resolve 'closed' | 'failed'
        // https://docs.y8.com/sdk/intro/
        showInterstitial(...args)
        {
            return base.showInterstitial(...args)
        },

        // REPLACE: nothing
        // https://docs.y8.com/sdk/intro/
        sendMessage(...args)
        {
            return base.sendMessage(...args)
        },

        // REPLACE: nothing
        // https://docs.y8.com/sdk/intro/
        sendLifecycle(...args)
        {
            return base.sendLifecycle(...args)
        },

        // REPLACE: nothing (or gameanalytics.GameAnalytics.addDesignEvent(id, value) when GameAnalytics is on)
        // https://docs.y8.com/sdk/intro/
        track(...args)
        {
            return base.track(...args)
        },

        // REPLACE: nothing (or gameanalytics.GameAnalytics.addProgressionEvent(Start, stage) when GameAnalytics is on)
        // https://docs.y8.com/sdk/intro/
        startup(...args)
        {
            return base.startup(...args)
        },

        // REPLACE: nothing: Y8 has no ready call
        // https://docs.y8.com/sdk/intro/
        gameReady()
        {
            return base.gameReady()
        },

        // REPLACE: nothing: return {state: sdk ? 'success' : 'disabled'}
        // https://docs.y8.com/sdk/intro/
        readiness()
        {
            return base.readiness()
        },

        // REPLACE: nothing: return !document.hidden (mute on blur)
        // https://docs.y8.com/sdk/intro/
        isAudioEnabled()
        {
            return base.isAudioEnabled()
        },

        // REPLACE: window 'blur'/'focus' -> fn(true/false) (Y8 requires pause+mute on blur)
        // https://docs.y8.com/sdk/intro/
        onPause(fn)
        {
            return base.onPause(fn)
        },

        // REPLACE: window 'blur'/'focus' -> fn(false/true)
        // https://docs.y8.com/sdk/intro/
        onAudio(fn)
        {
            return base.onAudio(fn)
        },

        // REPLACE: wrap sdk.showAd(): fn('opened') before, fn('closed'|'failed') after
        // https://docs.y8.com/sdk/intro/
        onAdState(fn)
        {
            return base.onAdState(fn)
        },

        // REPLACE: nothing
        // https://docs.y8.com/sdk/intro/
        loadingProgress(percent)
        {
            return base.loadingProgress(percent)
        },

        // REPLACE: nothing
        // https://docs.y8.com/sdk/intro/
        gameplayStart(level)
        {
            return base.gameplayStart(level)
        },

        // REPLACE: nothing
        // https://docs.y8.com/sdk/intro/
        gameplayStop(reason, level)
        {
            return base.gameplayStop(reason, level)
        },

        // REPLACE: nothing
        // https://docs.y8.com/sdk/intro/
        happyMoment()
        {
            return base.happyMoment()
        },

        // REPLACE: return !!sdk && !sdk.isBlacklisted()
        // https://docs.y8.com/sdk/intro/
        isRewardedSupported()
        {
            return base.isRewardedSupported()
        },

        // REPLACE: await sdk.showAd({type: 'reward'}); resolve 'rewarded' only when the reward callback fired
        // https://docs.y8.com/sdk/intro/
        showRewarded(placement)
        {
            return base.showRewarded(placement)
        },

        // REPLACE: nothing: Y8 has no banner API
        // https://docs.y8.com/sdk/intro/
        showBanner(position)
        {
            return base.showBanner(position)
        },

        // REPLACE: nothing
        // https://docs.y8.com/sdk/intro/
        hideBanner()
        {
            return base.hideBanner()
        },

        // REPLACE: sdk.saveLeaderboardScore({table: board, points: value}) (signed-in only, else resolve false)
        // https://docs.y8.com/sdk/intro/
        submitScore(board, value)
        {
            return base.submitScore(board, value)
        },

        // REPLACE: sdk.awardAchievement({achievement: id}) (signed-in only, else resolve false)
        // https://docs.y8.com/sdk/intro/
        unlockAchievement(id)
        {
            return base.unlockAchievement(id)
        },

        // REPLACE: nothing: navigator.language 2-letter code
        // https://docs.y8.com/sdk/intro/
        getLanguage()
        {
            return base.getLanguage()
        },

        // REPLACE: nothing: 'y8'
        // https://docs.y8.com/sdk/intro/
        getPlatformId()
        {
            return this.platformId
        },

        storage:
        {
            // REPLACE: nothing: return true (localStorage is the save of record)
            // https://docs.y8.com/sdk/intro/
            remoteKnown()
            {
                return base.storage.remoteKnown()
            },

            // REPLACE: nothing
            // https://docs.y8.com/sdk/intro/
            onRecovery(fn)
            {
                return base.storage.onRecovery(fn)
            },

            // REPLACE: localStorage.getItem(key); optionally sdk.loadData(key) when signed in
            // https://docs.y8.com/sdk/intro/
            getMany(keys)
            {
                return base.storage.getMany(keys)
            },

            // REPLACE: localStorage.setItem(key, value); optionally sdk.saveData(key, value) when signed in (1 write/key/5 s)
            // https://docs.y8.com/sdk/intro/
            setMany(obj)
            {
                return base.storage.setMany(obj)
            }
        }
    }
})()
