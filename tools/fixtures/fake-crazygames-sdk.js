// Test double for the CrazyGames HTML5 SDK v3; served in place of
// crazygames-sdk-v3.js by tools/crazygames_harness.py.
// Set window.__cgFake.initHang to make init() never resolve; otherwise
// __cgFake.initResolvedAt records when init() resolved.
(function () {
    const fake = window.__cgFake = Object.assign({
        adOutcome: 'finished',
        adDurationMs: 50,
        adblock: false,
        environment: 'crazygames'
    }, window.__cgFake || {})
    fake.calls = []
    const prefix = '__cgfake:'

    function record(name, args) {
        fake.calls.push({name: name, args: Array.from(args), t: performance.now()})
    }

    function recorded(name, fn) {
        return function () {
            record(name, arguments)
            return fn ? fn.apply(this, arguments) : undefined
        }
    }

    // Callbacks are not cloneable; record only the ad type and callback names.
    function requestAd(type, callbacks) {
        callbacks = callbacks || {}
        record('ad.requestAd', [type, Object.keys(callbacks)])
        setTimeout(function () {
            if (fake.adOutcome === 'error') {
                record('ad.adError', [type])
                if (callbacks.adError) callbacks.adError({code: 'other', message: 'fake ad error'})
                return
            }
            record('ad.adStarted', [type])
            if (callbacks.adStarted) callbacks.adStarted()
            setTimeout(function () {
                record('ad.adFinished', [type])
                if (callbacks.adFinished) callbacks.adFinished()
            }, fake.adDurationMs)
        }, 0)
    }

    window.CrazyGames = {
        SDK: {
            environment: fake.environment,
            init: recorded('init', function () {
                if (fake.initHang) return new Promise(function () {})
                return Promise.resolve().then(function () { fake.initResolvedAt = performance.now() })
            }),
            game: {
                settings: {muteAudio: false, disableChat: false},
                gameplayStart: recorded('game.gameplayStart'),
                gameplayStop: recorded('game.gameplayStop'),
                loadingStart: recorded('game.loadingStart'),
                loadingStop: recorded('game.loadingStop'),
                happytime: recorded('game.happytime')
            },
            ad: {
                requestAd: requestAd,
                hasAdblock: recorded('ad.hasAdblock', function () {
                    return Promise.resolve(Boolean(fake.adblock))
                })
            },
            data: {
                getItem: recorded('data.getItem', function (key) {
                    return localStorage.getItem(prefix + key)
                }),
                setItem: recorded('data.setItem', function (key, value) {
                    localStorage.setItem(prefix + key, String(value))
                }),
                removeItem: recorded('data.removeItem', function (key) {
                    localStorage.removeItem(prefix + key)
                }),
                clear: recorded('data.clear', function () {
                    Object.keys(localStorage)
                        .filter(function (key) { return key.startsWith(prefix) })
                        .forEach(function (key) { localStorage.removeItem(key) })
                })
            }
        }
    }
})()
