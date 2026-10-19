// Momentum crystal pieces (Cave Crystal concept A): the inside of a momentum
// blue becomes faceted sapphire. A piece's sprite (a fan of facets over a
// diagonal gradient, a top-left sheen, two hairline cracks and an inner
// bevel) is painted once per shape and backing scale into a cached offscreen
// canvas, clipped to the piece polygon, and blitted every frame. The pattern
// is seeded from the piece kind and its points relative to its first point
// (rounded to 0.01 world units), so a moving piece keeps its look and every
// run and device draws the same crystal. Visual only; the only randomness is
// the seeded generator below.
const CRYSTAL_PIECES = (function()
{
    const CACHE_LIMIT = 128
    // Sizes below are canvas px at a 1080 px tall stage
    const REFERENCE_HEIGHT = 1080
    const FACETS = 10
    const CRACKS = 2
    const CRACK_SEGMENTS = 4
    const CRACK_WIDTH = 0.9
    const BEVEL_INSET = 4
    const BEVEL_WIDTH = 1
    const PAD = 2
    const KINDS = {blue: 1}

    // mulberry32 (render/wallveins.js): the same crystal on every run and device
    function generator(seed)
    {
        return () =>
        {
            seed = (seed + 0x6D2B79F5) >>> 0
            let t = seed
            t = Math.imul(t ^ t >>> 15, t | 1)
            t ^= t + Math.imul(t ^ t >>> 7, t | 61)
            return ((t ^ t >>> 14) >>> 0) / 4294967296
        }
    }
    function hash(a, b, c)
    {
        let h = Math.imul(a | 0, 0x27d4eb2d) ^ Math.imul(b | 0, 0x165667b1) ^ Math.imul(c | 0, 0x9e3779b1)
        h = Math.imul(h ^ h >>> 15, 0x85ebca6b)
        return (h ^ h >>> 13) >>> 0
    }
    // Piece points relative to the first one, in 0.01 world units
    function relativePoints(points)
    {
        const x0 = points[0].x, y0 = points[0].y
        return points.map(point => [Math.round((point.x - x0) * 100), Math.round((point.y - y0) * 100)])
    }
    // The convex polygon moved inward by inset (edges along their normals)
    function insetPolygon(points, inset)
    {
        const count = points.length
        let area = 0
        for (let i = 0; i < count; ++i)
        {
            const a = points[i], b = points[(i + 1) % count]
            area += a[0] * b[1] - b[0] * a[1]
        }
        const winding = area > 0 ? 1 : -1
        const edges = []
        for (let i = 0; i < count; ++i)
        {
            const a = points[i], b = points[(i + 1) % count]
            const length = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1
            const dx = (b[0] - a[0]) / length, dy = (b[1] - a[1]) / length
            edges.push([a[0] - dy * winding * inset, a[1] + dx * winding * inset, dx, dy])
        }
        const res = []
        for (let i = 0; i < count; ++i)
        {
            const p = edges[(i + count - 1) % count], q = edges[i]
            const denominator = p[2] * q[3] - p[3] * q[2]
            if (Math.abs(denominator) < 1e-9)
            {
                res.push([q[0], q[1]])
                continue
            }
            const t = ((q[0] - p[0]) * q[3] - (q[1] - p[1]) * q[2]) / denominator
            res.push([p[0] + p[2] * t, p[1] + p[3] * t])
        }
        return res
    }
    function tracePolygon(c, points)
    {
        c.beginPath()
        c.moveTo(points[0][0], points[0][1])
        for (let i = 1; i < points.length; ++i)
            c.lineTo(points[i][0], points[i][1])
        c.closePath()
    }
    // Point at fraction f (0..1) of the polygon's perimeter
    function perimeterPoint(points, lengths, total, f)
    {
        let d = f * total
        for (let i = 0; i < points.length; ++i)
        {
            if (d <= lengths[i] || i == points.length - 1)
            {
                const a = points[i], b = points[(i + 1) % points.length]
                const t = lengths[i] ? Math.min(1, d / lengths[i]) : 0
                return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]
            }
            d -= lengths[i]
        }
        return points[0]
    }

    return {
        // Test hook: draw the crystal at all
        enabled: true,
        stats: {builds: 0, hits: 0, size: 0},
        sprites: new Map(),

        // 32-bit seed of the piece kind and its relative points
        seed(piece, kind)
        {
            let h = hash(KINDS[kind || 'blue'] || 0, piece.getPoints().length, 0x51ed27)
            for (const [x, y] of relativePoints(piece.getPoints()))
                h = hash(h, x, y)
            return h
        },
        // Paints the sprite of polygon points (canvas px, origin at the
        // sprite's top-left) of size w x h; unit = canvas px per 1080-stage px
        paint(c, points, w, h, unit, seed)
        {
            const random = generator(seed)
            const range = (a, b) => a + (b - a) * random()
            let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
            for (const [x, y] of points)
            {
                x0 = Math.min(x0, x); y0 = Math.min(y0, y)
                x1 = Math.max(x1, x); y1 = Math.max(y1, y)
            }
            const bw = x1 - x0, bh = y1 - y0
            c.save()
            tracePolygon(c, points)
            c.clip()
            // Sapphire body: diagonal gradient
            const body = c.createLinearGradient(x0, y0, x1, y1)
            body.addColorStop(0, '#1d4fd8')
            body.addColorStop(0.55, '#0a1f6e')
            body.addColorStop(1, '#173fb8')
            c.fillStyle = body
            c.fillRect(0, 0, w, h)
            // Facets: a fan from a seeded core to points round the perimeter
            const core = [x0 + bw * range(0.35, 0.65), y0 + bh * range(0.35, 0.65)]
            const lengths = points.map((a, i) =>
            {
                const b = points[(i + 1) % points.length]
                return Math.hypot(b[0] - a[0], b[1] - a[1])
            })
            const total = lengths.reduce((a, b) => a + b, 0)
            const start = random()
            const rim = []
            for (let i = 0; i < FACETS; ++i)
                rim.push(perimeterPoint(points, lengths, total, (start + (i + range(-0.3, 0.3)) / FACETS) % 1))
            for (let i = 0; i < FACETS; ++i)
            {
                const a = rim[i], b = rim[(i + 1) % FACETS]
                c.beginPath()
                c.moveTo(core[0], core[1])
                c.lineTo(a[0], a[1])
                c.lineTo(b[0], b[1])
                c.closePath()
                const alpha = range(0.08, 0.3).toFixed(3)
                c.fillStyle = i % 2 ? `rgba(10,20,90,${alpha})` : `rgba(140,200,255,${alpha})`
                c.fill()
            }
            c.strokeStyle = 'rgba(160,215,255,0.35)'
            c.lineWidth = Math.max(0.75, unit)
            c.beginPath()
            for (const p of rim)
            {
                c.moveTo(core[0], core[1])
                c.lineTo(p[0], p[1])
            }
            c.stroke()
            // Refraction sheen from the top-left corner, gone at 30%
            const sheen = c.createLinearGradient(x0, y0, x1, y1)
            sheen.addColorStop(0, 'rgba(180,230,255,0.45)')
            sheen.addColorStop(0.3, 'rgba(180,230,255,0)')
            c.fillStyle = sheen
            c.fillRect(0, 0, w, h)
            // Hairline cracks: seeded 4-segment polylines
            c.strokeStyle = 'rgba(230,248,255,0.75)'
            c.lineWidth = Math.max(0.5, CRACK_WIDTH * unit)
            c.lineJoin = 'miter'
            const reach = Math.min(bw, bh) * 0.13 + Math.max(bw, bh) * 0.04
            for (let k = 0; k < CRACKS; ++k)
            {
                let p = [x0 + bw * range(0.2, 0.8), y0 + bh * range(0.2, 0.8)]
                let angle = range(0, Math.PI * 2)
                c.beginPath()
                c.moveTo(p[0], p[1])
                for (let j = 0; j < CRACK_SEGMENTS; ++j)
                {
                    angle += range(-0.9, 0.9)
                    const length = reach * range(0.5, 1)
                    p = [p[0] + Math.cos(angle) * length, p[1] + Math.sin(angle) * length]
                    c.lineTo(p[0], p[1])
                }
                c.stroke()
            }
            // Inner bevel
            const inset = BEVEL_INSET * unit
            if (Math.min(bw, bh) > 2 * inset + 1)
            {
                tracePolygon(c, insetPolygon(points, inset))
                c.strokeStyle = 'rgba(200,235,255,0.6)'
                c.lineWidth = Math.max(0.75, BEVEL_WIDTH * unit)
                c.stroke()
            }
            c.restore()
        },
        // Cached sprite of piece at canvas scale k (canvas px per world unit)
        sprite(piece, kind, k)
        {
            const rel = relativePoints(piece.getPoints())
            const stage = Math.min(canvas.width, canvas.height)
            const key = kind + ':' + k.toFixed(4) + ':' + stage + ':' + rel.join(';')
            let sprite = this.sprites.get(key)
            if (sprite)
            {
                ++this.stats.hits
                return sprite
            }
            let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
            for (const [x, y] of rel)
            {
                minX = Math.min(minX, x); minY = Math.min(minY, y)
                maxX = Math.max(maxX, x); maxY = Math.max(maxY, y)
            }
            const s = k / 100
            const w = Math.ceil((maxX - minX) * s) + 2 * PAD
            const h = Math.ceil((maxY - minY) * s) + 2 * PAD
            const points = rel.map(([x, y]) => [(x - minX) * s + PAD, (y - minY) * s + PAD])
            const image = document.createElement('canvas')
            image.width = Math.max(1, w)
            image.height = Math.max(1, h)
            this.paint(image.getContext('2d'), points, w, h, stage / REFERENCE_HEIGHT, this.seed(piece, kind))
            // Sprite origin relative to the first point, in world units
            sprite = {image: image, dx: minX / 100 - PAD / k, dy: minY / 100 - PAD / k, k: k}
            this.sprites.set(key, sprite)
            if (this.sprites.size > CACHE_LIMIT)
                this.sprites.delete(this.sprites.keys().next().value)
            ++this.stats.builds
            this.stats.size = this.sprites.size
            return sprite
        },
        // Draws the blue crystal inside piece with globalAlpha alpha, clipped
        // to its polygon (the current path is left as the piece outline)
        drawBlue(piece, alpha)
        {
            const points = piece.getPoints()
            const m = ctx.getTransform()
            const k = Math.hypot(m.a, m.b)
            const sprite = this.sprite(piece, 'blue', k)
            ctx.save()
            ctx.beginPath()
            ctx.moveTo(points[points.length - 1].x + screen.x, points[points.length - 1].y + screen.y)
            for (let i = 0; i < points.length; ++i)
                ctx.lineTo(points[i].x + screen.x, points[i].y + screen.y)
            ctx.closePath()
            ctx.clip()
            ctx.globalAlpha = alpha
            const x = points[0].x + screen.x + sprite.dx, y = points[0].y + screen.y + sprite.dy
            if (m.b == 0 && m.c == 0)
            {
                // Whole canvas px: the cached raster is not resampled
                ctx.setTransform(1, 0, 0, 1, 0, 0)
                ctx.drawImage(sprite.image, Math.round(m.a * x + m.e), Math.round(m.d * y + m.f))
            }
            else
                ctx.drawImage(sprite.image, x, y, sprite.image.width / k, sprite.image.height / k)
            ctx.restore()
        }
    }
})()
