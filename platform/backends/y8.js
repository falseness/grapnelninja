// Y8 platform backend (ported, TASK-858). Y8 minimal SDK 2.x (window.y8.sdk()).
// Docs: https://docs.y8.com/sdk/intro/ , https://docs.y8.com/sdk/advertising/
// Script tag: <script src="https://cdn.y8.com/minimal-sdk/2-0/y8.min.js" async></script> (before platform/backends/y8.js; wait for the y8sdk.ready event)
// Self-contained: it does not call LOCAL_PLATFORM_BACKEND (local.js still
// loads first in a build, see docs/platform-sdk.md, but nothing here uses it).
// - init: waits for the async SDK (window.y8 already there, the y8sdk.ready
//   event or the script tag's load; a script error or a load without
//   window.y8 gives up at once, else readyTimeoutMs), then
//   sdk.init({appId, autoLogin: false}, {gameId}) with BUILD_CONFIG.y8 ids,
//   at most initTimeoutMs. A missing SDK, a throw, a rejection or a timeout
//   -> environment 'disabled' (no ads, free go back); the game always plays.
// - guest play: never logs in; localStorage (memory fallback) is the save of
//   record. Only when a Y8 user is signed in (sdk.getUser()) getMany fills
//   keys missing locally from sdk.loadData({key}) and setMany mirrors writes
//   to sdk.saveData({key, value}), at most 1 write per key per 5 s.
// - isBlacklisted(): asked once after init (async, at most
//   blacklistTimeoutMs); true disables interstitials and rewarded ads. Ads
//   wait for the pending answer; a failed or timed-out check allows ads.
// - ads: interstitial = sdk.showAd({type: 'next'}) only at natural breaks
//   (refused while a run is in play: gameplayStart without gameplayStop), at
//   most one in flight, min gap PLATFORM.interstitialMinGapMs. adBreakDone
//   'viewed' | 'dismissed' -> 'closed'; other statuses, a throw or a
//   rejection -> 'failed'. Rewarded: sdk.showAd({type: 'reward'}) ->
//   'rewarded' only when adViewed fired. A break that never starts (no
//   beforeAd / beforeReward / adBreakDone within adOpenTimeoutMs) or never
//   ends (adPlayingTimeoutMs) -> 'failed'.
// - pause: window blur or a hidden document -> onPause fn(true) and onAudio
//   fn(false) (Y8 requires pause AND mute on blur); focus with a visible
//   document -> fn(false) / fn(true). A blur while our own ad is up (the ad
//   iframe takes focus) is ignored and forgotten when the ad ends.
// - no leaderboards / achievements configured on Y8: resolve false.
// - track/startup: no-ops (GameAnalytics ships on itch.io only).
// Every SDK call is guarded: a missing SDK, a throw or a promise that never
// settles never blocks the game and never leaves an unhandled rejection.
var PLATFORM_BACKEND = (function()
{
    const SDK_SRC = 'cdn.y8.com/minimal-sdk/'
    const memory = new Map()
    const listeners = {pause: [], audio: [], adState: []}
    const warnedCalls = new Set()
    let language = null
    let storageWarned = false
    // The initialized SDK object, or null (missing, not ready, init failed)
    let sdk = null
    let initPromise = null
    // isBlacklisted(): 'unknown' (not asked yet or pending), 'clear', 'blocked'
    let blacklist = 'unknown'
    let blacklistPromise = Promise.resolve()
    // Pause: window blurred, document hidden, last state told to listeners
    let watching = false
    let blurred = false
    let hidden = false
    let paused = false
    // A run is in play (gameplayStart without gameplayStop)
    let playing = false
    // The one ad up {type} or null; interstitialInFlight stays true until
    // the break itself ends (adBreakDone, a throw or a rejection)
    let currentAd = null
    let interstitialInFlight = false
    let lastInterstitialAt = -Infinity
    // Remote save mirror (signed in only): key -> {value, timer, lastAt}
    const remoteWrites = new Map()

    function warnOnce(name, e)
    {
        if (warnedCalls.has(name))
            return
        warnedCalls.add(name)
        console.warn('Y8 ' + name + ' failed:', e && e.message || e)
    }

    // window.y8.sdk() as the SDK script defines it, or null
    function rawSdk()
    {
        try
        {
            const y8 = typeof window === 'undefined' ? undefined : window.y8
            if (!y8 || typeof y8.sdk !== 'function')
                return null
            const candidate = y8.sdk()
            return candidate && typeof candidate === 'object' ? candidate : null
        }
        catch (e)
        {
            warnOnce('y8.sdk', e)
            return null
        }
    }

    // sdk.<name> bound to sdk, or null (no SDK, not a function, getter throws)
    function sdkFunction(name)
    {
        if (!sdk)
            return null
        try
        {
            const fn = sdk[name]
            return typeof fn === 'function' ? fn.bind(sdk) : null
        }
        catch (e)
        {
            warnOnce(name, e)
            return null
        }
    }

    // A promise for fn() (a value, a thenable or a throw) that never rejects
    // and settles within ms; resolves {ok, value} or {ok: false} on a throw,
    // a rejection or the timeout
    function guarded(name, fn, ms)
    {
        return new Promise(resolve =>
        {
            let done = false
            const finish = result =>
            {
                if (done)
                    return
                done = true
                clearTimeout(timer)
                resolve(result)
            }
            const timer = setTimeout(() =>
            {
                warnOnce(name + ' timeout', new Error('no answer within ' + ms + ' ms'))
                finish({ok: false, timeout: true})
            }, ms)
            let value
            try
            {
                value = fn()
            }
            catch (e)
            {
                warnOnce(name, e)
                finish({ok: false})
                return
            }
            Promise.resolve(value).then(v => finish({ok: true, value: v}), e =>
            {
                warnOnce(name, e)
                finish({ok: false})
            })
        })
    }

    function buildIds()
    {
        try
        {
            const y8 = typeof BUILD_CONFIG !== 'undefined' && BUILD_CONFIG && BUILD_CONFIG.y8 || {}
            return {appId: String(y8.appId || ''), gameId: String(y8.gameId || '')}
        }
        catch (e)
        {
            return {appId: '', gameId: ''}
        }
    }

    // Resolves once the async SDK script has run (or can never run)
    function waitForSdkScript()
    {
        return new Promise(resolve =>
        {
            let settled = false
            let timer = null
            const tags = []
            function finish()
            {
                if (settled)
                    return
                settled = true
                clearTimeout(timer)
                window.removeEventListener('y8sdk.ready', finish)
                for (const tag of tags)
                {
                    tag.removeEventListener('load', finish)
                    tag.removeEventListener('error', finish)
                }
                resolve()
            }
            if (rawSdk())
                return finish()
            timer = setTimeout(finish, BACKEND.readyTimeoutMs)
            window.addEventListener('y8sdk.ready', finish)
            try
            {
                for (const tag of document.querySelectorAll('script[src]'))
                {
                    if (String(tag.src).indexOf(SDK_SRC) < 0)
                        continue
                    tags.push(tag)
                    tag.addEventListener('load', finish)
                    tag.addEventListener('error', finish)
                }
            }
            catch (e)
            {
                warnOnce('script tag', e)
            }
        })
    }

    async function initSdk()
    {
        await waitForSdkScript()
        const candidate = rawSdk()
        if (!candidate)
        {
            console.warn('Y8 SDK missing: playing without it')
            return null
        }
        const ids = buildIds()
        if (!ids.appId || !ids.gameId)
            console.warn('Y8 build ids missing in BUILD_CONFIG.y8')
        let init = null
        try
        {
            init = typeof candidate.init === 'function' ? candidate.init.bind(candidate) : null
        }
        catch (e)
        {
            warnOnce('init', e)
        }
        if (!init)
        {
            console.warn('Y8 SDK has no init(): playing without it')
            return null
        }
        const result = await guarded('init', () => init({appId: ids.appId, autoLogin: false}, {gameId: ids.gameId}),
            BACKEND.initTimeoutMs)
        if (!result.ok)
        {
            console.warn('Y8 SDK init failed: playing without it')
            return null
        }
        return candidate
    }

    // sdk.isBlacklisted() once; 'blocked' only on a true answer
    function checkBlacklist()
    {
        const isBlacklisted = sdkFunction('isBlacklisted')
        if (!isBlacklisted)
        {
            blacklist = 'clear'
            return Promise.resolve()
        }
        return guarded('isBlacklisted', () => isBlacklisted(), BACKEND.blacklistTimeoutMs).then(result =>
        {
            blacklist = result.ok && result.value === true ? 'blocked' : 'clear'
            if (blacklist === 'blocked')
                console.warn('Y8 isBlacklisted(): ads disabled on this site')
        })
    }

    function adsAllowed()
    {
        return !!sdkFunction('showAd') && blacklist !== 'blocked'
    }

    // The signed-in Y8 user, or null (guest)
    function signedIn()
    {
        const getUser = sdkFunction('getUser')
        if (!getUser)
            return false
        try
        {
            return !!getUser()
        }
        catch (e)
        {
            warnOnce('getUser', e)
            return false
        }
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
                console.warn('Y8 ' + name + ' listener failed:', e && e.message || e)
            }
        }
    }

    function documentHidden()
    {
        try
        {
            return document.visibilityState === 'hidden'
        }
        catch (e)
        {
            return false
        }
    }

    // Tells the listeners when the paused state changes (blur while our ad
    // is up does not count)
    function update()
    {
        const now = hidden || (blurred && !currentAd)
        if (now === paused)
            return
        paused = now
        emit('pause', paused)
        emit('audio', !paused)
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

    function interstitialMinGapMs()
    {
        return typeof PLATFORM !== 'undefined' && Number.isFinite(PLATFORM.interstitialMinGapMs) ?
            PLATFORM.interstitialMinGapMs : 120000
    }

    // Runs one sdk.showAd(options) break. hooks(ad) returns the extra
    // showAd callbacks; ad.start() marks the break as started, ad.end(result)
    // ends it. Emits adState 'opened' before and 'closed' | 'failed' after.
    // onBreakOver runs when the break itself is over (adBreakDone, a throw or
    // a rejection), even after a timeout.
    function runAd(name, options, hooks, onBreakOver)
    {
        const showAd = sdkFunction('showAd')
        return new Promise(resolve =>
        {
            let finished = false
            let breakOver = false
            let timer = null
            const ad = {
                start()
                {
                    if (finished)
                        return
                    clearTimeout(timer)
                    timer = setTimeout(() => finish('failed'), BACKEND.adPlayingTimeoutMs)
                },
                end(result)
                {
                    over()
                    finish(result)
                }
            }
            function over()
            {
                if (breakOver)
                    return
                breakOver = true
                if (onBreakOver)
                    onBreakOver()
            }
            function finish(result)
            {
                if (finished)
                    return
                finished = true
                clearTimeout(timer)
                if (currentAd === ad)
                    currentAd = null
                // The ad iframe may have taken focus: that blur is not the player's
                blurred = false
                hidden = documentHidden()
                update()
                emit('adState', result === 'failed' ? 'failed' : 'closed')
                resolve(result)
            }
            timer = setTimeout(() => finish('failed'), BACKEND.adOpenTimeoutMs)
            currentAd = ad
            emit('adState', 'opened')
            let request
            try
            {
                request = Promise.resolve(showAd(Object.assign({}, options, hooks(ad))))
            }
            catch (e)
            {
                request = Promise.reject(e)
            }
            request.catch(e =>
            {
                warnOnce(name, e)
                ad.end('failed')
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

    // Mirrors key=value to sdk.saveData when signed in: the latest value per
    // key, at most one write per key per remoteWriteGapMs
    function remoteSave(key, value)
    {
        if (!signedIn())
            return
        const saveData = sdkFunction('saveData')
        if (!saveData)
            return
        const entry = remoteWrites.get(key) || {value: null, timer: null, lastAt: -Infinity}
        remoteWrites.set(key, entry)
        entry.value = value
        if (entry.timer)
            return
        const write = () =>
        {
            entry.timer = null
            entry.lastAt = performance.now()
            const latest = entry.value
            guarded('saveData', () => saveData({key, value: latest}), BACKEND.remoteTimeoutMs)
        }
        const wait = entry.lastAt + BACKEND.remoteWriteGapMs - performance.now()
        if (wait <= 0)
            write()
        else
            entry.timer = setTimeout(write, wait)
    }

    const BACKEND = {
        platformId: 'y8',

        // Timeouts (ms) for an SDK that never answers
        readyTimeoutMs: 3000,
        initTimeoutMs: 3000,
        blacklistTimeoutMs: 6000,
        adOpenTimeoutMs: 3000,
        adPlayingTimeoutMs: 120000,
        remoteTimeoutMs: 3000,
        // Y8 saveData allows 1 write per key per 5 s
        remoteWriteGapMs: 5000,

        now()
        {
            return performance.now()
        },

        // Resolves {environment: 'y8' | 'disabled', language}; never rejects
        init()
        {
            if (!initPromise)
            {
                watch()
                language = isoLanguage(navigatorLanguage()) || 'en'
                initPromise = initSdk().catch(e =>
                {
                    warnOnce('init', e)
                    return null
                }).then(candidate =>
                {
                    sdk = candidate
                    blacklistPromise = sdk ? checkBlacklist() : Promise.resolve()
                    return {environment: sdk ? 'y8' : 'disabled', language}
                })
            }
            return initPromise
        },

        isInterstitialSupported()
        {
            return adsAllowed()
        },

        // Y8 caps ads itself too; this adds the min gap and one ad at a time
        isInterstitialDue()
        {
            return adsAllowed() && !playing && !interstitialInFlight && !currentAd &&
                performance.now() - lastInterstitialAt >= interstitialMinGapMs()
        },

        // sdk.showAd({type: 'next'}) at a natural break. Resolves 'closed'
        // (viewed or dismissed), 'failed' or 'skipped' (no SDK, blacklisted,
        // a run in play, another ad up or one still in flight). Never rejects.
        async showInterstitial(placement)
        {
            if (!adsAllowed() || playing || interstitialInFlight || currentAd)
                return 'skipped'
            interstitialInFlight = true
            await blacklistPromise
            if (!adsAllowed() || playing || currentAd)
            {
                interstitialInFlight = false
                return 'skipped'
            }
            lastInterstitialAt = performance.now()
            return runAd('showAd next', {type: 'next', name: placement || 'game_over'}, ad => ({
                beforeAd: () => ad.start(),
                adBreakDone: info =>
                {
                    const status = info && info.breakStatus
                    ad.end(status === 'viewed' || status === 'dismissed' ? 'closed' : 'failed')
                },
            }), () => { interstitialInFlight = false })
        },

        sendMessage()
        {
            return Promise.resolve()
        },

        sendLifecycle()
        {
            return Promise.resolve()
        },

        // GameAnalytics ships on itch.io only
        track()
        {
        },

        startup()
        {
        },

        // Y8 has no ready call
        gameReady()
        {
            return Promise.resolve()
        },

        readiness()
        {
            return {state: sdk ? 'success' : 'disabled'}
        },

        // Muted while paused (blur or hidden)
        isAudioEnabled()
        {
            return !paused
        },

        onPause(fn)
        {
            if (typeof fn !== 'function')
                return
            watch()
            listeners.pause.push(fn)
        },

        onAudio(fn)
        {
            if (typeof fn !== 'function')
                return
            watch()
            listeners.audio.push(fn)
        },

        onAdState(fn)
        {
            if (typeof fn === 'function')
                listeners.adState.push(fn)
        },

        loadingProgress()
        {
        },

        gameplayStart()
        {
            playing = true
        },

        gameplayStop()
        {
            playing = false
        },

        happyMoment()
        {
        },

        // True when the SDK is initialized and the site is not blacklisted
        isRewardedSupported()
        {
            return adsAllowed()
        },

        // sdk.showAd({type: 'reward'}) settles once the break is over
        // (afterAd or adBreakDone): 'rewarded' only when adViewed fired,
        // 'closed' when adDismissed fired (closed early), else 'failed' (no
        // ad shown: noAdPreloaded, frequencyCapped, timeout, error, a throw, a
        // rejection, a break that never starts or never ends, another ad up);
        // no SDK or blacklisted -> 'unavailable'.
        async showRewarded(placement)
        {
            if (!adsAllowed())
                return 'unavailable'
            if (currentAd)
                return 'failed'
            await blacklistPromise
            if (!adsAllowed())
                return 'unavailable'
            if (currentAd)
                return 'failed'
            let viewed = false
            let dismissed = false
            return runAd('showAd reward', {type: 'reward', name: placement || 'reward'}, ad =>
            {
                const finish = () => ad.end(viewed ? 'rewarded' : dismissed ? 'closed' : 'failed')
                return {
                    beforeReward: showAdFn =>
                    {
                        ad.start()
                        try
                        {
                            showAdFn()
                        }
                        catch (e)
                        {
                            warnOnce('beforeReward', e)
                            ad.end('failed')
                        }
                    },
                    beforeAd: () => ad.start(),
                    adViewed: () => { viewed = true },
                    adDismissed: () => { dismissed = true },
                    afterAd: () => { if (viewed || dismissed) finish() },
                    adBreakDone: info =>
                    {
                        if (info && info.breakStatus === 'dismissed' && !viewed)
                            dismissed = true
                        finish()
                    },
                }
            })
        },

        // Y8 has no banner API in this game
        showBanner()
        {
            return Promise.resolve()
        },

        hideBanner()
        {
            return Promise.resolve()
        },

        // No Y8 leaderboard tables or achievements are configured
        submitScore()
        {
            return Promise.resolve(false)
        },

        unlockAchievement()
        {
            return Promise.resolve(false)
        },

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

            onRecovery()
            {
            },

            // {key: string | null} from localStorage; signed in, keys missing
            // locally are filled from sdk.loadData({key})
            async getMany(keys)
            {
                const result = {}
                for (const key of keys)
                    result[key] = localGet(String(key))
                const loadData = signedIn() ? sdkFunction('loadData') : null
                if (!loadData)
                    return result
                const missing = Object.keys(result).filter(key => result[key] === null)
                await Promise.all(missing.map(key =>
                    guarded('loadData', () => loadData({key}), BACKEND.remoteTimeoutMs).then(answer =>
                    {
                        if (answer.ok && answer.value !== null && answer.value !== undefined)
                        {
                            const value = typeof answer.value === 'string' ? answer.value : JSON.stringify(answer.value)
                            result[key] = value
                            localSet(key, value)
                        }
                    })))
                return result
            },

            // Saves {key: value} as strings in localStorage (true once
            // written); signed in, mirrors them to sdk.saveData
            async setMany(obj)
            {
                for (const key of Object.keys(obj))
                {
                    const value = String(obj[key])
                    localSet(String(key), value)
                    remoteSave(String(key), value)
                }
                return true
            }
        }
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

    return BACKEND
})()
