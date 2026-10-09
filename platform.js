// Thin wrapper over the Playgama Bridge v2. When window.bridge is missing or
// bridge.initialize() rejects or times out, PLATFORM.environment is
// 'disabled' and every call is a safe no-op: ads report unavailable/skipped,
// storage falls back to window.localStorage.
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
        }, () =>
        {
            if (readyAttempt > readyRetryMs.length)
            {
                readyStage('exhausted')
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
                if (state === 'opened' && (event !== names.INTERSTITIAL_STATE_CHANGED || adBusy)) setAdOpen(event, true)
                else if (state === 'closed' || state === 'failed') setAdOpen(event, false)
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
                Promise.resolve().then(() => candidate.initialize({
                    configFilePath: new URL('playgama-bridge-config.json', document.baseURI).href
                })).then(() =>
                {
                    bridge = candidate
                    PLATFORM.platformId = bridge.platform.id
                    PLATFORM.language = isoLanguage(bridge.platform.language)
                    subscribe()
                    emit('audio', PLATFORM.isAudioEnabled())
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

    function localGet(key)
    {
        try
        {
            return window.localStorage.getItem(key)
        }
        catch (e)
        {
            return null
        }
    }

    function localSet(key, value)
    {
        try
        {
            window.localStorage.setItem(key, value)
        }
        catch (e)
        {
            console.warn('localStorage write failed', e)
        }
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

        // Resolves 'closed' | 'failed' | 'skipped' (unsupported, disabled,
        // another ad in progress, or not 'opened' in time). Never rejects.
        showInterstitial(placement = 'game_over')
        {
            if (placement !== 'game_over' || typeof runOver === 'undefined' || !runOver ||
                !continueOffer.visible || !bridge || !bridge.advertisement.isInterstitialSupported ||
                interstitialBusy() || PLATFORM.now() - lastInterstitialRequestAt < 120000)
                return Promise.resolve('skipped')
            lastInterstitialRequestAt = PLATFORM.now()
            adBusy = true
            return new Promise(resolve =>
            {
                let finished = false
                let watchdog = null
                let unwatch = () => {}
                function finish(result)
                {
                    if (finished) return
                    finished = true
                    setAdOpen(bridge.EVENT_NAME.INTERSTITIAL_STATE_CHANGED, false)
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
                        watchdog = setTimeout(() => finish('closed'), PLATFORM.interstitialPlayingTimeoutMs)
                    }
                    else if (state === 'closed' || state === 'failed')
                        finish(state)
                })
                watchdog = setTimeout(() => finish('skipped'), PLATFORM.interstitialOpenTimeoutMs)
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

        // Gameplay lifecycle messages; dropped until game_ready was sent
        sendLifecycle(name, data)
        {
            if (readyState !== 'success')
                return Promise.resolve()
            return PLATFORM.sendMessage(name, data)
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
            localGet,
            localSet,
            async getMany(keys)
            {
                storageKeys = keys.slice()
                const fallback = {}
                keys.forEach(key => fallback[key] = localGet(key))
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
