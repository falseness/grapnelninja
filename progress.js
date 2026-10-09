// Progress is reconciled before remote writes. A local journal retains pending
// session deltas across reloads; unavailable local storage degrades to memory.
const PROGRESS = (function()
{
    const recordsKey = 'grapnelninja.records'
    const timeKey = 'grapnelninja.time'
    const langKey = 'grapnelninja.lang'
    const tutorialKey = 'grapnelninja.tutorialDone'
    const muteKey = 'grapnelninja.muted'
    const journalKey = 'grapnelninja.pending'
    const state = {time: 0, lang: null, muted: false, tutorialDone: false}
    let loaded = false, known = false, baseTime = 0, langChanged = false, muteChanged = false
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
            [timeKey]: String(state.time), [langKey]: state.lang || '', [muteKey]: String(state.muted)
        }
    }
    function journal()
    {
        const values = snapshot()
        Object.keys(values).forEach(key => PLATFORM.storage.localSet(key, values[key]))
        PLATFORM.storage.localSet(journalKey, JSON.stringify({
            records: JSON.stringify(values) === savedJson ? {} : parse(values[recordsKey]), delta: Math.max(0, state.time - baseTime),
            tutorialDone: state.tutorialDone, lang: state.lang, langChanged, muted: state.muted, muteChanged, known, baseTime
        }))
    }
    function refresh()
    {
        I18N.language = I18N.pick(state.lang, PLATFORM.language)
        applyLanguage()
        MUTE_BUTTON.restore(state.muted)
        if (state.tutorialDone) TUTORIAL.element.hidden = true
    }
    function reconcile(values)
    {
        const records = parse(values[recordsKey])
        state.tutorialDone ||= values[tutorialKey] === 'true'
        const delta = Math.max(0, state.time - baseTime)
        scoreText.record.classic = Math.max(scoreText.record.classic, number(records.classic))
        scoreText.record.bad = Math.max(scoreText.record.bad, number(records.bad))
        baseTime = Math.max(baseTime, number(values[timeKey]))
        state.time = baseTime + delta
        if (!langChanged) state.lang = values[langKey] || null
        if (!muteChanged) state.muted = values[muteKey] === 'true'
        known = true
        refresh()
        PROGRESS.save()
    }
    async function write()
    {
        saveTimer = null
        if (writing) return
        journal()
        if (!known) return
        const values = snapshot(), json = JSON.stringify(values)
        if (json === savedJson) return
        writing = true
        lastSaveAt = performance.now()
        const sentTime = state.time, sentLang = state.lang, sentMuted = state.muted
        const ok = await PLATFORM.storage.setMany(values)
        writing = false
        if (ok)
        {
            savedJson = json
            baseTime = sentTime
            if (state.lang === sentLang) langChanged = false
            if (state.muted === sentMuted) muteChanged = false
            journal()
        }
        if (JSON.stringify(snapshot()) !== savedJson)
            saveTimer = setTimeout(write, 1000)
    }
    const PROGRESS = {
        keys: [recordsKey, timeKey, langKey, muteKey, tutorialKey],
        load(values)
        {
            const pending = parse(PLATFORM.storage.localGet(journalKey))
            const records = parse(values[recordsKey])
            state.tutorialDone = values[tutorialKey] === 'true' || pending.tutorialDone === true
            known = PLATFORM.storage.remoteKnown
            baseTime = number(values[timeKey])
            // Cached time already includes the journal delta; remote time does not.
            if (!known) baseTime = Math.max(0, baseTime - number(pending.delta))
            state.time = known && pending.known && number(pending.delta) > 0
                ? Math.max(baseTime, number(pending.baseTime) + number(pending.delta))
                : baseTime + number(pending.delta)
            state.lang = pending.langChanged ? pending.lang : values[langKey] || null
            state.muted = pending.muteChanged ? !!pending.muted : values[muteKey] === 'true'
            muteChanged = !!pending.muteChanged
            langChanged = !!pending.langChanged
            for (const mode of ['classic', 'bad'])
                scoreText.record[mode] = Math.max(number(records[mode]), number((pending.records || {})[mode]))
            // An unknown cached snapshot is not an acknowledgement of journaled
            // records, even when no time or language change accompanies them.
            const pendingRecords = !known && Object.keys(pending.records || {}).length > 0
            savedJson = (state.tutorialDone && values[tutorialKey] !== 'true') || pendingRecords || pending.delta || pending.langChanged || pending.muteChanged || JSON.stringify(records) !== snapshot()[recordsKey] ? null : JSON.stringify(snapshot())
            loaded = true
            if (known && savedJson === null) PROGRESS.save()
        },
        save()
        {
            if (!loaded) return
            journal()
            if (saveTimer !== null || writing) return
            const wait = lastSaveAt + 1000 - performance.now()
            if (wait > 0) saveTimer = setTimeout(write, wait)
            else write()
        },
        flush()
        {
            if (!loaded) return
            journal()
            clearTimeout(saveTimer)
            write()
        },
        getTutorialDone() { return state.tutorialDone },
        completeTutorial() { state.tutorialDone = true; PROGRESS.save() },
        getMuted() { return state.muted },
        setMuted(value) { state.muted = !!value; muteChanged = true },
        getTime() { return state.time },
        setTime(seconds) { state.time = Math.max(state.time, number(seconds)) },
        getLang() { return state.lang },
        setLang(lang) { state.lang = lang || null; langChanged = true }
    }
    PLATFORM.storage.onRecovery(values => { if (loaded) reconcile(values) })
    window.addEventListener('pagehide', () => PROGRESS.flush())
    return PROGRESS
})()
