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
    // phase}. Bounds are absolute world coordinates; phase is in [0, 1).
    movers: []
}

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
        if (!['bounce', 'solid', 'hazard'].includes(e.role)) fail('InvalidSurfaceRole', e.id + '.role')
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
        moving.add(m.element)
        if (!['x', 'y'].includes(m.axis) ||
            ![m.min, m.max, m.periodMs, m.phase].every(Number.isFinite) ||
            m.min >= m.max || m.periodMs <= 0 || m.phase < 0 || m.phase >= 1 ||
            element[m.axis] < m.min || element[m.axis] > m.max)
            fail('InvalidMoverBounds', m.id)
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
        this.elements = this.level.elements.map(model => {
            const element = new Trampoline(model)
            if (model.role === 'hazard')
            {
                element.fill = STYLE.colors.hazard.fill
                element.stroke = STYLE.colors.hazard.stroke
            }
            if (model.role === 'solid')
            {
                element.fill = '#182028'
                element.stroke = '#a3adb8'
            }
            element.id = model.id
            element.surfaceRole = model.role
            element.grapplable = model.grapplable !== false
            return element
        })
        this.byId = new Map(this.elements.map(e => [e.id, e]))
        this.applyMovers(0)
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
