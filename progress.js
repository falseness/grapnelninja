// Records and time-in-game persisted through CG.data (CrazyGames data
// module, or localStorage when the SDK is disabled). Records are written
// only on run end or pause, never per point, to respect the data debounce.
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
        // Call once after CG.init(): migrate legacy time, load records
        load()
        {
            const legacy = localStorage.getItem(legacyTimeKey)
            if (legacy !== null)
            {
                if (CG.data.getItem(timeKey) === null)
                    CG.data.setItem(timeKey, String(readNumber(legacy)))
                localStorage.removeItem(legacyTimeKey)
            }

            let records = {}
            try
            {
                records = JSON.parse(CG.data.getItem(recordsKey)) || {}
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
            CG.data.setItem(recordsKey, json)
            savedRecords = json
        },
        getTime()
        {
            return readNumber(CG.data.getItem(timeKey))
        },
        setTime(seconds)
        {
            CG.data.setItem(timeKey, String(readNumber(seconds)))
        }
    }
    // Closing the tab mid-run must not lose a new record
    window.addEventListener('pagehide', () => PROGRESS.saveRecords())
    return PROGRESS
})()
