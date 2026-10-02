// Thin wrapper over the GamePix SDK v3. The SDK tag is synchronous, so
// window.GamePix either exists when this script runs or never will. Without
// it PLATFORM.environment is 'disabled' and every call is a safe no-op
// (rewarded ads report adError, storage falls back to window.localStorage).
const PLATFORM = (function()
{
    let sdk = null
    let initPromise = null
    let loadedPromise = null
    // The pending GamePix.rewardAd() Promise, kept until it settles even if
    // the watchdog gave up: a second rewardAd() would supersede it
    // (REWARD_AD_CALLED_TWICE).
    let rewardInFlight = false

    function detect()
    {
        if (initPromise)
            return
        sdk = window.GamePix || null
        PLATFORM.environment = sdk ? 'gamepix' : 'disabled'
        if (!sdk)
            console.warn('GamePix SDK disabled: window.GamePix missing')
        initPromise = Promise.resolve(PLATFORM.environment)
    }

    // Runs fn(sdk) when enabled; returns fallback when disabled or on throw
    function call(name, fn, fallback)
    {
        detect()
        if (!sdk)
            return fallback
        try
        {
            return fn(sdk)
        }
        catch (e)
        {
            console.warn('GamePix ' + name + ' failed', e)
            return fallback
        }
    }

    function storageBackend()
    {
        detect()
        return (sdk && sdk.localStorage) || window.localStorage
    }

    function storageCall(name, fallback, args)
    {
        try
        {
            const backend = storageBackend()
            return backend[name].apply(backend, args.map(String))
        }
        catch (e)
        {
            console.warn('GamePix storage ' + name + ' failed', e)
            return fallback
        }
    }

    const PLATFORM =
    {
        environment: 'pending',
        // Watchdog for a rewarded ad that never settles. GamePix has no
        // ad-started callback, so a single limit must cover a full video.
        rewardPlayingTimeoutMs: 120000,

        init()
        {
            detect()
            return initPromise
        },

        // pct is clamped to an integer 0..100
        loading(pct)
        {
            let n = Math.round(Number(pct))
            if (isNaN(n))
                n = 0
            n = Math.min(100, Math.max(0, n))
            call('loading', s => s.loading(n))
        },

        // Calls GamePix.loaded() once; later calls return the same Promise.
        // Always resolves, even when the SDK throws or rejects.
        loaded()
        {
            if (!loadedPromise)
            {
                loadedPromise = Promise.resolve(call('loaded', s => s.loaded()))
                    .catch(e => console.warn('GamePix loaded rejected', e))
            }
            return loadedPromise
        },

        // Calls exactly one of callbacks.adFinished() / callbacks.adError({code, message});
        // callbacks.adStarted() runs right before GamePix.rewardAd().
        requestRewarded(callbacks)
        {
            callbacks = callbacks || {}
            let finished = false
            let watchdog = null

            function notify(name, arg)
            {
                if (typeof callbacks[name] !== 'function')
                    return
                try
                {
                    callbacks[name](arg)
                }
                catch (e)
                {
                    console.warn('GamePix rewarded callback failed', e)
                }
            }
            function finish(name, arg)
            {
                if (finished)
                    return
                finished = true
                clearTimeout(watchdog)
                notify(name, arg)
            }
            function fail(code, message)
            {
                finish('adError', {code: code, message: message})
            }

            detect()
            if (!sdk)
            {
                fail('disabled', 'GamePix SDK disabled')
                return
            }
            if (!loadedPromise)
            {
                fail('not-loaded', 'PLATFORM.loaded() was not called')
                return
            }
            if (rewardInFlight)
            {
                fail('busy', 'GamePix rewarded ad already in flight')
                return
            }
            rewardInFlight = true
            watchdog = setTimeout(() => fail('timeout', 'GamePix rewarded ad timed out'),
                PLATFORM.rewardPlayingTimeoutMs)
            notify('adStarted')
            let result
            try
            {
                result = sdk.rewardAd()
            }
            catch (e)
            {
                rewardInFlight = false
                fail('exception', (e && e.message) || 'GamePix rewardAd threw')
                return
            }
            Promise.resolve(result).then(res =>
            {
                rewardInFlight = false
                if (res && res.success === true)
                    finish('adFinished')
                else
                    fail('unavailable', (res && res.message) || 'GamePix rewarded ad not available')
            }, e =>
            {
                rewardInFlight = false
                fail('rejected', (e && e.message) || 'GamePix rewardAd rejected')
            })
        },

        // GamePix.localStorage when enabled, window.localStorage otherwise.
        // Keys and values are coerced to strings; never throws.
        storage:
        {
            getItem(key)
            {
                return storageCall('getItem', null, [key])
            },
            setItem(key, value)
            {
                storageCall('setItem', undefined, [key, value])
            },
            removeItem(key)
            {
                storageCall('removeItem', undefined, [key])
            }
        },

        // Only finite non-negative integers are forwarded
        updateScore(n)
        {
            if (Number.isInteger(n) && n >= 0)
                call('updateScore', s => s.updateScore(n))
        },

        happyMoment()
        {
            call('happyMoment', s => s.happyMoment())
        },

        onPause(fn)
        {
            setHandler('pause', fn)
        },

        onResume(fn)
        {
            setHandler('resume', fn)
        }
    }

    function setHandler(name, fn)
    {
        if (typeof fn !== 'function')
            return
        call('on.' + name, s =>
        {
            s.on[name] = () =>
            {
                try
                {
                    fn()
                }
                catch (e)
                {
                    console.warn('GamePix on.' + name + ' handler failed', e)
                }
            }
        })
    }

    return PLATFORM
})()
