// Records and time-in-game persisted in localStorage. Records are written
// only on run end or pause, never per point.
const PROGRESS = (function()
{
    const recordsKey = 'grapnelninja.records'
    const timeKey    = 'grapnelninja.time'
    const legacyTimeKey = 'time'

    let savedRecords = null

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
        // Every key read by the single PLATFORM.storage.getMany at boot
        keys: [recordsKey],
        // Call once with the boot getMany result: migrate legacy time, load records
        load(values)
        {
            const legacy = localStorage.getItem(legacyTimeKey)
            if (legacy !== null)
            {
                if (localStorage.getItem(timeKey) === null)
                    localStorage.setItem(timeKey, String(readNumber(legacy)))
                localStorage.removeItem(legacyTimeKey)
            }

            let records = {}
            try
            {
                records = JSON.parse(values[recordsKey]) || {}
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
            localStorage.setItem(recordsKey, json)
            savedRecords = json
        },
        getTime()
        {
            return readNumber(localStorage.getItem(timeKey))
        },
        setTime(seconds)
        {
            localStorage.setItem(timeKey, String(readNumber(seconds)))
        }
    }
    // Closing the tab mid-run must not lose a new record
    window.addEventListener('pagehide', () => PROGRESS.saveRecords())
    return PROGRESS
})()
