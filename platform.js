// Thin wrapper over the Playgama Bridge v2. When window.bridge is missing or
// bridge.initialize() rejects or times out, PLATFORM.environment is
// 'disabled' and every call is a safe no-op: ads report unavailable/skipped,
// unsaved progress stays in memory until Bridge Storage recovers.
const PLATFORM = (function()
{
    const busyStates = ['loading', 'opened', 'rewarded']

    let bridge = null
    let initPromise = null
    let warned = false
    let readyState = 'pending'
    let readyAttempt = 0
    let readyPromise = null
    let readyTimer = null
    const readyRetryMs = [500, 1000, 2000]
    const readyEvents = []
    // Fixed vocabulary and page-lifetime deduplication bound retention to five.
    const startupStages = new Set(['mode_selected', 'run_initialized',
        'first_gameplay_frame', 'first_grapple', 'tutorial_dismissed'])
    const startupSeen = new Set()
    const startupQueue = []
    const lifecycleQueue = []
    const lifecycleCapacity = 64
    let lifecycleOverflow = 0
    function readyStage(state, detail = {})
    {
        readyState = state
        readyEvents.push({state, attempt: readyAttempt, ms: performance.now(), ...detail})
    }

    // Only explicit rejection permits a retry. An unresolved send may still
    // reach the host, so keep it in flight indefinitely without a second send.
    function deliverReady()
    {
        if (!applicationReady || !bridge || readyState !== 'pending' || readyTimer !== null)
            return readyPromise || Promise.resolve()
        readyAttempt++
        readyStage('inflight')
        readyPromise = Promise.resolve().then(() => bridge.platform.sendMessage('game_ready')).then(() =>
        {
            readyStage('success')
            // Submit in order, without waiting for host responses. A rejected
            // or unresolved lifecycle send must never block or replay others.
            for (const event of lifecycleQueue.splice(0))
                PLATFORM.sendMessage(event.name, event.data)
            for (const data of startupQueue.splice(0))
                PLATFORM.track('startup_funnel', data)
        }, () =>
        {
            if (readyAttempt > readyRetryMs.length)
            {
                readyStage('exhausted')
                lifecycleQueue.length = 0
                startupQueue.length = 0
                return
            }
            const delayMs = readyRetryMs[readyAttempt - 1]
            readyStage('pending', {delayMs})
            readyTimer = setTimeout(() =>
            {
                readyTimer = null
                deliverReady()
            }, delayMs)
        })
        return readyPromise
    }
    let applicationReady = false
    let lastInterstitialRequestAt = -Infinity
    let adBusy = false
    // Our interstitial request the SDK has not yet closed or failed: a late
    // 'opened' after the open watchdog is still our ad and freezes the game
    let interstitialOutstanding = false
    const listeners = {pause: [], audio: [], adState: []}

    function warn(message, e)
    {
        if (warned)
            return
        warned = true
        console.warn('Playgama Bridge disabled:', message, e && e.message)
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
                console.warn('Playgama ' + kind + ' listener failed', e)
            }
        }
    }

    function isoLanguage(value)
    {
        const code = String(value || '').slice(0, 2).toLowerCase()
        return /^[a-z]{2}$/.test(code) ? code : 'en'
    }

    const openAds = new Set()
    function setAdOpen(event, opened)
    {
        const wasOpen = openAds.size > 0
        if (opened) openAds.add(event)
        else openAds.delete(event)
        if (wasOpen !== (openAds.size > 0))
            emit('adState', openAds.size ? 'opened' : 'closed')
    }

    // Host pause/audio and the 'opened'/'closed' of any full-screen ad
    function subscribe()
    {
        const names = bridge.EVENT_NAME
        bridge.platform.on(names.PAUSE_STATE_CHANGED, isPaused => emit('pause', !!isPaused))
        bridge.platform.on(names.AUDIO_STATE_CHANGED, isEnabled => emit('audio', !!isEnabled))
        for (const event of [names.INTERSTITIAL_STATE_CHANGED, names.REWARDED_STATE_CHANGED])
        {
            bridge.advertisement.on(event, state =>
            {
                const interstitial = event === names.INTERSTITIAL_STATE_CHANGED
                if (state === 'opened' && (!interstitial || adBusy || interstitialOutstanding)) setAdOpen(event, true)
                else if (state === 'closed' || state === 'failed')
                {
                    if (interstitial) interstitialOutstanding = false
                    setAdOpen(event, false)
                }
            })
        }
    }

    function init()
    {
        // One deadline covers both download and initialize. Keep the success
        // continuation alive after fallback so a late SDK can attach in place.
        return new Promise(resolve =>
        {
            let attempted = false
            const finish = () => resolve(PLATFORM.environment)
            const disable = error =>
            {
                clearTimeout(timer)
                warn('initialize failed', error)
                PLATFORM.environment = 'disabled'
                finish()
            }
            const timer = setTimeout(() => disable(new Error('SDK startup timeout')), PLATFORM.initTimeoutMs)
            function attach()
            {
                const candidate = window.bridge
                if (attempted || !candidate || typeof candidate.initialize !== 'function')
                    return
                attempted = true
                document.removeEventListener('bridge-loaded', attach)
                Promise.resolve().then(() => {
                    candidate.gameVersion = PLATFORM.buildVersion
                    return candidate.initialize({
                    configFilePath: './playgama-bridge-config.json',
                    // Also used as SDK fallback if the local config request fails.
                    // Our own loading screen has a bounded timeout; a second SDK
                    // overlay would otherwise block input if the host never replies.
                    disableLoadingLogo: true
                    })
                }).then(() =>
                {
                    bridge = candidate
                    PLATFORM.platformId = bridge.platform.id
                    PLATFORM.language = isoLanguage(bridge.platform.language)
                    subscribe()
                    emit('audio', PLATFORM.isAudioEnabled())
                    emit('pause', !!bridge.platform.isPaused)
                    PLATFORM.environment = 'playgama'
                    if (storageKeys) readRemote()
                    clearTimeout(timer)
                    if (applicationReady)
                        PLATFORM.gameReady()
                    finish()
                }).catch(disable)
            }
            document.addEventListener('bridge-loaded', attach)
            attach()
        })
    }

    function interstitialBusy()
    {
        return adBusy || busyStates.indexOf(bridge.advertisement.interstitialState) >= 0
    }

    // Subscribe to one ad's state events until done() is called
    function watchAd(event, onState)
    {
        bridge.advertisement.on(event, onState)
        return () => bridge.advertisement.off(event, onState)
    }

    // The Bridge JSON-parses stored strings on get ('12' -> 12): turn every
    // value back into the string that was saved.
    function storedString(value)
    {
        if (value === null || value === undefined)
            return null
        return typeof value === 'string' ? value : JSON.stringify(value)
    }

    // Keep late results alive, but bound callers' wait. Never issue overlapping
    // writes: a timed-out write may still reach the host later.
    let storageKeys = null
    let remoteKnown = false
    let readPending = null
    let writePending = null
    let retryRead = null
    const recoveryListeners = []
    function bounded(promise, fallback)
    {
        return new Promise(resolve =>
        {
            // Reserve 300ms for a busy render frame inside the 1.5s budget.
            const timer = setTimeout(() => resolve(fallback), 1200)
            promise.then(value => { clearTimeout(timer); resolve(value) })
        })
    }
    function readRemote()
    {
        if (readPending || !bridge) return readPending
        clearTimeout(retryRead)
        readPending = Promise.resolve().then(() => bridge.storage.get(storageKeys.slice())).then(values =>
        {
            const result = {}
            storageKeys.forEach((key, i) => result[key] = storedString((values || [])[i]))
            remoteKnown = true
            recoveryListeners.forEach(fn => fn(result))
            return result
        }).catch(e =>
        {
            console.warn('Playgama storage.get failed', e)
            retryRead = setTimeout(readRemote, 2000)
            return null
        }).finally(() => { readPending = null })
        return readPending
    }

    const PLATFORM =
    {
        environment: 'pending',
        platformId: null,
        language: 'en',
        buildVersion: '2026-10-14-no-audio-firefox-perf',
        // Leave scheduling headroom inside the three-second startup budget.
        initTimeoutMs: 2900,
        // An interstitial that is not 'opened' by then counts as skipped
        interstitialOpenTimeoutMs: 3000,
        interstitialPlayingTimeoutMs: 120000,
        // The game also skips an interstitial this soon after the last one:
        // at most one game over ad per 2 minutes
        interstitialMinGapMs: 120000,

        // Clock for the interstitial gap; tests replace it
        now()
        {
            return performance.now()
        },

        init()
        {
            if (!initPromise)
                initPromise = init()
            return initPromise
        },

        isInterstitialSupported()
        {
            return !!(bridge && bridge.advertisement.isInterstitialSupported)
        },

        // A game over interstitial would be requested now: supported, no ad
        // in progress and PLATFORM.interstitialMinGapMs since the last one
        isInterstitialDue()
        {
            return !!bridge && !!bridge.advertisement.isInterstitialSupported &&
                !interstitialBusy() &&
                PLATFORM.now() - lastInterstitialRequestAt >= PLATFORM.interstitialMinGapMs
        },

        // Resolves 'closed' | 'failed' | 'skipped' (unsupported, disabled,
        // another ad in progress, or not 'opened' in time). Never rejects.
        showInterstitial(placement = 'game_over')
        {
            if (placement !== 'game_over' || typeof runOver === 'undefined' || !runOver ||
                !continueOffer.visible || !PLATFORM.isInterstitialDue())
                return Promise.resolve('skipped')
            lastInterstitialRequestAt = PLATFORM.now()
            adBusy = true
            interstitialOutstanding = true
            return new Promise(resolve =>
            {
                let finished = false
                let watchdog = null
                let unwatch = () => {}
                // The open watchdog ('skipped') leaves the request outstanding;
                // the playing watchdog keeps the ad open while the SDK still
                // reports it opened. Either way its 'closed'/'failed' ends it.
                function finish(result, sdkMayStillShow = false)
                {
                    if (finished) return
                    finished = true
                    const stillOpen = sdkMayStillShow && bridge.advertisement.interstitialState === 'opened'
                    if (!stillOpen)
                    {
                        if (result !== 'skipped') interstitialOutstanding = false
                        setAdOpen(bridge.EVENT_NAME.INTERSTITIAL_STATE_CHANGED, false)
                    }
                    clearTimeout(watchdog)
                    unwatch()
                    adBusy = false
                    resolve(result)
                }
                unwatch = watchAd(bridge.EVENT_NAME.INTERSTITIAL_STATE_CHANGED, state =>
                {
                    if (finished) return
                    if (state === 'opened')
                    {
                        clearTimeout(watchdog)
                        watchdog = setTimeout(() => finish('closed', true), PLATFORM.interstitialPlayingTimeoutMs)
                    }
                    else if (state === 'closed' || state === 'failed')
                        finish(state)
                })
                watchdog = setTimeout(() => finish('skipped', true), PLATFORM.interstitialOpenTimeoutMs)
                try
                {
                    Promise.resolve(bridge.advertisement.showInterstitial(placement))
                        .catch(() => finish('failed'))
                }
                catch (e)
                {
                    finish('failed')
                }
            })
        },

        // Safe wrapper: never throws or rejects; a no-op when disabled
        sendMessage(name, data)
        {
            if (!bridge)
                return Promise.resolve()
            try
            {
                return Promise.resolve(data === undefined
                    ? bridge.platform.sendMessage(name)
                    : bridge.platform.sendMessage(name, data)).catch(e =>
                {
                    console.warn('Playgama sendMessage failed', name, e)
                })
            }
            catch (e)
            {
                console.warn('Playgama sendMessage failed', name, e)
                return Promise.resolve()
            }
        },

        // Optional Bridge telemetry must never interrupt rendering or boot.
        track(name, data)
        {
            if (!bridge || readyState !== 'success' || !bridge.analytics) return
            try
            {
                Promise.resolve(bridge.analytics.send(name, {...data, game_version: PLATFORM.buildVersion}))
                    .catch(() => {})
            }
            catch (_) {}
        },

        // performance.now() measures milliseconds since this page's time origin.
        startup(stage, mode)
        {
            if (!startupStages.has(stage) || startupSeen.has(stage)) return
            startupSeen.add(stage)
            const data = {stage, elapsed_ms: Math.round(performance.now())}
            if (mode === 'classic' || mode === 'bad') data.mode = mode
            if (readyState === 'success') PLATFORM.track('startup_funnel', data)
            else if (readyState !== 'exhausted') startupQueue.push(data)
        },

        // Buffer during SDK/readiness recovery without gating local gameplay.
        sendLifecycle(name, data)
        {
            if (readyState === 'success')
                return PLATFORM.sendMessage(name, data)
            if (readyState !== 'exhausted')
            {
                if (lifecycleQueue.length === lifecycleCapacity)
                {
                    lifecycleQueue.shift()
                    lifecycleOverflow++
                }
                lifecycleQueue.push({name, data})
            }
            return Promise.resolve()
        },

        // Call only after local rendering and input setup, independent of play.
        gameReady()
        {
            if (!applicationReady)
            {
                applicationReady = true
                readyStage('pending', {localReady: true})
            }
            return deliverReady()
        },

        // Local diagnostics only: snapshots cannot mutate delivery state.
        get readiness()
        {
            return {state: readyState, attempts: readyAttempt, applicationReady,
                startup: {queued: startupQueue.length, capacity: startupStages.size, seen: startupSeen.size},
                lifecycle: {queued: lifecycleQueue.length, capacity: lifecycleCapacity,
                    overflow: lifecycleOverflow},
                events: readyEvents.map(event => ({...event}))}
        },

        isAudioEnabled()
        {
            return bridge ? bridge.platform.isAudioEnabled !== false : true
        },

        onPause(fn)
        {
            listeners.pause.push(fn)
        },

        onAudio(fn)
        {
            listeners.audio.push(fn)
        },

        // fn('opened') / fn('closed') around any full-screen ad
        onAdState(fn)
        {
            listeners.adState.push(fn)
        },

        storage:
        {
            get remoteKnown() { return remoteKnown },
            onRecovery(fn) { recoveryListeners.push(fn) },
            async getMany(keys)
            {
                storageKeys = keys.slice()
                const fallback = {}
                keys.forEach(key => fallback[key] = null)
                if (!bridge) return fallback
                return await bounded(readRemote(), null) || fallback
            },
            async setMany(obj)
            {
                // Unknown remote data must be read before any defaults can be sent.
                if (!bridge || !remoteKnown || writePending) return false
                const keys = Object.keys(obj)
                writePending = Promise.resolve().then(() => bridge.storage.set(keys, keys.map(key => String(obj[key]))))
                    .then(() => true).catch(e =>
                    {
                        console.warn('Playgama storage.set failed', e)
                        return false
                    }).finally(() => { writePending = null })
                return bounded(writePending, false)
            }
        }
    }
    return PLATFORM
})()
