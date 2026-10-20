// Momentum crystal pieces (Cave Crystal concept A): the inside of a momentum
// blue becomes faceted sapphire (a fan of facets over a diagonal gradient, a
// top-left sheen, two hairline cracks and an inner bevel), a green becomes
// jade rock (diagonal strata, emerald nubs and a bright lip just inside the
// outline along every free edge: one that neither lies on a corridor wall
// face nor touches another piece). A piece's sprite is painted once per
// shape and backing scale into a cached offscreen canvas, clipped to the
// piece polygon, and blitted every frame. The pattern
// is seeded from the piece kind and its points relative to its first point
// (rounded to 0.01 world units), so a moving piece keeps its look and every
// run and device draws the same crystal. Visual only; the only randomness is
// the seeded generator below.
// Glints (TASK-125): 2-4 seeded points per piece twinkle on the render clock
// (performance.now(), as ScreenEffects.drawBluePops), drawn every frame on
// top of the piece from one cached star sprite per backing scale, clipped to
// the piece polygon. Positions, periods and phases are fixed per sprite.
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
    const KINDS = {blue: 1, green: 2}
    // Green: strata spacing and width ranges, nub size range, lip width
    const STRATA_SPACING = [7, 16]
    const STRATA_WIDTH = [1, 4]
    const NUB_SIZE = [3, 7]
    const NUB_AREA = 2500
    const NUB_GLOW = 4
    const LIP_WIDTH = 4
    // A corridor wall face or another piece's edge closer than this (in W,
    // as momentumSnapWallFace) is in contact
    const CONTACT_TOLERANCE = 1e-5
    // Glints: star radius, blue corner inset, green edge inset, period range (ms)
    const GLINT_RADIUS = 8
    const GLINT_CORNER_INSET = 3
    const GLINT_EDGE_INSET = 2
    const GLINT_PERIOD = [1600, 3200]
    const GLINT_MAX = 4
    const GLINT_SALT = 0x6a7e11

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
    function polygonArea(points)
    {
        let area = 0
        for (let i = 0; i < points.length; ++i)
        {
            const a = points[i], b = points[(i + 1) % points.length]
            area += a[0] * b[1] - b[0] * a[1]
        }
        return area / 2
    }
    // Inside the convex polygon (either winding)
    function insidePolygon(points, x, y)
    {
        let sign = 0
        for (let i = 0; i < points.length; ++i)
        {
            const a = points[i], b = points[(i + 1) % points.length]
            const cross = (b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0])
            if (cross == 0)
                continue
            if (sign && Math.sign(cross) != sign)
                return false
            sign = Math.sign(cross)
        }
        return true
    }
    // Edge i (points[i] -> points[i + 1]) lies on a face of a built corridor
    // segment of momentumCourse
    function onWallFace(a, b)
    {
        if (typeof momentumCourse === 'undefined' || !momentumCourse)
            return false
        for (const s of momentumCourse.segments)
        {
            const halfWidth = s.dir == 'right' ? GAMEPLAY.momentumBorders.halfWidth : s.halfWidth
            if (halfWidth === undefined)
                continue
            const tolerance = CONTACT_TOLERANCE * 2 * halfWidth
            const margin = 4 * halfWidth
            // across: the face coordinate axis; along: the segment's own
            const across = s.dir == 'right' ? 'y' : 'x', along = s.dir == 'right' ? 'x' : 'y'
            const lo = Math.min(s[along + '0'], s[along + '1']) - margin
            const hi = Math.max(s[along + '0'], s[along + '1']) + margin
            if (Math.max(a[along], b[along]) < lo || Math.min(a[along], b[along]) > hi)
                continue
            for (const face of [s[across + '0'] - halfWidth, s[across + '0'] + halfWidth])
                if (Math.abs(a[across] - face) < tolerance && Math.abs(b[across] - face) < tolerance)
                    return true
        }
        return false
    }
    // Edge a-b overlaps (collinear, a common stretch) an edge of other
    function touchesPiece(a, b, other, tolerance)
    {
        const length = Math.hypot(b.x - a.x, b.y - a.y)
        if (!length)
            return false
        const ux = (b.x - a.x) / length, uy = (b.y - a.y) / length
        const points = other.getPoints()
        for (let i = 0; i < points.length; ++i)
        {
            const c = points[i], d = points[(i + 1) % points.length]
            const off = p => Math.abs((p.x - a.x) * uy - (p.y - a.y) * ux)
            if (off(c) > tolerance || off(d) > tolerance)
                continue
            const tc = (c.x - a.x) * ux + (c.y - a.y) * uy, td = (d.x - a.x) * ux + (d.y - a.y) * uy
            if (Math.min(length, Math.max(tc, td)) - Math.max(0, Math.min(tc, td)) > tolerance)
                return true
        }
        return false
    }
    // Seeded period and phase of each glint position
    function timeGlints(positions, seed)
    {
        const random = generator(hash(seed, GLINT_SALT, positions.length))
        return positions.slice(0, GLINT_MAX).map(([x, y]) =>
            [x, y, GLINT_PERIOD[0] + (GLINT_PERIOD[1] - GLINT_PERIOD[0]) * random(), random()])
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
        // Test hooks: draw the crystal at all, draw its glints
        enabled: true,
        glints: true,
        stats: {builds: 0, hits: 0, size: 0},
        sprites: new Map(),
        glintSprites: new Map(),

        // Per edge i (points[i] -> points[i + 1]) of a piece: 'wall' (on a
        // corridor wall face), 'piece' (overlapping an edge of another piece
        // of its placement group) or 'free'. Measured once, at the first draw,
        // and kept on the piece: crystalEdges, crystalFreeEdges (free indices)
        edges(piece)
        {
            if (piece.crystalEdges)
                return piece.crystalEdges
            const points = piece.getPoints()
            const tolerance = CONTACT_TOLERANCE * 2 * GAMEPLAY.momentumBorders.halfWidth
            const floor = typeof floors !== 'undefined' && floors && piece.generationGroupId !== undefined
                ? floors.find(f => f.elements.includes(piece)) : null
            const others = floor ? floor.elements.filter(e => e !== piece && e instanceof MomentumOneTime &&
                e.generationGroupId === piece.generationGroupId) : []
            piece.crystalEdges = points.map((a, i) =>
            {
                const b = points[(i + 1) % points.length]
                if (onWallFace(a, b))
                    return 'wall'
                return others.some(other => touchesPiece(a, b, other, tolerance)) ? 'piece' : 'free'
            })
            piece.crystalFreeEdges = piece.crystalEdges.map((kind, i) => kind == 'free' ? i : -1).filter(i => i >= 0)
            return piece.crystalEdges
        },
        // 32-bit seed of the piece kind and its relative points
        seed(piece, kind)
        {
            let h = hash(KINDS[kind || 'blue'] || 0, piece.getPoints().length, 0x51ed27)
            for (const [x, y] of relativePoints(piece.getPoints()))
                h = hash(h, x, y)
            return h
        },
        // Paints the blue sprite of polygon points (canvas px, origin at the
        // sprite's top-left) of size w x h; unit = canvas px per 1080-stage px
        paintBlue(c, points, w, h, unit, seed)
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
            // Glints: two opposite corners of the polygon inset 3 px, then
            // up to 2 facet vertices (the core, a rim point 3 px towards it)
            const pick = generator(hash(seed, GLINT_SALT, 1))
            const corners = insetPolygon(points, GLINT_CORNER_INSET * unit)
            const first = Math.floor(pick() * points.length)
            const glints = [corners[first], corners[(first + Math.floor(points.length / 2)) % points.length]]
            const facets = 1 + Math.floor(pick() * 2)
            glints.push(core)
            if (facets > 1)
            {
                const p = rim[Math.floor(pick() * FACETS)]
                const d = Math.hypot(core[0] - p[0], core[1] - p[1]) || 1
                const t = Math.min(1, GLINT_CORNER_INSET * unit / d)
                glints.push([p[0] + (core[0] - p[0]) * t, p[1] + (core[1] - p[1]) * t])
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
            return timeGlints(glints, seed)
        },
        // Paints the green sprite: jade gradient, diagonal strata, emerald
        // nubs and the lip along the free edges (free[i]: edge i is free),
        // inside the outline (its inner half is outlineHalf canvas px wide)
        paintGreen(c, points, w, h, unit, seed, free, outlineHalf)
        {
            const random = generator(seed)
            const range = (a, b) => a + (b - a) * random()
            let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
            for (const [x, y] of points)
            {
                x0 = Math.min(x0, x); y0 = Math.min(y0, y)
                x1 = Math.max(x1, x); y1 = Math.max(y1, y)
            }
            c.save()
            tracePolygon(c, points)
            c.clip()
            // Jade body: diagonal gradient
            const body = c.createLinearGradient(x0, y0, x1, y1)
            body.addColorStop(0, '#0f4a2a')
            body.addColorStop(1, '#04180d')
            c.fillStyle = body
            c.fillRect(0, 0, w, h)
            // Strata: parallel lines falling to the right at a seeded angle,
            // seeded spacing, width and tone (30% light, the rest dark)
            const angle = range(0.35, 0.7)
            const dx = Math.cos(angle), dy = Math.sin(angle)
            const reach = Math.hypot(w, h)
            for (let d = -reach + range(0, STRATA_SPACING[0]) * unit; d < reach; d += range(...STRATA_SPACING) * unit)
            {
                // The line through (w/2, h/2) + d * normal
                const cx = w / 2 - dy * d, cy = h / 2 + dx * d
                const light = random() < 0.3
                const alpha = range(0.08, 0.25).toFixed(3)
                c.strokeStyle = light ? `rgba(120,255,160,${alpha})` : `rgba(0,0,0,${alpha})`
                c.lineWidth = Math.max(0.5, range(...STRATA_WIDTH) * unit)
                c.beginPath()
                c.moveTo(cx - dx * reach, cy - dy * reach)
                c.lineTo(cx + dx * reach, cy + dy * reach)
                c.stroke()
            }
            // Lip: a band just inside the outline along each free edge,
            // kept off the other edges' outlines
            const lip = LIP_WIDTH * Math.max(1, unit)
            const inner = insetPolygon(points, outlineHalf)
            const lipped = free.some(f => f)
            if (lipped && Math.min(x1 - x0, y1 - y0) > 2 * outlineHalf + 1)
            {
                c.save()
                tracePolygon(c, inner)
                c.clip()
                const winding = polygonArea(points) > 0 ? 1 : -1
                c.strokeStyle = '#b6ffbf'
                c.lineWidth = lip
                c.lineCap = 'butt'
                c.beginPath()
                for (let i = 0; i < points.length; ++i)
                {
                    if (!free[i])
                        continue
                    const a = points[i], b = points[(i + 1) % points.length]
                    const length = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1
                    const ux = (b[0] - a[0]) / length, uy = (b[1] - a[1]) / length
                    // Inward normal, the band's centre line; overlong, the clip trims it
                    const nx = -uy * winding * (outlineHalf + lip / 2), ny = ux * winding * (outlineHalf + lip / 2)
                    c.moveTo(a[0] + nx - ux * reach, a[1] + ny - uy * reach)
                    c.lineTo(b[0] + nx + ux * reach, b[1] + ny + uy * reach)
                }
                c.stroke()
                c.restore()
            }
            // Emerald nubs: rhombi wholly inside the polygon past the outline
            // and the lip, glowing inside the shape only (the clip)
            const room = insetPolygon(points, outlineHalf + lip + 1)
            const nubs = Math.max(2, Math.floor(Math.abs(polygonArea(points)) / (unit * unit) / NUB_AREA))
            c.fillStyle = 'rgba(110,255,140,0.85)'
            c.shadowColor = 'rgba(110,255,140,0.85)'
            c.shadowBlur = NUB_GLOW * unit
            // An inset past the middle turns the polygon inside out: no room
            const fits = polygonArea(room) * polygonArea(points) > 0
            const nubCentres = []
            for (let n = 0, tries = 0; fits && n < nubs && tries < 50 * nubs; ++tries)
            {
                const size = range(...NUB_SIZE) * unit
                const x = range(x0, x1), y = range(y0, y1)
                const r = size / 2, s = r * 0.6
                const rhombus = [[x, y - r], [x + s, y], [x, y + r], [x - s, y]]
                if (!rhombus.every(([px, py]) => insidePolygon(room, px, py) && insidePolygon(points, px, py)))
                    continue
                tracePolygon(c, rhombus)
                c.fill()
                nubCentres.push([x, y])
                ++n
            }
            c.restore()
            // Glints: 0.3 along the longest free edge (any edge if none is
            // free) 2 px inside, then one seeded nub (the centre without one)
            const winding = polygonArea(points) > 0 ? 1 : -1
            let longest = -1, best = 0
            for (let pass = 0; pass < 2 && longest < 0; ++pass)
                for (let i = 0; i < points.length; ++i)
                {
                    const a = points[i], b = points[(i + 1) % points.length]
                    const length = Math.hypot(b[0] - a[0], b[1] - a[1])
                    if ((pass || free[i]) && length > best)
                    {
                        longest = i
                        best = length
                    }
                }
            const a = points[longest], b = points[(longest + 1) % points.length]
            const ux = (b[0] - a[0]) / best, uy = (b[1] - a[1]) / best
            const inset = GLINT_EDGE_INSET * unit
            const glints = [[a[0] + (b[0] - a[0]) * 0.3 - uy * winding * inset, a[1] + (b[1] - a[1]) * 0.3 + ux * winding * inset]]
            const pick = generator(hash(seed, GLINT_SALT, 2))
            if (nubCentres.length)
                glints.push(nubCentres[Math.floor(pick() * nubCentres.length)])
            else
                glints.push([(x0 + x1) / 2, (y0 + y1) / 2])
            return timeGlints(glints, seed)
        },
        // Cached sprite of piece at canvas scale k (canvas px per world unit);
        // a green also keys on its free edges and the outline width
        sprite(piece, kind, k, free, outlineHalf)
        {
            const rel = relativePoints(piece.getPoints())
            const stage = Math.min(canvas.width, canvas.height)
            let key = kind + ':' + k.toFixed(4) + ':' + stage + ':' + rel.join(';')
            if (kind == 'green')
                key += ':' + free.map(f => f ? 1 : 0).join('') + ':' + outlineHalf.toFixed(3)
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
            let glints
            if (kind == 'green')
                glints = this.paintGreen(image.getContext('2d'), points, w, h, stage / REFERENCE_HEIGHT,
                    this.seed(piece, kind), free, outlineHalf)
            else
                glints = this.paintBlue(image.getContext('2d'), points, w, h, stage / REFERENCE_HEIGHT,
                    this.seed(piece, kind))
            // Sprite origin relative to the first point, in world units;
            // glints: [x, y (sprite px), period ms, phase]
            sprite = {image: image, dx: minX / 100 - PAD / k, dy: minY / 100 - PAD / k, k: k, glints: glints}
            this.sprites.set(key, sprite)
            if (this.sprites.size > CACHE_LIMIT)
                this.sprites.delete(this.sprites.keys().next().value)
            ++this.stats.builds
            this.stats.size = this.sprites.size
            return sprite
        },
        // Draws the blue crystal inside piece with globalAlpha alpha, clipped
        // to its polygon; returns its sprite (for drawGlints)
        drawBlue(piece, alpha)
        {
            return this.draw(piece, 'blue', alpha)
        },
        // Draws the green jade (and its lip) inside piece with globalAlpha
        // alpha, clipped to its polygon; returns its sprite
        drawGreen(piece, alpha)
        {
            return this.draw(piece, 'green', alpha)
        },
        // Glint alpha (0.2 .. 1) of a [x, y, period, phase] glint at now ms
        glintAlpha(glint, now)
        {
            const wave = Math.max(0, Math.sin(2 * Math.PI * (now / glint[2] + glint[3])))
            return 0.2 + 0.8 * wave * wave
        },
        // The 4-point star of the backing scale (canvas px per 1080-stage px):
        // a soft core and four tapered rays within GLINT_RADIUS
        glintSprite(unit)
        {
            const key = unit.toFixed(4)
            let sprite = this.glintSprites.get(key)
            if (sprite)
                return sprite
            const r = GLINT_RADIUS * unit
            // Odd: the star is centred on a canvas pixel
            const size = 2 * Math.ceil(r) + 1
            const image = document.createElement('canvas')
            image.width = image.height = size
            const c = image.getContext('2d')
            const m = size / 2
            const halo = c.createRadialGradient(m, m, 0, m, m, r * 0.45)
            halo.addColorStop(0, 'rgba(240,252,255,0.95)')
            halo.addColorStop(0.35, 'rgba(200,240,255,0.55)')
            halo.addColorStop(1, 'rgba(160,220,255,0)')
            c.fillStyle = halo
            c.fillRect(0, 0, size, size)
            const ray = Math.max(0.6, 0.9 * unit)
            c.fillStyle = 'rgba(240,252,255,0.95)'
            c.beginPath()
            c.moveTo(m, m - r); c.lineTo(m + ray, m - ray); c.lineTo(m + r, m); c.lineTo(m + ray, m + ray)
            c.lineTo(m, m + r); c.lineTo(m - ray, m + ray); c.lineTo(m - r, m); c.lineTo(m - ray, m - ray)
            c.closePath()
            c.fill()
            sprite = {image: image, half: Math.floor(size / 2)}
            this.glintSprites.set(key, sprite)
            return sprite
        },
        // Glints of piece (its sprite from drawBlue/drawGreen) in canvas px
        // under the current transform: [{x, y, period, phase}]
        glintPoints(piece, sprite)
        {
            const points = piece.getPoints()
            const m = ctx.getTransform()
            const x = points[0].x + screen.x + sprite.dx, y = points[0].y + screen.y + sprite.dy
            const axis = m.b == 0 && m.c == 0
            const ox = Math.round(m.a * x + m.e), oy = Math.round(m.d * y + m.f)
            return sprite.glints.map(([gx, gy, period, phase]) =>
            {
                if (axis)
                    return {x: ox + gx, y: oy + gy, period: period, phase: phase}
                const wx = x + gx / sprite.k, wy = y + gy / sprite.k
                return {x: m.a * wx + m.c * wy + m.e, y: m.b * wx + m.d * wy + m.f, period: period, phase: phase}
            })
        },
        // Draws the glints of piece at piece alpha alpha on the render clock,
        // clipped to its polygon (on top of the piece and its outline)
        drawGlints(piece, sprite, alpha)
        {
            if (!this.glints || !sprite || !sprite.glints.length)
                return
            const now = performance.now()
            const star = this.glintSprite(Math.min(canvas.width, canvas.height) / REFERENCE_HEIGHT)
            const glints = this.glintPoints(piece, sprite)
            const points = piece.getPoints()
            ctx.save()
            ctx.beginPath()
            ctx.moveTo(points[points.length - 1].x + screen.x, points[points.length - 1].y + screen.y)
            for (let i = 0; i < points.length; ++i)
                ctx.lineTo(points[i].x + screen.x, points[i].y + screen.y)
            ctx.closePath()
            ctx.clip()
            ctx.setTransform(1, 0, 0, 1, 0, 0)
            for (const glint of glints)
            {
                ctx.globalAlpha = alpha * this.glintAlpha([0, 0, glint.period, glint.phase], now)
                ctx.drawImage(star.image, Math.round(glint.x) - star.half, Math.round(glint.y) - star.half)
            }
            ctx.restore()
        },
        draw(piece, kind, alpha)
        {
            const points = piece.getPoints()
            const m = ctx.getTransform()
            const k = Math.hypot(m.a, m.b)
            let sprite
            if (kind == 'green')
            {
                const free = this.edges(piece).map(edge => edge == 'free')
                const outlineHalf = STYLE.strokes.neonOutline.width / scale[version] * k / 2
                sprite = this.sprite(piece, kind, k, free, outlineHalf)
            }
            else
                sprite = this.sprite(piece, kind, k)
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
            return sprite
        }
    }
})()
