// Grapple Over section landmarks (GRAPPLE_OVER_LANDMARKS): each section's
// mountain.js landmark is drawn as one large glowing silhouette in that
// section's palette, at background depth (in the background renderer, after
// the palette wash, so it glows over the far scenery but stays behind the
// world). Each silhouette is one glow sprite built once (render/glowsprites.js:
// the only shadowBlur, at build time); a frame only copies sprites. Purely
// visual: there is no collider, so shots and the player pass through.
const LANDMARKS =
{
    enabled: new URLSearchParams(location.search).get('landmarks') !== '0',
    // Per viewport: each section's entry camera and screen anchor
    anchors: null,
    anchorsKey: null,
    // What the last game-canvas frame drew, for the proofs
    frame: null
}

// Entry pose of a section: the start of its first encounter. Its camera is
// the snapped Grapple Over camera there (the real tracker, state restored).
function grappleOverLandmarkAnchors()
{
    const config = GRAPPLE_OVER_LANDMARKS
    const key = [width, height, scale[version], floors[0].level.bounds.top].join('|')
    if (LANDMARKS.anchorsKey === key)
        return LANDMARKS.anchors
    const encounters = new Map(GRAPPLE_OVER_MOUNTAIN.encounters.map(e => [e.id, e]))
    const saved = [ninja.x, ninja.y, ninja.speedX, ninja.speedY, screen.x, screen.y]
    const k = scale[version]
    const anchors = []
    try
    {
        GRAPPLE_OVER_MOUNTAIN.sections.forEach((section, index) =>
        {
            const first = encounters.get(section.encounters[0])
            const entry = first.start || first
            ninja.x = entry.x
            ninja.y = entry.y
            ninja.speedX = ninja.speedY = 0
            screen.trackGrappleOver(true)
            const camera = {x: screen.x, y: screen.y}
            // Where the landmark point lies on screen from the entry pose,
            // pulled inside the viewport with the whole silhouette in frame
            const clamp = (v, low, high) => Math.max(low, Math.min(high, v))
            const x = clamp((section.landmark.x + camera.x) * k,
                config.margin + config.width / 2, width - config.margin - config.width / 2)
            const y = clamp((section.landmark.y + camera.y) * k,
                config.margin + config.height / 2, height - config.margin - config.height / 2)
            anchors.push({id: section.landmark.id, name: section.landmark.name, section: section.id, band: index,
                entry: {x: entry.x, y: entry.y}, camera, x, y})
        })
    }
    finally
    {
        [ninja.x, ninja.y, ninja.speedX, ninja.speedY, screen.x, screen.y] = saved
    }
    LANDMARKS.anchorsKey = key
    return LANDMARKS.anchors = anchors
}

// Draws the landmarks into renderer.ctx (logical units). A landmark follows
// `factor` of the camera motion from its entry camera. It is at full strength
// when its entry camera is the nearest one and fades out as the camera gets
// rivalSpan farther from it than from the nearest (several upper sections
// start under nearly the same clamped camera), and past fadeNear..fadeFar
// from it; invisible ones are skipped.
function drawGrappleOverLandmarks(renderer)
{
    if (GRAPPLE_OVER_PREVIEW)
        return drawReplacementLandmark(renderer)
    if (!LANDMARKS.enabled || version !== 'grapple_over' || !floors[0] || !floors[0].level)
        return null
    const config = GRAPPLE_OVER_LANDMARKS
    const context = renderer.ctx
    const bounds = renderer.fillBounds()
    const k = scale[version]
    const pixelScale = glowSpriteScale(Math.max(0.25, Math.min(2, renderer.canvas.width / LOGICAL_VIEWPORT.width || 1)))
    const drawn = []

    context.save()
    context.shadowBlur = 0
    context.globalCompositeOperation = 'source-over'
    const anchors = grappleOverLandmarkAnchors()
    const distances = anchors.map(a => Math.hypot(screen.x - a.camera.x, screen.y - a.camera.y))
    const nearest = Math.min(...distances)
    const fadeOut = t => t <= 0 ? 1 : t >= 1 ? 0 : 1 - t * t * (3 - 2 * t)
    for (const [i, anchor] of anchors.entries())
    {
        const dx = screen.x - anchor.camera.x, dy = screen.y - anchor.camera.y
        const weight = fadeOut((distances[i] - config.fadeNear) / (config.fadeFar - config.fadeNear)) *
            fadeOut((distances[i] - nearest) / config.rivalSpan)
        const left = anchor.x + dx * k * config.factor - config.width / 2
        const top = anchor.y + dy * k * config.factor - config.height / 2
        if (weight <= 0 || left > bounds.x + bounds.width || left + config.width < bounds.x ||
            top > bounds.y + bounds.height || top + config.height < bounds.y)
            continue
        const sprite = getGlowSprite('landmark|' + anchor.band + '|' + pixelScale, () =>
            buildGlowSprite(Math.round((config.width + 2 * config.pad) * pixelScale),
                Math.round((config.height + 2 * config.pad) * pixelScale), config.pad * pixelScale,
                pixelScale, pixelScale, 0, 0, 1, paintGrappleOverLandmark, [anchor.band]))
        context.globalAlpha = config.alpha * weight
        context.drawImage(sprite, left - config.pad, top - config.pad,
            config.width + 2 * config.pad, config.height + 2 * config.pad)
        drawn.push({id: anchor.id, rect: [left, top, left + config.width, top + config.height], weight})
    }
    context.restore()
    if (!renderer.bounds)
        LANDMARKS.frame = {drawn, camera: {x: screen.x, y: screen.y}}
    return drawn
}

// Paints one landmark with the global ctx (the sprite canvas) in its own
// units (0..width x 0..height, base at the bottom): a soft halo, the body
// fading into the ground haze, a glowing rim and a few lights.
function paintGrappleOverLandmark(band, replacementShape)
{
    const config = GRAPPLE_OVER_LANDMARKS
    const palette = GRAPPLE_OVER_THEME.palettes[band]
    const W = config.width, H = config.height
    const shape = replacementShape || GRAPPLE_OVER_LANDMARK_SHAPES[band](W, H)

    const halo = ctx.createRadialGradient(W / 2, H * 0.45, 0, W / 2, H * 0.45, W * 0.62)
    halo.addColorStop(0, palette.glow + '88')
    halo.addColorStop(1, palette.glow + '00')
    ctx.save()
    ctx.globalAlpha = config.haloAlpha
    ctx.fillStyle = halo
    ctx.fillRect(0, 0, W, H)
    ctx.restore()

    const body = ctx.createLinearGradient(0, 0, 0, H)
    body.addColorStop(0, palette.top)
    body.addColorStop(0.75, palette.top)
    body.addColorStop(1, palette.top + '00')
    const trace = () =>
    {
        ctx.beginPath()
        for (const part of shape.parts)
        {
            part.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))
            ctx.closePath()
        }
        for (const [x, y, r] of shape.wheels || [])
        {
            ctx.moveTo(x + r, y)
            ctx.arc(x, y, r, 0, Math.PI * 2)
        }
    }
    ctx.save()
    ctx.globalAlpha = config.body
    ctx.fillStyle = body
    trace()
    ctx.fill('nonzero')
    ctx.restore()

    // Rim: shadowBlur here only (this runs once per sprite, inside buildGlowSprite)
    const rim = ctx.createLinearGradient(0, 0, 0, H)
    rim.addColorStop(0, palette.bottom)
    rim.addColorStop(0.8, palette.glow)
    rim.addColorStop(1, palette.glow + '00')
    ctx.save()
    ctx.strokeStyle = rim
    ctx.shadowColor = palette.glow
    ctx.shadowBlur = config.rimBlur
    ctx.lineWidth = config.rimWidth
    ctx.lineJoin = 'round'
    const strokeAll = () =>
    {
        trace()
        ctx.stroke()
        for (const line of shape.lines || [])
        {
            ctx.beginPath()
            line.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))
            ctx.stroke()
        }
    }
    strokeAll()
    // A thin hot core along the glowing rim
    const core = ctx.createLinearGradient(0, 0, 0, H)
    core.addColorStop(0, '#ffffffdd')
    core.addColorStop(0.8, palette.bottom + 'aa')
    core.addColorStop(1, palette.bottom + '00')
    ctx.strokeStyle = core
    ctx.shadowBlur = 0
    ctx.lineWidth = config.coreWidth
    strokeAll()
    ctx.restore()

    ctx.save()
    ctx.fillStyle = '#ffffff'
    ctx.shadowColor = palette.bottom
    ctx.shadowBlur = config.rimBlur
    for (const [x, y, r] of shape.lights || [])
    {
        ctx.beginPath()
        ctx.arc(x, y, config.lightRadius * (r || 1), 0, Math.PI * 2)
        ctx.fill()
    }
    ctx.restore()
}

// One silhouette per section, in sprite units: closed polygons (parts),
// circles (wheels), open strokes (lines) and lights ([x, y, size])
const GRAPPLE_OVER_LANDMARK_SHAPES = [
    // S01 broken loading yard: a gantry crane with a snapped boom over stacked containers
    (W, H) => ({
        parts: [
            [[60, H], [80, 120], [100, 120], [96, H]],
            [[250, H], [262, 120], [282, 120], [290, H]],
            [[40, 100], [330, 100], [345, 88], [360, 112], [372, 96], [372, 130], [40, 130]],
            [[150, 130], [160, 130], [160, 250], [150, 250]],
            [[130, 250], [180, 250], [170, 275], [140, 275]],
            [[110, H - 80], [250, H - 80], [250, H], [110, H]],
            [[150, H - 150], [290, H - 150], [290, H - 80], [150, H - 80]],
            [[290, H - 70], [400, H - 90], [405, H], [295, H]]
        ],
        lines: [[[80, 130], [272, 300]], [[272, 130], [80, 300]], [[96, 300], [262, 300]]],
        lights: [[52, 112], [360, 104, 1.3], [155, 262], [200, H - 115, 0.7], [340, H - 50, 0.7]]
    }),
    // S02 alternating industrial balconies: a tall shaft tower, balconies left and right in turn
    (W, H) => ({
        parts: [
            [[160, 30], [260, 30], [270, H], [150, H]],
            ...[0, 1, 2, 3, 4].map(i =>
            {
                const y = 90 + i * 80, left = i % 2 == 0
                return left ? [[60, y], [160, y], [160, y + 18], [80, y + 18], [80, y + 40], [60, y + 40]]
                    : [[260, y], [360, y], [360, y + 40], [340, y + 40], [340, y + 18], [260, y + 18]]
            }),
            [[190, 30], [200, 0], [220, 0], [230, 30]]
        ],
        lights: [[210, 6, 1.3], [70, 100], [350, 180], [70, 260], [350, 340], [70, 420],
            [210, 120, 0.6], [210, 220, 0.6], [210, 320, 0.6]]
    }),
    // S03 interrupted elevated bridge: two arched spans on piers with a missing middle
    (W, H) => ({
        parts: [
            [[0, 200], [175, 200], [165, 215], [180, 228], [160, 240], [0, 240]],
            [[245, 205], [420, 200], [420, 240], [262, 240], [250, 228], [258, 215]],
            [[30, 240], [70, 240], [76, H], [24, H]],
            [[350, 240], [390, 240], [396, H], [344, H]],
            [[120, 240], [150, 240], [140, H - 60], [118, H - 120]]
        ],
        lines: [[[70, 300], [100, 262], [140, 250]], [[350, 300], [320, 262], [270, 250]],
            [[40, 200], [40, 120], [160, 200]], [[380, 200], [380, 120], [262, 205]]],
        lights: [[40, 116, 1.3], [380, 116, 1.3], [172, 222, 0.7], [254, 222, 0.7], [50, 320, 0.6], [370, 320, 0.6]]
    }),
    // S04 angled green machinery: a big cog with angled deflector arms on a plinth
    (W, H) => ({
        parts: [
            Array.from({length: 32}, (_, i) =>
            {
                const a = i * Math.PI / 16, r = i % 2 ? 130 : 150
                return [210 + Math.cos(a) * r, 200 + Math.sin(a) * r]
            }),
            [[20, 120], [60, 90], [170, 210], [140, 240]],
            [[400, 330], [370, 360], [250, 250], [280, 220]],
            [[120, 380], [300, 380], [330, H], [90, H]]
        ],
        wheels: [[210, 200, 46]],
        lines: [[[210, 70], [210, 330]], [[80, 200], [340, 200]]],
        lights: [[210, 200, 1.6], [30, 115], [395, 338], [210, 430, 0.8]]
    }),
    // S05 projecting beams and deep overhangs: a column carrying cantilevers and a deep top slab
    (W, H) => ({
        parts: [
            [[180, 60], [240, 60], [250, H], [170, H]],
            [[20, 30], [400, 30], [400, 70], [330, 70], [330, 90], [90, 90], [90, 70], [20, 70]],
            [[240, 160], [400, 150], [400, 172], [240, 186]],
            [[20, 250], [180, 240], [180, 266], [20, 272]],
            [[240, 330], [380, 320], [380, 342], [240, 356]]
        ],
        lines: [[[400, 172], [250, 260]], [[20, 272], [170, 360]], [[380, 342], [250, 420]],
            [[20, 70], [180, 160]], [[400, 70], [240, 160]]],
        lights: [[24, 50], [396, 50], [396, 160], [24, 260], [376, 330], [210, 110, 0.8]]
    }),
    // S06 moving counterweights: a braced lift frame, a head pulley and two hanging weights
    (W, H) => ({
        parts: [
            [[100, 80], [124, 80], [130, H], [94, H]],
            [[296, 80], [320, 80], [326, H], [290, H]],
            [[80, 60], [340, 60], [340, 84], [80, 84]],
            [[140, 230], [190, 230], [190, 320], [140, 320]],
            [[230, 140], [280, 140], [280, 210], [230, 210]]
        ],
        wheels: [[210, 42, 34]],
        lines: [[[165, 42], [165, 230]], [[255, 42], [255, 140]], [[176, 42], [244, 42]],
            [[112, 120], [308, 220], [112, 320], [308, 420]], [[308, 120], [112, 220], [308, 320], [112, 420]]],
        lights: [[210, 42, 1.4], [165, 275], [255, 175], [88, 72, 0.7], [332, 72, 0.7]]
    }),
    // S07 open rooftop machinery: a roof deck with exhaust fans, a tank and a lattice mast
    (W, H) => ({
        parts: [
            [[0, 300], [420, 300], [420, H], [0, H]],
            [[30, 230], [150, 230], [150, 300], [30, 300]],
            [[180, 190], [270, 190], [280, 300], [170, 300]],
            [[300, 60], [316, 60], [330, 300], [286, 300]],
            [[200, 150], [250, 150], [250, 190], [200, 190]]
        ],
        wheels: [[60, 210, 26], [120, 210, 26], [225, 135, 30]],
        lines: [[[290, 120], [326, 160], [292, 200], [328, 240], [288, 280]], [[308, 60], [308, 10]],
            [[350, 300], [350, 250], [400, 250], [400, 300]]],
        lights: [[308, 10, 1.4], [60, 210, 0.8], [120, 210, 0.8], [225, 135, 0.9], [375, 270, 0.7]]
    }),
    // S08 distinct final beacon silhouette: a tall tapered spire with a lantern and rays
    (W, H) => ({
        parts: [
            [[180, 110], [240, 110], [300, H], [120, H]],
            [[170, 70], [250, 70], [240, 110], [180, 110]],
            [[195, 20], [225, 20], [230, 70], [190, 70]],
            [[90, H - 60], [330, H - 60], [350, H], [70, H]]
        ],
        lines: [[[210, 40], [40, 0]], [[210, 40], [380, 0]], [[210, 40], [20, 90]], [[210, 40], [400, 90]],
            [[160, 200], [260, 200]], [[148, 300], [272, 300]], [[136, 400], [284, 400]]],
        lights: [[210, 42, 2.4], [210, 160, 0.7], [210, 260, 0.7], [210, 360, 0.7]]
    })
]

// Presentation follows built preview terrain, without legacy encounter positions.
function replacementSection()
{
    // Pick the closest built terrain in two dimensions, not the first section
    // with any surface within a broad altitude band. Shared shelves belong to
    // the later section at the boundary. This is presentation only.
    let nearest = Infinity, selected = floors[0].level.sections[0]
    for (const section of floors[0].level.sections)
        for (const encounter of floors[0].level.encounters.filter(e => section.encounters.includes(e.id)))
            for (const id of encounter.elements)
            {
                const e = floors[0].byId.get(id)
                if (!e) continue
                const b = {}; elementBounds(e, b)
                const d = Math.hypot(Math.max(b.left - ninja.x, 0, ninja.x - b.right),
                    Math.max(b.top - ninja.y, 0, ninja.y - b.bottom))
                if (d <= nearest) { nearest = d; selected = section }
            }
    return selected
}

// Broad stepped excavation walls: a visual silhouette, never collision terrain.
function replacementQuarryShape(W, H)
{
    return {
        parts: [[[0,H],[0,H*.15],[W*.18,H*.15],[W*.18,H*.34],
            [W*.38,H*.34],[W*.38,H*.54],[W*.62,H*.54],
            [W*.62,H*.34],[W*.82,H*.34],[W*.82,H*.15],[W,H*.15],[W,H]]],
        lines: [.68,.82].map(y => [[0,H*y],[W,H*y]]),
        lights: [[W*.18,H*.34],[W*.38,H*.54],[W*.62,H*.54],[W*.82,H*.34]]
    }
}

function drawReplacementLandmark(renderer)
{
    if (!LANDMARKS.enabled || version !== 'grapple_over' || !floors[0]?.byId.has('yard-entry'))
        return null
    const config = GRAPPLE_OVER_LANDMARKS, k = scale[version]
    const context = renderer.ctx
    const section = replacementSection().id
    const gallery = section === 'S05'
    const quarry = section === 'S02', freight = section === 'S03', viaduct = section === 'S04'
    const id = gallery ? 'cable-galleries' : viaduct ? 'broken-viaduct' : freight ? 'freight-crossing' : quarry ? 'terraced-quarry' : 'loading-yard'
    const sprite = getGlowSprite('replacement-' + id, () =>
        buildGlowSprite(config.width + 2 * config.pad, config.height + 2 * config.pad,
            config.pad, 1, 1, 0, 0, 1, paintGrappleOverLandmark, gallery ? [4, replacementGalleryShape(config.width, config.height)] : viaduct ? [3, replacementViaductShape(config.width, config.height)] : freight ? [2, replacementFreightShape(config.width, config.height)] : quarry ? [1, replacementQuarryShape(config.width, config.height)] : [0]))
    const left = ((gallery ? 12000 : viaduct ? 7700 : freight ? 4320 : 2366) + screen.x) * k - config.width / 2
    const top = ((gallery ? -1200 : viaduct ? -1200 : freight ? -800 : quarry ? -610 : -150) + screen.y) * k - config.height
    context.save()
    context.globalAlpha = config.alpha
    context.drawImage(sprite, left - config.pad, top - config.pad,
        config.width + 2 * config.pad, config.height + 2 * config.pad)
    context.restore()
    const drawn = [{id, rect:[left,top,left+config.width,top+config.height], weight:1}]
    if (!renderer.bounds) LANDMARKS.frame = {drawn, camera:{x:screen.x,y:screen.y}}
    return drawn
}

// Freight signal mast and overhead rail, presentation only: no collision panels.
function replacementFreightShape(W, H)
{
    return {parts: [[[W*.12,0],[W*.17,0],[W*.17,H],[W*.12,H]],
        [[0,H*.18],[W,H*.18],[W,H*.23],[0,H*.23]],
        [[W*.05,H*.32],[W*.25,H*.32],[W*.25,H*.52],[W*.05,H*.52]]],
        lines: [[[W*.17,H*.8],[W*.65,H*.23]],[[W*.8,H*.23],[W*.8,H*.6]]],
        lights: [[W*.15,H*.37,1.5],[W*.15,H*.47],[W*.8,H*.6]]}
}

// Broken bridge piers and interrupted deck: visual only, never collision terrain.
function replacementViaductShape(W, H)
{
    return {parts: [[[0,H*.2],[W*.4,H*.2],[W*.35,H*.3],[0,H*.3]],
        [[W*.65,H*.2],[W,H*.2],[W,H*.3],[W*.7,H*.3]],
        [[W*.12,H*.3],[W*.22,H*.3],[W*.22,H],[W*.12,H]],
        [[W*.8,H*.3],[W*.9,H*.3],[W*.9,H],[W*.8,H]]],
        lines: [[[0,H*.12],[W*.35,H*.12]],[[W*.7,H*.12],[W,H*.12]]],
        lights: [[W*.35,H*.2],[W*.7,H*.2]]}
}

// Cable fan and deep gallery slab: presentation only, never grapple targets.
function replacementGalleryShape(W, H)
{
    return {parts: [[[0,0],[W,0],[W,H*.12],[0,H*.12]],
        [[W*.08,0],[W*.15,0],[W*.15,H],[W*.08,H]]],
        lines: [.32,.52,.72,.92].map(x => [[W*.12,H*.12],[W*x,H*.85]]),
        lights: [.32,.52,.72,.92].map(x => [W*x,H*.85])}
}
