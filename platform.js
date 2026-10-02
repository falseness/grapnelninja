// Thin wrapper over the Y8 minimal SDK 2.x. When the SDK is missing, never
// becomes ready, or init throws, rejects or times out, PLATFORM.environment
// is 'disabled' and every call is a safe no-op (rewarded ads report adError).
const PLATFORM = (function()
{
    const initTimeoutMs = 3000

    let sdk = null
    let initPromise = null

    // Resolves once 'y8sdk.ready' fires. A listener added after the SDK has
    // loaded misses the first event, so ask the SDK to emit it again.
    // Rejects at once when the page has loaded without window.y8: 'load'
    // waits for async scripts, so the SDK is blocked or empty.
    function whenReady()
    {
        return new Promise((resolve, reject) =>
        {
            window.addEventListener('y8sdk.ready', () => resolve(), {once: true})
            if (window.y8 && typeof window.y8.emitReadyEvent === 'function')
                window.y8.emitReadyEvent()
            const checkLoaded = () =>
            {
                if (!window.y8)
                    reject(new Error('Y8 SDK not loaded'))
            }
            if (document.readyState === 'complete')
                checkLoaded()
            else
                window.addEventListener('load', checkLoaded, {once: true})
        })
    }

    async function start()
    {
        await whenReady()
        const candidate = window.y8.sdk()
        // init() returns a Promise that resolves to undefined (TASK-089 probe)
        await candidate.init(
            {appId: Y8_CONFIG.appId, autoLogin: false},
            {gameId: Y8_CONFIG.gameId, preloadAdBreaks: 'auto', sound: 'off'})
        return candidate
    }

    async function init()
    {
        let timer
        try
        {
            sdk = await Promise.race([
                start(),
                new Promise((resolve, reject) =>
                {
                    timer = setTimeout(() => reject(new Error('Y8 SDK init timeout')), initTimeoutMs)
                })
            ])
            PLATFORM.environment = 'y8'
        }
        catch (e)
        {
            console.warn('Y8 SDK disabled:', e && e.message)
            sdk = null
            PLATFORM.environment = 'disabled'
        }
        finally
        {
            clearTimeout(timer)
        }
        return PLATFORM.environment
    }

    const PLATFORM =
    {
        environment: 'pending',
        // Watchdog for a rewarded break that never reports an outcome
        rewardTimeoutMs: 15000,

        init()
        {
            if (!initPromise)
                initPromise = init()
            return initPromise
        },

        // Calls exactly one of callbacks.adFinished() / callbacks.adError({code, message});
        // callbacks.adStarted() may run before it when an ad is actually shown.
        requestRewarded(callbacks)
        {
            callbacks = callbacks || {}
            let finished = false
            let viewed = false
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
                    console.warn('Y8 rewarded callback failed', e)
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

            if (!sdk)
            {
                fail('disabled', 'Y8 SDK disabled')
                return
            }
            watchdog = setTimeout(() => fail('timeout', 'Y8 rewarded ad timed out'), PLATFORM.rewardTimeoutMs)
            try
            {
                // The showAd Promise resolves before adBreakDone; only rejection matters
                Promise.resolve(sdk.showAd({
                    type: 'reward',
                    name: 'continue',
                    beforeReward: showAdFn => showAdFn(),
                    beforeAd: () =>
                    {
                        if (!finished)
                            notify('adStarted')
                    },
                    adViewed: () =>
                    {
                        viewed = true
                        finish('adFinished')
                    },
                    adDismissed: () => fail('dismissed', 'Y8 rewarded ad dismissed'),
                    adBreakDone: info =>
                    {
                        const status = info && info.breakStatus
                        if (status !== 'viewed' || !viewed)
                            fail(status || 'unknown', 'Y8 ad break ended: ' + status)
                    }
                })).catch(e => fail('rejected', (e && e.message) || 'Y8 showAd rejected'))
            }
            catch (e)
            {
                fail('exception', (e && e.message) || 'Y8 showAd threw')
            }
        }
    }
    return PLATFORM
})()
