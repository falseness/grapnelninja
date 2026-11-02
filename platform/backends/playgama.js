// Playgama Bridge platform backend (ported, TASK-859). Playgama Bridge v2 (window.bridge).
// Docs: https://wiki.playgama.com/playgama/bridge-sdk/setup.md
// Script tag: <script src="https://bridge.playgama.com/v2/stable/playgama-bridge.js"></script> (synchronous, before platform/backends/playgama.js)
// NO external analytics (no GameAnalytics) on Playgama: telemetry goes only
// through bridge.analytics.send (track/startup).
// Self-contained: it does not call LOCAL_PLATFORM_BACKEND (local.js still
// loads first in a build, see docs/platform-sdk.md, but nothing here uses it).
// - init: bridge.initialize({configFilePath: 'playgama-bridge-config.json',
//   disableLoadingLogo: true}) within PLATFORM.initTimeoutMs; no bridge, a
//   throw, a rejection or the timeout -> environment 'disabled' (the game
//   plays, no ads). A late initialize still attaches the bridge in place.
// - game_ready: gameReady() (the first playable frame, index.html) sends
//   bridge.platform.sendMessage('game_ready') once. Only an explicit
//   rejection is retried (500/1000/2000 ms); a send that never settles stays
//   in flight and is never repeated. Lifecycle messages (level_*,
//   gameplay_started/stopped, player_got_achievement) and the startup funnel
//   wait in a bounded queue until game_ready was delivered, then go out in
//   order.
// - pause/audio: PAUSE_STATE_CHANGED -> onPause fn(isPaused);
//   AUDIO_STATE_CHANGED -> onAudio fn(isEnabled); repeated states are folded.
// - ads: interstitial only while no run is in play (gameplayStart without a
//   gameplayStop -> 'skipped'), at most one in flight, min gap
//   PLATFORM.interstitialMinGapMs (the bridge config also sets 120 s);
//   settles on INTERSTITIAL_STATE_CHANGED 'closed' -> 'closed' | 'failed' ->
//   'failed'; a throw or rejection -> 'failed'; not 'opened' within
//   adOpenTimeoutMs -> 'failed' (still in flight until the SDK ends it).
//   Rewarded: REWARDED_STATE_CHANGED 'rewarded' then 'closed' -> 'rewarded',
//   'closed' alone -> 'closed', 'failed' / throw / rejection / timeouts ->
//   'failed'; no bridge or unsupported -> 'unavailable'.
// - saves: bridge.storage.get/set with the same keys and string values as
//   the published Grapnel Ninja build (release-20261014): the bridge keeps
//   them in Playgama's platform storage or in localStorage under the raw
//   key. The bridge JSON-parses values on get, so every value is turned
//   back into its saved string. A read that does not answer within
//   storageWaitMs leaves remoteKnown() false (no writes, so defaults never
//   overwrite unread saves) and onRecovery() delivers it later; a rejected
//   read is retried every 2 s. Without a usable bridge.storage the saves go
//   to localStorage under the same keys (in-memory fallback).
// Every SDK call is guarded: a missing bridge, a throw or a promise that
// never settles never blocks the game and never leaves an unhandled rejection.
var PLATFORM_BACKEND = (function()
{
    const CONFIG_FILE = 'playgama-bridge-config.json'
    const STARTUP_STAGES = ['mode_selected', 'run_initialized', 'first_gameplay_frame',
        'first_grapple', 'tutorial_dismissed']
    const READY_RETRY_MS = [500, 1000, 2000]
    const LIFECYCLE_CAPACITY = 64

    const listeners = {pause: [], audio: [], adState: [], recovery: []}
    const warnedCalls = new Set()
    const memory = new Map()
    let storageWarned = false

    // Init: 'pending' | 'success' | 'disabled' (a late success still attaches)
    let initState = 'pending'
    let initPromise = null
    let bridge = null
    let language = null
    let hostPlatformId = null
    // Host pause and audio as last told to the listeners
    let hostPaused = false
    let audioEnabled = true
    // game_ready: 'idle' | 'inflight' | 'retry' | 'success' | 'exhausted'
    let readyWanted = false
    let readyState = 'idle'
    let readyAttempts = 0
    const readyEvents = []
    const lifecycleQueue = []
    let lifecycleOverflow = 0
    const startupSeen = new Set()
    const startupQueue = []
    // A run is in play (gameplayStart without gameplayStop)
    let playing = false
    let gameplaySent = false
    // Ads: the full-screen ad events currently open, our interstitial request
    // the SDK has not closed or failed yet, the rewarded ad being shown
    const openAds = new Set()
    let interstitialInFlight = false
    let rewardedInFlight = false
    let lastInterstitialAt = -Infinity
    // Storage
    let storageKeys = null
    let remoteKnown = false
    let readPending = null
    let retryTimer = null
    let writePending = null
    let localStorageMode = false

    function warnOnce(name, e)
    {
        if (warnedCalls.has(name))
            return
        warnedCalls.add(name)
        console.warn('Playgama ' + name + ' failed:', e && e.message || e)
    }

    // fn() or fallback on a throw
    function guard(name, fn, fallback)
    {
        try
        {
            return fn()
        }
        catch (e)
        {
            warnOnce(name, e)
            return fallback
        }
    }

    // A promise for fn()'s value that never rejects: a throw or a rejection
    // resolves failValue
    function attempt(name, fn, failValue)
    {
        let value
        try
        {
            value = fn()
        }
        catch (e)
        {
            warnOnce(name, e)
            return Promise.resolve(failValue)
        }
        return Promise.resolve(value).catch(e =>
        {
            warnOnce(name, e)
            return failValue
        })
    }

    // Resolves with promise's value, or timeoutValue after ms
    function bounded(promise, ms, timeoutValue)
    {
        return new Promise(resolve =>
        {
            const timer = setTimeout(() => resolve(timeoutValue), ms)
            promise.then(value =>
            {
                clearTimeout(timer)
                resolve(value)
            })
        })
    }

    function emit(kind, value)
    {
        for (const fn of listeners[kind].slice())
        {
            try
            {
                fn(value)
            }
            catch (e)
            {
                console.warn('Playgama ' + kind + ' listener failed:', e && e.message || e)
            }
        }
    }

    function eventName(key)
    {
        return guard('EVENT_NAME', () => bridge.EVENT_NAME && bridge.EVENT_NAME[key], undefined)
    }

    function isoLanguage(value)
    {
        const code = String(value || '').slice(0, 2).toLowerCase()
        return /^[a-z]{2}$/.test(code) ? code : null
    }

    function navigatorLanguage()
    {
        try
        {
            return navigator.language
        }
        catch (e)
        {
            return null
        }
    }

    function number(value, fallback)
    {
        return Number.isFinite(value) ? value : fallback
    }

    function platformValue(name, fallback)
    {
        return typeof PLATFORM !== 'undefined' ? number(PLATFORM[name], fallback) : fallback
    }

    function buildVersion()
    {
        if (typeof BUILD_CONFIG !== 'undefined' && BUILD_CONFIG && BUILD_CONFIG.build)
            return String(BUILD_CONFIG.build)
        return typeof PLATFORM !== 'undefined' ? PLATFORM.buildVersion : undefined
    }

    function advertisement()
    {
        return bridge ? guard('advertisement', () => bridge.advertisement || null, null) : null
    }

    // -- pause, audio and ad state ----------------------------------------

    function setHostPaused(isPaused)
    {
        if (isPaused === hostPaused)
            return
        hostPaused = isPaused
        emit('pause', isPaused)
    }

    function setAudioEnabled(isEnabled)
    {
        if (isEnabled === audioEnabled)
            return
        audioEnabled = isEnabled
        emit('audio', isEnabled)
    }

    // 'opened' while any full-screen ad is open, 'closed' once none is
    function setAdOpen(event, opened)
    {
        const wasOpen = openAds.size > 0
        if (opened)
            openAds.add(event)
        else
            openAds.delete(event)
        if (wasOpen !== openAds.size > 0)
            emit('adState', openAds.size ? 'opened' : 'closed')
    }

    // Host pause/audio and the open/closed state of our full-screen ads
    function subscribe()
    {
        const pauseEvent = eventName('PAUSE_STATE_CHANGED')
        const audioEvent = eventName('AUDIO_STATE_CHANGED')
        guard('platform.on', () => bridge.platform.on(pauseEvent, isPaused => setHostPaused(!!isPaused)))
        guard('platform.on', () => bridge.platform.on(audioEvent, isEnabled => setAudioEnabled(isEnabled !== false)))
        const interstitialEvent = eventName('INTERSTITIAL_STATE_CHANGED')
        const rewardedEvent = eventName('REWARDED_STATE_CHANGED')
        const ads = advertisement()
        if (!ads)
            return
        for (const event of [interstitialEvent, rewardedEvent])
        {
            guard('advertisement.on', () => ads.on(event, state =>
            {
                const ours = event === interstitialEvent ? interstitialInFlight : rewardedInFlight
                if (state === 'opened' && ours)
                    setAdOpen(event, true)
                else if (state === 'closed' || state === 'failed')
                {
                    // The SDK ended our ad (also one we stopped waiting for)
                    if (event === interstitialEvent)
                        interstitialInFlight = false
                    else
                        rewardedInFlight = false
                    setAdOpen(event, false)
                }
            }))
        }
    }

    // initialize() resolved: the bridge is usable from now on
    function attach(candidate)
    {
        if (bridge)
            return
        bridge = candidate
        initState = 'success'
        hostPlatformId = guard('platform.id', () => bridge.platform.id, null)
        language = isoLanguage(guard('platform.language', () => bridge.platform.language, null)) ||
            language || isoLanguage(navigatorLanguage()) || 'en'
        subscribe()
        setAudioEnabled(guard('platform.isAudioEnabled', () => bridge.platform.isAudioEnabled, true) !== false)
        if (guard('platform.isPaused', () => bridge.platform.isPaused === true, false))
            setHostPaused(true)
        if (storageKeys && !remoteKnown)
            readRemote()
        if (readyWanted)
            deliverReady()
    }

    function init()
    {
        language = isoLanguage(navigatorLanguage()) || 'en'
        const candidate = guard('window.bridge', () => window.bridge || null, null)
        const initialize = candidate && guard('initialize', () => candidate.initialize, null)
        if (typeof initialize !== 'function')
        {
            initState = 'disabled'
            console.warn('Playgama Bridge missing: playing without it')
            return Promise.resolve({environment: 'disabled', language})
        }
        guard('gameVersion', () => { candidate.gameVersion = buildVersion() })
        const request = attempt('initialize', () => Promise.resolve(initialize.call(candidate,
            {configFilePath: CONFIG_FILE, disableLoadingLogo: true})).then(() => true), false)
        // A late success still attaches the bridge (environment stays 'disabled')
        request.then(ok =>
        {
            if (ok)
                attach(candidate)
            else if (initState === 'pending')
                initState = 'disabled'
        })
        return bounded(request, platformValue('initTimeoutMs', 2900), false).then(ok =>
        {
            if (!ok || !bridge)
            {
                if (initState === 'pending')
                    initState = 'disabled'
                return {environment: 'disabled', language}
            }
            return {environment: 'playgama', language}
        })
    }

    // -- game_ready and lifecycle messages --------------------------------

    function readyStage(state, detail)
    {
        readyState = state
        readyEvents.push(Object.assign({state, attempt: readyAttempts, ms: Math.round(performance.now())}, detail || {}))
        if (readyEvents.length > 20)
            readyEvents.shift()
    }

    function send(message, data)
    {
        return attempt('sendMessage ' + message, () => data === undefined ?
            bridge.platform.sendMessage(message) : bridge.platform.sendMessage(message, data), undefined)
    }

    function deliverReady()
    {
        if (!bridge || readyState !== 'idle')
            return
        readyAttempts++
        readyStage('inflight')
        let request
        try
        {
            request = Promise.resolve(bridge.platform.sendMessage('game_ready'))
        }
        catch (e)
        {
            request = Promise.reject(e)
        }
        request.then(() =>
        {
            readyStage('success')
            // In order, without waiting for host answers
            for (const event of lifecycleQueue.splice(0))
                send(event.name, event.data)
            for (const data of startupQueue.splice(0))
                analytics('startup_funnel', data)
        }, e =>
        {
            warnOnce('game_ready', e)
            if (readyAttempts > READY_RETRY_MS.length)
            {
                readyStage('exhausted')
                lifecycleQueue.length = 0
                startupQueue.length = 0
                return
            }
            const delayMs = READY_RETRY_MS[readyAttempts - 1]
            readyStage('retry', {delayMs})
            setTimeout(() =>
            {
                readyStage('idle')
                deliverReady()
            }, delayMs)
        })
    }

    // Sent now once game_ready went out, else queued (bounded) until it does
    function lifecycle(name, data)
    {
        if (readyState === 'success')
            return send(name, data)
        if (readyState !== 'exhausted')
        {
            if (lifecycleQueue.length >= LIFECYCLE_CAPACITY)
            {
                lifecycleQueue.shift()
                lifecycleOverflow++
            }
            lifecycleQueue.push({name, data})
        }
        return Promise.resolve()
    }

    // bridge.analytics.send, only once game_ready went out
    function analytics(name, data)
    {
        if (!bridge || readyState !== 'success')
            return
        const module = guard('analytics', () => bridge.analytics || null, null)
        if (!module || typeof module.send !== 'function')
            return
        attempt('analytics.send', () => module.send(name, Object.assign({}, data, {game_version: buildVersion()})))
    }

    // -- ads ----------------------------------------------------------------

    function interstitialSupported()
    {
        const ads = advertisement()
        return !!ads && guard('isInterstitialSupported', () => ads.isInterstitialSupported === true, false)
    }

    function interstitialBusy()
    {
        const ads = advertisement()
        const state = ads ? guard('interstitialState', () => ads.interstitialState, null) : null
        return interstitialInFlight || rewardedInFlight || state === 'loading' || state === 'opened'
    }

    // Shows one ad: show(ads) starts it; resolves onState(state, rewarded)
    // once that is a final result. A throw or a rejection -> onRejected()
    // and 'failed'; no 'opened'/'rewarded' within adOpenTimeoutMs or no end
    // within adPlayingTimeoutMs -> onTimeout(rewarded). Our listener is
    // removed once it settles.
    function runAd(name, event, show, onState, onTimeout, onRejected)
    {
        return new Promise(resolve =>
        {
            const ads = advertisement()
            let finished = false
            let rewarded = false
            let openTimer = null
            let playTimer = null
            const listener = state =>
            {
                if (finished)
                    return
                if (state === 'opened' || state === 'rewarded')
                    clearTimeout(openTimer)
                if (state === 'rewarded')
                    rewarded = true
                const result = onState(state, rewarded)
                if (result)
                    finish(result)
            }
            function finish(result)
            {
                if (finished)
                    return
                finished = true
                clearTimeout(openTimer)
                clearTimeout(playTimer)
                guard('advertisement.off', () => ads.off(event, listener))
                resolve(result)
            }
            function rejected(e)
            {
                warnOnce(name, e)
                onRejected()
                finish('failed')
            }
            guard('advertisement.on', () => ads.on(event, listener))
            let request
            try
            {
                request = show(ads)
            }
            catch (e)
            {
                rejected(e)
                return
            }
            Promise.resolve(request).catch(rejected)
            if (finished)
                return
            openTimer = setTimeout(() => finish(onTimeout(rewarded)), BACKEND.adOpenTimeoutMs)
            playTimer = setTimeout(() => finish(onTimeout(rewarded)), BACKEND.adPlayingTimeoutMs)
        })
    }

    // -- storage ----------------------------------------------------------

    // The Bridge JSON-parses stored strings on get ('12' -> 12): turn every
    // value back into the string that was saved
    function storedString(value)
    {
        if (value === null || value === undefined)
            return null
        return typeof value === 'string' ? value : JSON.stringify(value)
    }

    function bridgeStorage()
    {
        const storage = bridge ? guard('storage', () => bridge.storage || null, null) : null
        if (!storage || typeof guard('storage.get', () => storage.get, null) !== 'function' ||
            typeof guard('storage.set', () => storage.set, null) !== 'function')
            return null
        return storage
    }

    // Reads storageKeys through the bridge; resolves {key: string|null} or
    // null (rejected: retried in 2 s; the caller's wait is bounded)
    function readRemote()
    {
        if (readPending)
            return readPending
        const storage = bridgeStorage()
        if (!storage)
            return Promise.resolve(null)
        clearTimeout(retryTimer)
        const keys = storageKeys.slice()
        readPending = attempt('storage.get', () => Promise.resolve(storage.get(keys.slice())).then(values =>
        {
            if (values !== undefined && values !== null && !Array.isArray(values))
                throw new Error('storage.get answered a non-array')
            const result = {}
            keys.forEach((key, i) => result[key] = storedString((values || [])[i]))
            remoteKnown = true
            emit('recovery', result)
            return result
        }), null).then(result =>
        {
            readPending = null
            if (!result && !remoteKnown)
                retryTimer = setTimeout(readRemote, 2000)
            return result
        })
        return readPending
    }

    function localStore()
    {
        try
        {
            return window.localStorage || null
        }
        catch (e)
        {
            storageWarn('access failed', e)
            return null
        }
    }

    function storageWarn(message, e)
    {
        if (storageWarned)
            return
        storageWarned = true
        console.warn('localStorage unavailable, keeping progress in memory:', message, e && e.message)
    }

    function localGet(key)
    {
        const local = localStore()
        if (local)
        {
            try
            {
                const value = local.getItem(key)
                if (value !== null && value !== undefined)
                    return String(value)
            }
            catch (e)
            {
                storageWarn('read failed', e)
            }
        }
        return memory.has(key) ? memory.get(key) : null
    }

    function localSet(key, value)
    {
        memory.set(key, value)
        const local = localStore()
        if (!local)
            return
        try
        {
            local.setItem(key, value)
        }
        catch (e)
        {
            storageWarn('write failed', e)
        }
    }

    const BACKEND = {
        platformId: 'playgama',

        // Timeouts (ms) for SDK answers that never come
        adOpenTimeoutMs: 3000,
        adPlayingTimeoutMs: 120000,
        storageWaitMs: 1200,

        now()
        {
            return performance.now()
        },

        // await bridge.initialize(); resolves {environment, language}
        init()
        {
            if (!initPromise)
                initPromise = init()
            return initPromise
        },

        // bridge.advertisement.isInterstitialSupported
        isInterstitialSupported()
        {
            return interstitialSupported()
        },

        // Supported, no run in play, no ad in progress and the min gap passed
        isInterstitialDue()
        {
            return interstitialSupported() && !playing && !interstitialBusy() &&
                BACKEND.now() - lastInterstitialAt >= platformValue('interstitialMinGapMs', 120000)
        },

        // bridge.advertisement.showInterstitial(placement), settled on
        // INTERSTITIAL_STATE_CHANGED: 'closed' | 'failed'; 'skipped' when not
        // due (no support, a run in play, another ad up, inside the min gap).
        // Never rejects.
        showInterstitial(placement = 'game_over')
        {
            if (!BACKEND.isInterstitialDue())
                return Promise.resolve('skipped')
            lastInterstitialAt = BACKEND.now()
            interstitialInFlight = true
            const event = eventName('INTERSTITIAL_STATE_CHANGED')
            return runAd('showInterstitial', event, ads => ads.showInterstitial(placement),
                state => state === 'closed' || state === 'failed' ? state : null,
                () => 'failed', () => { interstitialInFlight = false }).then(result =>
            {
                if (!interstitialInFlight)
                    setAdOpen(event, false)
                return result
            })
        },

        // bridge.platform.sendMessage(message[, data]); never rejects
        sendMessage(message, data)
        {
            if (!bridge)
                return Promise.resolve()
            return send(message, data)
        },

        // level_started / level_completed / level_failed / level_paused /
        // level_resumed / player_got_achievement, after game_ready
        sendLifecycle(name, data)
        {
            return lifecycle(name, data)
        },

        // bridge.analytics.send(event, data): the only analytics on Playgama
        track(name, data)
        {
            analytics(name, data)
        },

        // bridge.analytics.send('startup_funnel', {stage, elapsed_ms, mode}),
        // once per stage, queued until game_ready went out
        startup(stage, mode)
        {
            if (!STARTUP_STAGES.includes(stage) || startupSeen.has(stage))
                return
            startupSeen.add(stage)
            const data = {stage, elapsed_ms: Math.round(performance.now())}
            if (typeof mode === 'string' && mode)
                data.mode = mode
            if (readyState === 'success')
                analytics('startup_funnel', data)
            else if (readyState !== 'exhausted' && startupQueue.length < STARTUP_STAGES.length)
                startupQueue.push(data)
        },

        // bridge.platform.sendMessage('game_ready') once (mandatory), at the
        // first playable frame
        gameReady()
        {
            readyWanted = true
            deliverReady()
            return Promise.resolve()
        },

        readiness()
        {
            return {state: initState === 'success' ? 'success' : initState === 'pending' ? 'pending' : 'disabled',
                hostPlatformId, gameReady: readyState, attempts: readyAttempts,
                lifecycle: {queued: lifecycleQueue.length, capacity: LIFECYCLE_CAPACITY, overflow: lifecycleOverflow},
                startup: {queued: startupQueue.length, seen: startupSeen.size},
                events: readyEvents.map(e => Object.assign({}, e))}
        },

        // bridge.platform.isAudioEnabled, kept by AUDIO_STATE_CHANGED
        isAudioEnabled()
        {
            return audioEnabled
        },

        // PAUSE_STATE_CHANGED -> fn(isPaused)
        onPause(fn)
        {
            if (typeof fn === 'function')
                listeners.pause.push(fn)
        },

        // AUDIO_STATE_CHANGED -> fn(isEnabled)
        onAudio(fn)
        {
            if (typeof fn === 'function')
                listeners.audio.push(fn)
        },

        // fn('opened') / fn('closed') around our full-screen ads
        onAdState(fn)
        {
            if (typeof fn === 'function')
                listeners.adState.push(fn)
        },

        // Bridge has no loading-progress call
        loadingProgress()
        {
        },

        // bridge.platform.sendMessage('gameplay_started') on each start of play
        gameplayStart()
        {
            playing = true
            if (!gameplaySent)
            {
                gameplaySent = true
                lifecycle('gameplay_started')
            }
        },

        // bridge.platform.sendMessage('gameplay_stopped') when play stops
        gameplayStop()
        {
            playing = false
            if (gameplaySent)
            {
                gameplaySent = false
                lifecycle('gameplay_stopped')
            }
        },

        // Bridge has no happy-moment call
        happyMoment()
        {
        },

        // bridge.advertisement.isRewardedSupported
        isRewardedSupported()
        {
            const ads = advertisement()
            return !!ads && guard('isRewardedSupported', () => ads.isRewardedSupported === true, false)
        },

        // Resolves on REWARDED_STATE_CHANGED: 'closed' -> 'rewarded' when
        // 'rewarded' fired before it, else 'closed'; 'failed' -> 'failed'.
        // A throw, a rejection, no state within adOpenTimeoutMs or no end
        // within adPlayingTimeoutMs -> 'failed' ('rewarded' if it was earned);
        // another ad up -> 'failed'. The listener is removed once it settles.
        // https://wiki.playgama.com/playgama/bridge-sdk/api/advertisement/rewarded.md
        showRewarded(placement)
        {
            if (!BACKEND.isRewardedSupported())
                return Promise.resolve('unavailable')
            if (interstitialBusy())
                return Promise.resolve('failed')
            rewardedInFlight = true
            const event = eventName('REWARDED_STATE_CHANGED')
            return runAd('showRewarded', event, ads => ads.showRewarded(placement),
                (state, rewarded) => state === 'closed' ? (rewarded ? 'rewarded' : 'closed') :
                    state === 'failed' ? 'failed' : null,
                rewarded => rewarded ? 'rewarded' : 'failed', () => { rewardedInFlight = false }).then(result =>
            {
                if (!rewardedInFlight)
                    setAdOpen(event, false)
                return result
            })
        },

        // bridge.advertisement.showBanner(position)
        showBanner(position)
        {
            const ads = advertisement()
            if (!ads || !guard('isBannerSupported', () => ads.isBannerSupported === true, false))
                return Promise.resolve()
            return bounded(attempt('showBanner', () => ads.showBanner(position)), BACKEND.adOpenTimeoutMs).then(() => undefined)
        },

        // bridge.advertisement.hideBanner()
        hideBanner()
        {
            const ads = advertisement()
            if (!ads || !guard('isBannerSupported', () => ads.isBannerSupported === true, false))
                return Promise.resolve()
            return bounded(attempt('hideBanner', () => ads.hideBanner()), BACKEND.adOpenTimeoutMs).then(() => undefined)
        },

        // bridge.leaderboards.setScore(board, value); false when the host
        // has no leaderboards or it fails
        submitScore(board, value)
        {
            const boards = bridge ? guard('leaderboards', () => bridge.leaderboards || null, null) : null
            if (!boards || guard('leaderboards.type', () => boards.type, 'not_available') === 'not_available')
                return Promise.resolve(false)
            return bounded(attempt('leaderboards.setScore', () => Promise.resolve(boards.setScore(board, value)).then(() => true), false),
                BACKEND.adOpenTimeoutMs, false)
        },

        // bridge.achievements.unlock(id); false without the module or on failure
        unlockAchievement(id)
        {
            const achievements = bridge ? guard('achievements', () => bridge.achievements || null, null) : null
            if (!achievements || typeof guard('achievements.unlock', () => achievements.unlock, null) !== 'function')
                return Promise.resolve(false)
            return bounded(attempt('achievements.unlock', () => Promise.resolve(achievements.unlock(id)).then(() => true), false),
                BACKEND.adOpenTimeoutMs, false)
        },

        // bridge.platform.language (2-letter), read by init()
        getLanguage()
        {
            return language
        },

        // 'playgama' (readiness().hostPlatformId is bridge.platform.id)
        getPlatformId()
        {
            return BACKEND.platformId
        },

        storage:
        {
            // True once bridge.storage.get answered (always without a bridge)
            remoteKnown()
            {
                return localStorageMode || remoteKnown
            },

            // fn({key: string|null}) for a bridge read that answered late
            onRecovery(fn)
            {
                if (typeof fn === 'function')
                    listeners.recovery.push(fn)
            },

            // bridge.storage.get(keys) -> {key: string|null}; nulls (and
            // remoteKnown() false) when it does not answer in storageWaitMs
            async getMany(keys)
            {
                storageKeys = Array.from(keys || [], String)
                if (!bridgeStorage())
                {
                    // No usable bridge: the same keys in localStorage (where
                    // the bridge's own local mode keeps them); a late
                    // initialize still reads the bridge (onRecovery)
                    localStorageMode = true
                    return Object.fromEntries(storageKeys.map(key => [key, localGet(key)]))
                }
                const fallback = Object.fromEntries(storageKeys.map(key => [key, null]))
                return await bounded(readRemote(), BACKEND.storageWaitMs, null) || fallback
            },

            // bridge.storage.set(keys, values) with string values; false
            // until the saves were read, while a write is pending, or on a
            // failure (the game retries)
            async setMany(obj)
            {
                const keys = Object.keys(obj)
                const storage = bridgeStorage()
                if (storage && remoteKnown)
                {
                    if (writePending)
                        return false
                    const values = keys.map(key => String(obj[key]))
                    writePending = attempt('storage.set', () => Promise.resolve(storage.set(keys, values)).then(() => true), false)
                        .then(ok =>
                        {
                            writePending = null
                            return ok
                        })
                    return bounded(writePending, BACKEND.storageWaitMs, false)
                }
                if (!localStorageMode)
                    return false
                for (const key of keys)
                    localSet(key, String(obj[key]))
                return true
            }
        }
    }
    return BACKEND
})()
