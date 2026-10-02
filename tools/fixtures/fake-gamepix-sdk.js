// Test double for the GamePix SDK v3; served in place of gamepix.sdk.js by
// tools/gamepix_harness.py. API shape follows artifacts/TASK-099/probe.json.
// The real SDK is silent on misuse on localhost, so the fake records the
// documented error codes in window.__fakeGamePix.errors (and console.warn).
// Options are read from window.__fakeGamePix before load:
//   reward: 'success' | 'fail' | 'never' | 'throw', rewardDelayMs, lang.
(function () {
    const fake = window.__fakeGamePix = Object.assign({
        reward: 'fail',
        rewardDelayMs: 5,
        lang: 'en'
    }, window.__fakeGamePix || {})
    fake.calls = []
    fake.errors = []
    let loadedCalled = false
    let pendingReward = null

    function record(name, args) {
        fake.calls.push({name: name, args: Array.from(args || [], function (arg) {
            return typeof arg === 'function' ? 'function' : arg
        }), t: performance.now()})
    }

    function error(code) {
        fake.errors.push(code)
        console.warn('[fake GamePix] ' + code)
    }

    function recorded(name, fn) {
        return function () {
            record(name, arguments)
            return fn.apply(this, arguments)
        }
    }

    function isNumber(value) {
        return typeof value === 'number' && isFinite(value)
    }

    function loading() {}

    function loaded() {
        if (loadedCalled) error('LOADED_ALREADY_CALLED')
        loadedCalled = true
        return Promise.resolve({})
    }

    function rewardAd() {
        if (!loadedCalled) {
            error('GAMEPIX_LOADED_NOT_CALLED')
            return Promise.resolve({success: false})
        }
        if (fake.reward === 'throw') throw new Error('fake rewardAd threw')
        if (pendingReward) {
            error('REWARD_AD_CALLED_TWICE')
            pendingReward({success: false,
                           message: 'Reward ad superseded by a new request'})
        }
        return new Promise(function (resolve) {
            let settled = false
            const settle = pendingReward = function (result) {
                if (settled) return
                settled = true
                if (pendingReward === settle) pendingReward = null
                resolve(result)
            }
            if (fake.reward === 'never') return
            setTimeout(function () {
                settle({success: fake.reward === 'success'})
            }, fake.rewardDelayMs)
        })
    }

    function storageArgsOk(args) {
        for (let i = 0; i < args.length; i++) {
            if (typeof args[i] !== 'string') {
                error('KEY_OR_VALUE_FOR_LOCALSTORAGE_NOT_A_STRING')
                return false
            }
        }
        return true
    }

    const storage = {
        getItem: recorded('localStorage.getItem', function (key) {
            return storageArgsOk([key]) ? window.localStorage.getItem(key) : null
        }),
        setItem: recorded('localStorage.setItem', function (key, value) {
            if (storageArgsOk([key, value])) window.localStorage.setItem(key, value)
        }),
        removeItem: recorded('localStorage.removeItem', function (key) {
            if (storageArgsOk([key])) window.localStorage.removeItem(key)
        })
    }

    function numberCall(code) {
        return function (value) {
            if (!isNumber(value)) error(code)
        }
    }

    const on = {pause: false, resume: false, soundOn: false, soundOff: false}

    window.GamePix = {
        loading: recorded('loading', loading),
        loaded: recorded('loaded', loaded),
        rewardAd: recorded('rewardAd', rewardAd),
        localStorage: storage,
        updateScore: recorded('updateScore', numberCall('SCORE_NOT_A_NUMBER')),
        updateLevel: recorded('updateLevel', numberCall('LEVEL_NOT_A_NUMBER')),
        happyMoment: recorded('happyMoment', function () {}),
        lang: recorded('lang', function () { return fake.lang }),
        on: on
    }

    // Test hook: call the game's GamePix.on[name] slot, if it set one.
    fake.fire = function (name) {
        record('fire', [name])
        if (typeof on[name] === 'function') on[name]()
    }
})()
