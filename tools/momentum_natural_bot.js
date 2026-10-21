// Momentum natural-run bot (test-only, injected after boot; ported from
// TASK-086). Same idea as tools/autopilot.js: every SEARCH_TICKS the run
// (ninja, grapnel, floors, screen, hp) is cloned, each candidate grapnel
// action is played HORIZON ticks ahead on the clone and the best one is
// applied to the real run through synthetic mousedown/mouseup events (the
// game's own input handlers). The real run is never edited: no teleports,
// no invulnerability. Score: no hp loss / death first, then progress along
// the course centre line (extrapolated a little along the velocity), then
// staying near it. Used by tools/momentum_natural_run.py.
(function()
{
    'use strict'
    const SEARCH_TICKS = 12
    const CHECK_TICKS = 4
    const HORIZON = 60
    const EXTRAPOLATE_TICKS = 15
    // throw directions relative to the course tangent at the ninja (deg, - = left of travel)
    const REL_ANGLES = [-80, -55, -30, -10, 10, 30, 55, 80]
    // and absolute ones (0 = right, -90 = up)
    const ABS_ANGLES = [-90, -60, -120]
    const AIM_DISTANCE = 60

    function lcg(seed)
    {
        const rng = {state: seed >>> 0}
        rng.next = () => (rng.state = (1664525 * rng.state + 1013904223) >>> 0) / 4294967296
        return rng
    }
    function isClonable(value)
    {
        if (Array.isArray(value))
            return true
        const proto = Object.getPrototypeOf(value)
        if (proto === Object.prototype || proto === null)
            return true
        return typeof proto.constructor == 'function' &&
            /^class\b/.test(Function.prototype.toString.call(proto.constructor))
    }
    function deepClone(value, seen)
    {
        if (value === null || typeof value != 'object' || !isClonable(value))
            return value
        if (seen.has(value))
            return seen.get(value)
        const copy = Array.isArray(value) ? [] : Object.create(Object.getPrototypeOf(value))
        seen.set(value, copy)
        for (const key of Object.keys(value))
            copy[key] = deepClone(value[key], seen)
        return copy
    }

    const ap = window.__mb = {tick: 0, deathTick: null, simulating: false, simDead: false,
                              actions: [], pendingRelease: null, hpLost: 0}

    ap.install = function(seed)
    {
        ap.gameRng = lcg(seed * 2654435761)
        ap.fxRng = lcg(seed * 40503 + 12345)
        Math.random = () => ap.fxRng.next()
        const gameRandom = window.random
        window.random = function(min, max)
        {
            const fx = Math.random
            Math.random = ap.gameRng.next
            try { return gameRandom(min, max) }
            finally { Math.random = fx }
        }
        const realLethal = window.onLethalDeath
        window.onLethalDeath = function()
        {
            if (ap.simulating)
            {
                ap.simDead = true
                return
            }
            if (ap.deathTick === null && !ninja.isInvulnerable())
                ap.deathTick = ap.tick
            return realLethal.apply(this, arguments)
        }
    }
    function clientPoint(worldX, worldY)
    {
        const rect = canvas.getBoundingClientRect()
        const s = scale[version]
        return {x: rect.left + (worldX + screen.x) * s * rect.width / width,
                y: rect.top + (worldY + screen.y) * s * rect.height / height}
    }
    function dispatch(type, point)
    {
        document.dispatchEvent(new MouseEvent(type, {
            clientX: point ? point.x : 0, clientY: point ? point.y : 0, bubbles: true}))
    }
    function apply(action)
    {
        if (action.type == 'release')
            dispatch('mouseup')
        else if (action.type == 'throw')
        {
            // a new throw is a new press: lift the old one first
            if (grapnel.throwed)
                dispatch('mouseup')
            dispatch('mousedown', action)
            if (menu.gamePaused)
            {
                // a plan whose click lands on the HUD pause button is dropped
                menu.changeGamePause(false)
                ap.pauseHits = (ap.pauseHits || 0) + 1
                if (!ap.simulating)
                    throw Error('bot click hit the pause button')
                ap.simDead = true
            }
        }
    }
    // The ninja's nearest point on the course centre line (segments around
    // the camera's): its distance s along the course and how far off it is
    function courseAt()
    {
        const course = screen.course
        let best = null, start = 0
        for (let i = 0; i <= screen.segmentIndex + 2; ++i)
        {
            const seg = course.segment(i), d = segmentDirection(seg.dir)
            if (i >= screen.segmentIndex - 1)
            {
                const along = Math.min(seg.length, Math.max(0, (ninja.x - seg.x0) * d.x + (ninja.y - seg.y0) * d.y))
                const off = Math.hypot(ninja.x - seg.x0 - d.x * along, ninja.y - seg.y0 - d.y * along)
                if (!best || off < best.off)
                    best = {s: start + along, off}
            }
            start += seg.length
        }
        return best
    }
    // The course centre line point at distance s
    function coursePoint(s)
    {
        const course = screen.course
        for (let i = 0; ; ++i)
        {
            const seg = course.segment(i)
            if (s <= seg.length)
            {
                const d = segmentDirection(seg.dir)
                return {x: seg.x0 + d.x * s, y: seg.y0 + d.y * s}
            }
            s -= seg.length
        }
    }
    // Unit direction from the ninja to the course half a view height ahead
    function aheadDirection(s)
    {
        const p = coursePoint(s + 0.5 * height / scale[version])
        const len = Math.hypot(p.x - ninja.x, p.y - ninja.y) || 1
        return {x: (p.x - ninja.x) / len, y: (p.y - ninja.y) / len}
    }
    function throwAt(degrees)
    {
        const r = degrees * Math.PI / 180
        const p = clientPoint(ninja.x + AIM_DISTANCE * Math.cos(r), ninja.y + AIM_DISTANCE * Math.sin(r))
        // never aim at or near the HUD pause button
        for (const [dx, dy] of [[0, 0], [-40, 0], [40, 0], [0, -40], [0, 40], [-40, -40], [40, 40], [-40, 40], [40, -40]])
        {
            const c = viewportCoordsToCanvasCoords({x: p.x + dx, y: p.y + dy})
            // bounds only: isClickOnButton() would press the button
            const b = menu.button.background, x = c.x / scale[version], y = c.y / scale[version]
            if (b.x < x && x < b.x + b.width && b.y < y && y < b.y + b.height)
                return null
        }
        return {type: 'throw', x: p.x, y: p.y, aim: Math.round(degrees)}
    }
    // Rollouts change the cloned grapnel the way events.js throwGrapnel /
    // pickUpGrapnel do, without the DOM handlers (whose pause button and
    // real-time unTouch latch would leak into the real run)
    function simApply(action)
    {
        if (action.type == 'release' || (action.type == 'throw' && grapnel.throwed))
        {
            grapnel.setGrappled(false)
            grapnel.throwed = false
        }
        if (action.type == 'throw')
        {
            const c = viewportCoordsToCanvasCoords({x: action.x, y: action.y})
            grapnel.pos = [[ninja.x, ninja.y, new Empty()]]
            const ratio = grapnel.calcSpeed({x: c.x / scale[version] - screen.x, y: c.y / scale[version] - screen.y})
            const speed = grapnelSpeed * momentumMotionScale(1)
            grapnel.speedY = ratio.sin * speed
            grapnel.speedX = ratio.cos * speed
            grapnel.throwed = true
            grapnel.setGrappled(false)
        }
    }
    function rollout(base, action, releaseAfter)
    {
        const seen = new Map()
        ninja = deepClone(base.ninja, seen)
        grapnel = deepClone(base.grapnel, seen)
        floors = deepClone(base.floors, seen)
        screen = deepClone(base.screen, seen)
        Object.assign(momentumState, base.hp)
        ap.gameRng.state = base.rngState
        ap.simDead = false
        simApply(action)
        const s0 = courseAt().s
        let t = 0
        for (; t < HORIZON && !ap.simDead; ++t)
        {
            if (t == releaseAfter && grapnel.throwed)
                simApply({type: 'release'})
            physics()
        }
        const lost = base.hp.hp - momentumState.hp
        if (ap.simDead)
            return t * 1000 - 1e6
        const ext = EXTRAPOLATE_TICKS * cyclesPerTick
        const view = height / scale[version]
        const at = courseAt(), sNow = at.s, tg = aheadDirection(sNow)
        const along = (ninja.speedX * tg.x + ninja.speedY * tg.y) * ext
        const off = at.off / view
        return -lost * 50000 + (sNow + Math.max(-0.3 * view, Math.min(0.5 * view, along)) - s0) / view * 1000 - off * 300
    }
    function evaluate(plans)
    {
        const real = {ninja, grapnel, floors, screen, visualEffects,
            score: scoreText.count[version], record: scoreText.record[version],
            hp: Object.assign({}, momentumState), rngState: ap.gameRng.state, fxState: ap.fxRng.state}
        const seen = new Map()
        const base = {ninja: deepClone(ninja, seen), grapnel: deepClone(grapnel, seen),
                      floors: deepClone(floors, seen), screen: deepClone(screen, seen),
                      hp: real.hp, rngState: real.rngState}
        ap.simulating = true
        visualEffects = null
        let best = null
        try
        {
            for (const plan of plans)
            {
                const value = rollout(base, plan.action, plan.releaseAfter)
                if (!best || value > best.value)
                    best = Object.assign({value}, plan)
            }
        }
        finally
        {
            ({ninja, grapnel, floors, screen, visualEffects} = real)
            scoreText.count[version] = real.score
            scoreText.record[version] = real.record
            Object.assign(momentumState, real.hp)
            ap.gameRng.state = real.rngState
            ap.fxRng.state = real.fxState
            ap.simulating = false
        }
        return best
    }
    function currentPlan()
    {
        return {action: {type: 'none'},
            releaseAfter: ap.pendingRelease === null ? Infinity : ap.pendingRelease - ap.tick}
    }
    function allPlans()
    {
        const plans = [currentPlan()]
        for (const releaseAfter of [Infinity, 6, 15])
            plans.push({action: {type: 'none'}, releaseAfter})
        if (grapnel.throwed)
            plans.push({action: {type: 'release'}, releaseAfter: Infinity})
        const tg = aheadDirection(courseAt().s)
        const base = Math.atan2(tg.y, tg.x) * 180 / Math.PI
        const angles = REL_ANGLES.map(a => base + a).concat(ABS_ANGLES)
        for (const a of angles)
        {
            const action = throwAt(a)
            if (action)
                for (const releaseAfter of [Infinity, 20])
                    plans.push({action, releaseAfter})
        }
        return plans
    }
    function act(action)
    {
        apply(action)
        ap.actions.push(Object.assign({tick: ap.tick}, action))
    }
    // One real physics tick, deciding first on decision ticks
    ap.step = function()
    {
        if (ap.pendingRelease !== null && ap.tick >= ap.pendingRelease)
        {
            ap.pendingRelease = null
            if (grapnel.throwed)
                act({type: 'release'})
        }
        let best = null
        if (ap.tick % SEARCH_TICKS == 0)
            best = evaluate(allPlans())
        else if (ap.tick % CHECK_TICKS == 0)
        {
            best = evaluate([currentPlan()])
            if (best.value < -1000)
                best = evaluate(allPlans())
        }
        if (best)
        {
            if (best.action.type != 'none')
                act(best.action)
            ap.pendingRelease = isFinite(best.releaseAfter) ? ap.tick + best.releaseAfter : null
        }
        const hp = momentumState.hp
        physics()
        ap.hpLost += Math.max(0, hp - momentumState.hp)
        ap.tick++
    }
})()
