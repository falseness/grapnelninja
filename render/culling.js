// Off-screen culling for floor elements and their tracks. A box is drawn only
// if, padded by the furthest any sprite or trail paints past its geometry, it
// meets the visible world rect. The padding is conservative: culling must never
// change a pixel.

// World-unit padding for the current version. shadowBlur is in canvas pixels
// and ignores the transform, so it grows by 1 / scale; a blur reaches about
// 1.5 * shadowBlur, 2 is used. Strokes extend by half their width, miter joins
// by up to miterLimit (10) / 2 widths. Screen shake translates the world layer.
// Extruded back faces reach up to STYLE.extrusion.depth past the geometry.
// Neon outlines (strokeNeonPath) are screen widths, so they grow by 1 / scale:
// the round-joined halo reaches half its width, the mitered outline 5 widths.
function getCullPadding()
{
    const obstacles = STYLE.badVersionEffects.obstacles
    const hazardTrail = STYLE.trails.hazard
    const geometry = STYLE.spriteGeometry
    const maxBlur = Math.max(STYLE.strokes.neonGlowWidth, obstacles.outerGlowWidth, hazardTrail.glowBlur)
    const maxLineWidth = Math.max(STYLE.strokes.seamWidth, STYLE.strokes.neonGlowWidth, STYLE.strokes.neonWidth,
        obstacles.outerGlowWidth, obstacles.thinStrokeWidth, hazardTrail.envelopeGlowWidth, hazardTrail.envelopeLineWidth)
    const maxBand = Math.max(2, screenHeightPercent(geometry.capHeightPercent), screenHeightPercent(geometry.bandHeightPercent))
    const maxShake = Math.max(STYLE.screenEffects.shakeMagnitudeX, STYLE.screenEffects.shakeMagnitudeY)

    const maxExtrusion = STYLE.extrusion.depth / scale[version] + STYLE.extrusion.edgeWidth
    const neon = STYLE.strokes.neonOutline
    const maxNeon = Math.max(neon.haloWidth / 2, neon.innerHaloWidth / 2, 5 * neon.width) / scale[version]

    return 2 * maxBlur / scale[version] + 5 * maxLineWidth + maxBand + maxShake + maxExtrusion + maxNeon + 1
}

// Visible world rect (element coordinates, before + screen.x / + screen.y),
// padded by getCullPadding().
// Several layers ask for it every frame, so it is rebuilt only when the draw
// frame, the camera or the view changes; read it before the next draw frame.
const cullRectCache = {frame: -1, screenX: 0, screenY: 0, width: 0, height: 0, version: '',
                       rect: {left: 0, top: 0, right: 0, bottom: 0}}
function getCullRect()
{
    const cache = cullRectCache
    const frame = typeof drawFrameId == 'number' ? drawFrameId : -1
    if (frame >= 0 && cache.frame === frame && cache.screenX === screen.x && cache.screenY === screen.y &&
        cache.width === width && cache.height === height && cache.version === version)
        return cache.rect

    const pad = getCullPadding()
    const rect = cache.rect
    rect.left = -screen.x - pad
    rect.top = -screen.y - pad
    rect.right = -screen.x + width / scale[version] + pad
    rect.bottom = -screen.y + height / scale[version] + pad
    cache.frame = frame
    cache.screenX = screen.x
    cache.screenY = screen.y
    cache.width = width
    cache.height = height
    cache.version = version
    return rect
}

// The bounds test: false only when the box lies fully outside the rect.
function isBoxInCullRect(box, rect)
{
    return !(box.right < rect.left || box.left > rect.right || box.bottom < rect.top || box.top > rect.bottom)
}

function addPointToBox(box, point)
{
    box.left = Math.min(box.left, point.x)
    box.right = Math.max(box.right, point.x)
    box.top = Math.min(box.top, point.y)
    box.bottom = Math.max(box.bottom, point.y)
}

// Element geometry box, including quadratic curve control points.
// null (never culled) for elements without points, such as Empty.
// Elements with writeCullBox fill one shared box, so read it before the next call.
const elementCullBox = {left: 0, top: 0, right: 0, bottom: 0}
function getElementCullBox(element)
{
    if (element.writeCullBox)
        return element.writeCullBox(elementCullBox)

    const points = element.getPoints && element.getPoints()
    if (!points || !points.length)
        return null

    const box = {left: Infinity, top: Infinity, right: -Infinity, bottom: -Infinity}
    for (let i = 0; i < points.length; ++i)
    {
        addPointToBox(box, points[i])
        if (points[i].curvature)
            addPointToBox(box, points[i].curvature)
    }
    return box
}

// Track box: every stored position (a point or an array of points), padded by
// the track's own width and height (cube trails sweep a square around centres).
function getTrackCullBox(track)
{
    if (!track || !track.pos || !track.pos.length)
        return null

    const box = {left: Infinity, top: Infinity, right: -Infinity, bottom: -Infinity}
    for (let i = 0; i < track.pos.length; ++i)
    {
        const pos = track.pos[i]
        if (Array.isArray(pos))
            for (let j = 0; j < pos.length; ++j)
                addPointToBox(box, pos[j])
        else
            addPointToBox(box, pos)
    }

    const extent = Math.max(track.lineWidth || 0, track.width || 0, track.height || 0)
    box.left -= extent
    box.top -= extent
    box.right += extent
    box.bottom += extent
    return box
}

function isCullBoxVisible(box, rect)
{
    return !box || isBoxInCullRect(box, rect)
}
