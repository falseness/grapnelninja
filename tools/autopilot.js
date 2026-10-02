// Seeded autopilot for store-asset capture (TASK-084). Test-only: injected
// with Playwright add_init_script, never loaded by index.html.
//
// Every few physics ticks the bot clones the run (ninja, grapnel,
// floors, screen, score, gameplay RNG), plays each candidate action a short
// horizon ahead on the clone and applies the best one to the real run through
// synthetic mousedown/mouseup events, i.e. the game's own input handlers.
// The real run is never edited: no invulnerability, no removed obstacles.
//
// Determinism: the game's random() draws from a seeded gameplay stream and
// Math.random (visual effects only) from a second seeded stream, so a
// recorded action list replays the same run under requestAnimationFrame.
(function()
{
    'use strict'

    // Full search every SEARCH_TICKS, plan check every CHECK_TICKS: bad mode
    // physics costs ~7 ms per tick on the capture machine.
    const SEARCH_TICKS = 18
    const CHECK_TICKS = 6
    // bad mode's world is 2.2x larger, so it needs a longer look ahead
    const HORIZON = {classic: 48, bad: 64}
    // Throw directions in degrees, 0 = right, negative = up
    const THROW_ANGLES = [-60, -30, 5]
    // Aimed throws: nearest element tops ahead plus ceiling points (fractions
    // of the visible width ahead)
    const TARGET_ELEMENTS = 5
    const CEILING_AHEAD = [0.05, 0.15, 0.3, 0.5]
    // Free horizontal distance ahead (fraction of the visible width) that
    // still earns a bonus: climbing over an obstacle pays before progress does
    const CLEAR_AHEAD_MAX = 0.6
    const EXTRAPOLATE_TICKS = 20
    // keep at least this much (visible widths) between ninja and deletion border
    const BORDER_MARGIN = 0.6
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
        // instances of the game's own classes
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

    const ap = window.__ap = {
        seed: null,
        tick: 0,
        deathTick: null,
        simulating: false,
        simDead: false,
        actions: [],
        pendingRelease: null,
        replans: 0,
        // ninja position at every game second, to compare search and replay
        trace: []
    }

    // Seeds both streams and routes the game's random() to the gameplay one.
    ap.install = function(seed)
    {
        ap.seed = seed
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
            if (continueOffer.visible || ninja.isInvulnerable())
                return realLethal.apply(this, arguments)
            if (ap.simulating)
            {
                ap.simDead = true
                return
            }
            if (ap.deathTick === null)
            {
                ap.deathTick = ap.tick
                ap.death = deathInfo()
            }
            return realLethal.apply(this, arguments)
        }
    }

    function deathInfo()
    {
        const near = floors.flatMap(f => f.elements)
            .filter(e => e.collision === Element.prototype.collision || e instanceof Side)
            .map(e => [e.constructor.name, getBounds(e)])
            .filter(([, b]) => b.l - 3 * ninja.radius < ninja.x && ninja.x < b.r + 3 * ninja.radius &&
                b.t - 3 * ninja.radius < ninja.y && ninja.y < b.b + 3 * ninja.radius)
        return {x: ninja.x, y: ninja.y, speedX: ninja.speedX, speedY: ninja.speedY, screenX: screen.x,
            behindBorder: ninja.x + screen.x < screen.getDeletionBorder(), near: near}
    }
    function clientPoint(worldX, worldY)
    {
        const rect = canvas.getBoundingClientRect()
        const s = scale[version]
        return {
            x: rect.left + (worldX + screen.x) * s * rect.width / width,
            y: rect.top + (worldY + screen.y) * s * rect.height / height
        }
    }
    function dispatch(type, point)
    {
        document.dispatchEvent(new MouseEvent(type, {
            clientX: point ? point.x : 0, clientY: point ? point.y : 0, bubbles: true}))
    }
    // An action is {type: 'none'|'release'|'throw', x, y} in client coordinates.
    function apply(action)
    {
        if (action.type == 'release')
            dispatch('mouseup')
        else if (action.type == 'throw')
        {
            dispatch('mousedown', action)
            if (menu.gamePaused)
                throw Error('autopilot click hit the pause button')
        }
    }
    function throwAction(degrees)
    {
        const r = degrees * Math.PI / 180
        return throwAt(ninja.x + AIM_DISTANCE * Math.cos(r), ninja.y + AIM_DISTANCE * Math.sin(r), degrees)
    }
    // Throw toward a world point (the grapnel flies straight and catches the
    // first surface on its way).
    function throwAt(worldX, worldY, label)
    {
        const p = clientPoint(worldX, worldY)
        // never aim through the HUD pause button
        const c = viewportCoordsToCanvasCoords(p)
        if (menu.clickToPause({x: c.x / scale[version], y: c.y / scale[version]}))
            return null
        return {type: 'throw', x: p.x, y: p.y, aim: label}
    }

    function snapshot()
    {
        const seen = new Map()
        return {
            ninja: deepClone(ninja, seen),
            grapnel: deepClone(grapnel, seen),
            floors: deepClone(floors, seen),
            screen: deepClone(screen, seen)
        }
    }
    // Plays action, then holds it or releases after releaseAfter ticks.
    function rollout(base, action, releaseAfter)
    {
        const seen = new Map()
        ninja = deepClone(base.ninja, seen)
        grapnel = deepClone(base.grapnel, seen)
        floors = deepClone(base.floors, seen)
        screen = deepClone(base.screen, seen)
        ap.gameRng.state = base.rngState
        scoreText.count[version] = base.score
        ap.simDead = false

        apply(action)
        const startX = ninja.x
        let t = 0
        for (; t < HORIZON[version] && !ap.simDead; ++t)
        {
            if (t == releaseAfter && grapnel.throwed)
                apply({type: 'release'})
            physics()
        }
        if (ap.simDead)
            return t * 1000
        // Survival first; then, at the position extrapolated EXTRAPOLATE_TICKS
        // along the current velocity: progress, a clear row ahead, a short
        // detour around the next obstacle and staying mid-band.
        const v = height / scale[version]
        const band = version == 'classic' ? {top: 0.1 * height, bottom: 0.9 * height} :
            {top: Math.max(0.2 * height, -screen.y), bottom: Math.min(2 * height, -screen.y + v)}
        const ext = EXTRAPOLATE_TICKS * cyclesPerTick
        const px = ninja.x + ninja.speedX * ext
        const py = Math.min(band.bottom, Math.max(band.top, ninja.y + ninja.speedY * ext))
        const mid = (band.top + band.bottom) / 2
        const centre = Math.abs(py - mid) / ((band.bottom - band.top) / 2)
        const ahead = aheadInfo(px, py, v, band)
        // falling far behind the camera is lethal (deletion border)
        const borderMargin = ninja.x + screen.x - screen.getDeletionBorder()
        const behind = Math.max(0, BORDER_MARGIN * v - borderMargin)
        return HORIZON[version] * 1000 + 100 + (px - startX) / v * 1000 + ahead.clear / v * 600 -
            ahead.detour / v * 2000 - centre * 150 - behind / v * 3000
    }
    // Best of the plans ({action, releaseAfter}) over a cloned run.
    // Nearest element ahead blocking the row at y: free distance up to it
    // and the vertical detour around it (over or under, inside the band).
    function aheadInfo(x, y, v, band)
    {
        let clear = CLEAR_AHEAD_MAX * v
        let detour = 0
        const r = ninja.radius
        for (const floor of floors)
        {
            if (floor instanceof SideFloor)
                continue
            for (const element of floor.elements)
            {
                const pts = element.getPoints()
                const left = Math.min(...pts.map(p => p.x))
                const right = Math.max(...pts.map(p => p.x))
                if (right < x || left - x >= clear)
                    continue
                const top = Math.min(...pts.map(p => p.y)) - 2 * r
                const bottom = Math.max(...pts.map(p => p.y)) + 2 * r
                if (y < top || y > bottom)
                    continue
                clear = Math.max(0, left - x)
                const over = top > band.top ? y - top : Infinity
                const under = bottom < band.bottom ? bottom - y : Infinity
                detour = Math.min(over, under, band.bottom - band.top)
            }
        }
        return {clear, detour}
    }
    function evaluate(plans)
    {
        const real = {ninja, grapnel, floors, screen, visualEffects,
            score: scoreText.count[version], record: scoreText.record[version],
            rngState: ap.gameRng.state, fxState: ap.fxRng.state}
        const base = snapshot()
        base.rngState = real.rngState
        base.score = real.score

        ap.simulating = true
        visualEffects = null
        let best = null
        try
        {
            for (const plan of plans)
            {
                const value = rollout(base, plan.action, plan.releaseAfter)
                if (ap.debug)
                    ap.debug.push({plan, value, end: [ninja.x, ninja.y], dead: ap.simDead})
                if (!best || value > best.value)
                    best = Object.assign({value}, plan)
            }
        }
        finally
        {
            ({ninja, grapnel, floors, screen, visualEffects} = real)
            scoreText.count[version] = real.score
            scoreText.record[version] = real.record
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
    // Grappleable surfaces ahead: element top edges and the ceiling side.
    function targetPoints()
    {
        const v = width / scale[version]
        const right = -screen.x + 1.1 * v
        const points = []
        for (const floor of floors)
        {
            if (floor instanceof SideFloor)
                continue
            for (const element of floor.elements)
            {
                const pts = element.getPoints()
                const left = Math.min(...pts.map(p => p.x))
                const rightX = Math.max(...pts.map(p => p.x))
                const top = Math.min(...pts.map(p => p.y))
                if (rightX < ninja.x + 4 * ninja.radius || left > right)
                    continue
                points.push([left + 0.3 * (rightX - left), top + 1, 'top'])
            }
        }
        points.sort((a, b) => a[0] - b[0])
        const result = points.slice(0, TARGET_ELEMENTS)
        const ceilingY = version == 'classic' ? 0.1 * height : 0.2 * height
        for (const ahead of CEILING_AHEAD)
            result.push([ninja.x + ahead * v, ceilingY - 1, 'ceiling'])
        return result
    }
    function allPlans()
    {
        const plans = [currentPlan()]
        for (const releaseAfter of [Infinity, 12, 24])
            plans.push({action: {type: 'none'}, releaseAfter})
        if (grapnel.throwed)
            plans.push({action: {type: 'release'}, releaseAfter: Infinity})
        const throws = THROW_ANGLES.map(throwAction)
        for (const [x, y, kind] of targetPoints())
            throws.push(throwAt(x, y, kind))
        // a later release comes from the 'none' plans of later decisions
        for (const action of throws)
        {
            if (action)
                plans.push({action, releaseAfter: Infinity})
        }
        return plans
    }
    function act(action)
    {
        apply(action)
        ap.actions.push(Object.assign({tick: ap.tick}, action))
    }

    function traceTick()
    {
        if (ap.tick % physicsTicksPerSecond == 0)
            ap.trace.push([ap.tick, Math.round(ninja.x * 1000) / 1000, Math.round(ninja.y * 1000) / 1000])
    }
    ap.debugPlans = function()
    {
        ap.debug = []
        evaluate(allPlans())
        const out = ap.debug
        ap.debug = null
        return {ninja: [ninja.x, ninja.y, ninja.speedX, ninja.speedY], screen: [screen.x, screen.y],
            elements: floors[1].elements.map(e => [e.constructor.name, ...Object.values(getBounds(e))]), plans: out}
    }
    function getBounds(e)
    {
        const pts = e.getPoints()
        return {l: Math.round(Math.min(...pts.map(p => p.x))), r: Math.round(Math.max(...pts.map(p => p.x))),
            t: Math.round(Math.min(...pts.map(p => p.y))), b: Math.round(Math.max(...pts.map(p => p.y)))}
    }
    // One real physics tick, deciding first on decision ticks.
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
            // cheap check of the committed plan; search again if it dies
            best = evaluate([currentPlan()])
            if (best.value < HORIZON[version] * 1000)
            {
                ap.replans++
                best = evaluate(allPlans())
            }
        }
        if (best)
        {
            if (best.action.type != 'none')
                act(best.action)
            ap.pendingRelease = isFinite(best.releaseAfter) ? ap.tick + best.releaseAfter : null
        }
        traceTick()
        physics()
        ap.tick++
    }
    // Headless run: physics driven by hand until death or maxTicks.
    ap.run = function(maxTicks)
    {
        const t0 = performance.now()
        while (ap.tick < maxTicks && ap.deathTick === null)
            ap.step()
        return {seed: ap.seed, version: version, ticks: ap.tick, deathTick: ap.deathTick,
            survivalS: (ap.deathTick === null ? ap.tick : ap.deathTick) / physicsTicksPerSecond,
            score: scoreText.count[version], death: ap.death || null, actions: ap.actions, trace: ap.trace, replans: ap.replans, wallMs: performance.now() - t0}
    }
    // Replay under requestAnimationFrame: the recorded actions are dispatched
    // right before their physics tick; nothing is simulated.
    ap.replay = function(actions)
    {
        const queue = actions.slice()
        const realPhysics = window.physics
        ap.replaying = true
        window.physics = function()
        {
            while (queue.length && queue[0].tick == ap.tick)
                apply(queue.shift())
            traceTick()
            realPhysics()
            ap.tick++
        }
    }
})()
