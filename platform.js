// PLATFORM facade: the API the game calls. It holds no SDK or storage code;
// every public method delegates to the same-named inner method of
// PLATFORM_BACKEND (platform/backends/<id>.js, loaded by index.html right
// before this file). To port to a portal (itch.io, GamePix, Y8, Playgama)
// or add an SDK, replace the inner methods in ONE backend file and swap that
// one script tag; nothing else changes. local.js is the default backend.
//
// delegate() catches a throwing, rejecting or missing inner method and
// returns the method's safe default instead (one console.warn per method):
//   now -> performance.now()        init -> {environment: 'local', language: 'en'}
//   isInterstitialSupported -> false    isInterstitialDue -> false
//   showInterstitial -> 'skipped'       sendMessage/sendLifecycle/gameReady -> undefined
//   track/startup/onPause/onAudio/onAdState -> undefined
//   readiness -> {state: 'local'}       isAudioEnabled -> true
//   storage.remoteKnown -> true         storage.onRecovery -> undefined
//   storage.getMany(keys) -> {key: null, ...}    storage.setMany -> false
// Methods that return promises always resolve (never reject) to the default.
const PLATFORM = (function()
{
    let initPromise = null
    const warned = new Set()

    function backend()
    {
        return typeof PLATFORM_BACKEND === 'undefined' ? null : PLATFORM_BACKEND
    }

    function fail(path, e)
    {
        if (warned.has(path))
            return
        warned.add(path)
        console.warn('PLATFORM_BACKEND.' + path + ' failed, using default:', e && e.message || e)
    }

    // Calls PLATFORM_BACKEND.<path>(...args); on a throw or missing method
    // returns fallback(...args). isAsync methods always return a promise and
    // resolve to fallback(...args) when the inner promise rejects.
    function delegate(path, args, fallback, isAsync)
    {
        let result
        try
        {
            let owner = null
            let fn = backend()
            for (const part of path.split('.'))
            {
                owner = fn
                fn = fn == null ? undefined : fn[part]
            }
            if (typeof fn !== 'function')
                throw new Error('missing')
            result = fn.apply(owner, args)
        }
        catch (e)
        {
            fail(path, e)
            const value = fallback(...args)
            return isAsync ? Promise.resolve(value) : value
        }
        if (!isAsync)
            return result
        return Promise.resolve(result).catch(e =>
        {
            fail(path, e)
            return fallback(...args)
        })
    }

    function platformId()
    {
        try
        {
            return backend().platformId || 'local'
        }
        catch (e)
        {
            return 'local'
        }
    }

    const nothing = () => undefined

    const PLATFORM =
    {
        environment: 'pending',
        platformId: platformId(),
        language: 'en',
        buildVersion: '2026-10-14-sandbox-ads-gc',
        initTimeoutMs: 2900,
        interstitialOpenTimeoutMs: 3000,
        interstitialPlayingTimeoutMs: 120000,
        interstitialMinGapMs: 120000,

        now()
        {
            return delegate('now', [], () => performance.now())
        },

        // Resolves the environment once language and environment are set
        init()
        {
            if (!initPromise)
            {
                const fallback = () => ({environment: 'local', language: 'en'})
                initPromise = delegate('init', [], fallback, true).then(result =>
                {
                    PLATFORM.language = result && result.language || 'en'
                    PLATFORM.environment = result && result.environment || 'local'
                    return PLATFORM.environment
                })
            }
            return initPromise
        },

        isInterstitialSupported()
        {
            return delegate('isInterstitialSupported', [], () => false)
        },

        isInterstitialDue(...args)
        {
            return delegate('isInterstitialDue', args, () => false)
        },

        showInterstitial(...args)
        {
            return delegate('showInterstitial', args, () => 'skipped', true)
        },

        sendMessage(...args)
        {
            return delegate('sendMessage', args, nothing, true)
        },

        sendLifecycle(...args)
        {
            return delegate('sendLifecycle', args, nothing, true)
        },

        track(...args)
        {
            delegate('track', args, nothing)
        },

        startup(...args)
        {
            delegate('startup', args, nothing)
        },

        gameReady()
        {
            return delegate('gameReady', [], nothing, true)
        },

        get readiness()
        {
            return delegate('readiness', [], () => ({state: 'local'}))
        },

        isAudioEnabled()
        {
            return delegate('isAudioEnabled', [], () => true)
        },

        onPause(fn)
        {
            delegate('onPause', [fn], nothing)
        },

        onAudio(fn)
        {
            delegate('onAudio', [fn], nothing)
        },

        onAdState(fn)
        {
            delegate('onAdState', [fn], nothing)
        },

        storage:
        {
            get remoteKnown()
            {
                return delegate('storage.remoteKnown', [], () => true)
            },

            onRecovery(fn)
            {
                delegate('storage.onRecovery', [fn], nothing)
            },

            // Resolves {key: string | null}
            getMany(keys)
            {
                const fallback = keys => Object.fromEntries(Array.from(keys || [], key => [key, null]))
                return delegate('storage.getMany', [keys], fallback, true)
            },

            // Saves {key: value} as strings; true once written
            setMany(obj)
            {
                return delegate('storage.setMany', [obj], () => false, true)
            }
        }
    }
    return PLATFORM
})()
