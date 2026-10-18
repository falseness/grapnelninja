// Momentum crystal veins (STYLE.momentumFx.veins): thin angular veins in
// the dark wall bodies, seen only where light reaches them. Each border
// strip is cut into squares of its thickness along it, on a grid anchored
// in the world (x for floors and ceilings, y for walls); a square's veins
// are seeded from its world position and painted once into a cached tile.
// Per frame the tiles of the corridor's borders go into a work canvas
// clipped to each body between its cap and its back, are masked by the
// frame's lights (unshadowed: the light of the corridor falls on its wall
// faces) and added over the wall mass, under the cap and the neon face.
// Momentum lighting (MOMENTUM_FX) only; no Math.random.
const WALL_VEINS = (function()
{
    const TILE_LIMIT = 96

    // mulberry32: the same veins on every run and device
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

    return {
        // Test hooks: draw the veins at all / unmasked by the light (white)
        enabled: true,
        fullLight: false,
        // Tile builds, frames drawn
        builds: 0,
        frames: 0,
        tiles: new Map(),
        work: null,
        workCtx: null,
        light: null,
        lightCtx: null,
        // The last frame's drawn box in canvas px [x0, y0, x1, y1] (or null)
        box: null,

        shouldDraw()
        {
            return version == 'momentum' && MOMENTUM_FX.enabled && STYLE.momentumFx.veins.show && this.enabled
        },
        // Vein polylines of the square seeded by seed, in 0..1 tile units
        // (u along the strip's world axis, v from its face into the body)
        layoutVeins(seed)
        {
            const config = STYLE.momentumFx.veins
            const random = generator(seed)
            const range = r => r[0] + (r[1] - r[0]) * random()
            const lo = config.margin, hi = 1 - config.margin
            const inside = p => p[0] >= lo && p[0] <= hi && p[1] >= lo && p[1] <= hi
            const step = (p, angle, length) => [p[0] + length * Math.cos(angle), p[1] + length * Math.sin(angle)]
            const turns = [-2, -1, 1, 2]
            const lines = []
            const count = Math.floor(range([config.veinCount[0], config.veinCount[1] + 1]))
            for (let i = 0; i < count; ++i)
            {
                let p = [range([lo, hi]), range([lo, hi])]
                let k = Math.floor(random() * 12)
                const vein = [p]
                const pieces = Math.floor(range([config.pieces[0], config.pieces[1] + 1]))
                for (let j = 0; j < pieces; ++j)
                {
                    const q = step(p, k * Math.PI / 6, range(config.pieceLength))
                    if (!inside(q))
                        break
                    vein.push(q)
                    p = q
                    if (random() < config.branchChance)
                    {
                        const b = step(p, (k + (random() < 0.5 ? -2 : 2)) * Math.PI / 6, range(config.branchLength))
                        if (inside(b))
                            lines.push([p, b])
                    }
                    k += turns[Math.floor(random() * turns.length)]
                }
                if (vein.length > 1)
                    lines.push(vein)
            }
            return lines
        },
        // The square's tile, size x size canvas px (cached, least recently
        // used dropped past TILE_LIMIT)
        getTile(seed, size)
        {
            const key = seed + '|' + size
            let tile = this.tiles.get(key)
            if (tile)
            {
                this.tiles.delete(key)
                this.tiles.set(key, tile)
                return tile
            }
            const config = STYLE.momentumFx.veins
            tile = document.createElement('canvas')
            tile.width = size
            tile.height = size
            const c = tile.getContext('2d')
            c.strokeStyle = '#ffffff'
            c.lineJoin = 'miter'
            c.lineCap = 'butt'
            const lines = this.layoutVeins(seed)
            const px = canvas.height / 1080
            for (const [width, alpha] of [[config.glowWidth, config.glowAlpha], [config.lineWidth, 1]])
            {
                c.lineWidth = Math.max(1, width * px)
                c.globalAlpha = alpha
                c.beginPath()
                for (const line of lines)
                {
                    c.moveTo(line[0][0] * size, line[0][1] * size)
                    for (let i = 1; i < line.length; ++i)
                        c.lineTo(line[i][0] * size, line[i][1] * size)
                }
                c.stroke()
            }
            this.tiles.set(key, tile)
            if (this.tiles.size > TILE_LIMIT)
                this.tiles.delete(this.tiles.keys().next().value)
            ++this.builds
            return tile
        },
        // Reused canvases: the veins being composed (canvas size) and their
        // light (light canvas size)
        ensureCanvases(lightmap)
        {
            if (!this.work)
            {
                this.work = document.createElement('canvas')
                this.workCtx = this.work.getContext('2d')
                this.light = document.createElement('canvas')
                this.lightCtx = this.light.getContext('2d')
            }
            if (this.work.width != canvas.width || this.work.height != canvas.height)
            {
                this.work.width = canvas.width
                this.work.height = canvas.height
            }
            const source = lightmap.lightCanvas
            if (this.light.width != source.width || this.light.height != source.height)
            {
                this.light.width = source.width
                this.light.height = source.height
            }
        },
        // Tiles of border's squares into the work canvas (transform t: the
        // game's), clipped to its body behind the cap; grows box
        drawBorder(border, t, box)
        {
            const line = border.line
            const thickness = border.thickness
            const n = line.normal
            const vertical = line.direction.x == 0
            // The world axis the squares run along and the face's place on it
            const ax = vertical ? 0 : 1, ay = vertical ? 1 : 0
            const face = Math.round(vertical ? line.x0 : line.y0)
            const a0 = (vertical ? Math.min(line.y0, line.y1) : Math.min(line.x0, line.x1)) - thickness
            const a1 = (vertical ? Math.max(line.y0, line.y1) : Math.max(line.x0, line.x1)) + thickness
            // The view along that axis (world units)
            const v0 = vertical ? -screen.y : -screen.x
            const v1 = v0 + (vertical ? height : width) / scale[version]
            const first = Math.floor(Math.max(a0, v0 - thickness) / thickness)
            const last = Math.floor(Math.min(a1, v1 + thickness) / thickness)
            if (last < first)
                return
            const unit = Math.hypot(t.a, t.b)
            const size = Math.max(1, Math.round(thickness * unit))
            const c = this.workCtx
            c.save()
            c.setTransform(t)
            c.clip(border.getBandPath(thickness, border.getCapDepth()))
            for (let i = first; i <= last; ++i)
            {
                const ox = (vertical ? face : i * thickness) + screen.x
                const oy = (vertical ? i * thickness : face) + screen.y
                const tile = this.getTile(hash(i, face, (n.x + 2) * 4 + n.y + 2), size)
                c.setTransform(t)
                c.transform(ax * thickness, ay * thickness, n.x * thickness, n.y * thickness, ox, oy)
                c.drawImage(tile, 0, 0, 1, 1)
                // Canvas px corners of the square
                for (const [u, v] of [[0, 0], [1, 0], [0, 1], [1, 1]])
                {
                    const wx = ox + (ax * u + n.x * v) * thickness, wy = oy + (ay * u + n.y * v) * thickness
                    const x = t.a * wx + t.c * wy + t.e, y = t.b * wx + t.d * wy + t.f
                    box[0] = Math.min(box[0], x)
                    box[1] = Math.min(box[1], y)
                    box[2] = Math.max(box[2], x)
                    box[3] = Math.max(box[3], y)
                }
            }
            c.restore()
        },
        // Called by drawMomentumOutsideMask inside its clip with the
        // corridor's borders, before their caps and neon faces
        draw(borders)
        {
            this.box = null
            if (!this.shouldDraw() || !borders.length)
                return
            const config = STYLE.momentumFx.veins
            const lightmap = visualEffects.lightmap
            this.ensureCanvases(lightmap)
            if (!this.fullLight && !lightmap.fillUnshadowedLights(this.lightCtx, config.reach, config.gain))
                return
            const c = this.workCtx
            const w = canvas.width, h = canvas.height
            c.setTransform(1, 0, 0, 1, 0, 0)
            c.globalAlpha = 1
            c.globalCompositeOperation = 'source-over'
            c.clearRect(0, 0, w, h)
            const t = ctx.getTransform()
            const box = [Infinity, Infinity, -Infinity, -Infinity]
            for (const border of borders)
                this.drawBorder(border, t, box)
            const x0 = Math.max(0, Math.floor(box[0])), y0 = Math.max(0, Math.floor(box[1]))
            const x1 = Math.min(w, Math.ceil(box[2])), y1 = Math.min(h, Math.ceil(box[3]))
            if (x1 <= x0 || y1 <= y0)
                return
            this.box = [x0, y0, x1, y1]
            c.setTransform(1, 0, 0, 1, 0, 0)
            if (!this.fullLight)
            {
                // Light px -> canvas px (the light canvas spans the logical viewport)
                const k = canvas.width / LOGICAL_VIEWPORT.width / lightmap.scale
                c.globalCompositeOperation = 'source-in'
                c.imageSmoothingEnabled = true
                c.drawImage(this.light, 0, 0, this.light.width * k, this.light.height * k)
                c.globalCompositeOperation = 'source-over'
            }
            ctx.save()
            ctx.setTransform(1, 0, 0, 1, 0, 0)
            ctx.globalAlpha = 1
            ctx.globalCompositeOperation = 'lighter'
            ctx.drawImage(this.work, x0, y0, x1 - x0, y1 - y0, x0, y0, x1 - x0, y1 - y0)
            ctx.restore()
            ++this.frames
        }
    }
})()
