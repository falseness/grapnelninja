// Thin wrapper over the CrazyGames HTML5 SDK v3. When the SDK is missing,
// fails to init or times out, CG.environment is 'disabled' and every call
// is a safe no-op (data falls back to localStorage).
const CG = (function()
{
    const initTimeoutMs = 3000

    let sdk = null
    let loading = false
    // Never send the same gameplay event twice in a row
    let gameplayActive = false

    function call(fn)
    {
        if (!sdk)
            return undefined
        try
        {
            return fn(sdk)
        }
        catch (e)
        {
            console.warn('CrazyGames SDK call failed', e)
            return undefined
        }
    }

    const CG =
    {
        environment: 'pending',

        async init()
        {
            const candidate = window.CrazyGames && window.CrazyGames.SDK
            if (!candidate)
            {
                CG.environment = 'disabled'
                return CG.environment
            }
            let timer
            try
            {
                await Promise.race([
                    candidate.init(),
                    new Promise((resolve, reject) =>
                    {
                        timer = setTimeout(() => reject(new Error('CrazyGames SDK init timeout')), initTimeoutMs)
                    })
                ])
                sdk = candidate
                CG.environment = sdk.environment
            }
            catch (e)
            {
                console.warn('CrazyGames SDK disabled:', e && e.message)
                CG.environment = 'disabled'
            }
            finally
            {
                clearTimeout(timer)
            }
            // loadingStart() may have been requested before init finished
            if (loading)
                call(s => s.game.loadingStart())
            return CG.environment
        },

        gameplayStart()
        {
            if (gameplayActive)
                return
            gameplayActive = true
            call(s => s.game.gameplayStart())
        },
        gameplayStop()
        {
            if (!gameplayActive)
                return
            gameplayActive = false
            call(s => s.game.gameplayStop())
        },
        loadingStart()
        {
            loading = true
            call(s => s.game.loadingStart())
        },
        loadingStop()
        {
            if (!loading)
                return
            loading = false
            call(s => s.game.loadingStop())
        },

        data:
        {
            getItem(key)
            {
                return sdk ? call(s => s.data.getItem(key)) : localStorage.getItem(key)
            },
            setItem(key, value)
            {
                if (sdk)
                    call(s => s.data.setItem(key, value))
                else
                    localStorage.setItem(key, value)
            },
            removeItem(key)
            {
                if (sdk)
                    call(s => s.data.removeItem(key))
                else
                    localStorage.removeItem(key)
            }
        },

        requestAd(type, callbacks)
        {
            if (!sdk)
            {
                if (callbacks && callbacks.adError)
                    callbacks.adError({code: 'unfilled', message: 'CrazyGames SDK disabled'})
                return
            }
            call(s => s.ad.requestAd(type, callbacks))
        },
        async hasAdblock()
        {
            if (!sdk)
                return false
            try
            {
                return await sdk.ad.hasAdblock()
            }
            catch (e)
            {
                return false
            }
        }
    }
    return CG
})()
