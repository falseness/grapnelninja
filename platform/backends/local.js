// Local platform backend: no SDK, no network, no ads. platform.js (the
// facade) calls these inner methods; a portal port replaces this file and
// its script tag in index.html. Storage uses window.localStorage and falls
// back to an in-memory map when it is missing or throws (a cross-origin
// iframe with blocked storage raises SecurityError on access). With no ads
// no interstitial is ever due, so every death restarts at once.
const PLATFORM_BACKEND = (function()
{
    let warned = false
    const memory = new Map()
    const listeners = {pause: [], audio: [], adState: []}
    let language = null

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

    return {
        platformId: 'local',

        now()
        {
            return performance.now()
        },

        // Resolves {environment, language} (2-letter ISO code)
        init()
        {
            language = isoLanguage(navigatorLanguage())
            return Promise.resolve({environment: 'local', language})
        },

        // No ads locally: the death screen never waits for an interstitial
        isInterstitialSupported()
        {
            return false
        },

        isInterstitialDue()
        {
            return false
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

        // Telemetry has nowhere to go locally
        track()
        {
        },

        startup()
        {
        },

        gameReady()
        {
            return Promise.resolve()
        },

        readiness()
        {
            return {state: 'local'}
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

        // No portal locally: lifecycle, ads, scores and achievements are no-ops
        loadingProgress()
        {
        },

        gameplayStart()
        {
        },

        gameplayStop()
        {
        },

        happyMoment()
        {
        },

        isRewardedSupported()
        {
            return false
        },

        showRewarded()
        {
            return Promise.resolve('unavailable')
        },

        showBanner()
        {
            return Promise.resolve()
        },

        hideBanner()
        {
            return Promise.resolve()
        },

        submitScore()
        {
            return Promise.resolve(false)
        },

        unlockAchievement()
        {
            return Promise.resolve(false)
        },

        // The language init() detected
        getLanguage()
        {
            return language
        },

        getPlatformId()
        {
            return this.platformId
        },

        storage:
        {
            // Local storage is always read in full at boot
            remoteKnown()
            {
                return true
            },

            // There is no late remote read to reconcile
            onRecovery()
            {
            },

            // Resolves {key: string | null}
            async getMany(keys)
            {
                const result = {}
                for (const key of keys)
                    result[key] = localGet(key)
                return result
            },

            // Saves {key: value} as strings; true once written
            async setMany(obj)
            {
                for (const key of Object.keys(obj))
                    localSet(key, String(obj[key]))
                return true
            }
        }
    }
})()
