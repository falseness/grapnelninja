// Grapple Over long-fall reactions. Detection and message choice only; the
// event is transient (never saved) and is left for a renderer to show.
const LONG_FALL_THRESHOLD = 4000
const LONG_FALL_MESSAGES = Object.freeze(['OOPS...', 'GG!', 'BRUH.', 'NOT AGAIN.', 'SO CLOSE...',
    'GRAVITY WINS.', 'GOING DOWN!', 'BACK SO SOON?', 'NICE SHORTCUT.', 'WRONG WAY.',
    'ONE MORE TRY?', 'SEE YOU AT THE TOP.'])
// The first long fall of a single-grapnel run suggests double grapnel mode
// instead (climb.fallHint, shown in the current language).
const LONG_FALL_HINT_KEY = 'climb.fallHint'
// Grapple Over: a fall longer than this (measured like LONG_FALL_THRESHOLD)
// with the go-back checkpoint above the player pauses on the 'Go back?'
// dialog (CLIMB_UI.offerGoBack), once per catch.
const GO_BACK_FALL_THRESHOLD = 10000

const LONG_FALL = (function()
{
    // Math.random is shared with level generation (seeded in tests), so
    // reactions draw from their own source. Tests can inject one.
    const cryptoRandom = () => crypto.getRandomValues(new Uint32Array(1))[0] / 4294967296
    let random = cryptoRandom
    // The world and player the tracking belongs to: a restart, reload or mode
    // switch replaces them, so a new run never inherits a fall in progress.
    let world = null, body = null
    let startY = 0, lastY = 0, armed = true, wasGrappled = false
    let event = null, emitted = 0
    // The go-back offer: armed by a new world and by each new catch
    let goBackArmed = true

    function pick(r)
    {
        const n = LONG_FALL_MESSAGES.length
        const index = Math.min(n - 1, Math.max(0, Math.floor(r * n) || 0))
        return {index, message: LONG_FALL_MESSAGES[index]}
    }
    function baseline()
    {
        startY = lastY = ninja.y
        armed = true
        wasGrappled = grapnel.isGrappled()
    }
    return {
        // One physics cycle, after movement and grapple collision and before the
        // fall recovery check, so a qualifying fall emits before the teleport.
        step()
        {
            if (floors[0] !== world || ninja !== body)
            {
                if (world !== null) event = null
                world = floors[0]
                body = ninja
                goBackArmed = true
                baseline()
                return
            }
            const y = ninja.y, grappled = grapnel.isGrappled()
            // Only the moment of a new catch counts; holding the rope does not.
            const caught = grappled && !wasGrappled
            wasGrappled = grappled
            if (caught) goBackArmed = true
            if (caught || y < lastY)
            {
                startY = y
                armed = true
            }
            else if (armed && y - startY > LONG_FALL_THRESHOLD)
            {
                armed = false
                // The run's first long fall; world.fallHintShown is saved with the climb.
                const first = !world.fallHintShown
                world.fallHintShown = true
                event = first && world.grapnelMode !== 'double'
                    ? {id: ++emitted, index: -1, hint: true, message: I18N.t(LONG_FALL_HINT_KEY), displacement: y - startY}
                    : {id: ++emitted, ...pick(random()), displacement: y - startY}
            }
            lastY = y
        },
        // Recovery teleport: restart tracking at the spawn, keep the reaction.
        restartTracking()
        {
            baseline()
        },
        // The fall since the last catch (or the apex since it) is long enough
        // for the go-back offer, which was not yet made for that catch.
        goBackDue()
        {
            return goBackArmed && lastY - startY > GO_BACK_FALL_THRESHOLD
        },
        // armed: false after the offer (until the next catch), true after a go back
        setGoBackArmed(armed)
        {
            goBackArmed = armed
        },
        clearEvent()
        {
            event = null
        },
        // A replaced world (restart, reload, mode switch) owns no reaction.
        get event() { return floors[0] === world && ninja === body ? event : null },
        get emitted() { return emitted },
        get goBackArmed() { return goBackArmed },
        tracking()
        {
            return {startY, lastY, armed, wasGrappled, displacement: lastY - startY}
        },
        pick,
        // Text of an event; the double grapnel hint follows the current language.
        text(e)
        {
            return e.hint ? I18N.t(LONG_FALL_HINT_KEY) : e.message
        },
        // Test hook: a function returning [0, 1), or null for the default source.
        setRandom(source)
        {
            random = source || cryptoRandom
        }
    }
})()
