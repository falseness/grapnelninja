// Test double for Playgama Bridge v2; served in place of
// https://bridge.playgama.com/v2/stable/playgama-bridge.js by
// tools/playgama_harness.py. Every member exists on the real Bridge 2.3.0
// (artifacts/TASK-114/probe.json surface/event_names).
// Options are read from window.__fakeBridge before load:
//   init: 'resolve' | 'reject' | 'never', initDelayMs,
//   platformId, language, isAudioEnabled, isPaused,
//   interstitialSupported, rewardedSupported, stateDelayMs,
//   interstitialSeq, rewardedSeq: arrays of states or {state, delayMs};
//   a sequence without 'closed'/'failed' never ends.
// Real-Bridge behaviour kept: after an interstitial closes, showInterstitial
// fails until minimumDelayBetweenInterstitial seconds have passed.
// Misuse (bridge calls before initialize resolved, a second showRewarded
// while one is in progress, bad storage arguments) lands in errors.
(function () {
    const fake = window.__fakeBridge = Object.assign({
        init: 'resolve',
        initDelayMs: 0,
        platformId: 'mock',
        language: 'en',
        isAudioEnabled: true,
        isPaused: false,
        interstitialSupported: true,
        rewardedSupported: true,
        stateDelayMs: 20,
        interstitialSeq: ['loading', 'opened', 'closed'],
        rewardedSeq: ['loading', 'opened', 'rewarded', 'closed']
    }, window.__fakeBridge || {})
    fake.calls = []
    fake.errors = []
    const STORAGE_KEY = '__fakeBridgeStorage'
    const TERMINAL = ['closed', 'failed']
    const EVENT_NAME = {
        INTERSTITIAL_STATE_CHANGED: 'interstitial_state_changed',
        REWARDED_STATE_CHANGED: 'rewarded_state_changed',
        AUDIO_STATE_CHANGED: 'audio_state_changed',
        PAUSE_STATE_CHANGED: 'pause_state_changed'
    }
    let initialized = false
    let initPromise = null

    function cloneable(arg) {
        if (typeof arg === 'function') return 'function'
        if (arg === undefined) return 'undefined'
        try { return JSON.parse(JSON.stringify(arg)) } catch (e) { return String(arg) }
    }

    function record(name, args) {
        fake.calls.push({name: name, args: Array.from(args || [], cloneable),
                         t: performance.now()})
    }

    function error(name, message) {
        fake.errors.push({name: name, message: message, t: performance.now()})
    }

    function checkInit(name) {
        if (!initialized) error(name, 'called before bridge.initialize() resolved')
    }

    // Wrap a method: record it and flag calls made before initialization.
    function method(name, fn) {
        return function () {
            record(name, arguments)
            checkInit(name)
            return fn.apply(this, arguments)
        }
    }

    // Define a getter that flags reads made before initialization.
    function getter(target, prop, name, read) {
        Object.defineProperty(target, prop, {enumerable: true, get: function () {
            checkInit(name)
            return read()
        }})
    }

    function emitter() {
        const listeners = {}
        return {
            listeners: listeners,
            on: function (event, cb) {
                (listeners[event] = listeners[event] || []).push(cb)
            },
            off: function (event, cb) {
                listeners[event] = (listeners[event] || []).filter(function (f) {
                    return f !== cb
                })
            },
            emit: function (event, value) {
                (listeners[event] || []).slice().forEach(function (cb) { cb(value) })
            }
        }
    }

    // platform
    const platformEvents = emitter()
    const platform = {}
    getter(platform, 'id', 'platform.id', function () { return fake.platformId })
    getter(platform, 'language', 'platform.language', function () { return fake.language })
    getter(platform, 'isAudioEnabled', 'platform.isAudioEnabled',
           function () { return fake.isAudioEnabled })
    getter(platform, 'isPaused', 'platform.isPaused', function () { return fake.isPaused })
    platform.sendMessage = method('platform.sendMessage', function () {
        return Promise.resolve()
    })
    platform.on = method('platform.on', platformEvents.on)
    platform.off = method('platform.off', platformEvents.off)

    // storage: in-memory map mirrored to sessionStorage so reloads keep it.
    // Like the real mock, strings are stored raw and get() JSON-parses them.
    function loadStore() {
        try { return JSON.parse(sessionStorage.getItem(STORAGE_KEY)) || {} } catch (e) { return {} }
    }
    function saveStore(store) {
        sessionStorage.setItem(STORAGE_KEY, JSON.stringify(store))
    }
    function badKeys(name, keys) {
        if (Array.isArray(keys)) return false
        error(name, 'keys must be an array, got ' + typeof keys)
        return true
    }
    const storage = {
        get: method('storage.get', function (keys) {
            if (badKeys('storage.get', keys)) return Promise.reject(new Error('bad keys'))
            const store = loadStore()
            return Promise.resolve(keys.map(function (key) {
                if (!(key in store)) return null
                try { return JSON.parse(store[key]) } catch (e) { return store[key] }
            }))
        }),
        set: method('storage.set', function (keys, values) {
            if (badKeys('storage.set', keys)) return Promise.reject(new Error('bad keys'))
            if (!Array.isArray(values) || values.length !== keys.length) {
                error('storage.set', 'values must be an array as long as keys')
                return Promise.reject(new Error('bad values'))
            }
            const store = loadStore()
            keys.forEach(function (key, i) {
                const value = values[i]
                store[key] = typeof value === 'string' ? value : JSON.stringify(value)
            })
            saveStore(store)
            return Promise.resolve()
        }),
        delete: method('storage.delete', function (keys) {
            if (badKeys('storage.delete', keys)) return Promise.reject(new Error('bad keys'))
            const store = loadStore()
            keys.forEach(function (key) { delete store[key] })
            saveStore(store)
            return Promise.resolve()
        })
    }

    // advertisement
    const adEvents = emitter()
    const ads = {
        interstitial: {state: 'closed', event: EVENT_NAME.INTERSTITIAL_STATE_CHANGED},
        rewarded: {state: 'closed', event: EVENT_NAME.REWARDED_STATE_CHANGED}
    }
    let minimumDelay = 60
    let interstitialCooldownUntil = 0

    function setState(kind, state) {
        const ad = ads[kind]
        ad.state = state
        record(kind + ':' + state, [])
        if (kind === 'interstitial' && state === 'closed' && minimumDelay > 0) {
            interstitialCooldownUntil = performance.now() + minimumDelay * 1000
        }
        adEvents.emit(ad.event, state)
    }

    function inProgress(kind) {
        return ['loading', 'opened', 'rewarded'].indexOf(ads[kind].state) >= 0
    }

    function play(kind, seq) {
        let delay = 0
        seq.forEach(function (step) {
            const state = typeof step === 'string' ? step : step.state
            delay += typeof step === 'string' || step.delayMs === undefined
                ? fake.stateDelayMs : step.delayMs
            setTimeout(function () { setState(kind, state) }, delay)
        })
    }

    const advertisement = {}
    getter(advertisement, 'isInterstitialSupported', 'advertisement.isInterstitialSupported',
           function () { return fake.interstitialSupported })
    getter(advertisement, 'isRewardedSupported', 'advertisement.isRewardedSupported',
           function () { return fake.rewardedSupported })
    getter(advertisement, 'interstitialState', 'advertisement.interstitialState',
           function () { return ads.interstitial.state })
    getter(advertisement, 'rewardedState', 'advertisement.rewardedState',
           function () { return ads.rewarded.state })
    getter(advertisement, 'minimumDelayBetweenInterstitial',
           'advertisement.minimumDelayBetweenInterstitial', function () { return minimumDelay })
    advertisement.setMinimumDelayBetweenInterstitial = method(
        'advertisement.setMinimumDelayBetweenInterstitial', function (seconds) {
            minimumDelay = Number(seconds) || 0
            interstitialCooldownUntil = 0
        })
    advertisement.showInterstitial = method('advertisement.showInterstitial', function () {
        if (inProgress('interstitial')) return
        if (performance.now() < interstitialCooldownUntil) {
            setState('interstitial', 'failed')
            return
        }
        play('interstitial', fake.interstitialSeq)
    })
    advertisement.showRewarded = method('advertisement.showRewarded', function () {
        if (inProgress('rewarded')) {
            error('advertisement.showRewarded', 'called while a rewarded ad is in progress')
            return
        }
        // Mark it in progress at once so a second synchronous call is caught.
        ads.rewarded.state = 'loading'
        play('rewarded', fake.rewardedSeq)
    })
    advertisement.on = method('advertisement.on', adEvents.on)
    advertisement.off = method('advertisement.off', adEvents.off)

    // Test controls.
    fake.script = function (kind, seq) {
        if (!(kind in ads)) throw new Error('unknown ad kind ' + kind)
        fake[kind + 'Seq'] = seq
    }
    // Ends the minimumDelayBetweenInterstitial cooldown at once.
    fake.clearInterstitialCooldown = function () { interstitialCooldownUntil = 0 }
    // Accepts an EVENT_NAME value or its key ('PAUSE_STATE_CHANGED').
    fake.fire = function (event, value) {
        if (event in EVENT_NAME) event = EVENT_NAME[event]
        record('fire', [event, value])
        if (event === EVENT_NAME.AUDIO_STATE_CHANGED) fake.isAudioEnabled = value
        if (event === EVENT_NAME.PAUSE_STATE_CHANGED) fake.isPaused = value
        platformEvents.emit(event, value)
        adEvents.emit(event, value)
    }

    function initialize() {
        record('initialize', arguments)
        if (initPromise) return initPromise
        if (fake.init === 'never') return (initPromise = new Promise(function () {}))
        initPromise = new Promise(function (resolve, reject) {
            setTimeout(function () {
                if (fake.init === 'reject') {
                    reject(new Error('fake initialize rejected'))
                    return
                }
                initialized = true
                fake.initResolvedAt = performance.now()
                resolve()
            }, fake.initDelayMs)
        })
        return initPromise
    }

    window.bridge = {
        EVENT_NAME: EVENT_NAME,
        initialize: initialize,
        platform: platform,
        storage: storage,
        advertisement: advertisement
    }
    Object.defineProperty(window.bridge, 'isInitialized', {
        enumerable: true, get: function () { return initialized }})
})()
