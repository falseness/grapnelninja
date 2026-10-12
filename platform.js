// Y8 adapter. Anonymous play and local progress remain available when the
// SDK cannot initialize. Browser storage denial falls back to session memory.
const PLATFORM = (function()
{
    let initPromise = null
    let sdk = null
    let adPending = false
    let warned = false
    const memory = new Map()
    const listeners = {pause: [], adState: []}

    function warn(message, e)
    {
        if (warned)
            return
        warned = true
        console.warn('localStorage unavailable, keeping progress in memory:', message, e && e.message)
    }

    function isoLanguage(value)
    {
        const code = String(value || '').slice(0, 2).toLowerCase()
        return /^[a-z]{2}$/.test(code) ? code : 'en'
    }

    function storage()
    {
        try
        {
            return window.localStorage || null
        }
        catch (e)
        {
            warn('access failed', e)
            return null
        }
    }

    function localGet(key)
    {
        const local = storage()
        if (local)
        {
            try
            {
                const value = local.getItem(key)
                if (value !== null)
                    return value
            }
            catch (e)
            {
                warn('read failed', e)
            }
        }
        return memory.has(key) ? memory.get(key) : null
    }

    function localSet(key, value)
    {
        memory.set(key, value)
        const local = storage()
        if (!local)
            return
        try
        {
            local.setItem(key, value)
        }
        catch (e)
        {
            warn('write failed', e)
        }
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

    const PLATFORM =
    {
        environment: 'pending',
        platformId: 'y8',
        buildVersion: '2026-10-12-y8-candidate311',
        rewardTimeoutMs: 15000,
        rewardPlayingTimeoutMs: 120000,
        language: 'en',
        // The game skips an interstitial this soon after the last one
        interstitialMinGapMs: 60000,

        now()
        {
            return performance.now()
        },

        init()
        {
            if (!initPromise)
            {
                PLATFORM.language = isoLanguage(navigatorLanguage())
                initPromise = new Promise(resolve =>
                {
                    let settled = false, started = false
                    const finish = candidate =>
                    {
                        if (settled) return
                        settled = true
                        clearTimeout(timer)
                        window.removeEventListener('y8sdk.ready', ready)
                        sdk = candidate
                        PLATFORM.environment = sdk ? 'y8' : 'disabled'
                        resolve(PLATFORM.environment)
                    }
                    const ready = () =>
                    {
                        if (settled || started) return
                        started = true
                        try
                        {
                            const candidate = window.y8.sdk()
                            Promise.resolve(candidate.init(
                                {appId: Y8_CONFIG.appId, autoLogin: false},
                                {gameId: Y8_CONFIG.gameId, preloadAdBreaks: 'auto', sound: 'off'}
                            )).then(() => finish(candidate), () => finish(null))
                        }
                        catch (_) { finish(null) }
                    }
                    const timer = setTimeout(() => finish(null), 2900)
                    window.addEventListener('y8sdk.ready', ready)
                    if (window.y8 && typeof window.y8.emitReadyEvent === 'function')
                        window.y8.emitReadyEvent()
                })
            }
            return initPromise
        },

        // Preserve the Y8 release's optional rewarded continue; no interstitials.
        isRewardedSupported()
        {
            return !!sdk
        },

        isInterstitialSupported()
        {
            return false
        },

        requestRewarded()
        {
            if (!sdk || adPending)
                return Promise.resolve({status: 'unavailable', reason: adPending ? 'busy' : 'unsupported'})
            adPending = true
            return new Promise(resolve =>
            {
                let ended = false, viewed = false, watchdog
                const emit = state => listeners.adState.forEach(fn => {
                    try { fn(state) } catch (_) { /* host observers must not strand the ad */ }
                })
                const finish = (status, reason) =>
                {
                    if (ended) return
                    ended = true
                    clearTimeout(watchdog)
                    adPending = false
                    emit('closed')
                    resolve({status, reason})
                }
                const timeout = ms => {
                    clearTimeout(watchdog)
                    watchdog = setTimeout(() => finish('unavailable', 'timeout'), ms)
                }
                timeout(PLATFORM.rewardTimeoutMs)
                try
                {
                    Promise.resolve(sdk.showAd({
                        type: 'reward', name: 'continue',
                        beforeReward: show => { if (!ended) show() },
                        beforeAd: () => {
                            if (ended) return
                            emit('opened')
                            timeout(PLATFORM.rewardPlayingTimeoutMs)
                        },
                        adViewed: () => { if (!ended) viewed = true },
                        adDismissed: () => { if (!ended) viewed = false },
                        adBreakDone: info => finish(viewed ? 'rewarded' : 'unavailable', info && info.breakStatus)
                    })).catch(() => finish('unavailable', 'rejected'))
                }
                catch (_) { finish('unavailable', 'exception') }
            })
        },

        showInterstitial()
        {
            return Promise.resolve('skipped')
        },

        sendMessage()
        {
            return Promise.resolve()
        },

        sendLifecycle()
        {
            return Promise.resolve()
        },

        gameReady()
        {
            return Promise.resolve()
        },

        onPause(fn)
        {
            listeners.pause.push(fn)
        },

        onAdState(fn)
        {
            listeners.adState.push(fn)
        },

        storage:
        {
            // Resolves {key: string | null}
            async getMany(keys)
            {
                const result = {}
                for (const key of keys)
                    result[key] = localGet(key)
                return result
            },

            // Saves {key: value} as strings
            async setMany(obj)
            {
                for (const key of Object.keys(obj))
                    localSet(key, String(obj[key]))
            }
        }
    }
    return PLATFORM
})()
