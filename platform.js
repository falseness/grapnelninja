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
//   loadingProgress/gameplayStart/gameplayStop/happyMoment -> undefined
//   isRewardedSupported -> false        showRewarded -> 'unavailable'
//   showBanner/hideBanner -> undefined  submitScore/unlockAchievement -> false
//   getLanguage -> PLATFORM.language    getPlatformId -> PLATFORM.platformId
// Methods that return promises always resolve (never reject) to the default.
const PLATFORM = (function()
{
    let initPromise = null
    let loadingPct = 0
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
    const REWARDED = ['rewarded', 'closed', 'failed', 'unavailable']

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

        // loadingProgress(pct): integer 0..100, never decreasing; the inner method gets the clamped value
        // Playgama: none (bridge shows its own loader) | GamePix: GamePix.lifecycle.loading(pct) | Y8: none | itch: none
        loadingProgress(pct)
        {
            const n = Math.floor(Number(pct))
            loadingPct = Math.max(loadingPct, Math.min(100, Math.max(0, Number.isFinite(n) ? n : 0)))
            delegate('loadingProgress', [loadingPct], nothing)
        },

        // gameplayStart(level): a run or level becomes playable
        // Playgama: bridge.platform.sendMessage('gameplay_started') | GamePix: GamePix.lifecycle.gameStart() | Y8: none | itch: none
        gameplayStart(level)
        {
            delegate('gameplayStart', [level], nothing)
        },

        // gameplayStop(reason, level): reason is 'pause' | 'death' | 'complete'
        // Playgama: bridge.platform.sendMessage('gameplay_stopped') (+ 'level_completed'/'level_failed') | GamePix: none (lifecycle has no stop) | Y8: none | itch: none
        gameplayStop(reason, level)
        {
            delegate('gameplayStop', [reason, level], nothing)
        },

        // happyMoment(): a celebratory moment (summit, record)
        // Playgama: none | GamePix: GamePix.happyMoment() | Y8: none | itch: none
        happyMoment()
        {
            delegate('happyMoment', [], nothing)
        },

        // isRewardedSupported() -> boolean, false when no rewarded ads exist
        // Playgama: bridge.advertisement.isRewardedSupported | GamePix: true when window.GamePix (ads.reward) | Y8: true when the SDK is ready (showAd reward) | itch: false
        isRewardedSupported()
        {
            return delegate('isRewardedSupported', [], () => false) === true
        },

        // showRewarded(placement) -> Promise<'rewarded' | 'closed' | 'failed' | 'unavailable'>, never rejects; grant only on 'rewarded'
        // Playgama: bridge.advertisement.showRewarded(placement), 'rewarded' on state 'rewarded' | GamePix: GamePix.ads.reward() -> {success} | Y8: showAd({type: 'reward'}) | itch: 'unavailable'
        showRewarded(placement)
        {
            return delegate('showRewarded', [placement], () => 'unavailable', true)
                .then(result => REWARDED.includes(result) ? result : 'unavailable')
        },

        // showBanner(position) -> Promise<void>, never rejects
        // Playgama: bridge.advertisement.showBanner(position) | GamePix: none (no banner API) | Y8: none | itch: none
        showBanner(position)
        {
            return delegate('showBanner', [position], nothing, true).then(nothing)
        },

        // hideBanner() -> Promise<void>, never rejects
        // Playgama: bridge.advertisement.hideBanner() | GamePix: none | Y8: none | itch: none
        hideBanner()
        {
            return delegate('hideBanner', [], nothing, true).then(nothing)
        },

        // submitScore(board, value) -> Promise<boolean>, true once the portal accepted it
        // Playgama: bridge.leaderboards.setScore(board, value) | GamePix: none (false) | Y8: saveLeaderboardScore(board, value) | itch: none (false)
        submitScore(board, value)
        {
            return delegate('submitScore', [board, value], () => false, true).then(ok => ok === true)
        },

        // unlockAchievement(id) -> Promise<boolean>, true once the portal accepted it
        // Playgama: bridge.achievements.unlock({id}) | GamePix: none (false) | Y8: awardAchievement(id) | itch: none (false)
        unlockAchievement(id)
        {
            return delegate('unlockAchievement', [id], () => false, true).then(ok => ok === true)
        },

        // getLanguage() -> 2-letter code, the same value as PLATFORM.language
        // Playgama: bridge.platform.language | GamePix: GamePix.lang() | Y8: navigator.language | itch: navigator.language
        getLanguage()
        {
            const code = delegate('getLanguage', [], () => PLATFORM.language)
            return code === PLATFORM.language ? code : PLATFORM.language
        },

        // getPlatformId() -> backend id string, the same value as PLATFORM.platformId
        // Playgama: 'playgama' (bridge.platform.id for the host) | GamePix: 'gamepix' | Y8: 'y8' | itch: 'itch'
        getPlatformId()
        {
            const id = delegate('getPlatformId', [], () => PLATFORM.platformId)
            return typeof id === 'string' && id ? id : PLATFORM.platformId
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
