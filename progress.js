// Records, time in game and settings persisted through PLATFORM.storage
// (Bridge storage; platform.js falls back to browser storage when disabled).
// Everything is read by one getMany at boot and written by one setMany per
// meaningful change (run end, pause, menu return), at most once per second.
const PROGRESS = (function()
{
    const recordsKey = 'grapnelninja.records'
    const timeKey    = 'grapnelninja.time'
    const mutedKey   = 'grapnelninja.muted'
    const langKey    = 'grapnelninja.lang'
    const minSaveIntervalMs = 1000

    // In-memory state; muted and lang are reserved for TASK-120/TASK-126
    const state = { time: 0, muted: false, lang: null }

    let savedJson = null
    let lastSaveAt = -Infinity
    let saveTimer = null

    function readNumber(value)
    {
        const n = Number(value)
        return Number.isFinite(n) && n > 0 ? Math.floor(n) : 0
    }

    function readRecords(value)
    {
        try
        {
            const records = JSON.parse(value)
            return records && typeof records === 'object' ? records : {}
        }
        catch (e)
        {
            return {}
        }
    }

    // Every key with its string value, in PROGRESS.keys order
    function snapshot()
    {
        return {
            [recordsKey]: JSON.stringify({
                classic : scoreText.record.classic,
                bad     : scoreText.record.bad
            }),
            [timeKey]   : String(state.time),
            [mutedKey]  : state.muted ? '1' : '0',
            [langKey]   : state.lang || ''
        }
    }

    // One setMany with all keys, skipped when nothing changed
    function write()
    {
        saveTimer = null
        const values = snapshot()
        const json = JSON.stringify(values)
        if (json === savedJson)
            return
        savedJson = json
        lastSaveAt = performance.now()
        PLATFORM.storage.setMany(values)
    }

    const PROGRESS =
    {
        // Every key read by the single PLATFORM.storage.getMany at boot
        keys: [recordsKey, timeKey, mutedKey, langKey],
        // Call once with the boot getMany result; missing or bad values -> defaults
        load(values)
        {
            const records = readRecords(values[recordsKey])
            scoreText.record.classic = readNumber(records.classic)
            scoreText.record.bad     = readNumber(records.bad)
            state.time  = readNumber(values[timeKey])
            state.muted = values[mutedKey] === '1'
            state.lang  = values[langKey] || null
            savedJson = JSON.stringify(snapshot())

            menu.classicRecord.text = I18N.t('menu.record', {value: scoreText.record.classic})
            menu.badRecord.text     = I18N.t('menu.record', {value: scoreText.record.bad})
            menu.timeInGame.text    = I18N.t('menu.timeInGame', {minutes: getTimeInGame()})
        },
        // Save after a meaningful change; throttled to one setMany per second
        save()
        {
            if (savedJson === null || saveTimer !== null)
                return
            const wait = lastSaveAt + minSaveIntervalMs - performance.now()
            if (wait > 0)
                saveTimer = setTimeout(write, wait)
            else
                write()
        },
        // Write a pending change now (the page is going away)
        flush()
        {
            if (savedJson === null)
                return
            clearTimeout(saveTimer)
            write()
        },
        getTime()
        {
            return state.time
        },
        setTime(seconds)
        {
            state.time = readNumber(seconds)
        },
        getMuted()
        {
            return state.muted
        },
        setMuted(muted)
        {
            state.muted = !!muted
        },
        getLang()
        {
            return state.lang
        },
        setLang(lang)
        {
            state.lang = lang || null
        }
    }
    // Closing the tab mid-run must not lose a new record
    window.addEventListener('pagehide', () => PROGRESS.flush())
    return PROGRESS
})()
