// Grapple Over surface detail per role (GRAPPLE_OVER_ROLE_DETAIL), drawn over
// the world's elements and clipped to each element's own polygon, so nothing
// leaves the visible silhouette:
//   bounce  cached solder-mask material, and a fading pulse after a real bounce contact
//   solid   rivets along the edges and an edge bevel (lit up-left, shaded down-right)
//   mover   cached glass capsule with steel caps, grapple rings and a lit deck
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
    // Bounce element -> {step: world.elapsedSteps, strength, point (element-local)} of its last
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
    markContact(element, impact, point)
    {
        const config = GRAPPLE_OVER_ROLE_DETAIL.bounce
        const strength = Math.max(0, Math.min(1, (impact - config.pulseMinImpact) / (config.pulseFullImpact - config.pulseMinImpact)))
        if (element && element.surfaceRole === 'bounce' && strength > 0 && floors[0] && floors[0].elapsedSteps !== undefined)
        {
            const local = point ? {x: point.x - element.x, y: point.y - element.y} :
                element.points.reduce((a, p) => ({x: a.x + p.x / element.points.length,
                    y: a.y + p.y / element.points.length}), {x: 0, y: 0})
            this.contacts.set(element, {step: floors[0].elapsedSteps, strength, point: local})
        }
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
        drawBounceMaterial(element, world, clockMs)
        frame.bounceSprites++
        const pulse = ROLE_DETAIL.pulse(element, world)
        ctx.beginPath()
        traceRoleDetailPath(element)
        if (pulse > 0)
        {
            drawBounceContact(element, world)
            frame.pulses.push({id: element.id, intensity: pulse})
        }
        // Restore the existing crisp neon rim above material and contact glow.
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
        const horizontal = mover.axis === 'x'
        const velocity = horizontal ? element.speedX : element.speedY
        const direction = velocity < 0 ? -1 : 1
        const m = ctx.getTransform()
        const sprite = moverShellSprite(element, mover.axis, glowSpriteScale(m.a), glowSpriteScale(m.d), u)
        const b = sprite.box
        ctx.globalAlpha = 1
        ctx.drawImage(sprite.image, ox + element.points[0].x + b.left,
            oy + element.points[0].y + b.top, b.right - b.left, b.bottom - b.top)
        drawMoverAurora(sprite, ox + element.points[0].x, oy + element.points[0].y, clockMs)
        // Keep the blue neon rim above the opaque shell.
        ctx.beginPath(); traceRoleDetailPath(element)
        const neon = STYLE.strokes.neonOutline
        ctx.lineWidth = Math.min(neon.width, 0.8) * u; ctx.strokeStyle = element.stroke; ctx.stroke()
        ctx.lineWidth *= neon.coreWidthRatio; ctx.globalAlpha = neon.coreAlpha * neonPulse
        ctx.strokeStyle = neon.coreColors[element.stroke] || neon.coreColor; ctx.stroke()
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
// circuitScale is the board motif scale in use (part of every sprite key).
const BOUNCE_MATERIAL = {sprites: new Map(), star: null, circuitScale: GRAPPLE_OVER_ROLE_DETAIL.bounce.circuitScale}

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

function circuitPointSegment(p, a, b)
{
    const dx = b.x - a.x, dy = b.y - a.y, length2 = dx * dx + dy * dy
    const t = length2 ? Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / length2)) : 0
    return Math.hypot(p.x - a.x - t * dx, p.y - a.y - t * dy)
}

function circuitSegmentGap(a, b, c, d)
{
    const cross = (o, p, q) => (p.x - o.x) * (q.y - o.y) - (p.y - o.y) * (q.x - o.x)
    if (cross(a, b, c) * cross(a, b, d) < 0 && cross(c, d, a) * cross(c, d, b) < 0)
        return 0
    return Math.min(circuitPointSegment(a, c, d), circuitPointSegment(b, c, d),
        circuitPointSegment(c, a, b), circuitPointSegment(d, a, b))
}

// Coordinates are local to the shape's first point, like the sprite itself.
// Motifs are sized by s = circuit scale x one screen px: grid steps are 6..15 s
// axial or 4.24..12.73 s diagonal. Every trace vertex, via ring and pad is kept
// fully inside the polygon (no geometry change), and traces keep a clear gap,
// so the board gets fewer, wider-spaced paths as the scale grows. A shape too
// thin for a motif simply goes without it: the scale never shrinks to fit.
function bounceBoardDetail(points, box, seed, unit, circuit = 1)
{
    const s = circuit * unit
    const width = (box.right - box.left) / s, height = (box.bottom - box.top) / s
    const thin = Math.min(width, height) < 10, horizontal = width >= height
    let index = 100
    const random = () => roleDetailHash(seed, index++)
    const grid = 3 * s
    const edges = points.map((a, i) => [a, points[(i + 1) % points.length]])
    const inside = (p, margin) => pointInPolygon(points, p.x, p.y) &&
        edges.every(([a, b]) => circuitPointSegment(p, a, b) >= margin)
    const traceMargin = 0.6 * s, viaMargin = 1.6 * s, gap = 1.5 * grid
    const middle = horizontal ? (box.top + box.bottom) / 2 : (box.left + box.right) / 2
    const sample = () =>
    {
        const p = {x: Math.round((box.left + random() * (box.right - box.left)) / grid) * grid,
            y: Math.round((box.top + random() * (box.bottom - box.top)) / grid) * grid}
        // Thin shapes run their traces down the middle of the strip
        if (thin) horizontal ? p.y = middle : p.x = middle
        return p
    }
    const area = Math.abs(points.reduce((a, p, i) =>
    {
        const q = points[(i + 1) % points.length]
        return a + p.x * q.y - q.x * p.y
    }, 0)) / 2 / (s * s)
    const traces = [], segments = []
    const count = thin ? 1 + Math.floor(random() * 2) :
        Math.max(2, Math.min(6, Math.round(area / 3000))) + Math.floor(random() * 2)
    const directions = [[1,0],[1,1],[0,1],[-1,1],[-1,0],[-1,-1],[0,-1],[1,-1]]
    const clear = (a, b) => segments.every(([c, d]) => circuitSegmentGap(a, b, c, d) >= gap)
    for (let attempt = 0; traces.length < count && attempt < 4000; attempt++)
    {
        const path = [sample()], wanted = thin ? 1 + Math.floor(random() * 2) : 2 + Math.floor(random() * 3)
        if (!inside(path[0], traceMargin) || !clear(path[0], path[0])) continue
        let previous = null
        for (let j = 0; j < wanted; j++)
        {
            const d = thin ? (horizontal ? [1,0] : [0,1]) : directions[Math.floor(random() * 8)]
            // No doubling back or acute bends: a trace turns at most 90 degrees
            if (previous && d[0] * previous[0] + d[1] * previous[1] < 0) break
            const steps = d[0] && d[1] ? 1 + Math.floor(random() * 3) : 2 + Math.floor(random() * 4)
            const last = path[path.length - 1]
            const next = {x: last.x + d[0] * steps * grid, y: last.y + d[1] * steps * grid}
            // The new segment also keeps the gap from its own path, except the segment it joins
            const own = path.slice(0, -2).every((p, i) => circuitSegmentGap(last, next, p, path[i + 1]) >= gap)
            if (!inside(next, traceMargin) || !clear(last, next) || !own) break
            path.push(next); previous = d
        }
        if (path.length < 2) continue
        // A via ring only where the whole ring fits
        const vias = [path[0], path[path.length - 1]].filter(p => inside(p, viaMargin))
        traces.push({points: path, vias})
        for (let i = 1; i < path.length; i++) segments.push([path[i - 1], path[i]])
    }
    const pads = []
    for (let attempt = 0, count = thin ? 1 : 1 + Math.floor(random() * 3); pads.length < count && attempt < 1000; attempt++)
    {
        const p = sample()
        if ([[-3,-1],[3,-1],[-3,1],[3,1]].every(([x,y]) => inside({x:p.x+x*s,y:p.y+y*s}, 0.3 * s)) &&
            segments.every(([a, b]) => circuitPointSegment(p, a, b) >= 2.5 * s) &&
            pads.every(q => Math.hypot(q.x - p.x, q.y - p.y) >= gap))
            pads.push(p)
    }
    let label = null
    if (!thin && width > 60)
        for (let attempt = 0; !label && attempt < 1000; attempt++)
        {
            const p = sample()
            if ([[0,-3],[6,-3],[0,1],[6,1]].every(([x,y]) => inside({x:p.x+x*s,y:p.y+y*s}, 0)) &&
                segments.every(([a, b]) => circuitPointSegment({x: p.x + 3 * s, y: p.y - s}, a, b) >= 4 * s))
                label = {...p, text: 'R12'}
        }
    return {thin, scale: s, traces, pads, label}
}

function paintBounceBoard(c, board, config)
{
    const s = board.scale
    c.save(); c.lineJoin = c.lineCap = 'round'
    c.strokeStyle = config.trace; c.globalAlpha = config.traceAlpha; c.lineWidth = 0.8 * s
    for (const trace of board.traces)
    {
        c.beginPath()
        trace.points.forEach((p,i) => i ? c.lineTo(p.x,p.y) : c.moveTo(p.x,p.y))
        c.stroke()
    }
    c.strokeStyle = config.via; c.fillStyle = config.baseDark; c.lineWidth = 0.5 * s
    for (const trace of board.traces)
        for (const p of trace.vias)
        {
            c.beginPath(); c.arc(p.x,p.y,1.2*s,0,2*Math.PI)
            c.globalAlpha = 1; c.fill(); c.globalAlpha = config.viaAlpha; c.stroke()
        }
    c.fillStyle = config.pad; c.globalAlpha = config.padAlpha
    for (const p of board.pads)
        for (const x of [-3,1]) c.fillRect(p.x+x*s,p.y-s,2*s,2*s)
    if (board.label)
    {
        c.fillStyle = config.label; c.globalAlpha = config.labelAlpha
        c.font = 3*s + 'px monospace'; c.fillText(board.label.text,board.label.x,board.label.y)
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
    const circuit = BOUNCE_MATERIAL.circuitScale
    const key = shape + '|' + [sx, sy, unit, circuit].join(',') + '|' + free.join(',')
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
    const board = bounceBoardDetail(points, box, seed, unit, circuit)
    paintBounceBoard(c, board, config)
    const sprite = {image, box, glints: board.thin ? [] : glints, free, board, circuit,
        bright: cacheBounceContact(board, sx, sy, config)}
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

// Small cached bright copies of each trace segment and via, at the board's
// circuit scale. Animation only changes their alpha; rasterization and the
// soft contact dot happen once.
function cacheBounceContact(board, sx, sy, config)
{
    const unit = board.scale
    const parts = []
    for (const trace of board.traces)
    {
        for (let i = 1; i < trace.points.length; i++)
            parts.push({a: trace.points[i - 1], b: trace.points[i], via: false})
        for (const p of trace.vias) parts.push({a: p, b: p, via: true})
    }
    for (const part of parts)
    {
        const {a, b} = part, pad = 2 * unit
        const left = Math.min(a.x,b.x)-pad, top = Math.min(a.y,b.y)-pad
        const image = document.createElement('canvas')
        image.width = Math.ceil((Math.abs(b.x-a.x)+2*pad)*sx)
        image.height = Math.ceil((Math.abs(b.y-a.y)+2*pad)*sy)
        const c = image.getContext('2d')
        c.setTransform(sx,0,0,sy,-left*sx,-top*sy)
        c.strokeStyle = config.pulseTrace; c.lineWidth = (part.via ? 0.5 : 0.8)*unit
        c.lineCap = 'round'; c.beginPath()
        if (part.via) c.arc(a.x,a.y,1.2*unit,0,2*Math.PI)
        else {c.moveTo(a.x,a.y); c.lineTo(b.x,b.y)}
        c.stroke()
        Object.assign(part,{image,left,top,width:image.width/sx,height:image.height/sy})
    }
    const dot = document.createElement('canvas'); dot.width = dot.height = 33
    const c = dot.getContext('2d'), g = c.createRadialGradient(16.5,16.5,0,16.5,16.5,16.5)
    g.addColorStop(0,config.pulseTrace); g.addColorStop(1,config.pulseDotFade)
    c.fillStyle=g; c.fillRect(0,0,33,33)
    return {parts,dot}
}

function bounceContactWave(element, world, sprite, unit)
{
    const contact = ROLE_DETAIL.contacts.get(element), config = GRAPPLE_OVER_ROLE_DETAIL.bounce
    const ageMs = contact ? (world.elapsedSteps-contact.step)*physicsStepMs/cyclesPerTick : -1
    const t = ageMs/config.pulseMs, active = contact && t >= 0 && t < 1
    const origin = element.points[0], point = contact ?
        {x:contact.point.x-origin.x,y:contact.point.y-origin.y} : {x:0,y:0}
    const radius = t*Math.max(sprite.box.right-sprite.box.left,sprite.box.bottom-sprite.box.top)
    const parts = sprite.bright.parts.map(part => {
        const {a,b} = part, dx=b.x-a.x, dy=b.y-a.y, length2=dx*dx+dy*dy
        const f=length2 ? Math.max(0,Math.min(1,((point.x-a.x)*dx+(point.y-a.y)*dy)/length2)) : 0
        const distance=Math.hypot(point.x-a.x-f*dx,point.y-a.y-f*dy)
        return {distance,glow:active ? contact.strength*Math.max(0,1-Math.abs(distance-radius)/(18*sprite.board.scale))*(1-t) : 0}
    })
    return {point,radius,ageMs,parts,dot:active ? contact.strength*Math.max(0,1-ageMs/120) : 0}
}

function drawBounceContact(element, world)
{
    const m=ctx.getTransform(), unit=1/scale[version]
    const sprite=bounceMaterialSprite(element,world,glowSpriteScale(m.a),glowSpriteScale(m.d),unit)
    const wave=bounceContactWave(element,world,sprite,unit)
    const ox=element.x+element.points[0].x+screen.x, oy=element.y+element.points[0].y+screen.y
    ctx.save(); ctx.globalCompositeOperation='lighter'
    sprite.bright.parts.forEach((part,i) => {
        if (wave.parts[i].glow <= 0) return
        ctx.globalAlpha=wave.parts[i].glow
        ctx.drawImage(part.image,ox+part.left,oy+part.top,part.width,part.height)
    })
    if (wave.dot > 0)
    {
        ctx.globalAlpha=wave.dot
        const r=8*sprite.board.scale
        ctx.drawImage(sprite.bright.dot,ox+wave.point.x-r,oy+wave.point.y-r,2*r,2*r)
    }
    ctx.restore()
}

// Static capsule art shares the bounded material cache with bounce boards.
// Relative polygon points keep translation and travel phase out of the key.
function moverShellSprite(element, axis, sx, sy, unit)
{
    const origin = element.points[0]
    const points = element.points.map(p => ({x: Math.round((p.x-origin.x)*100)/100,
        y: Math.round((p.y-origin.y)*100)/100}))
    const key = 'mover|' + axis + '|' + points.map(p => p.x+','+p.y).join(';') + '|' + [sx,sy,unit].join(',')
    const cache = BOUNCE_MATERIAL.sprites
    if (cache.has(key))
    {
        const sprite = cache.get(key); cache.delete(key); cache.set(key,sprite); return sprite
    }
    const box = roleDetailLayout({points}).box, config = GRAPPLE_OVER_ROLE_DETAIL.mover
    const {left:l,top:t,right:r,bottom:b} = box, w=r-l, h=b-t, horizontal=axis==='x'
    const image = document.createElement('canvas')
    image.width=Math.max(1,Math.ceil(w*sx)); image.height=Math.max(1,Math.ceil(h*sy))
    const c=image.getContext('2d')
    c.setTransform(sx,0,0,sy,-l*sx,-t*sy)
    c.beginPath(); points.forEach((p,i)=>i?c.lineTo(p.x,p.y):c.moveTo(p.x,p.y)); c.closePath(); c.clip()
    c.fillStyle=config.glass; c.fillRect(l,t,w,h)
    const cap=Math.min(config.capWidth*unit,(horizontal?w:h)/2)
    const caps=horizontal ? [[l,t,cap,h],[r-cap,t,cap,h]] : [[l,t,w,cap],[l,b-cap,w,cap]]
    const glass={left:horizontal?l+cap:l,top:horizontal?t:t+cap,
        right:horizontal?r-cap:r,bottom:horizontal?b:b-cap}
    c.strokeStyle=config.highlight; c.lineWidth=config.highlightWidth*unit; c.globalAlpha=config.highlightAlpha
    c.beginPath(); c.moveTo(glass.left,glass.top+unit); c.lineTo(glass.right,glass.top+unit); c.stroke()
    c.globalAlpha=config.reflectionAlpha
    c.beginPath(); c.moveTo(glass.left,glass.bottom-unit); c.lineTo(glass.right,glass.bottom-unit); c.stroke()
    for (const [x,y,cw,ch] of caps)
    {
        c.globalAlpha=1
        const g=c.createLinearGradient(x,y,x+cw,y+ch)
        g.addColorStop(0,config.steelLight); g.addColorStop(1,config.steelDark)
        c.fillStyle=g; c.fillRect(x,y,cw,ch)
        c.strokeStyle=config.band; c.lineWidth=0.5*unit
        for (const f of [0.25,0.75])
        {
            c.beginPath()
            if(horizontal){c.moveTo(x+cw*f,y);c.lineTo(x+cw*f,y+ch)}
            else {c.moveTo(x,y+ch*f);c.lineTo(x+cw,y+ch*f)}
            c.stroke()
        }
        c.globalAlpha=config.ringAlpha; c.strokeStyle=config.ring; c.lineWidth=0.5*unit
        c.beginPath(); c.arc(x+cw/2,y+ch/2,Math.min(config.ringRadius*unit,cw/2,ch/2),0,2*Math.PI); c.stroke()
    }
    c.globalAlpha=1; c.fillStyle=config.deck
    c.fillRect(l,t,w,config.deckWidth*unit)
    const thickness=horizontal ? glass.bottom-glass.top : glass.right-glass.left
    const crossScale=horizontal ? sy : sx
    const pixel=1/crossScale, half=thickness/2
    const inset=Math.min(half*0.4,2*pixel)
    const start=(horizontal?glass.left:glass.top)+inset
    const end=(horizontal?glass.right:glass.bottom)-inset
    let seed=0
    for(const ch of points.map(p=>p.x+','+p.y).join(';'))
        seed=(Math.imul(seed,31)+ch.charCodeAt(0))>>>0
    const ribbons=Array.from({length:thickness*crossScale<6?1:3},(_,i)=>({
        amplitude:Math.min(half*0.45,Math.max(0,half-2*pixel))* (0.7+0.3*roleDetailHash(seed,i*3)),
        frequency:2+2*roleDetailHash(seed,i*3+1),
        speed:0.0004+0.0004*roleDetailHash(seed,i*3+2),
        phase:2*Math.PI*roleDetailHash(seed,i*3+9)}))
    // The glow is static material art, painted only on cache misses.
    c.save(); c.beginPath(); c.rect(glass.left+inset,glass.top+inset,
        Math.max(0,glass.right-glass.left-2*inset),Math.max(0,glass.bottom-glass.top-2*inset));c.clip()
    c.translate((glass.left+glass.right)/2,(glass.top+glass.bottom)/2)
    c.scale((glass.right-glass.left)/2,(glass.bottom-glass.top)/2)
    const glow=c.createRadialGradient(0,0,0,0,0,0.8)
    glow.addColorStop(0,config.auroraGlow);glow.addColorStop(1,config.auroraGlowFade)
    c.globalAlpha=0.3;c.fillStyle=glow;c.fillRect(-1,-1,2,2);c.restore()
    const aurora={horizontal,half,start,end,center:horizontal?(glass.top+glass.bottom)/2:(glass.left+glass.right)/2,
        pixel,strokeScale:Math.min(1,thickness*crossScale/5),ribbons}
    const sprite={image,box,glass,caps,aurora,deck:{x:l,y:t,width:w,height:config.deckWidth*unit}}
    cache.set(key,sprite)
    if(cache.size>128)cache.delete(cache.keys().next().value)
    return sprite
}

// Smooth sine curves with a zero-at-ends envelope. Hermite controls preserve
// the analytic tangent; no jagged lightning, wall-clock time or world writes.
function moverAuroraPoint(ribbon, u, clockMs)
{
    const a=u*ribbon.frequency*Math.PI+clockMs*ribbon.speed+ribbon.phase
    const envelope=Math.sin(Math.PI*u)
    return {offset:ribbon.amplitude*Math.sin(a)*envelope,
        slope:ribbon.amplitude*Math.PI*(ribbon.frequency*Math.cos(a)*envelope+Math.sin(a)*Math.cos(Math.PI*u))}
}

function drawMoverAurora(sprite, x, y, clockMs)
{
    const a=sprite.aurora, g=sprite.glass, config=GRAPPLE_OVER_ROLE_DETAIL.mover
    if(a.end<=a.start || a.half<=0)return
    ctx.save();ctx.translate(x,y)
    ctx.beginPath();ctx.rect(g.left,g.top,g.right-g.left,g.bottom-g.top);ctx.clip()
    ctx.lineCap=ctx.lineJoin='round'
    const point=(u,p)=>a.horizontal?[a.start+u*(a.end-a.start),a.center+p.offset]:
        [a.center+p.offset,a.start+u*(a.end-a.start)]
    a.ribbons.forEach((r,i)=>{
        ctx.beginPath()
        let p=moverAuroraPoint(r,0,clockMs),v=point(0,p);ctx.moveTo(...v)
        const n=64,du=1/n
        for(let j=1;j<=n;j++){
            const q=moverAuroraPoint(r,j/n,clockMs),w=point(j/n,q)
            const along=(a.end-a.start)*du/3
            const c1=a.horizontal?[v[0]+along,v[1]+p.slope*du/3]:[v[0]+p.slope*du/3,v[1]+along]
            const c2=a.horizontal?[w[0]-along,w[1]-q.slope*du/3]:[w[0]-q.slope*du/3,w[1]-along]
            ctx.bezierCurveTo(...c1,...c2,...w);p=q;v=w
        }
        ctx.strokeStyle=config.auroraColors[i]
        ctx.globalAlpha=0.25;ctx.lineWidth=3*a.pixel*a.strokeScale;ctx.stroke()
        ctx.globalAlpha=0.8;ctx.lineWidth=a.pixel*a.strokeScale;ctx.stroke()
    })
    ctx.restore()
}
