// Playgama Bridge platform backend stub.
// Playgama Bridge (window.bridge). game_ready is mandatory; ads only through
// bridge.advertisement; NO external analytics (no GameAnalytics) on Playgama.
// Docs: https://wiki.playgama.com/playgama/bridge-sdk/setup.md
// Script tag: <script src="https://bridge.playgama.com/v2/stable/playgama-bridge.js"></script> (before platform/backends/playgama.js)
// For now every inner method behaves like local.js (localStorage storage,
// no-op ads/lifecycle/leaderboards) by calling LOCAL_PLATFORM_BACKEND, which
// must be loaded first; to port, replace each body with its REPLACE line.
// See docs/platform-sdk.md.
var PLATFORM_BACKEND = (function()
{
    const base = LOCAL_PLATFORM_BACKEND

    return {
        platformId: 'playgama',

        // REPLACE: nothing: performance.now()
        // https://wiki.playgama.com/playgama/bridge-sdk/setup.md
        now()
        {
            return base.now()
        },

        // REPLACE: await bridge.initialize(); resolve {environment: bridge.platform.id, language: bridge.platform.language}
        // https://wiki.playgama.com/playgama/bridge-sdk/setup.md
        init()
        {
            return base.init()
        },

        // REPLACE: return bridge.advertisement.isInterstitialSupported
        // https://wiki.playgama.com/playgama/bridge-sdk/setup.md
        isInterstitialSupported()
        {
            return base.isInterstitialSupported()
        },

        // REPLACE: nothing: own min-gap check (bridge.advertisement.setMinimumDelayBetweenInterstitial)
        // https://wiki.playgama.com/playgama/bridge-sdk/setup.md
        isInterstitialDue(...args)
        {
            return base.isInterstitialDue(...args)
        },

        // REPLACE: bridge.advertisement.showInterstitial(placement); settle on INTERSTITIAL_STATE_CHANGED 'closed' | 'failed'
        // https://wiki.playgama.com/playgama/bridge-sdk/setup.md
        showInterstitial(...args)
        {
            return base.showInterstitial(...args)
        },

        // REPLACE: bridge.platform.sendMessage(message)
        // https://wiki.playgama.com/playgama/bridge-sdk/setup.md
        sendMessage(...args)
        {
            return base.sendMessage(...args)
        },

        // REPLACE: bridge.platform.sendMessage(name, data) (level_started / level_completed / level_failed ...)
        // https://wiki.playgama.com/playgama/bridge-sdk/setup.md
        sendLifecycle(...args)
        {
            return base.sendLifecycle(...args)
        },

        // REPLACE: bridge.analytics.send(event, data)  (the only analytics allowed on Playgama)
        // https://wiki.playgama.com/playgama/bridge-sdk/setup.md
        track(...args)
        {
            return base.track(...args)
        },

        // REPLACE: bridge.analytics.send('startup_funnel', {stage, elapsed_ms, mode})
        // https://wiki.playgama.com/playgama/bridge-sdk/setup.md
        startup(...args)
        {
            return base.startup(...args)
        },

        // REPLACE: bridge.platform.sendMessage('game_ready')  (mandatory)
        // https://wiki.playgama.com/playgama/bridge-sdk/setup.md
        gameReady()
        {
            return base.gameReady()
        },

        // REPLACE: nothing: return {state: bridge ? 'success' : 'disabled'}
        // https://wiki.playgama.com/playgama/bridge-sdk/setup.md
        readiness()
        {
            return base.readiness()
        },

        // REPLACE: return bridge.platform.isAudioEnabled
        // https://wiki.playgama.com/playgama/bridge-sdk/setup.md
        isAudioEnabled()
        {
            return base.isAudioEnabled()
        },

        // REPLACE: bridge.platform.on(bridge.EVENT_NAME.PAUSE_STATE_CHANGED, isPaused => fn(isPaused))
        // https://wiki.playgama.com/playgama/bridge-sdk/setup.md
        onPause(fn)
        {
            return base.onPause(fn)
        },

        // REPLACE: bridge.platform.on(bridge.EVENT_NAME.AUDIO_STATE_CHANGED, isEnabled => fn(isEnabled))
        // https://wiki.playgama.com/playgama/bridge-sdk/setup.md
        onAudio(fn)
        {
            return base.onAudio(fn)
        },

        // REPLACE: bridge.advertisement.on(bridge.EVENT_NAME.INTERSTITIAL_STATE_CHANGED / REWARDED_STATE_CHANGED, fn)
        // https://wiki.playgama.com/playgama/bridge-sdk/setup.md
        onAdState(fn)
        {
            return base.onAdState(fn)
        },

        // REPLACE: nothing: Bridge has no loading-progress call
        // https://wiki.playgama.com/playgama/bridge-sdk/setup.md
        loadingProgress(percent)
        {
            return base.loadingProgress(percent)
        },

        // REPLACE: bridge.platform.sendMessage('gameplay_started')
        // https://wiki.playgama.com/playgama/bridge-sdk/setup.md
        gameplayStart(level)
        {
            return base.gameplayStart(level)
        },

        // REPLACE: bridge.platform.sendMessage('gameplay_stopped')
        // https://wiki.playgama.com/playgama/bridge-sdk/setup.md
        gameplayStop(reason, level)
        {
            return base.gameplayStop(reason, level)
        },

        // REPLACE: nothing: Bridge has no happy-moment call
        // https://wiki.playgama.com/playgama/bridge-sdk/setup.md
        happyMoment()
        {
            return base.happyMoment()
        },

        // REPLACE: return bridge.advertisement.isRewardedSupported
        // https://wiki.playgama.com/playgama/bridge-sdk/setup.md
        isRewardedSupported()
        {
            return base.isRewardedSupported()
        },

        // REPLACE: bridge.advertisement.showRewarded(placement); reward only on REWARDED_STATE_CHANGED 'rewarded'
        // https://wiki.playgama.com/playgama/bridge-sdk/setup.md
        showRewarded(placement)
        {
            return base.showRewarded(placement)
        },

        // REPLACE: bridge.advertisement.showBanner(position)
        // https://wiki.playgama.com/playgama/bridge-sdk/setup.md
        showBanner(position)
        {
            return base.showBanner(position)
        },

        // REPLACE: bridge.advertisement.hideBanner()
        // https://wiki.playgama.com/playgama/bridge-sdk/setup.md
        hideBanner()
        {
            return base.hideBanner()
        },

        // REPLACE: bridge.leaderboards.setScore(board, value)
        // https://wiki.playgama.com/playgama/bridge-sdk/setup.md
        submitScore(board, value)
        {
            return base.submitScore(board, value)
        },

        // REPLACE: bridge.achievements.unlock({id})
        // https://wiki.playgama.com/playgama/bridge-sdk/setup.md
        unlockAchievement(id)
        {
            return base.unlockAchievement(id)
        },

        // REPLACE: bridge.platform.language
        // https://wiki.playgama.com/playgama/bridge-sdk/setup.md
        getLanguage()
        {
            return base.getLanguage()
        },

        // REPLACE: nothing: 'playgama' (bridge.platform.id is the host portal)
        // https://wiki.playgama.com/playgama/bridge-sdk/setup.md
        getPlatformId()
        {
            return this.platformId
        },

        storage:
        {
            // REPLACE: return true once bridge.storage.get resolved at boot
            // https://wiki.playgama.com/playgama/bridge-sdk/setup.md
            remoteKnown()
            {
                return base.storage.remoteKnown()
            },

            // REPLACE: nothing unless a late bridge.storage.get must be reconciled
            // https://wiki.playgama.com/playgama/bridge-sdk/setup.md
            onRecovery(fn)
            {
                return base.storage.onRecovery(fn)
            },

            // REPLACE: bridge.storage.get(keys) -> values in key order
            // https://wiki.playgama.com/playgama/bridge-sdk/setup.md
            getMany(keys)
            {
                return base.storage.getMany(keys)
            },

            // REPLACE: bridge.storage.set(Object.keys(obj), Object.values(obj))
            // https://wiki.playgama.com/playgama/bridge-sdk/setup.md
            setMany(obj)
            {
                return base.storage.setMany(obj)
            }
        }
    }
})()
