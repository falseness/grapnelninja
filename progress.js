// Bridge Storage owns persistence. Retain unsaved session changes in memory
// and reconcile them before writing after a delayed or failed initial read.
const PROGRESS = (function()
{
    const climbKey = GRAPPLE_OVER_PREVIEW
        ? 'grapnelninja.grappleOver.preview.replacement-v1' : 'grapnelninja.grappleOver'
    let climbJson = null, climbChanged = false, climbActive = false
    let climbTimer = null, climbWriting = false, climbFlushPending = false
    let climbSaved = null, climbLastWrite = -Infinity

    function readClimb(value)
    {
        if (climbChanged) return
        // Input can change between physics ticks, too.
        if (climbActive && JSON.stringify(captureClimbState()) !== climbBaseline) return
        climbJson = value
        climbSaved = value
        if (climbActive) restoreClimb()
    }
    let climbBaseline = null
    function restoreClimb()
    {
        if (climbJson !== null && climbJson !== undefined)
        {
            try {
                restoreClimbState(JSON.parse(climbJson))
                // Saved physical state survives; a previous session owns no input.
                pressHeld = false
                stalePress = false
                gameplayPressOwned = false
                if (floors[0].climbStats.completed) runInProgress = false
                draw()
                menu.startPause()
            }
            catch (_)
            {
                // A rejected save restarts silently at the base; the next write replaces it.
                climbJson = null
            }
        }
        climbBaseline = JSON.stringify(captureClimbState())
    }
    async function writeClimb()
    {
        climbTimer = null
        if (climbWriting) { climbFlushPending = true; return }
        if (climbActive) climbJson = JSON.stringify(captureClimbState())
        if (!climbChanged || climbJson === climbSaved) return
        const sent = climbJson
        climbWriting = true
        climbLastWrite = performance.now()
        try { if (await PLATFORM.storage.setMany({[climbKey]: sent})) climbSaved = sent }
        catch (_) { /* Keep the current state in memory and retry. */ }
        finally { climbWriting = false }
        if (climbFlushPending)
        {
            climbFlushPending = false
            writeClimb()
        }
        else if (climbJson !== climbSaved) climbTimer = setTimeout(writeClimb, 1000)
    }
    const recordsKey = 'grapnelninja.records'
    const timeKey = 'grapnelninja.time'
    const langKey = 'grapnelninja.lang'
    const tutorialKey = 'grapnelninja.tutorialDone'
    // Play time totals per grapnel mode (TELEMETRY owns the values)
    const playTimeKey = 'grapnelninja_playtime_v1'
    const state = {time: 0, lang: null, tutorialDone: false}
    let loaded = false, known = false, baseTime = 0, langChanged = false
    let savedJson = null, saveTimer = null, writing = false, lastSaveAt = -Infinity
    function number(value) { const n = Number(value); return Number.isFinite(n) ? Math.max(0, Math.floor(n)) : 0 }
    function parse(value)
    {
        try { return JSON.parse(value) || {} } catch (_) { return {} }
    }
    function snapshot()
    {
        return {
            [recordsKey]: JSON.stringify({classic: scoreText.record.classic, bad: scoreText.record.bad}),
            [tutorialKey]: String(state.tutorialDone),
            [timeKey]: String(state.time), [langKey]: state.lang || '',
            [playTimeKey]: TELEMETRY.playTimeJson()
        }
    }
    function refresh()
    {
        I18N.language = I18N.pick(state.lang, PLATFORM.language)
        applyLanguage()
        redrawOverlays()
    }
    function reconcile(values)
    {
        readClimb(values[climbKey])
        TELEMETRY.loadPlayTime(values[playTimeKey])
        const records = parse(values[recordsKey])
        state.tutorialDone ||= values[tutorialKey] === 'true'
        const delta = Math.max(0, state.time - baseTime)
        scoreText.record.classic = Math.max(scoreText.record.classic, number(records.classic))
        scoreText.record.bad = Math.max(scoreText.record.bad, number(records.bad))
        baseTime = Math.max(baseTime, number(values[timeKey]))
        state.time = baseTime + delta
        if (!langChanged) state.lang = values[langKey] || null
        known = true
        refresh()
        PROGRESS.save()
    }
    async function write()
    {
        saveTimer = null
        if (writing) return
        if (!known) return
        const values = snapshot(), json = JSON.stringify(values)
        if (json === savedJson) return
        writing = true
        lastSaveAt = performance.now()
        const sentTime = state.time, sentLang = state.lang
        const ok = await PLATFORM.storage.setMany(values)
        writing = false
        if (ok)
        {
            savedJson = json
            baseTime = sentTime
            if (state.lang === sentLang) langChanged = false
        }
        if (JSON.stringify(snapshot()) !== savedJson)
            saveTimer = setTimeout(write, 1000)
    }
    const PROGRESS = {
        keys: [recordsKey, timeKey, langKey, tutorialKey, climbKey, playTimeKey],
        load(values)
        {
            readClimb(values[climbKey])
            TELEMETRY.loadPlayTime(values[playTimeKey])
            const records = parse(values[recordsKey])
            state.tutorialDone = values[tutorialKey] === 'true'
            known = PLATFORM.storage.remoteKnown
            baseTime = number(values[timeKey])
            state.time = baseTime
            state.lang = values[langKey] || null
            langChanged = false
            for (const mode of ['classic', 'bad'])
                scoreText.record[mode] = number(records[mode])
            savedJson = known ? JSON.stringify(snapshot()) : null
            loaded = true
        },
        save()
        {
            if (!loaded) return
            if (saveTimer !== null || writing) return
            const wait = lastSaveAt + 1000 - performance.now()
            if (wait > 0) saveTimer = setTimeout(write, wait)
            else write()
        },
        flush()
        {
            if (!loaded) return
            clearTimeout(saveTimer)
            write()
        },
        resetClimb()
        {
            climbJson = null
            climbChanged = true
            startGrappleOverVersion()
            this.flushClimb()
        },
        enterClimb()
        {
            // Preview persistence uses its own key, leaving shipped saves intact.
            climbActive = true
            restoreClimb()
        },
        climbTick()
        {
            if (!climbActive) return
            climbChanged = true
            if (climbTimer === null && !climbWriting)
                climbTimer = setTimeout(writeClimb, Math.max(0, climbLastWrite + 1000 - performance.now()))
        },
        flushClimb(exit = false)
        {
            if (!climbActive) return
            climbChanged = true
            climbJson = JSON.stringify(captureClimbState())
            clearTimeout(climbTimer)
            writeClimb()
            if (exit) climbActive = false
        },
        getTime() { return state.time },
        setTime(seconds) { state.time = Math.max(state.time, number(seconds)) },
        getLang() { return state.lang },
        setLang(lang) { state.lang = lang || null; langChanged = true }
    }
    PLATFORM.storage.onRecovery(values => { if (loaded) reconcile(values) })
    // pagehide: everything unsaved in ONE setMany (the climb, and the
    // snapshot with the current play time totals; this listener runs before
    // index.html's TELEMETRY.flushPlayTime). Playgama's bridge refuses a set
    // while another is pending, and a retry timer never fires after pagehide.
    let hidden = false
    function flushAll()
    {
        // Like index.html's play time events, once per page: the saved
        // totals match the playtime:total values reported on this pagehide
        if (!hidden) TELEMETRY.updatePlayTime()
        hidden = true
        const values = {}
        let climbSent = null, json = null
        if (climbActive)
        {
            climbChanged = true
            climbJson = JSON.stringify(captureClimbState())
            clearTimeout(climbTimer)
            climbTimer = null
            if (climbJson !== climbSaved) values[climbKey] = climbSent = climbJson
        }
        if (loaded && known)
        {
            const snap = snapshot()
            clearTimeout(saveTimer)
            saveTimer = null
            if (JSON.stringify(snap) !== savedJson)
            {
                Object.assign(values, snap)
                json = JSON.stringify(snap)
            }
        }
        if (!Object.keys(values).length) return
        // Optimistic, so a save() later in this pagehide sends nothing again
        const previous = savedJson, sentTime = state.time, sentLang = state.lang
        if (json !== null) savedJson = json
        Promise.resolve(PLATFORM.storage.setMany(values)).then(ok =>
        {
            if (!ok)
            {
                if (json !== null && savedJson === json) savedJson = previous
                return
            }
            if (climbSent !== null) climbSaved = climbSent
            if (json !== null)
            {
                baseTime = sentTime
                if (state.lang === sentLang) langChanged = false
            }
        }).catch(() => { if (json !== null && savedJson === json) savedJson = previous })
    }
    window.addEventListener('pagehide', flushAll)
    return PROGRESS
})()
