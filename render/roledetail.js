// Grapple Over surface detail per role (GRAPPLE_OVER_ROLE_DETAIL), drawn over
// the world's elements and clipped to each element's own polygon, so nothing
// leaves the visible silhouette:
//   bounce  cached solder-mask material, and a fading pulse after a real bounce contact
//   solid   rivets along the edges and an edge bevel (lit up-left, shaded down-right)
//   mover   running lights along the travel axis, chasing the travel direction
//   hazard  warning chevrons
//   drag    slow drifting particles
// Glow dots (rivets, lights, particles) are copies of cached glow sprites
// (render/glowsprites.js); no shadowBlur per frame. The clock is simulated
// time (world.elapsedSteps), so a pause freezes the animation and a seeded run
// draws the same frames. Purely visual: no geometry, role or physics field is
// written.
const ROLE_DETAIL =
{
    enabled: new URLSearchParams(location.search).get('roledetail') !== '0',
    // Bounce element -> {step: world.elapsedSteps, strength} of its last
    // approaching contact
    contacts: new WeakMap(),
    // Element -> local detail layout (points never change after construction)
    layouts: new WeakMap(),
    // Side (device px) of the element cells whose rivets share one sprite
    rivetCellPx: 256,
    // Drag motes: the clock step between repaints of a zone's mote layer,
    // and the largest layer (device px); bigger zones draw each mote
    particleStepMs: 100,
    maxLayerPx: 1 << 20,
    // What the last frame drew, for the proofs: counts per role and pulses
    frame: null,
    // impact: normal approach speed per physics cycle. Resting micro-hops
    // stay dark; a real landing lights the pad fully.
    markContact(element, impact)
    {
        const config = GRAPPLE_OVER_ROLE_DETAIL.bounce
        const strength = Math.max(0, Math.min(1, (impact - config.pulseMinImpact) / (config.pulseFullImpact - config.pulseMinImpact)))
        if (element && element.surfaceRole === 'bounce' && strength > 0 && floors[0] && floors[0].elapsedSteps !== undefined)
            this.contacts.set(element, {step: floors[0].elapsedSteps, strength})
    },
    // 0..1: strength on the contact step, easing out to 0 after pulseMs
    pulse(element, world)
    {
        const contact = this.contacts.get(element)
        if (contact === undefined)
            return 0
        const ageMs = (world.elapsedSteps - contact.step) * physicsStepMs / cyclesPerTick
        const t = ageMs / GRAPPLE_OVER_ROLE_DETAIL.bounce.pulseMs
        return t < 0 || t >= 1 ? 0 : contact.strength * (1 - t) * (1 - t)
    }
}

function drawGrappleOverRoleDetail(world)
{
    if (!ROLE_DETAIL.enabled || version !== 'grapple_over' || !world || !world.level)
        return
    const cullRect = getCullRect()
    const clockMs = world.elapsedSteps * physicsStepMs / cyclesPerTick
    const movers = world.moverByElement || new Map(world.level.movers.map(m => [m.element, m]))
    const frame = {clockMs, counts: {bounce: 0, solid: 0, mover: 0, hazard: 0, drag: 0}, pulses: [], dots: 0, bounceSprites: 0}

    // One clip per role (the union of that role's visible silhouettes)
    // instead of a save/clip/restore per element: each element's detail still
    // stays inside its role's shapes, at a fraction of the clip cost
    const groups = {drag: [], bounce: [], solid: [], mover: [], hazard: []}
    for (const zone of world.dragZones)
        if (isCullBoxVisible(getElementCullBox(zone), cullRect))
            groups.drag.push([zone, null])
    for (const element of world.elements)
    {
        // The detail layout is built from local polygon points; an element
        // without them (a Rect or Triangle placed by a test) keeps its base look
        if (!element.points || !isCullBoxVisible(getElementCullBox(element), cullRect))
            continue
        const mover = movers.get(element.id)
        const role = element.surfaceRole === 'hazard' ? 'hazard' : mover ? 'mover' : element.surfaceRole
        if (groups[role])
            groups[role].push([element, mover])
    }
    ctx.save()
    ctx.shadowBlur = 0
    ctx.globalCompositeOperation = 'source-over'
    ctx.lineJoin = 'miter'
    ctx.lineCap = 'butt'
    for (const role in groups)
    {
        const items = groups[role]
        if (!items.length)
            continue
        ctx.save()
        ctx.beginPath()
        for (const [element] of items)
            traceRoleDetailPath(element)
        ctx.clip()
        for (const [element, mover] of items)
            drawRoleDetail(element, role, mover, clockMs, world, frame)
        ctx.restore()
    }
    ctx.restore()
    ROLE_DETAIL.frame = frame
}

function roleDetailLayout(element)
{
    let layout = ROLE_DETAIL.layouts.get(element)
    if (layout)
        return layout
    const points = element.points
    let area = 0
    for (let i = 0, j = points.length - 1; i < points.length; j = i++)
        area += points[j].x * points[i].y - points[i].x * points[j].y
    // Outward normal of edge a->b: (dy, -dx) for a positive (y-down clockwise) area
    const sign = area >= 0 ? 1 : -1
    const edges = []
    for (let i = 0; i < points.length; ++i)
    {
        const a = points[i], b = points[(i + 1) % points.length]
        const length = Math.hypot(b.x - a.x, b.y - a.y)
        if (length < 1e-6)
            continue
        edges.push({a, b, length, ux: (b.x - a.x) / length, uy: (b.y - a.y) / length,
            nx: sign * (b.y - a.y) / length, ny: -sign * (b.x - a.x) / length})
    }
    const xs = points.map(p => p.x), ys = points.map(p => p.y)
    layout = {edges, area: Math.abs(area) / 2,
        box: {left: Math.min(...xs), top: Math.min(...ys), right: Math.max(...xs), bottom: Math.max(...ys)}}
    ROLE_DETAIL.layouts.set(element, layout)
    return layout
}

// Adds element's outline to the current path as one closed subpath
function traceRoleDetailPath(element)
{
    const points = element.getPoints()
    ctx.moveTo(points[0].x + screen.x, points[0].y + screen.y)
    for (let i = 1; i < points.length; ++i)
        ctx.lineTo(points[i].x + screen.x, points[i].y + screen.y)
    ctx.closePath()
}

function drawRoleDetail(element, role, mover, clockMs, world, frame)
{
    const style = GRAPPLE_OVER_ROLE_DETAIL
    const layout = roleDetailLayout(element)
    const ox = element.x + screen.x, oy = element.y + screen.y
    // Screen px to world units
    const u = 1 / scale[version]
    const dots = []
    // Inside its role's clip (drawGrappleOverRoleDetail)
    if (role === 'bounce')
    {
        const config = style.bounce
        drawBounceMaterial(element, world, clockMs)
        frame.bounceSprites++
        const pulse = ROLE_DETAIL.pulse(element, world)
        ctx.beginPath()
        traceRoleDetailPath(element)
        if (pulse > 0)
        {
            ctx.globalAlpha = config.pulseFillAlpha * pulse
            ctx.fillStyle = config.pulseFill
            ctx.fill()
            frame.pulses.push({id: element.id, intensity: pulse})
        }
        // Restore the existing crisp neon rim above material and contact fill.
        const neon = STYLE.strokes.neonOutline
        ctx.globalAlpha = 1
        ctx.lineWidth = neon.width * u
        ctx.strokeStyle = element.stroke
        ctx.stroke()
        ctx.lineWidth *= neon.coreWidthRatio
        ctx.globalAlpha = neon.coreAlpha * neonPulse
        ctx.strokeStyle = neon.coreColors[element.stroke] || neon.coreColor
        ctx.stroke()
    }
    else if (role === 'solid')
    {
        const config = style.solid
        for (const pass of [[config.light, config.lightAlpha, 1], [config.shade, config.shadeAlpha, -1]])
        {
            ctx.beginPath()
            for (const e of layout.edges)
                if ((e.nx + e.ny < 0 ? 1 : -1) === pass[2])
                {
                    ctx.moveTo(e.a.x + ox, e.a.y + oy)
                    ctx.lineTo(e.b.x + ox, e.b.y + oy)
                }
            ctx.globalAlpha = pass[1]
            ctx.strokeStyle = pass[0]
            ctx.lineWidth = config.bevel * 2 * u
            ctx.stroke()
        }
        // The rivet spacing is in screen px: relayout if the world scale changes
        if (!layout.rivets || layout.rivetUnit !== u)
        {
            layout.rivets = []
            layout.rivetUnit = u
            for (const e of layout.edges)
            {
                const count = Math.floor(e.length / (config.rivetSpacing * u))
                for (let k = 0; k < count; ++k)
                {
                    const along = (k + 0.5) * e.length / count
                    const x = e.a.x + e.ux * along - e.nx * config.rivetInset * u
                    const y = e.a.y + e.uy * along - e.ny * config.rivetInset * u
                    if (pointInPolygon(element.points, x, y))
                        layout.rivets.push({x, y})
                }
            }
        }
        for (const r of layout.rivets)
            dots.push([r.x + ox, r.y + oy, 1])
        if (dots.length)
            drawRoleDetailRivets(layout, config.rivet, config.rivetRadius * u, ox, oy)
    }
    else if (role === 'mover')
    {
        const config = style.mover
        const box = layout.box
        const horizontal = mover.axis === 'x'
        const velocity = horizontal ? element.speedX : element.speedY
        const direction = velocity < 0 ? -1 : 1
        const from = (horizontal ? box.left : box.top) + config.inset * u
        const to = (horizontal ? box.right : box.bottom) - config.inset * u
        const across = horizontal ? (box.top + box.bottom) / 2 : (box.left + box.right) / 2
        const count = Math.max(2, Math.floor((to - from) / (config.spacing * u)) + 1)
        const head = clockMs / config.periodMs
        for (let i = 0; i < count; ++i)
        {
            const along = count > 1 ? from + (to - from) * i / (count - 1) : (from + to) / 2
            // A bright head every 4 lights moves one light per period/4 along the travel
            const wave = 0.5 + 0.5 * Math.cos(2 * Math.PI * (i / 4 - direction * head))
            const level = config.dim + (1 - config.dim) * Math.pow(wave, 4)
            dots.push(horizontal ? [along + ox, across + oy, level] : [across + ox, along + oy, level])
        }
        drawRoleDetailDots(config.light, config.lightRadius * u, dots)
        frame.movers = frame.movers || []
        frame.movers.push({id: element.id, axis: mover.axis, direction})
    }
    else if (role === 'hazard')
    {
        const config = style.hazard
        const box = layout.box
        const w = box.right - box.left, h = box.bottom - box.top
        const spacing = config.spacing * u
        ctx.beginPath()
        if (w >= h)
            for (let x = box.left - h; x < box.right + spacing; x += spacing)
            {
                ctx.moveTo(x + ox, box.top + oy)
                ctx.lineTo(x + h / 2 + ox, (box.top + box.bottom) / 2 + oy)
                ctx.lineTo(x + ox, box.bottom + oy)
            }
        else
            for (let y = box.top - w; y < box.bottom + spacing; y += spacing)
            {
                ctx.moveTo(box.left + ox, y + oy)
                ctx.lineTo((box.left + box.right) / 2 + ox, y + w / 2 + oy)
                ctx.lineTo(box.right + ox, y + oy)
            }
        ctx.globalAlpha = config.alpha
        ctx.strokeStyle = config.chevron
        ctx.lineWidth = config.width * u
        ctx.stroke()
    }
    else if (role === 'drag')
    {
        const config = style.drag
        const box = layout.box
        const w = box.right - box.left, h = box.bottom - box.top
        const count = Math.max(config.min, Math.min(config.max, Math.round(layout.area / (u * u) * config.density)))
        let seed = 0
        for (let i = 0; i < element.id.length; ++i)
            seed = (seed * 31 + element.id.charCodeAt(i)) >>> 0
        // The motes drift about a pixel per second: they are painted into the
        // zone's layer once per particleStepMs of the clock (the steps of the
        // zones staggered) and the layer is copied in between
        const step = ROLE_DETAIL.particleStepMs
        const phase = roleDetailHash(seed, 4 * config.max) * step
        const stamp = Math.floor((clockMs + phase) / step)
        const seconds = (stamp * step - phase) / 1000
        for (let i = 0; i < count; ++i)
        {
            const u = roleDetailHash(seed, i * 4), v = roleDetailHash(seed, i * 4 + 1)
            const vx = (roleDetailHash(seed, i * 4 + 2) - 0.5) * config.speed * u
            const vy = -(0.4 + 0.6 * roleDetailHash(seed, i * 4 + 3)) * config.speed * u
            const x = box.left + ((u * w + vx * seconds) % w + w) % w
            const y = box.top + ((v * h + vy * seconds) % h + h) % h
            dots.push([x, y, 0.55 + 0.45 * Math.sin(seconds * 1.3 + i * 2.1)])
        }
        drawRoleDetailDotLayer(layout, stamp, config.particle, config.radius * u, dots, config.alpha, ox, oy)
    }
    frame.counts[role]++
    frame.dots += dots.length
}

// Deterministic 0..1 from (seed, index)
function roleDetailHash(seed, index)
{
    let h = (seed ^ Math.imul(index + 1, 0x9e3779b1)) >>> 0
    h = Math.imul(h ^ (h >>> 16), 0x85ebca6b) >>> 0
    h = Math.imul(h ^ (h >>> 13), 0xc2b2ae35) >>> 0
    return ((h ^ (h >>> 16)) >>> 0) / 4294967296
}

// Draws dots ([x, y, level] in element units) through the element's layer
// canvas (its box in device px): the dots are painted into it with the cached
// glow dot only when stamp or the canvas scale changes, and every frame copies
// the layer once
function drawRoleDetailDotLayer(layout, stamp, color, radius, dots, alpha, ox, oy)
{
    const m = ctx.getTransform()
    const sx = glowSpriteScale(m.a), sy = glowSpriteScale(m.d)
    const dot = getRoleDetailDotSprite(color, radius, sx)
    const half = dot.width / 2
    const box = layout.box
    const left = Math.floor(box.left * sx - half), top = Math.floor(box.top * sy - half)
    const width = Math.ceil(box.right * sx + half) - left + 1
    const height = Math.ceil(box.bottom * sy + half) - top + 1
    if (width * height > ROLE_DETAIL.maxLayerPx)
        return drawRoleDetailDots(color, radius, dots.map(([x, y, level]) => [x + ox, y + oy, level]), alpha)
    const key = stamp + '|' + color + '|' + radius + '|' + sx + '|' + sy
    let layer = layout.dotLayer
    if (!layer)
        layer = layout.dotLayer = {canvas: document.createElement('canvas'), key: null}
    if (layer.key !== key)
    {
        const canvas = layer.canvas
        if (canvas.width !== width || canvas.height !== height)
        {
            canvas.width = width
            canvas.height = height
        }
        const context = canvas.getContext('2d')
        context.clearRect(0, 0, width, height)
        for (const [x, y, level] of dots)
        {
            context.globalAlpha = alpha * level
            context.drawImage(dot, Math.round(x * sx - half) - left, Math.round(y * sy - half) - top)
        }
        layer.key = key
    }
    const x = Math.round(m.a * ox + m.e) + left, y = Math.round(m.d * oy + m.f) + top
    if (x >= ctx.canvas.width || y >= ctx.canvas.height || x + width <= 0 || y + height <= 0)
        return
    ctx.save()
    ctx.setTransform(1, 0, 0, 1, 0, 0)
    ctx.globalAlpha = 1
    ctx.drawImage(layer.canvas, x, y)
    ctx.restore()
}

// Copies one cached glow dot per [x, y, level] (logical screen coordinates)
// at globalAlpha alpha * level, centred on whole device pixels
// The glow dot of color and radius (logical units) at canvas scale sx
function getRoleDetailDotSprite(color, radius, sx)
{
    const blur = radius * 2.5 * sx
    const pad = glowSpritePad(blur, radius, sx)
    const size = Math.ceil(radius * 2 * sx) + pad * 2
    return getGlowSprite('roledetail|dot|' + color + '|' + radius + '|' + sx,
        () => buildGlowSprite(size, size, pad, sx, sx, -radius, -radius, 1, () =>
        {
            ctx.fillStyle = color
            ctx.shadowColor = color
            ctx.shadowBlur = blur
            ctx.beginPath()
            ctx.arc(0, 0, radius, 0, Math.PI * 2)
            ctx.fill()
            ctx.shadowBlur = 0
            ctx.fillStyle = '#ffffff'
            ctx.globalAlpha = 0.6
            ctx.beginPath()
            ctx.arc(0, 0, radius * 0.45, 0, Math.PI * 2)
            ctx.fill()
        }))
}

// Rivets never move on their element, and every drawImage has a fixed cost
// that dominates a small dot: they are copied from a few cell sprites per
// element (ROLE_DETAIL.rivetCellPx device px squares of the element), each
// composited once from the cached glow dot, instead of one copy per rivet.
// Every rivet lands within a device pixel of where its own copy would.
function drawRoleDetailRivets(layout, color, radius, ox, oy)
{
    const m = ctx.getTransform()
    const sx = glowSpriteScale(m.a), sy = glowSpriteScale(m.d)
    const key = color + '|' + radius + '|' + sx + '|' + sy
    if (layout.rivetCellsKey !== key)
    {
        const dot = getRoleDetailDotSprite(color, radius, sx)
        const half = dot.width / 2, cell = ROLE_DETAIL.rivetCellPx
        const groups = new Map()
        for (const r of layout.rivets)
        {
            const x = Math.round(r.x * sx - half), y = Math.round(r.y * sy - half)
            const id = Math.floor(x / cell) + ',' + Math.floor(y / cell)
            if (!groups.has(id))
                groups.set(id, [])
            groups.get(id).push([x, y])
        }
        layout.rivetCells = []
        for (const points of groups.values())
        {
            const left = Math.min(...points.map(p => p[0])), top = Math.min(...points.map(p => p[1]))
            const sprite = document.createElement('canvas')
            sprite.width = Math.max(...points.map(p => p[0])) - left + dot.width
            sprite.height = Math.max(...points.map(p => p[1])) - top + dot.height
            const context = sprite.getContext('2d')
            for (const [x, y] of points)
                context.drawImage(dot, x - left, y - top)
            layout.rivetCells.push({sprite, left, top})
        }
        layout.rivetCellsKey = key
    }
    const baseX = Math.round(m.a * ox + m.e), baseY = Math.round(m.d * oy + m.f)
    const width = ctx.canvas.width, height = ctx.canvas.height
    ctx.save()
    ctx.setTransform(1, 0, 0, 1, 0, 0)
    ctx.globalAlpha = 1
    for (const {sprite, left, top} of layout.rivetCells)
    {
        const x = baseX + left, y = baseY + top
        if (x < width && y < height && x + sprite.width > 0 && y + sprite.height > 0)
            ctx.drawImage(sprite, x, y)
    }
    ctx.restore()
}

function drawRoleDetailDots(color, radius, dots, alpha = 1)
{
    const m = ctx.getTransform()
    const sprite = getRoleDetailDotSprite(color, radius, glowSpriteScale(m.a))
    const half = sprite.width / 2
    const right = ctx.canvas.width + half, bottom = ctx.canvas.height + half
    ctx.save()
    ctx.setTransform(1, 0, 0, 1, 0, 0)
    for (const [x, y, level] of dots)
    {
        // Off-canvas dots (long walls and drag zones) are skipped
        const px = m.a * x + m.e, py = m.d * y + m.f
        if (px < -half || py < -half || px > right || py > bottom)
            continue
        ctx.globalAlpha = alpha * level
        ctx.drawImage(sprite, Math.round(px - half), Math.round(py - half))
    }
    ctx.restore()
}


// Material-owned state only: no cache or render fields are added to colliders.
const BOUNCE_MATERIAL = {sprites: new Map(), star: null}

function bounceFreeEdges(element, world)
{
    const points = element.getPoints()
    return points.map((a, i) =>
    {
        const b = points[(i + 1) % points.length]
        return !world.elements.some(other => other !== element && other.getPoints().some((c, j, ps) =>
        {
            const d = ps[(j + 1) % ps.length]
            const dx = d.x - c.x, dy = d.y - c.y, length = Math.hypot(dx, dy)
            if (length < 1e-6) return false
            const on = p => Math.abs(dx * (p.y - c.y) - dy * (p.x - c.x)) / length < 1e-5 &&
                (p.x - c.x) * dx + (p.y - c.y) * dy >= -1e-5 &&
                (p.x - d.x) * dx + (p.y - d.y) * dy <= 1e-5
            return on(a) && on(b)
        }))
    })
}

// Coordinates are local to the shape's first point, like the sprite itself.
// Rejection keeps whole walks inside the convex collision polygon without
// changing it; grid steps are 6..15 px axial or 4.24..12.73 px diagonal.
function bounceBoardDetail(points, box, seed, unit)
{
    const width = (box.right - box.left) / unit, height = (box.bottom - box.top) / unit
    const thin = Math.min(width, height) < 10, horizontal = width >= height
    let index = 100
    const random = () => roleDetailHash(seed, index++)
    const grid = 3 * unit
    const inside = p => pointInPolygon(points, p.x, p.y)
    const sample = () => ({x: Math.round((box.left + random() * (box.right - box.left)) / grid) * grid,
        y: Math.round((box.top + random() * (box.bottom - box.top)) / grid) * grid})
    const traces = [], count = thin ? 2 + Math.floor(random() * 2) : 10 + Math.floor(random() * 11)
    const directions = [[1,0],[1,1],[0,1],[-1,1],[-1,0],[-1,-1],[0,-1],[1,-1]]
    for (let attempt = 0; traces.length < count && attempt < 4000; attempt++)
    {
        const path = [sample()], segments = 3 + Math.floor(random() * 4)
        if (!inside(path[0])) continue
        for (let j = 0; j < segments; j++)
        {
            const d = thin ? (horizontal ? [1,0] : [0,1]) : directions[Math.floor(random() * 8)]
            const steps = d[0] && d[1] ? 1 + Math.floor(random() * 3) : 2 + Math.floor(random() * 4)
            const last = path[path.length - 1]
            const next = {x: last.x + d[0] * steps * grid, y: last.y + d[1] * steps * grid}
            if (!inside(next)) break
            path.push(next)
        }
        if (path.length === segments + 1)
            traces.push({points: path, vias: [path[0], path[path.length - 1]]})
    }
    const pads = []
    if (!thin)
        for (let attempt = 0, count = 2 + Math.floor(random() * 4); pads.length < count && attempt < 1000; attempt++)
        {
            const p = sample()
            if ([[-3,-1],[3,-1],[-3,1],[3,1]].every(([x,y]) => inside({x:p.x+x*unit,y:p.y+y*unit})))
                pads.push(p)
        }
    let label = null
    if (!thin && width > 60)
        for (let attempt = 0; !label && attempt < 1000; attempt++)
        {
            const p = sample()
            if ([[0,-3],[6,-3],[0,1],[6,1]].every(([x,y]) => inside({x:p.x+x*unit,y:p.y+y*unit})))
                label = {...p, text: 'R12'}
        }
    return {thin, traces, pads, label}
}

function paintBounceBoard(c, board, unit, config)
{
    c.save(); c.lineJoin = c.lineCap = 'round'
    c.strokeStyle = config.trace; c.globalAlpha = config.traceAlpha; c.lineWidth = 0.8 * unit
    for (const trace of board.traces)
    {
        c.beginPath()
        trace.points.forEach((p,i) => i ? c.lineTo(p.x,p.y) : c.moveTo(p.x,p.y))
        c.stroke()
    }
    c.strokeStyle = config.via; c.fillStyle = config.baseDark; c.lineWidth = 0.5 * unit
    for (const trace of board.traces)
        for (const p of trace.vias)
        {
            c.beginPath(); c.arc(p.x,p.y,1.2*unit,0,2*Math.PI)
            c.globalAlpha = 1; c.fill(); c.globalAlpha = config.viaAlpha; c.stroke()
        }
    c.fillStyle = config.pad; c.globalAlpha = config.padAlpha
    for (const p of board.pads)
        for (const x of [-3,1]) c.fillRect(p.x+x*unit,p.y-unit,2*unit,2*unit)
    if (board.label)
    {
        c.fillStyle = config.label; c.globalAlpha = config.labelAlpha
        c.font = 3*unit + 'px monospace'; c.fillText(board.label.text,board.label.x,board.label.y)
    }
    c.restore()
}

function bounceMaterialSprite(element, world, sx, sy, unit)
{
    const origin = element.points[0]
    const points = element.points.map(p => ({x: Math.round((p.x - origin.x) * 100) / 100,
        y: Math.round((p.y - origin.y) * 100) / 100}))
    const free = bounceFreeEdges(element, world)
    const shape = 'bounce|' + points.map(p => p.x + ',' + p.y).join(';')
    const key = shape + '|' + [sx, sy, unit].join(',') + '|' + free.join(',')
    const cache = BOUNCE_MATERIAL.sprites
    if (cache.has(key))
    {
        const sprite = cache.get(key)
        cache.delete(key); cache.set(key, sprite)
        return sprite
    }
    let seed = 0
    for (const ch of shape) seed = (Math.imul(seed, 31) + ch.charCodeAt(0)) >>> 0
    const layout = roleDetailLayout({points})
    const box = layout.box, config = GRAPPLE_OVER_ROLE_DETAIL.bounce
    const image = document.createElement('canvas')
    image.width = Math.max(1, Math.ceil((box.right - box.left) * sx))
    image.height = Math.max(1, Math.ceil((box.bottom - box.top) * sy))
    const c = image.getContext('2d')
    c.setTransform(sx, 0, 0, sy, -box.left * sx, -box.top * sy)
    c.beginPath()
    points.forEach((p, i) => i ? c.lineTo(p.x, p.y) : c.moveTo(p.x, p.y))
    c.closePath(); c.clip()
    const base = c.createLinearGradient(box.left, box.top, box.right, box.bottom)
    base.addColorStop(0, config.baseLight); base.addColorStop(1, config.baseDark)
    c.fillStyle = base
    c.fillRect(box.left, box.top, box.right - box.left, box.bottom - box.top)
    layout.edges.forEach((e, i) =>
    {
        if (!free[i]) return
        const thickness = Math.max(...points.map(p => -(p.x - e.a.x) * e.nx - (p.y - e.a.y) * e.ny))
        const lip = Math.min(config.lipWidth * unit, thickness * config.lipShare)
        if (lip <= 0) return
        const gradient = c.createLinearGradient(e.a.x, e.a.y, e.a.x - e.nx * lip, e.a.y - e.ny * lip)
        gradient.addColorStop(0, config.lip); gradient.addColorStop(1, config.lipFade)
        c.fillStyle = gradient; c.beginPath(); c.moveTo(e.a.x, e.a.y); c.lineTo(e.b.x, e.b.y)
        c.lineTo(e.b.x - e.nx * lip, e.b.y - e.ny * lip)
        c.lineTo(e.a.x - e.nx * lip, e.a.y - e.ny * lip); c.closePath(); c.fill()
    })
    // Convex combinations stay inside these convex surface polygons, even bars.
    const center = points.reduce((a, p) => ({x: a.x + p.x / points.length, y: a.y + p.y / points.length}), {x: 0, y: 0})
    const glints = Array.from({length: 2 + Math.floor(roleDetailHash(seed, 0) * 3)}, (_, i) =>
    {
        const e = layout.edges[i % layout.edges.length], t = 0.2 + 0.6 * roleDetailHash(seed, i * 3 + 1)
        return {x: center.x * 0.35 + (e.a.x + (e.b.x - e.a.x) * t) * 0.65,
            y: center.y * 0.35 + (e.a.y + (e.b.y - e.a.y) * t) * 0.65,
            period: 2400 + 1600 * roleDetailHash(seed, i * 3 + 2), phase: roleDetailHash(seed, i * 3 + 3)}
    })
    const board = bounceBoardDetail(points, box, seed, unit)
    paintBounceBoard(c, board, unit, config)
    const sprite = {image, box, glints: board.thin ? [] : glints, free, board}
    cache.set(key, sprite)
    if (cache.size > 128) cache.delete(cache.keys().next().value)
    return sprite
}

function drawBounceMaterial(element, world, clockMs)
{
    const m = ctx.getTransform(), unit = 1 / scale[version]
    const sprite = bounceMaterialSprite(element, world, glowSpriteScale(m.a), glowSpriteScale(m.d), unit)
    const config = GRAPPLE_OVER_ROLE_DETAIL.bounce
    if (!BOUNCE_MATERIAL.star)
    {
        const star = document.createElement('canvas'); star.width = star.height = 33
        const c = star.getContext('2d'); c.fillStyle = config.glint; c.beginPath()
        for (let i = 0; i < 8; i++)
        {
            const a = i * Math.PI / 4, r = i % 2 ? 3 : 16
            c.lineTo(16.5 + Math.cos(a) * r, 16.5 + Math.sin(a) * r)
        }
        c.closePath(); c.fill(); BOUNCE_MATERIAL.star = star
    }
    const ox = element.x + element.points[0].x + screen.x, oy = element.y + element.points[0].y + screen.y
    ctx.save(); ctx.beginPath(); traceRoleDetailPath(element); ctx.clip(); ctx.globalAlpha = 1
    const b = sprite.box
    ctx.drawImage(sprite.image, ox + b.left, oy + b.top, b.right - b.left, b.bottom - b.top)
    const r = config.glintRadius * unit
    for (const g of sprite.glints)
    {
        ctx.globalAlpha = 0.2 + 0.8 * Math.pow(0.5 + 0.5 * Math.sin(2 * Math.PI * (clockMs / g.period + g.phase)), 2)
        ctx.drawImage(BOUNCE_MATERIAL.star, ox + g.x - r, oy + g.y - r, 2 * r, 2 * r)
    }
    ctx.restore()
}
