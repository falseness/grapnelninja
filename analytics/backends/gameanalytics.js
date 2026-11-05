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
//
// Quit (TASK-899): the SDK runs every add*/endSession call later as a task
// on its timer "GA thread" and posts by async XHR, so on a page unload the
// quit-time events were never stored or sent, and its own beforeunload
// handler stored session_end before the game's pagehide events. Now its
// beforeunload session end waits for endSession(), which runs the queued
// GA-thread tasks at once (the events, then session_end and the send) with
// the /events POST sent by fetch(keepalive) - same body and Authorization
// header - so it outlives the page; rows handed to that request leave the
// SDK's localStorage store so a revisit does not send them again. After
// endSession nothing is sent until startSession() reopens the session (a
// page restored from the back/forward cache, TASK-907). A pagehide without
// endSession ends the session the same way. flush() (a hidden tab, TASK-908)
// sends the same way without ending the session.
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
    let listening = false
    // endSession ran: later calls are dropped until startSession()
    let ended = false
    // Bytes a keepalive request may carry (browsers allow 64 KiB in flight)
    const KEEPALIVE_MAX = 60000

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
        if (!ready || ended)
            return
        if (live)
            return deliver(fn, args)
        if (pending.length < PENDING_MAX)
            pending.push([fn, args])
    }

    function goLive()
    {
        if (live || ended)
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
        if (!listening && typeof ga.addRemoteConfigsListener === 'function')
        {
            listening = true
            deliver('addRemoteConfigsListener', [{onRemoteConfigsUpdated: () => setTimeout(goLive, 0)}])
        }
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

    // gameanalytics.<path> of the real SDK's internals; null in a mock / other SDK
    function internal(path)
    {
        let node = sdk()
        for (const key of path.split('.'))
            node = node && node[key]
        return node || null
    }

    // The SDK's beforeunload handler ends the session (storing session_end)
    // before the game's pagehide events: skip that while the page unloads,
    // endSession() ends it right after those events
    function holdUnloadSessionEnd()
    {
        const threading = internal('threading.GAThreading')
        const state = internal('state.GAState')
        if (!threading || typeof threading.endSessionAndStopQueue !== 'function' || !state)
            return
        const end = threading.endSessionAndStopQueue
        threading.endSessionAndStopQueue = function()
        {
            if (!ended && state.instance && state.instance.isUnloading)
                return
            return end.apply(this, arguments)
        }
    }

    // GAHTTPApi.sendRequest(url, payload, extra, gzip, callback, done) for
    // /events by fetch(keepalive); `sent` collects the batch ids (extra[1])
    // whose request went out. Anything else uses the SDK's XHR.
    function keepaliveSender(original, sent)
    {
        return function(url, payload, extra, gzip, callback, done)
        {
            const fallback = () => original.apply(this, arguments)
            const size = typeof TextEncoder === 'function' ? new TextEncoder().encode(payload).length
                : String(payload).length * 3
            if (gzip || typeof fetch !== 'function' || !/\/events$/.test(url) || size > KEEPALIVE_MAX)
                return fallback()
            let request, auth
            try
            {
                auth = internal('utilities.GAUtilities').getHmac(internal('state.GAState').getGameSecret(), payload)
                request = fetch(url, {method: 'POST', keepalive: true, body: payload,
                    headers: {'Content-Type': 'application/json', 'Authorization': auth}})
            }
            catch (e)
            {
                return fallback()
            }
            const args = [auth].concat(Array.from(extra || []))
            sent.push(extra && extra[1])
            const answer = (status, statusText, text) =>
            {
                try { callback({readyState: 4, status, statusText, responseText: text}, url, done, args) }
                catch (e) {}
            }
            request.then(r => r.text().then(text => answer(r.status, r.statusText, text)))
                .catch(() => answer(0, '', ''))
        }
    }

    // Runs the SDK's queued GA-thread tasks now (the add* events, then the
    // endSession task that stores session_end and sends the batch), with
    // /events sent by keepalive; then also sends anything still new
    function flushForUnload()
    {
        const threading = internal('threading.GAThreading')
        const http = internal('http.GAHTTPApi')
        if (!threading || typeof threading.run !== 'function')
            return
        const original = http && http.sendRequest
        const sent = []
        if (typeof original === 'function')
            http.sendRequest = keepaliveSender(original, sent)
        try
        {
            threading.run()
            const events = internal('events.GAEvents')
            if (events && typeof events.processEvents === 'function')
                events.processEvents('', false)
        }
        catch (e)
        {
            warn('flush', e)
        }
        finally
        {
            if (typeof original === 'function')
                http.sendRequest = original
        }
        // The keepalive request owns these rows now; the copy saved in
        // localStorage would be sent again on the next visit
        const store = internal('store.GAStore')
        const kinds = internal('store.EGAStore')
        const ops = internal('store.EGAStoreArgsOperator')
        const state = internal('state.GAState')
        if (!sent.length || !store || !kinds || !ops || !state)
            return
        try
        {
            for (const id of sent)
                if (id)
                    store.delete(kinds.Events, [['status', ops.Equal, id]])
            store.save(state.getGameKey())
        }
        catch (e)
        {
            warn('store', e)
        }
    }

    function endNow()
    {
        if (ended)
            return
        if (!live)
        {
            ended = ready
            return
        }
        deliver('endSession', [])
        ended = true
        flushForUnload()
    }

    // TASK-907: the page came back from the back/forward cache after endNow.
    // GameAnalytics.startSession() sends a new init request and starts a new
    // session (and its event queue timer, stopped by endSessionAndStopQueue;
    // the GA-thread task timer never stops) when that answers. Until then the
    // SDK drops events ("Session has not started yet"), so they wait in
    // `pending` again until GAState reports the new session (or the
    // remote-configs listener fires on the answer).
    function restart()
    {
        ended = false
        if (!live)
            return waitUntilReady()
        live = false
        deliver('startSession', [])
        const state = internal('state.GAState')
        if (!state || typeof state.sessionIsStarted !== 'function')
            return goLive()
        const started = Date.now()
        const timer = setInterval(() =>
        {
            let isStarted = false
            try { isStarted = !!state.sessionIsStarted() } catch (e) {}
            if (isStarted || Date.now() - started > POLL_FOR_MS)
                setTimeout(goLive, 0)
            if (isStarted || live || ended || Date.now() - started > POLL_FOR_MS)
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
            holdUnloadSessionEnd()
            // After the game's own pagehide handler (watchAnalytics, added
            // before boot): ends the session if the game did not
            window.addEventListener('pagehide', endNow)
            waitUntilReady()
        },

        // GA starts the session itself when its init answers, so a start or
        // end before that is dropped rather than queued. After endSession
        // (a pageshow from the back/forward cache) it reopens the session.
        startSession()
        {
            if (!ready)
                return
            if (ended)
                return restart()
            if (live)
                call('startSession', [])
        },

        // Once per session: runs the queued events, stores session_end and
        // sends the batch at once (keepalive); later calls are dropped
        endSession()
        {
            endNow()
        },

        // TASK-908: the tab went hidden (a phone may discard it with no
        // pagehide): the queued GA-thread tasks run now and the event store
        // goes out by keepalive, as on pagehide but without endSession: the
        // session and the SDK's timers go on. The sent rows leave the store
        // (the SDK's next timed processEvents resets every row to 'new', and
        // a discarded page would send them again on the next visit). Before
        // the SDK is live or after endSession there is nothing to send.
        flush()
        {
            if (live && !ended)
                flushForUnload()
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
