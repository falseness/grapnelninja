// GamePix platform backend (ported, TASK-857). GamePix SDK v3 (window.GamePix).
// Docs: https://partners.gamepix.com/sdk/doc/javascript
// Script tag: <script src="https://integration.gamepix.com/sdk/v3/gamepix.sdk.js"></script> (synchronous, before platform/backends/gamepix.js)
// NO third-party analytics (no GameAnalytics) on GamePix: track/startup are no-ops.
// Self-contained: it does not call LOCAL_PLATFORM_BACKEND (local.js still
// loads first in a build, see docs/platform-sdk.md, but nothing here uses it).
// - lifecycle: GamePix.lifecycle.loading(n) with n 0..100, never decreasing;
//   gameReady() sends loading(100) (if not sent) then lifecycle.loaded() once;
//   lifecycle.gameStart() once, on the first gameplayStart, after loaded()
//   (a gameplayStart before gameReady waits for it). Every ad call first
//   makes sure loaded() went out.
// - pause: GamePix.events.on('pause') -> onPause fn(true) and onAudio fn(false);
//   'resume' -> fn(false) / fn(true). Repeated events are folded.
// - ads: interstitial only while no run is in play (gameplayStart without a
//   gameplayStop -> 'skipped'), at most one in flight, min gap
//   PLATFORM.interstitialMinGapMs; rewarded via GamePix.ads.reward().
//   {success: true} -> 'closed' (interstitial) / 'rewarded'; anything else,
//   a throw or a rejection -> 'failed'. A call that never settles: 'failed'
//   after adOpenTimeoutMs without a GamePix 'pause', after adResumeGraceMs
//   past the 'resume' that ends the ad, or after adPlayingTimeoutMs. A pause
//   the ad caused is lifted (fn(false)) before the result resolves.
// - saves: plain localStorage, in-memory fallback when storage is blocked.
// Every SDK call is guarded: a missing SDK, a throw or a promise that never
// settles never blocks the game and never leaves an unhandled rejection.
var PLATFORM_BACKEND = (function()
{
    const memory = new Map()
    const listeners = {pause: [], audio: [], adState: []}
    const warnedCalls = new Set()
    let language = null
    let storageWarned = false
    let subscribed = false
    // Last pause state told to the listeners (GamePix may repeat events)
    let paused = false
    // Lifecycle
    let loadingSent = -1
    let loadedPromise = null
    let started = false
    let startWanted = false
    // A run is in play (gameplayStart without gameplayStop)
    let playing = false
    // Ads: the one ad in progress {pausedByAd, onPause(isPaused)} or null;
    // interstitialInFlight stays true until the SDK promise itself settles
    let currentAd = null
    let interstitialInFlight = false
    let lastInterstitialAt = -Infinity

    function sdk()
    {
        try
        {
            return typeof window !== 'undefined' && window.GamePix || null
        }
        catch (e)
        {
            return null
        }
    }

    function warnOnce(name, e)
    {
        if (warnedCalls.has(name))
            return
        warnedCalls.add(name)
        console.warn('GamePix ' + name + ' failed:', e && e.message || e)
    }

    // Calls fn(GamePix); returns fallback without the SDK or on a throw
    function call(name, fn, fallback)
    {
        const gamePix = sdk()
        if (!gamePix)
            return fallback
        try
        {
            return fn(gamePix)
        }
        catch (e)
        {
            warnOnce(name, e)
            return fallback
        }
    }

    // The SDK function at path ('ads.reward') bound to its owner, or null
    function sdkFunction(path)
    {
        return call(path, gamePix =>
        {
            let owner = null
            let value = gamePix
            for (const part of path.split('.'))
            {
                owner = value
                value = value == null ? undefined : value[part]
            }
            return typeof value === 'function' ? value.bind(owner) : null
        }, null)
    }

    // A promise for a possibly-thenable value that never rejects and settles
    // within ms (then resolves timeoutValue)
    function settle(name, value, ms, timeoutValue)
    {
        return new Promise(resolve =>
        {
            const timer = setTimeout(() => resolve(timeoutValue), ms)
            Promise.resolve(value).then(result =>
            {
                clearTimeout(timer)
                resolve(result)
            }, e =>
            {
                warnOnce(name, e)
                clearTimeout(timer)
                resolve(timeoutValue)
            })
        })
    }

    function emit(name, value)
    {
        for (const fn of listeners[name].slice())
        {
            try
            {
                fn(value)
            }
            catch (e)
            {
                console.warn('GamePix ' + name + ' listener failed:', e && e.message || e)
            }
        }
    }

    function setPaused(isPaused)
    {
        if (isPaused === paused)
            return
        paused = isPaused
        emit('pause', isPaused)
        emit('audio', !isPaused)
    }

    function onSdkPause(isPaused)
    {
        if (currentAd)
            currentAd.onPause(isPaused)
        setPaused(isPaused)
    }

    // GamePix.events.on('pause' | 'resume'), once
    function subscribe()
    {
        if (subscribed)
            return
        const on = sdkFunction('events.on')
        if (!on)
            return
        subscribed = true
        call('events.on', () =>
        {
            on('pause', () => onSdkPause(true))
            on('resume', () => onSdkPause(false))
        })
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

    function sendLoading(pct)
    {
        const n = Math.min(100, Math.max(0, Math.floor(Number(pct)) || 0))
        if (n <= loadingSent)
            return
        loadingSent = n
        const loading = sdkFunction('lifecycle.loading')
        if (loading)
            call('lifecycle.loading', () => loading(n))
    }

    function sendGameStart()
    {
        if (started)
            return
        started = true
        const gameStart = sdkFunction('lifecycle.gameStart')
        if (gameStart)
            call('lifecycle.gameStart', () => gameStart())
    }

    // loading(100) then lifecycle.loaded(), once; resolves within loadedTimeoutMs
    function ensureLoaded()
    {
        if (!loadedPromise)
        {
            sendLoading(100)
            const loaded = sdkFunction('lifecycle.loaded')
            const result = loaded ? call('lifecycle.loaded', () => loaded()) : undefined
            loadedPromise = settle('lifecycle.loaded', result, BACKEND.loadedTimeoutMs).then(() => undefined)
            if (startWanted)
                sendGameStart()
        }
        return loadedPromise
    }

    function interstitialMinGapMs()
    {
        return typeof PLATFORM !== 'undefined' && Number.isFinite(PLATFORM.interstitialMinGapMs) ?
            PLATFORM.interstitialMinGapMs : 120000
    }

    // Shows the ad sdkCall() starts and resolves mapResponse(response), or
    // 'failed' on a throw, a rejection or a timeout. Emits adState 'opened'
    // before the call and 'closed' | 'failed' after; a pause the ad caused
    // is lifted before the result resolves. onSettled runs when the SDK
    // promise itself settles (even after a timeout).
    function runAd(name, sdkCall, mapResponse, onSettled)
    {
        return new Promise(resolve =>
        {
            let finished = false
            let graceTimer = null
            const ad = {
                pausedByAd: false,
                onPause(isPaused)
                {
                    if (isPaused)
                    {
                        ad.pausedByAd = true
                        clearTimeout(openTimer)
                        clearTimeout(graceTimer)
                    }
                    else if (ad.pausedByAd)
                    {
                        clearTimeout(graceTimer)
                        graceTimer = setTimeout(() => finish('failed'), BACKEND.adResumeGraceMs)
                    }
                }
            }
            function finish(result)
            {
                if (finished)
                    return
                finished = true
                clearTimeout(openTimer)
                clearTimeout(playTimer)
                clearTimeout(graceTimer)
                if (currentAd === ad)
                    currentAd = null
                if (ad.pausedByAd)
                    setPaused(false)
                emit('adState', result === 'failed' ? 'failed' : 'closed')
                resolve(result)
            }
            const openTimer = setTimeout(() => finish('failed'), BACKEND.adOpenTimeoutMs)
            const playTimer = setTimeout(() => finish('failed'), BACKEND.adPlayingTimeoutMs)
            currentAd = ad
            emit('adState', 'opened')
            let request
            try
            {
                request = Promise.resolve(sdkCall())
            }
            catch (e)
            {
                request = Promise.reject(e)
            }
            request.then(response => mapResponse(response), e =>
            {
                warnOnce(name, e)
                return 'failed'
            }).then(result =>
            {
                if (onSettled)
                    onSettled()
                finish(result)
            })
        })
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
        platformId: 'gamepix',

        // Timeouts (ms) for SDK promises that never settle
        loadedTimeoutMs: 3000,
        adOpenTimeoutMs: 3000,
        adResumeGraceMs: 2000,
        adPlayingTimeoutMs: 120000,

        now()
        {
            return performance.now()
        },

        // The SDK tag is synchronous: window.GamePix exists now or never
        init()
        {
            subscribe()
            language = isoLanguage(call('lang', gamePix => gamePix.lang(), null)) ||
                isoLanguage(navigatorLanguage()) || 'en'
            if (!sdk())
                console.warn('GamePix SDK missing: playing without it')
            return Promise.resolve({environment: sdk() ? 'gamepix' : 'disabled', language})
        },

        isInterstitialSupported()
        {
            return !!sdkFunction('ads.interstitial')
        },

        // GamePix paces ads itself; this adds a min gap and one ad at a time
        isInterstitialDue()
        {
            return BACKEND.isInterstitialSupported() && !interstitialInFlight && !currentAd &&
                performance.now() - lastInterstitialAt >= interstitialMinGapMs()
        },

        // Resolves 'closed' (shown), 'failed' or 'skipped' (no SDK, a run in
        // play, another ad up or one still in flight). Never rejects.
        showInterstitial()
        {
            const interstitial = sdkFunction('ads.interstitial')
            if (!interstitial || playing || interstitialInFlight || currentAd)
                return Promise.resolve('skipped')
            ensureLoaded()
            lastInterstitialAt = performance.now()
            interstitialInFlight = true
            return runAd('ads.interstitial', () => interstitial(),
                response => response && response.success === true ? 'closed' : 'failed',
                () => { interstitialInFlight = false })
        },

        sendMessage()
        {
            return Promise.resolve()
        },

        sendLifecycle()
        {
            return Promise.resolve()
        },

        // Third-party analytics are banned on GamePix
        track()
        {
        },

        startup()
        {
        },

        // The first playable frame: loading(100), then lifecycle.loaded() once
        gameReady()
        {
            return ensureLoaded()
        },

        readiness()
        {
            return {state: sdk() ? 'success' : 'disabled'}
        },

        // Mute comes through the pause event
        isAudioEnabled()
        {
            return !paused
        },

        onPause(fn)
        {
            if (typeof fn !== 'function')
                return
            subscribe()
            listeners.pause.push(fn)
        },

        onAudio(fn)
        {
            if (typeof fn !== 'function')
                return
            subscribe()
            listeners.audio.push(fn)
        },

        onAdState(fn)
        {
            if (typeof fn === 'function')
                listeners.adState.push(fn)
        },

        // GamePix.lifecycle.loading(percent): 0..100, never decreasing
        loadingProgress(percent)
        {
            sendLoading(percent)
        },

        // GamePix.lifecycle.gameStart() once, after lifecycle.loaded()
        gameplayStart()
        {
            playing = true
            startWanted = true
            if (loadedPromise)
                sendGameStart()
        },

        // v3 has no gameplay-stop call; ends the in-play state
        gameplayStop()
        {
            playing = false
        },

        happyMoment()
        {
            const happyMoment = sdkFunction('happyMoment')
            if (happyMoment)
                call('happyMoment', () => happyMoment())
        },

        // True when the GamePix SDK has GamePix.ads.reward()
        isRewardedSupported()
        {
            return !!sdkFunction('ads.reward')
        },

        // GamePix.ads.reward() -> {success}: success -> 'rewarded', no
        // success (closed early, no fill) -> 'closed'; a throw, a rejection
        // or a timeout -> 'failed'; no SDK -> 'unavailable'; another ad up
        // -> 'failed'.
        showRewarded()
        {
            const reward = sdkFunction('ads.reward')
            if (!reward)
                return Promise.resolve('unavailable')
            if (currentAd)
                return Promise.resolve('failed')
            ensureLoaded()
            return runAd('ads.reward', () => reward(),
                response => response && response.success === true ? 'rewarded' : 'closed')
        },

        // GamePix owns banner placement
        showBanner()
        {
            return Promise.resolve()
        },

        hideBanner()
        {
            return Promise.resolve()
        },

        // No leaderboards or achievements in GamePix v3
        submitScore()
        {
            return Promise.resolve(false)
        },

        unlockAchievement()
        {
            return Promise.resolve(false)
        },

        // GamePix.lang(), read by init()
        getLanguage()
        {
            return language
        },

        getPlatformId()
        {
            return BACKEND.platformId
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
                    result[key] = localGet(String(key))
                return result
            },

            // Saves {key: value} as strings in localStorage; true once written
            async setMany(obj)
            {
                for (const key of Object.keys(obj))
                    localSet(String(key), String(obj[key]))
                return true
            }
        }
    }
    return BACKEND
})()
