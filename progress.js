// Bridge Storage owns persistence. Retain unsaved session changes in memory
// and reconcile them before writing after a delayed or failed initial read.
const PROGRESS = (function()
{
    const recordsKey = 'grapnelninja.records'
    const timeKey = 'grapnelninja.time'
    const langKey = 'grapnelninja.lang'
    const tutorialKey = 'grapnelninja.tutorialDone'
    const lightingKey = 'grapnelninja.lighting'
    const state = {time: 0, lang: null, tutorialDone: false}
    let loaded = false, known = false, baseTime = 0, langChanged = false, lightingChanged = false
    let savedJson = null, saveTimer = null, writing = false, lastSaveAt = -Infinity
    function number(value) { const n = Number(value); return Number.isFinite(n) ? Math.max(0, Math.floor(n)) : 0 }
    // Missing (an older stored blob) or anything but 'false' is on
    function lighting(value) { return value !== 'false' }
    function parse(value)
    {
        try { return JSON.parse(value) || {} } catch (_) { return {} }
    }
    function snapshot()
    {
        return {
            [recordsKey]: JSON.stringify({classic: scoreText.record.classic, bad: scoreText.record.bad,
                momentum: scoreText.record.momentum}),
            [tutorialKey]: String(state.tutorialDone),
            [timeKey]: String(state.time), [langKey]: state.lang || '',
            [lightingKey]: String(MOMENTUM_FX.enabled)
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
        const records = parse(values[recordsKey])
        state.tutorialDone ||= values[tutorialKey] === 'true'
        const delta = Math.max(0, state.time - baseTime)
        scoreText.record.classic = Math.max(scoreText.record.classic, number(records.classic))
        scoreText.record.bad = Math.max(scoreText.record.bad, number(records.bad))
        scoreText.record.momentum = Math.max(scoreText.record.momentum, number(records.momentum))
        baseTime = Math.max(baseTime, number(values[timeKey]))
        state.time = baseTime + delta
        if (!langChanged) state.lang = values[langKey] || null
        if (!lightingChanged) MOMENTUM_FX.enabled = lighting(values[lightingKey])
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
        const sentTime = state.time, sentLang = state.lang, sentLighting = MOMENTUM_FX.enabled
        const ok = await PLATFORM.storage.setMany(values)
        writing = false
        if (ok)
        {
            savedJson = json
            baseTime = sentTime
            if (state.lang === sentLang) langChanged = false
            if (MOMENTUM_FX.enabled === sentLighting) lightingChanged = false
        }
        if (JSON.stringify(snapshot()) !== savedJson)
            saveTimer = setTimeout(write, 1000)
    }
    const PROGRESS = {
        keys: [recordsKey, timeKey, langKey, tutorialKey, lightingKey],
        load(values)
        {
            const records = parse(values[recordsKey])
            state.tutorialDone = values[tutorialKey] === 'true'
            known = PLATFORM.storage.remoteKnown
            baseTime = number(values[timeKey])
            state.time = baseTime
            state.lang = values[langKey] || null
            langChanged = false
            MOMENTUM_FX.enabled = lighting(values[lightingKey])
            lightingChanged = false
            for (const mode of ['classic', 'bad', 'momentum'])
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
        getTime() { return state.time },
        setTime(seconds) { state.time = Math.max(state.time, number(seconds)) },
        getLang() { return state.lang },
        setLang(lang) { state.lang = lang || null; langChanged = true },
        setLighting(on) { MOMENTUM_FX.enabled = !!on; lightingChanged = true }
    }
    PLATFORM.storage.onRecovery(values => { if (loaded) reconcile(values) })
    window.addEventListener('pagehide', () => PROGRESS.flush())
    return PROGRESS
})()
