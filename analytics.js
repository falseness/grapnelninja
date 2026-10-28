// ANALYTICS facade: the telemetry API the game calls. It holds no SDK code;
// every public method sanitizes its arguments and delegates to an inner
// method of ANALYTICS_BACKEND (analytics/backends/<id>.js, loaded by
// index.html right before this file). Turning on GameAnalytics means
// replacing the inner methods of ONE backend file and swapping that one
// script tag; nothing else changes. none.js (no-ops) is the default and must
// stay on GamePix and Playgama builds, see docs/platform-sdk.md.
//
//   init({build})                  -> initialize({build})
//   sessionStart() / sessionEnd()  -> startSession() / endSession()
//   progression(status, level1, level2?, level3?, score?)
//                                  -> addProgressionEvent(status, p1, p2, p3, score)
//   design(id, value?)             -> addDesignEvent(id, value)
//   error(severity, message)       -> addErrorEvent(severity, message)
//   ad(action, type, placement)    -> addAdEvent(action, type, sdkName, placement)
//
// Sanitizing (GameAnalytics event id rules): an id splits on ':' into at
// most 5 segments; in each segment characters outside [A-Za-z0-9_.-] become
// '_', it is cut to 32 characters, and empty segments are dropped.
// Progression levels are sanitized the same way (one segment each) and fill
// in order, so a level3 without a level2 moves up to level2. An unknown
// status or severity, an empty id or level1 drops the call. Error messages
// are cut to 8000 characters. Calls never throw into the game: a throwing
// backend is caught (one console.warn per method).
//
// debugLog keeps the last 500 sanitized calls as {t, fn, args} for tests;
// dropped calls are not logged.
const ANALYTICS = (function()
{
    const LOG_SIZE = 500
    const SEGMENTS = 5
    const SEGMENT_LENGTH = 32
    const MESSAGE_LENGTH = 8000
    const STATUSES = ['Start', 'Complete', 'Fail']
    const SEVERITIES = ['debug', 'info', 'warning', 'error', 'critical']
    const SDK_NAME = 'grapnelninja'
    const debugLog = []
    const warned = new Set()

    function segment(value)
    {
        return String(value).replace(/[^A-Za-z0-9_.-]/g, '_').slice(0, SEGMENT_LENGTH)
    }

    // 'fall:S03 room!' -> 'fall:S03_room_'; '' when nothing is left
    function eventId(id)
    {
        if (id == null)
            return ''
        return String(id).split(':').map(segment).filter(s => s).slice(0, SEGMENTS).join(':')
    }

    // One progression level: no ':' allowed, '' when missing or empty
    function level(value)
    {
        return value == null ? '' : segment(value)
    }

    function number(value)
    {
        return typeof value === 'number' && isFinite(value) ? value : undefined
    }

    function fail(fn, e)
    {
        if (warned.has(fn))
            return
        warned.add(fn)
        console.warn('ANALYTICS_BACKEND.' + fn + ' failed, ignored:', e && e.message || e)
    }

    // Records the sanitized call, then calls ANALYTICS_BACKEND.<fn>(...args);
    // a missing or throwing inner method is swallowed
    function delegate(fn, args)
    {
        debugLog.push({t: Date.now(), fn, args})
        if (debugLog.length > LOG_SIZE)
            debugLog.splice(0, debugLog.length - LOG_SIZE)
        try
        {
            const backend = typeof ANALYTICS_BACKEND === 'undefined' ? null : ANALYTICS_BACKEND
            const method = backend && backend[fn]
            if (typeof method !== 'function')
                throw new Error('missing')
            method.apply(backend, args)
        }
        catch (e)
        {
            fail(fn, e)
        }
    }

    // Public methods never throw (bad arguments included)
    function safe(body)
    {
        return function(...args)
        {
            try
            {
                body(...args)
            }
            catch (e)
            {
                fail('facade', e)
            }
        }
    }

    return {
        debugLog,
        sanitizeId: eventId,

        init: safe(function(config)
        {
            const build = config && config.build != null ? String(config.build) : ''
            delegate('initialize', [{build}])
        }),

        sessionStart: safe(function()
        {
            delegate('startSession', [])
        }),

        sessionEnd: safe(function()
        {
            delegate('endSession', [])
        }),

        // status 'Start' | 'Complete' | 'Fail'; levels fill in order
        progression: safe(function(status, level1, level2, level3, score)
        {
            if (!STATUSES.includes(status))
                return
            const levels = [level1, level2, level3].map(level)
            if (!levels[0])
                return
            const filled = levels.filter(l => l)
            while (filled.length < 3)
                filled.push(undefined)
            delegate('addProgressionEvent', [status, ...filled, number(score)])
        }),

        design: safe(function(id, value)
        {
            const clean = eventId(id)
            if (!clean)
                return
            delegate('addDesignEvent', [clean, number(value)])
        }),

        // severity 'debug' | 'info' | 'warning' | 'error' | 'critical'
        error: safe(function(severity, message)
        {
            if (!SEVERITIES.includes(severity))
                return
            delegate('addErrorEvent', [severity, String(message == null ? '' : message).slice(0, MESSAGE_LENGTH)])
        }),

        ad: safe(function(action, type, placement)
        {
            delegate('addAdEvent', [String(action), String(type), SDK_NAME, level(placement)])
        }),
    }
})()
