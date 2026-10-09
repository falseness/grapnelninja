// Test double for the Y8 minimal SDK 2.x; served in place of y8.min.js by
// tools/y8_harness.py. API shape follows artifacts/TASK-089/probe.json:
// window.y8 = {sdk, emitReadyEvent}; init() and showAd() return Promises
// that resolve to undefined; adBreakDone(info) ends every non-silent break.
// Options are read from window.__y8Fake before load (see tools/y8_harness.py).
(function () {
    const fake = window.__y8Fake = Object.assign({
        readyNever: false,
        initReject: false,
        initHang: false,
        rewardOutcome: 'viewed',
        adDurationMs: 50
    }, window.__y8Fake || {})
    fake.calls = []
    const NO_AD = ['noAdPreloaded', 'frequencyCapped', 'notReady']

    // Callbacks are not cloneable; plain objects are recorded as their key names.
    function cloneable(arg) {
        if (typeof arg === 'function') return 'function'
        if (arg && typeof arg === 'object') return Object.keys(arg)
        return arg
    }

    function record(name, args) {
        fake.calls.push({name: name, args: Array.from(args || [], cloneable),
                         t: performance.now()})
    }

    function recorded(name, fn) {
        return function () {
            record(name, arguments)
            return fn ? fn.apply(this, arguments) : undefined
        }
    }

    function callback(options, name, arg) {
        record(name, arg === undefined ? [] : [arg])
        if (typeof options[name] === 'function') options[name](arg)
    }

    function init(appConfig, adConfig) {
        if (fake.initHang) return new Promise(function () {})
        if (fake.initReject) return Promise.reject(new Error('fake init rejected'))
        return Promise.resolve().then(function () {
            fake.initResolvedAt = performance.now()
            if (adConfig && typeof adConfig.onReady === 'function') {
                setTimeout(function () { callback(adConfig, 'onReady') }, 0)
            }
        })
    }

    function showAd(options) {
        options = options || {}
        const outcome = fake.rewardOutcome
        if (outcome === 'reject') return Promise.reject(new Error('fake showAd rejected'))
        if (outcome === 'silent') return Promise.resolve()
        setTimeout(function () {
            if (NO_AD.indexOf(outcome) >= 0) {
                callback(options, 'adBreakDone', {breakStatus: outcome})
                return
            }
            let shown = false
            const showAdFn = function () {
                if (shown) return
                shown = true
                record('showAdFn', [])
                callback(options, 'beforeAd')
                setTimeout(function () {
                    callback(options, outcome === 'dismissed' ? 'adDismissed' : 'adViewed')
                    callback(options, 'afterAd')
                    callback(options, 'adBreakDone', {breakStatus: outcome})
                }, fake.adDurationMs)
            }
            record('beforeReward', ['function'])
            if (typeof options.beforeReward === 'function') options.beforeReward(showAdFn)
        }, 0)
        // The real SDK resolves before adBreakDone; only rejection is meaningful.
        return Promise.resolve()
    }

    const sdk = {init: recorded('init', init), showAd: recorded('showAd', showAd)}
    const noops = ['awardAchievement', 'clearAllBanners', 'clearBanner',
        'getAccessToken', 'getAchievements', 'getLeaderboardScores',
        'getLeaderboards', 'getPlatformLocale', 'getToken', 'getUser',
        'isBlacklisted', 'isLoginGoing', 'loadData', 'login', 'logout',
        'onAuth', 'onAuthError', 'onAuthSuccess', 'openProfile', 'reloadUser',
        'removeData', 'requestBanner', 'saveData', 'saveLeaderboardScore',
        'showAchievements', 'showLeaderboard', 'signup', 'submitImage',
        'trackCustomEvent']
    noops.forEach(function (name) { sdk[name] = recorded(name) })

    function dispatchReady() {
        if (fake.readyNever) return
        record('y8sdk.ready', [])
        window.dispatchEvent(new Event('y8sdk.ready'))
    }

    window.y8 = {
        sdk: function () { return sdk },
        emitReadyEvent: function () {
            record('emitReadyEvent', [])
            dispatchReady()
        }
    }
    setTimeout(dispatchReady, 0)
})()
