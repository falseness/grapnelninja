// Local platform adapter: no SDK, no network, no ads. Keeps the
// PLATFORM API the game calls. Storage uses window.localStorage and falls
// back to an in-memory map when it is missing or throws (a cross-origin
// iframe with blocked storage raises SecurityError on access).
const PLATFORM = (function()
{
    let initPromise = null
    let warned = false
    const memory = new Map()
    const listeners = {pause: [], audio: [], adState: []}

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
        platformId: 'local',
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
                PLATFORM.environment = 'local'
                initPromise = Promise.resolve(PLATFORM.environment)
            }
            return initPromise
        },

        // No ads locally: the continue offer and the interstitial never show
        isRewardedSupported()
        {
            return false
        },

        isInterstitialSupported()
        {
            return false
        },

        requestRewarded()
        {
            return Promise.resolve({status: 'unavailable', reason: 'unsupported'})
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

        isAudioEnabled()
        {
            return true
        },

        onPause(fn)
        {
            listeners.pause.push(fn)
        },

        onAudio(fn)
        {
            listeners.audio.push(fn)
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
