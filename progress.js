// Records and time-in-game persisted through PLATFORM.storage (the GamePix
// SDK storage, or the browser's own storage when the SDK is disabled).
// Values are strings only. GamePix requires loaded() before any other SDK
// call, so nothing touches storage until load(), which index.html runs after
// PLATFORM.loaded() resolved (TASK-099 never probed storage before loaded()).
// Records are written only on run end or pause, never per point.
const PROGRESS = (function()
{
    const recordsKey = 'grapnelninja.records'
    const timeKey    = 'grapnelninja.time'
    const legacyTimeKey = 'time'

    const storage = PLATFORM.storage

    let savedRecords = null
    let loaded = false

    function readNumber(value)
    {
        const n = Number(value)
        return Number.isFinite(n) && n > 0 ? Math.floor(n) : 0
    }

    function recordsJson()
    {
        return JSON.stringify({
            classic : scoreText.record.classic,
            bad     : scoreText.record.bad
        })
    }

    const PROGRESS =
    {
        // Call once after PLATFORM.loaded(): migrate legacy time, load records
        load()
        {
            loaded = true
            const legacy = storage.getItem(legacyTimeKey)
            if (legacy !== null)
            {
                if (storage.getItem(timeKey) === null)
                    storage.setItem(timeKey, String(readNumber(legacy)))
                storage.removeItem(legacyTimeKey)
            }

            let records = {}
            try
            {
                records = JSON.parse(storage.getItem(recordsKey)) || {}
            }
            catch (e)
            {
                records = {}
            }
            scoreText.record.classic = readNumber(records.classic)
            scoreText.record.bad     = readNumber(records.bad)
            savedRecords = recordsJson()

            menu.classicRecord.text = 'record: ' + scoreText.record.classic
            menu.badRecord.text     = 'record: ' + scoreText.record.bad
            menu.timeInGame.text    = 'time spent in game: ' + getTimeInGame() + ' minutes'
        },
        // Write records only when they changed since the last write
        saveRecords()
        {
            if (savedRecords === null)
                return
            const json = recordsJson()
            if (json === savedRecords)
                return
            storage.setItem(recordsKey, json)
            savedRecords = json
        },
        getTime()
        {
            return loaded ? readNumber(storage.getItem(timeKey)) : 0
        },
        setTime(seconds)
        {
            if (!loaded)
                return
            storage.setItem(timeKey, String(readNumber(seconds)))
        }
    }
    // Closing the tab mid-run must not lose a new record
    window.addEventListener('pagehide', () => PROGRESS.saveRecords())
    return PROGRESS
})()
