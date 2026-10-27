// Versioned world units, independent of viewport dimensions. This is the tiny
// climb fixture only; IDs are persistence keys and must survive layout edits.
const GRAPPLE_OVER_LEVEL = {
    version: 1,
    bounds: {left: -1000, top: -1000, right: 2000, bottom: 2000},
    spawn: {x: 360, y: 980},
    finish: null,
    sections: [{id: 'climb', encounters: ['opening']}],
    encounters: [{id: 'opening', elements: ['base', 'right-step', 'left-step', 'top-step']}],
    elements: [
        ['base', 120, 1100, 1000, 60],
        ['right-step', 600, 800, 300, 40],
        ['left-step', 240, 500, 280, 40],
        ['top-step', 650, 200, 300, 40],
        ['left-bound', -1060, -1000, 60, 3060, false],
        ['right-bound', 2000, -1000, 60, 3060, false],
        ['catch-floor', -1060, 2000, 3120, 60, false]
    ].map(([id, x, y, w, h, grapplable = true]) => ({id, x, y, grapplable, role: 'solid',
        points: [{x: 0, y: 0}, {x: w, y: 0}, {x: w, y: h}, {x: 0, y: h}]})),
    // Optional movers: {id, element, axis: 'x'|'y', min, max, periodMs,
    // phase, velocity?}. Bounds are absolute world coordinates; phase is in [0, 1).
    // Explicit velocity is world units/second at phase; it must agree with
    // period/phase and the element initial position. Legacy descriptors omit it.
    movers: []
}

// Fraction of horizontal velocity kept per simulation tick while the player
// circle overlaps a `drag` zone.
const DRAG_ZONE_HORIZONTAL_DAMPING = 0.8
// Fraction of vertical velocity kept per tick in a drag zone (TASK-545
// drag_zone_vertical): a 1620 drop through a 300-tall zone onto a bouncer
// rebounds to well under half the drop height instead of the release height.
const DRAG_ZONE_VERTICAL_DAMPING = 0.985

// World units by which a circle that only touches a no-grapple zone may miss
// it through floating-point rounding and still count as tangent (inside).
const NO_GRAPPLE_TANGENCY_TOLERANCE = 1e-6

function validateFixedLevel(data)
{
    const fail = (name, path) => {throw new Error(name + ': ' + path)}
    const finite = (v, path) => {
        if (!Number.isFinite(v)) fail('NonFiniteGeometry', path)
    }
    const point = (p, path) => {
        finite(p?.x, path + '.x'); finite(p?.y, path + '.y')
    }
    const bounds = (b, path) => {
        for (const k of ['left', 'top', 'right', 'bottom']) finite(b?.[k], path + '.' + k)
        if (b.left >= b.right || b.top >= b.bottom) fail('InvalidBounds', path)
    }
    if (data?.version !== 1) fail('UnsupportedVersion', 'version')
    bounds(data.bounds, 'bounds')
    point(data.spawn, 'spawn')
    if (data.finish != null) bounds(data.finish, 'finish')
    const ids = new Set()
    for (const key of ['elements', 'sections', 'encounters', 'movers'])
    {
        if (!Array.isArray(data[key])) fail('InvalidCollection', key)
        for (const entry of data[key])
        {
            if (!entry || typeof entry.id !== 'string' || !entry.id.trim()) fail('InvalidId', key)
            if (ids.has(entry.id)) fail('DuplicateId', entry.id)
            ids.add(entry.id)
        }
    }
    const cross = (a, b, c) => (b.x-a.x)*(c.y-a.y)-(b.y-a.y)*(c.x-a.x)
    for (const e of data.elements)
    {
        point(e, e.id)
        if (!['bounce', 'solid', 'hazard', 'drag', 'no-grapple'].includes(e.role)) fail('InvalidSurfaceRole', e.id + '.role')
        if (e.role === 'no-grapple' && e.grapplable !== false) fail('InvalidNoGrappleZone', e.id + ': grapplable')
        const p = e.points
        if (!Array.isArray(p) || p.length < 3) fail('MalformedPolygon', e.id)
        p.forEach((v, i) => point(v, e.id + '.points[' + i + ']'))
        let area = 0
        for (let i = 0; i < p.length; i++)
        {
            const a = p[i], b = p[(i+1)%p.length]
            if (a.x === b.x && a.y === b.y) fail('MalformedPolygon', e.id + ': repeated vertex')
            area += a.x*b.y-b.x*a.y
            for (let j = i+1; j < p.length; j++)
            {
                if (j === i+1 || (i === 0 && j === p.length-1)) continue
                const c = p[j], d = p[(j+1)%p.length]
                if (Math.max(a.x,b.x) < Math.min(c.x,d.x) || Math.max(c.x,d.x) < Math.min(a.x,b.x) ||
                    Math.max(a.y,b.y) < Math.min(c.y,d.y) || Math.max(c.y,d.y) < Math.min(a.y,b.y)) continue
                if (cross(a,b,c)*cross(a,b,d) <= 0 && cross(c,d,a)*cross(c,d,b) <= 0)
                    fail('MalformedPolygon', e.id + ': intersecting edges')
            }
        }
        if (!Number.isFinite(area) || area === 0) fail('MalformedPolygon', e.id + ': area')
        // Convex, so a panel and its transfer segment are inside when their vertices are.
        if (e.role === 'no-grapple' && p.some((b, i) => {
            const a = p[(i+p.length-1)%p.length], c = p[(i+1)%p.length]
            return cross(a, b, c) * area < 0
        })) fail('InvalidNoGrappleZone', e.id + ': not convex')
    }
    const references = (items, key, targets) => {
        const targetIds = new Set(targets.map(e => e.id))
        for (const item of items)
        {
            if (!Array.isArray(item[key])) fail('MissingReference', item.id + '.' + key)
            for (const ref of item[key])
                if (!targetIds.has(ref)) fail('MissingReference', item.id + '.' + key + ' -> ' + ref)
        }
    }
    references(data.sections, 'encounters', data.encounters)
    references(data.encounters, 'elements', data.elements)
    const moving = new Set()
    for (const m of data.movers)
    {
        const element = data.elements.find(e => e.id === m.element)
        if (!element) fail('MissingReference', m.id + '.element -> ' + m.element)
        if (moving.has(m.element)) fail('InvalidMoverBounds', m.id + ': duplicate mover')
        if (element.role === 'drag') fail('InvalidMoverBounds', m.id + ': drag zones are static')
        if (element.role === 'no-grapple') fail('InvalidNoGrappleZone', m.id + ': no-grapple zones are static')
        moving.add(m.element)
        if (!['x', 'y'].includes(m.axis) ||
            ![m.min, m.max, m.periodMs, m.phase].every(Number.isFinite) ||
            m.min >= m.max || m.periodMs <= 0 || m.phase < 0 || m.phase >= 1 ||
            element[m.axis] < m.min || element[m.axis] > m.max)
            fail('InvalidMoverBounds', m.id)
        if (m.velocity !== undefined)
        {
            const initial = m.min + (m.max - m.min) * (1 - Math.abs(2 * m.phase - 1))
            const velocity = 2000 * (m.max - m.min) / m.periodMs * (m.phase < .5 ? 1 : -1)
            if (!Number.isFinite(m.velocity) || Math.abs(m.velocity - velocity) > 1e-6 ||
                Math.abs(element[m.axis] - initial) > 1e-6)
                fail('InvalidMoverInitialState', m.id)
        }
        const low = m.axis === 'x' ? data.bounds.left : data.bounds.top
        const high = m.axis === 'x' ? data.bounds.right : data.bounds.bottom
        const offsets = element.points.map(p => p[m.axis])
        if (m.min + Math.min(...offsets) < low || m.max + Math.max(...offsets) > high)
            fail('InvalidMoverBounds', m.id + ': outside world bounds')
    }
    return data
}

// Retain Floor's rendering interface, but none of its procedural lifecycle.
class PersistentWorld extends Floor
{
    constructor(source)
    {
        validateFixedLevel(source)
        super(source.bounds.top, source.bounds.bottom, {min: 0, max: 0}, [])
        this.level = structuredClone(source)
        this.elapsedSteps = 0
        this.climbStats = {elapsedActiveMs: 0, currentHeight: 0, maxHeight: 0, completed: false}
        // Earned once on entering the upgrade section; kept until a confirmed restart.
        this.rangeUpgraded = false
        // 'single' (default) or 'double' range; see setGrapnelMode.
        this.grapnelMode = 'single'
        this.usedDouble = false
        // HUD notice time left after the upgrade; display only, never saved.
        this.rangeNoticeMs = 0
        // Drag zones are neither collidable nor grappleable: keep them out of
        // `elements`, which every collision, rope and save consumer walks.
        this.dragZones = this.level.elements.filter(model => model.role === 'drag').map(model => {
            const zone = new Trampoline({...model, fill: STYLE.colors.drag.fill, stroke: STYLE.colors.drag.stroke})
            zone.id = model.id
            zone.surfaceRole = 'drag'
            zone.grapplable = false
            return zone
        })
        // No-grapple zones are static regions, not surfaces: like drag zones they
        // stay out of `elements` (and out of dragZones, they never slow).
        this.noGrappleZones = this.level.elements.filter(model => model.role === 'no-grapple').map(model => {
            const zone = new Trampoline(model)
            zone.id = model.id
            zone.surfaceRole = 'no-grapple'
            zone.grapplable = false
            return zone
        })
        this.elements = this.level.elements.filter(model => model.role !== 'drag' && model.role !== 'no-grapple').map(model => {
            const element = new Trampoline(model)
            if (model.role === 'hazard')
            {
                element.fill = STYLE.colors.hazard.fill
                element.stroke = STYLE.colors.hazard.stroke
            }
            if (model.role === 'solid')
            {
                element.fill = '#182028'
                element.stroke = '#6a5296'
            }
            // Authored movers never invoke procedural/random constructors or warm-up.
            if (this.level.movers.some(m => m.element === model.id) && model.role !== 'hazard')
            {
                element.fill = STYLE.colors.cube.blueFill
                element.stroke = STYLE.colors.cube.blueStroke
                model.role = 'solid'
            }
            // Trampoline's legacy extrema sample alternate vertices; authored
            // triangles need all vertices for deletion/collision consumers.
            element.leftPointX = Math.min(...model.points.map(p => p.x))
            element.rightPointX = Math.max(...model.points.map(p => p.x))
            element.id = model.id
            element.surfaceRole = model.role
            element.grapplable = model.grapplable !== false
            return element
        })
        this.byId = new Map(this.elements.map(e => [e.id, e]))
        this.applyMovers(0)
        for (const e of this.elements) e.dx = e.dy = 0
    }
    applyDragZones(player)
    {
        const r2 = player.radius * player.radius
        if (this.dragZones.some(zone => pointInPolygon(zone.getPoints(), player.x, player.y) ||
            zone.getLines().some(line => segmentDistanceSquared(line, player.x, player.y) < r2)))
        {
            player.speedX *= DRAG_ZONE_HORIZONTAL_DAMPING
            player.speedY *= DRAG_ZONE_VERTICAL_DAMPING
        }
    }
    // The player is inside a no-grapple zone while its circle overlaps the
    // zone, edge and corner tangency included (up to rounding).
    playerInNoGrappleZone(player)
    {
        const r2 = Math.pow(player.radius + NO_GRAPPLE_TANGENCY_TOLERANCE, 2)
        return this.noGrappleZones.some(zone => pointInPolygon(zone.getPoints(), player.x, player.y) ||
            zone.getLines().some(line => segmentDistanceSquared(line, player.x, player.y) <= r2))
    }
    // Inside a zone any rope, attached or in flight, is dropped. Position and
    // momentum are untouched. As after a fall recovery, a press held through
    // the release cannot grapple again until it is released.
    applyNoGrappleZones(player)
    {
        this.playerInNoGrapple = this.noGrappleZones.length > 0 && this.playerInNoGrappleZone(player)
        if (!this.playerInNoGrapple || !grapnel.throwed) return
        Object.assign(grapnel, {throwed: false, grappled: false, pos: [], shotStep: null,
            aim: null, clip: null, traveled: 0})
        gameplayPressOwned = false
        stalePress = pressHeld
    }
    draw()
    {
        const cullRect = getCullRect()
        for (const zone of this.dragZones)
            if (isCullBoxVisible(getElementCullBox(zone), cullRect)) zone.draw()
        super.draw()
    }
    generatePrimaryElements() {}
    generateElements() {return 0}
    replenishElements() {}
    deleteElements() {}
    rescaleSpacing() {}
    applyMovers(timeMs)
    {
        for (const mover of this.level.movers)
        {
            const element = this.byId.get(mover.element)
            const phase = (timeMs / mover.periodMs + mover.phase) % 1
            const next = mover.min + (mover.max - mover.min) * (1 - Math.abs(2 * phase - 1))
            element.dx = mover.axis === 'x' ? next - element.x : 0
            element.dy = mover.axis === 'y' ? next - element.y : 0
            element[mover.axis] = next
            const velocity = 2000 * (mover.max - mover.min) / mover.periodMs * (phase < .5 ? 1 : -1)
            element.speedX = mover.axis === 'x' ? velocity * physicsStepMs / cyclesPerTick / 1000 : 0
            element.speedY = mover.axis === 'y' ? velocity * physicsStepMs / cyclesPerTick / 1000 : 0
        }
    }
    moveElements()
    {
        this.applyMovers(++this.elapsedSteps * physicsStepMs / cyclesPerTick)
    }
}

function loadFixedLevel(data = GRAPPLE_OVER_LEVEL)
{
    return new PersistentWorld(data)
}

// Save only explicit simulation fields, never graphics caches or object references.
const CLIMB_PLAYER_FIELDS = ['x', 'y', 'speedX', 'speedY', 'radius', 'hazardCooldownMs', 'invulnerableMs']
const CLIMB_ELEMENT_FIELDS = ['x', 'y', 'dx', 'dy', 'speedX', 'speedY']
const climbFields = (object, keys) => Object.fromEntries(keys.map(k => [k, object[k] ?? 0]))

function captureClimbState()
{
    if (version !== 'grapple_over') throw new Error('ClimbModeRequired')
    const world = floors[0]
    return {
        version: 1, levelVersion: world.level.version,
        ...(world.level.layoutId ? {layoutId: world.level.layoutId} : {}),
        simulationTick: world.elapsedSteps,
        stats: {...world.climbStats},
        player: climbFields(ninja, CLIMB_PLAYER_FIELDS),
        input: {pressHeld, stalePress},
        upgrades: {range: world.rangeUpgraded},
        grapnelMode: world.grapnelMode, usedDouble: world.usedDouble,
        elements: world.elements.map(e => ({id: e.id, ...climbFields(e, CLIMB_ELEMENT_FIELDS)})),
        grapple: {
            throwed: grapnel.throwed, grappled: grapnel.grappled,
            speedX: grapnel.speedX ?? 0, speedY: grapnel.speedY ?? 0,
            // Release retains unused rope/flight data in the live object. Save
            // only active data so ordinary mouse/touch release can roundtrip.
            traveled: grapnel.traveled, shotStep: grapnel.throwed && grapnel.shotStep ? {...grapnel.shotStep} : null,
            segments: (grapnel.throwed ? grapnel.pos : []).map(([x, y, e]) => ({id: e.isEmpty() ? null : e.id,
                x: e.isEmpty() ? x : x - e.x, y: e.isEmpty() ? y : y - e.y}))
        }
    }
}

function restoreClimbState(save)
{
    if (version !== 'grapple_over') throw new Error('ClimbModeRequired')
    const fail = () => {throw new Error('InvalidClimbState')}
    // Validate the entire payload before changing any live simulation objects.
    const shape = (value, model) => {
        if (typeof model === 'number') {if (!Number.isFinite(value)) fail()}
        else if (typeof model === 'boolean' || typeof model === 'string') {
            if (typeof value !== typeof model) fail()
        } else {
            if (!value || typeof value !== 'object' || Array.isArray(value) ||
                Object.keys(value).sort().join() !== Object.keys(model).sort().join()) fail()
            for (const key of Object.keys(model)) shape(value[key], model[key])
        }
    }
    if (!save || save.version !== 1 || save.levelVersion !== floors[0].level.version) fail()
    // Serialization version is not geometry identity. Only the shipped legacy
    // layout accepts historical saves that predate explicit layout IDs.
    const layoutId = floors[0].level.layoutId
    if (save.layoutId !== layoutId &&
        !(save.layoutId === undefined && layoutId === 'grapple-over-legacy-v3')) fail()
    const s = structuredClone(save), world = floors[0]
    if (!Number.isSafeInteger(s.simulationTick) || s.simulationTick < 0) fail()
    shape(s.player, climbFields(ninja, CLIMB_PLAYER_FIELDS))
    shape(s.stats, {elapsedActiveMs: 0, currentHeight: 0, maxHeight: 0, completed: false})
    shape(s.input, {pressHeld: false, stalePress: false})
    // Saves from before the range upgrade existed carry no upgrades.
    if (s.upgrades === undefined) s.upgrades = {range: false}
    shape(s.upgrades, {range: false})
    // Saves from before double grapnel mode load as a single-mode run.
    if (s.grapnelMode === undefined) s.grapnelMode = 'single'
    if (s.usedDouble === undefined) s.usedDouble = false
    if (s.grapnelMode !== 'single' && s.grapnelMode !== 'double') fail()
    shape(s.usedDouble, false)
    if (s.player.radius <= 0 || s.player.hazardCooldownMs < 0 || s.player.invulnerableMs < 0 ||
        s.stats.elapsedActiveMs < 0 || s.stats.maxHeight < Math.max(0, s.stats.currentHeight)) fail()
    if (!Array.isArray(s.elements) || s.elements.length !== world.elements.length) fail()
    s.elements.forEach((e, i) => {
        shape(e, {id: '', ...climbFields(world.elements[i], CLIMB_ELEMENT_FIELDS)})
        if (e.id !== world.elements[i].id) fail()
    })
    const g = s.grapple
    if (!g || !Array.isArray(g.segments)) fail()
    shape({throwed:g.throwed, grappled:g.grappled, speedX:g.speedX, speedY:g.speedY, traveled:g.traveled},
        {throwed:false, grappled:false, speedX:0, speedY:0, traveled:0})
    if (g.traveled < 0 || (!g.throwed && (g.grappled || g.segments.length)) ||
        (g.throwed && !g.segments.length) || (!g.grappled && g.throwed && g.segments.length !== 1)) fail()
    if (g.shotStep !== null) {
        shape(g.shotStep, {x:0, y:0, length:0})
        if (g.shotStep.length < 0 || !g.throwed || g.grappled) fail()
    }
    const positions = g.segments.map(p => {
        if (!p) fail()
        shape({x:p.x, y:p.y}, {x:0, y:0})
        if (!g.grappled) {if (p.id !== null) fail(); return [p.x, p.y, new Empty()]}
        const e = world.byId.get(p.id), saved = s.elements.find(e => e.id === p.id)
        if (!e || e.grapplable === false) fail()
        if (!Number.isFinite(saved.x + p.x) || !Number.isFinite(saved.y + p.y)) fail()
        return [saved.x + p.x, saved.y + p.y, e]
    })
    // Constructors rebuild derived caches; publish only after validation succeeds.
    const nextWorld = loadFixedLevel(world.level)
    nextWorld.elapsedSteps = s.simulationTick
    nextWorld.climbStats = s.stats
    nextWorld.rangeUpgraded = s.upgrades.range
    nextWorld.grapnelMode = s.grapnelMode
    nextWorld.usedDouble = s.usedDouble || s.grapnelMode === 'double'
    s.elements.forEach(e => Object.assign(nextWorld.byId.get(e.id), e))
    const nextNinja = new Ninja({...s.player, fill:ninja.fill, stroke:ninja.stroke})
    Object.assign(nextNinja, s.player)
    const nextGrapnel = new Grapnel({stroke:grapnel.stroke})
    Object.assign(nextGrapnel, {throwed:g.throwed, grappled:g.grappled,
        speedX:g.speedX, speedY:g.speedY, traveled:g.traveled, shotStep:g.shotStep,
        pos:positions.map(([x,y,e]) => [x,y,e.isEmpty() ? e : nextWorld.byId.get(e.id)])})
    floors = [nextWorld]; ninja = nextNinja; grapnel = nextGrapnel
    pressHeld = s.input.pressHeld; stalePress = s.input.stalePress
    resetPhysicsTiming()
    screen.trackGrappleOver(true)
}
