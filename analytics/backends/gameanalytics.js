// GameAnalytics analytics backend (itch.io and Y8 builds: GamePix and Playgama
// forbid third-party analytics, see docs/platform-sdk.md). Same inner
// methods as none.js; analytics.js (the ANALYTICS facade) has already
// sanitized every argument. Needs the vendored SDK
// analytics/vendor/GameAnalytics.min.js (v5.0.0, MIT) loaded before it.
//
// GA_KEYS stays empty in the repo. tools/build_release.py --portal itch
// rewrites that one line with GA_GAME_KEY / GA_SECRET_KEY from the
// environment; without both keys (or without the SDK) every method is a
// no-op. Nothing here ever throws into the game.
//
// GameAnalytics drops events ("SDK is disabled") until its init request has
// answered, which takes a network round trip after initialize(). Events sent
// before that (the env:* events and the run's progression Start at boot) wait
// in a bounded queue and go out in order once the SDK reports it is ready
// (addRemoteConfigsListener / isRemoteConfigsReady). An SDK without those
// calls is treated as ready at once.
// Docs: https://github.com/GameAnalytics/GA-SDK-JAVASCRIPT
var GA_KEYS = {gameKey: '', secretKey: ''}

var ANALYTICS_BACKEND = (function()
{
    const PROGRESSION = {Start: 'Start', Complete: 'Complete', Fail: 'Fail'}
    const SEVERITY = {debug: 'Debug', info: 'Info', warning: 'Warning', error: 'Error', critical: 'Critical'}
    const AD_ACTION = {clicked: 'Clicked', show: 'Show', failed_show: 'FailedShow',
        reward_received: 'RewardReceived'}
    const AD_TYPE = {video: 'Video', rewarded: 'RewardedVideo', rewarded_video: 'RewardedVideo',
        playable: 'Playable', interstitial: 'Interstitial', offerwall: 'OfferWall', banner: 'Banner'}
    const warned = new Set()
    // Events held until GameAnalytics answered its init (oldest kept)
    const PENDING_MAX = 200
    const POLL_MS = 250, POLL_FOR_MS = 60000
    const pending = []
    let initialized = false
    let ready = false
    let live = false

    function own(table, key)
    {
        return Object.prototype.hasOwnProperty.call(table, key)
    }

    function sdk()
    {
        const ns = typeof gameanalytics === 'object' && gameanalytics
        return ns && ns.GameAnalytics ? ns : null
    }

    function warn(fn, e)
    {
        if (warned.has(fn))
            return
        warned.add(fn)
        console.warn('GameAnalytics.' + fn + ' failed, ignored:', e && e.message || e)
    }

    // gameanalytics.<enumName>[key]; undefined when the SDK lacks it
    function enumValue(enumName, key)
    {
        const table = sdk()[enumName]
        return table && own(table, key) ? table[key] : undefined
    }

    function deliver(fn, args)
    {
        try
        {
            sdk().GameAnalytics[fn](...args)
        }
        catch (e)
        {
            warn(fn, e)
        }
    }

    // Calls gameanalytics.GameAnalytics.<fn>(...args) once initialize() ran;
    // until the SDK is ready (live) the call waits in `pending`
    function call(fn, args)
    {
        if (!ready)
            return
        if (live)
            return deliver(fn, args)
        if (pending.length < PENDING_MAX)
            pending.push([fn, args])
    }

    function goLive()
    {
        if (live)
            return
        live = true
        for (const [fn, args] of pending.splice(0))
            deliver(fn, args)
    }

    // The SDK calls its remote-configs listeners while it handles the init
    // answer, just before it starts the session: flush on the next tick.
    // Polling covers a listener that is never called.
    function waitUntilReady()
    {
        const ga = sdk().GameAnalytics
        if (typeof ga.isRemoteConfigsReady !== 'function')
            return goLive()
        if (typeof ga.addRemoteConfigsListener === 'function')
            deliver('addRemoteConfigsListener', [{onRemoteConfigsUpdated: () => setTimeout(goLive, 0)}])
        const started = Date.now()
        const timer = setInterval(() =>
        {
            let isReady = false
            try { isReady = !!ga.isRemoteConfigsReady() } catch (e) {}
            if (isReady)
                setTimeout(goLive, 0)
            if (isReady || live || Date.now() - started > POLL_FOR_MS)
                clearInterval(timer)
        }, POLL_MS)
    }

    return {
        backendId: 'gameanalytics',

        // config: {build}. Once per page. The GA build is the release build id
        // (BUILD_CONFIG.build, '<sha12>-<YYYYMMDD>') when the build has one,
        // else config.build. GA itself starts the session when its init
        // request answers (automatic session handling)
        initialize(config)
        {
            if (initialized)
                return
            initialized = true
            const keys = typeof GA_KEYS === 'object' && GA_KEYS || {}
            if (!keys.gameKey || !keys.secretKey || !sdk())
                return
            const cfg = typeof BUILD_CONFIG === 'object' && BUILD_CONFIG || {}
            const release = String(cfg.build || config && config.build || '')
            // '<portal>-<build id>' so the itch.io and Y8 builds stay apart in GameAnalytics
            const build = (release && cfg.platform ? cfg.platform + '-' + release : release).slice(0, 32)
            ready = true
            if (build)
                deliver('configureBuild', [build])
            deliver('initialize', [keys.gameKey, keys.secretKey])
            waitUntilReady()
        },

        // GA starts the session itself when its init answers, so a start or
        // end before that is dropped rather than queued
        startSession()
        {
            if (live)
                call('startSession', [])
        },

        endSession()
        {
            if (live)
                call('endSession', [])
        },

        // status: 'Start' | 'Complete' | 'Fail' (EGAProgressionStatus)
        addProgressionEvent(status, p1, p2, p3, score)
        {
            if (!ready || !own(PROGRESSION, status))
                return
            const value = enumValue('EGAProgressionStatus', PROGRESSION[status])
            if (value === undefined)
                return
            const args = [value, p1, p2 || '', p3 || '']
            if (typeof score === 'number')
                args.push(score)
            call('addProgressionEvent', args)
        },

        addDesignEvent(id, value)
        {
            call('addDesignEvent', typeof value === 'number' ? [id, value] : [id])
        },

        // severity: 'debug' | 'info' | 'warning' | 'error' | 'critical' (EGAErrorSeverity)
        addErrorEvent(severity, message)
        {
            if (!ready || !own(SEVERITY, severity))
                return
            const value = enumValue('EGAErrorSeverity', SEVERITY[severity])
            if (value !== undefined)
                call('addErrorEvent', [value, String(message)])
        },

        // action: show | failed_show | reward_received | clicked (EGAAdAction);
        // type: interstitial | rewarded | ... (EGAAdType); others are dropped
        addAdEvent(action, type, sdkName, placement)
        {
            if (!ready || !own(AD_ACTION, action) || !own(AD_TYPE, type))
                return
            const adAction = enumValue('EGAAdAction', AD_ACTION[action])
            const adType = enumValue('EGAAdType', AD_TYPE[type])
            if (adAction !== undefined && adType !== undefined)
                call('addAdEvent', [adAction, adType, String(sdkName || 'grapnelninja').toLowerCase(),
                    placement || 'none'])
        },
    }
})()
