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
    let gameReadySent = false
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

    // Host pause/audio and the 'opened'/'closed' of any full-screen ad
    function subscribe()
    {
        const names = bridge.EVENT_NAME
        bridge.platform.on(names.PAUSE_STATE_CHANGED, isPaused => emit('pause', !!isPaused))
        bridge.platform.on(names.AUDIO_STATE_CHANGED, isEnabled => emit('audio', !!isEnabled))
        for (const event of [names.INTERSTITIAL_STATE_CHANGED, names.REWARDED_STATE_CHANGED])
        {
            let opened = false
            bridge.advertisement.on(event, state =>
            {
                if (state === 'opened' && !opened)
                {
                    opened = true
                    emit('adState', 'opened')
                }
                else if ((state === 'closed' || state === 'failed') && opened)
                {
                    opened = false
                    emit('adState', 'closed')
                }
            })
        }
    }

    async function init()
    {
        const candidate = window.bridge
        if (!candidate || typeof candidate.initialize !== 'function')
        {
            warn('window.bridge missing')
            PLATFORM.environment = 'disabled'
            return PLATFORM.environment
        }
        let timer
        try
        {
            await Promise.race([
                Promise.resolve().then(() => candidate.initialize()),
                new Promise((resolve, reject) =>
                {
                    timer = setTimeout(() => reject(new Error('initialize timeout')), PLATFORM.initTimeoutMs)
                })
            ])
            bridge = candidate
            PLATFORM.platformId = bridge.platform.id
            PLATFORM.language = isoLanguage(bridge.platform.language)
            subscribe()
            PLATFORM.environment = 'playgama'
        }
        catch (e)
        {
            warn('initialize failed', e)
            bridge = null
            PLATFORM.environment = 'disabled'
        }
        finally
        {
            clearTimeout(timer)
        }
        return PLATFORM.environment
    }

    function rewardedBusy()
    {
        return adBusy || busyStates.indexOf(bridge.advertisement.rewardedState) >= 0
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

    const PLATFORM =
    {
        environment: 'pending',
        platformId: null,
        language: 'en',
        initTimeoutMs: 8000,
        // Watchdog for a rewarded ad that never reports an outcome
        rewardTimeoutMs: 15000,
        // Once the ad is 'opened' the watchdog restarts with this limit:
        // rewarded videos often run 15-30 s and must not time out.
        rewardPlayingTimeoutMs: 120000,
        // An interstitial that is not 'opened' by then counts as skipped
        interstitialOpenTimeoutMs: 3000,
        interstitialPlayingTimeoutMs: 120000,

        init()
        {
            if (!initPromise)
                initPromise = init()
            return initPromise
        },

        // Resolves {status: 'rewarded' | 'dismissed' | 'unavailable', reason?};
        // grant the reward ONLY on 'rewarded'. Never rejects.
        requestRewarded(placement = 'continue')
        {
            if (!bridge)
                return Promise.resolve({status: 'unavailable', reason: 'disabled'})
            if (!bridge.advertisement.isRewardedSupported)
                return Promise.resolve({status: 'unavailable', reason: 'unsupported'})
            if (rewardedBusy())
                return Promise.resolve({status: 'unavailable', reason: 'busy'})
            adBusy = true
            return new Promise(resolve =>
            {
                let rewarded = false
                let watchdog = null
                let unwatch = () => {}
                function finish(result)
                {
                    clearTimeout(watchdog)
                    unwatch()
                    adBusy = false
                    resolve(result)
                }
                function startWatchdog(ms)
                {
                    clearTimeout(watchdog)
                    watchdog = setTimeout(() => finish({status: 'unavailable', reason: 'timeout'}), ms)
                }
                unwatch = watchAd(bridge.EVENT_NAME.REWARDED_STATE_CHANGED, state =>
                {
                    if (state === 'opened')
                        startWatchdog(PLATFORM.rewardPlayingTimeoutMs)
                    else if (state === 'rewarded')
                        rewarded = true
                    else if (state === 'failed')
                        finish({status: 'unavailable', reason: 'failed'})
                    else if (state === 'closed')
                        finish(rewarded ? {status: 'rewarded'} : {status: 'dismissed'})
                })
                startWatchdog(PLATFORM.rewardTimeoutMs)
                try
                {
                    bridge.advertisement.showRewarded(placement)
                }
                catch (e)
                {
                    finish({status: 'unavailable', reason: 'exception'})
                }
            })
        },

        // Resolves 'closed' | 'failed' | 'skipped' (unsupported, disabled,
        // another ad in progress, or not 'opened' in time). Never rejects.
        showInterstitial(placement = 'game_over')
        {
            if (!bridge || !bridge.advertisement.isInterstitialSupported || interstitialBusy())
                return Promise.resolve('skipped')
            adBusy = true
            return new Promise(resolve =>
            {
                let watchdog = null
                let unwatch = () => {}
                function finish(result)
                {
                    clearTimeout(watchdog)
                    unwatch()
                    adBusy = false
                    resolve(result)
                }
                unwatch = watchAd(bridge.EVENT_NAME.INTERSTITIAL_STATE_CHANGED, state =>
                {
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
                    bridge.advertisement.showInterstitial(placement)
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

        // Call when the first playable frame is ready; sends at most once
        gameReady()
        {
            if (gameReadySent || !bridge)
                return Promise.resolve()
            gameReadySent = true
            return PLATFORM.sendMessage('game_ready')
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
            // Resolves {key: string | null} with ONE bridge.storage.get call
            async getMany(keys)
            {
                const result = {}
                if (!bridge)
                {
                    for (const key of keys)
                        result[key] = localGet(key)
                    return result
                }
                let values = []
                try
                {
                    values = await bridge.storage.get(keys.slice())
                }
                catch (e)
                {
                    console.warn('Playgama storage.get failed', e)
                }
                keys.forEach((key, i) => result[key] = storedString((values || [])[i]))
                return result
            },

            // Saves {key: value} as strings with ONE bridge.storage.set call
            async setMany(obj)
            {
                const keys = Object.keys(obj)
                const values = keys.map(key => String(obj[key]))
                if (!bridge)
                {
                    keys.forEach((key, i) => localSet(key, values[i]))
                    return
                }
                try
                {
                    await bridge.storage.set(keys, values)
                }
                catch (e)
                {
                    console.warn('Playgama storage.set failed', e)
                }
            }
        }
    }
    return PLATFORM
})()
