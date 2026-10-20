// Grapple Over surface detail per role (GRAPPLE_OVER_ROLE_DETAIL), drawn over
// the world's elements and clipped to each element's own polygon, so nothing
// leaves the visible silhouette:
//   bounce  lit edge strip, and a fading pulse after a real bounce contact
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
    const movers = world.moverByElement || (world.moverByElement = new Map(world.level.movers.map(m => [m.element, m])))
    const frame = {clockMs, counts: {bounce: 0, solid: 0, mover: 0, hazard: 0, drag: 0}, pulses: [], dots: 0}

    // One clip per role (the union of that role's visible silhouettes)
    // instead of a save/clip/restore per element: each element's detail still
    // stays inside its role's shapes, at a fraction of the clip cost
    const groups = {drag: [], bounce: [], solid: [], mover: [], hazard: []}
    for (const zone of world.dragZones)
        if (isCullBoxVisible(getElementCullBox(zone), cullRect))
            groups.drag.push([zone, null])
    for (const element of world.elements)
    {
        if (!isCullBoxVisible(getElementCullBox(element), cullRect))
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
        // The path stroke is centred on the edge: the clip keeps its inner half
        ctx.globalAlpha = Math.min(1, config.stripAlpha * (1 + pulse))
        ctx.strokeStyle = config.strip
        ctx.lineWidth = config.stripWidth * 2 * (1 + pulse) * u
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

