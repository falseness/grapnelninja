// itch.io platform backend (ported, TASK-856).
// itch.io has no SDK: the game runs in an itch.io iframe and keeps saves in
// localStorage, so most methods are the local no-ops below.
// Docs: https://itch.io/docs/creators/html5
// Script tag: none: itch.io has no SDK; upload the zip with index.html at its root (no extra <script> tag)
// Self-contained: it no longer calls LOCAL_PLATFORM_BACKEND (local.js still
// loads first in a build, see docs/platform-sdk.md, but nothing here uses it).
// - init resolves {environment: 'itch', language} from navigator.language
// - no ads: no interstitials, no rewarded ads (Go back is free), no banners
// - saves: localStorage, with an in-memory fallback when storage is blocked
//   (a sandboxed or third-party iframe can throw SecurityError)
// - onPause: window blur or a hidden document -> fn(true); focus with a
//   visible document -> fn(false). The game pauses and mutes on fn(true).
var PLATFORM_BACKEND = (function()
{
    const memory = new Map()
    const pauseListeners = []
    let language = null
    let warned = false
    let blurred = false
    let hidden = false
    let paused = false
    let watching = false

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

    function documentHidden()
    {
        return document.visibilityState === 'hidden'
    }

    // Tells every listener when the paused state (blurred or hidden) changes
    function update()
    {
        const now = blurred || hidden
        if (now === paused)
            return
        paused = now
        for (const fn of pauseListeners.slice())
        {
            try
            {
                fn(paused)
            }
            catch (e)
            {
                console.warn('itch onPause listener failed:', e && e.message || e)
            }
        }
    }

    function watch()
    {
        if (watching)
            return
        watching = true
        hidden = documentHidden()
        paused = hidden
        window.addEventListener('blur', function()
        {
            blurred = true
            update()
        })
        window.addEventListener('focus', function()
        {
            blurred = false
            hidden = documentHidden()
            update()
        })
        document.addEventListener('visibilitychange', function()
        {
            hidden = documentHidden()
            update()
        })
    }

    return {
        platformId: 'itch',

        now()
        {
            return performance.now()
        },

        init()
        {
            language = isoLanguage(navigatorLanguage())
            return Promise.resolve({environment: 'itch', language})
        },

        // No ads on itch.io: the death screen never waits for an interstitial
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

        // GameAnalytics (when on) is a separate analytics backend
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

        // https://itch.io/docs/creators/html5: the game is an iframe on the
        // page; it pauses (and mutes) while the player is elsewhere
        onPause(fn)
        {
            if (typeof fn !== 'function')
                return
            watch()
            pauseListeners.push(fn)
        },

        // itch.io has no host mute; the game mutes itself on pause
        onAudio()
        {
        },

        // No ads, so no ad state
        onAdState()
        {
        },

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

        // itch.io has no ad SDK, so there are no rewarded ads: false, and
        // the go-back dialog offers Go back for free (no ad marker).
        isRewardedSupported()
        {
            return false
        },

        // No ad SDK: resolves 'unavailable' (going back is free)
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

        // No leaderboards or achievements
        submitScore()
        {
            return Promise.resolve(false)
        },

        unlockAchievement()
        {
            return Promise.resolve(false)
        },

        // The 2-letter code init() read from navigator.language
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
            // localStorage is read in full at boot
            remoteKnown()
            {
                return true
            },

            // No late remote read to reconcile
            onRecovery()
            {
            },

            // Resolves {key: string | null} from localStorage
            async getMany(keys)
            {
                const result = {}
                for (const key of keys)
                    result[key] = localGet(key)
                return result
            },

            // Saves {key: value} as strings in localStorage; true once written
            async setMany(obj)
            {
                for (const key of Object.keys(obj))
                    localSet(key, String(obj[key]))
                return true
            }
        }
    }
})()
