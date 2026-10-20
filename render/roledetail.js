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

    ctx.save()
    ctx.shadowBlur = 0
    ctx.globalCompositeOperation = 'source-over'
    for (const zone of world.dragZones)
        if (isCullBoxVisible(getElementCullBox(zone), cullRect))
            drawRoleDetail(zone, 'drag', null, clockMs, world, frame)
    for (const element of world.elements)
    {
        if (!isCullBoxVisible(getElementCullBox(element), cullRect))
            continue
        const mover = movers.get(element.id)
        const role = element.surfaceRole === 'hazard' ? 'hazard' : mover ? 'mover' : element.surfaceRole
        drawRoleDetail(element, role, mover, clockMs, world, frame)
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

function traceRoleDetailPath(element)
{
    const points = element.getPoints()
    ctx.beginPath()
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
    ctx.save()
    traceRoleDetailPath(element)
    ctx.clip()
    ctx.lineJoin = 'miter'
    ctx.lineCap = 'butt'
    if (role === 'bounce')
    {
        const config = style.bounce
        const pulse = ROLE_DETAIL.pulse(element, world)
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
            drawRoleDetailDots(config.rivet, config.rivetRadius * u, dots)
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
        const seconds = clockMs / 1000
        let seed = 0
        for (let i = 0; i < element.id.length; ++i)
            seed = (seed * 31 + element.id.charCodeAt(i)) >>> 0
        for (let i = 0; i < count; ++i)
        {
            const u = roleDetailHash(seed, i * 4), v = roleDetailHash(seed, i * 4 + 1)
            const vx = (roleDetailHash(seed, i * 4 + 2) - 0.5) * config.speed * u
            const vy = -(0.4 + 0.6 * roleDetailHash(seed, i * 4 + 3)) * config.speed * u
            const x = box.left + ((u * w + vx * seconds) % w + w) % w
            const y = box.top + ((v * h + vy * seconds) % h + h) % h
            dots.push([x + ox, y + oy, 0.55 + 0.45 * Math.sin(seconds * 1.3 + i * 2.1)])
        }
        drawRoleDetailDots(config.particle, config.radius * u, dots, config.alpha)
    }
    ctx.restore()
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

// Copies one cached glow dot per [x, y, level] (logical screen coordinates)
// at globalAlpha alpha * level, centred on whole device pixels
function drawRoleDetailDots(color, radius, dots, alpha = 1)
{
    const m = ctx.getTransform()
    const sx = glowSpriteScale(m.a)
    const blur = radius * 2.5 * sx
    const pad = glowSpritePad(blur, radius, sx)
    const size = Math.ceil(radius * 2 * sx) + pad * 2
    const sprite = getGlowSprite('roledetail|dot|' + color + '|' + radius + '|' + sx,
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
