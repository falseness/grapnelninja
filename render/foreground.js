// Momentum foreground crystal silhouettes (STYLE.momentumFx.foreground):
// near-black crystals in front of everything but the HUD, rising from the
// bottom screen edge and hanging under the HUD, visible only through edge
// windows at the left and right sides. A bottom and a top strip of the
// canvas width are painted once per viewport (soft: painted at 1 / blur of
// the resolution and scaled up) with an outline tile of the same crystals,
// and scroll horizontally at parallax x the camera shift, wrapping. The
// outline tile masked by the frame's lights (unshadowed: the crystals stand
// in front of the walls) is added as their rim. Momentum lighting
// (MOMENTUM_FX) only; no gradients, blur or allocations per frame.
const FOREGROUND = (function()
{
    const BANDS = ['bottom', 'top']

    return {
        // Test hooks: draw the silhouettes / their rim at all
        enabled: true,
        rimEnabled: true,
        // Strip and mask builds per band, and frames drawn
        builds: {bottom: 0, top: 0},
        frames: 0,
        cache: {bottom: null, top: null},
        work: null,
        workCtx: null,
        light: null,
        lightCtx: null,
        // The frame's band layout ({band, y, height, window, shift}), canvas px
        layout: [],

        shouldDraw()
        {
            return version == 'momentum' && MOMENTUM_FX.enabled && STYLE.momentumFx.foreground.show
                && this.enabled
        },
        // The strip's horizontal shift this frame in canvas px: parallax x
        // the world's translation on the canvas
        getShift()
        {
            return STYLE.momentumFx.foreground.parallax * screen.x * canvas.width / width * scale[version]
        },
        // Lowest canvas px row the HUD (score, record, hearts, menu button)
        // and its glow reach
        getHudBottom()
        {
            const viewWidth = width / scale[version]
            const viewHeight = height / scale[version]
            const toCanvas = canvas.height / height * scale[version]
            let bottom = getHudCenterY(viewHeight, version) + getHudFontSize(viewWidth, viewHeight, version) * 0.6
            if (menu.button && menu.button.background)
                bottom = Math.max(bottom, menu.button.background.y + menu.button.background.height)
            const glow = 2 * (STYLE.ui.textShadowBlur + STYLE.ui.hudExtraShadowBlur) * canvas.height / height
            return Math.ceil(bottom * toCanvas + glow) + 8
        },
        // Band rectangles of this canvas: the bottom band and the top band
        // under the HUD; window: the width of each side window
        getBands()
        {
            const config = STYLE.momentumFx.foreground
            const w = canvas.width, h = canvas.height
            const bandHeight = Math.floor(h * config.bandHeight) - 1
            const window = Math.floor(w * config.bandWidth) - 1
            const top = Math.min(this.getHudBottom(), bandHeight)
            return {
                bottom: {y: h - bandHeight, height: bandHeight, window: window, full: bandHeight},
                top: {y: top, height: bandHeight - top, window: window, full: bandHeight}
            }
        },
        // Strip, outline and window mask of band for the canvas size
        getTile(name, band)
        {
            const w = canvas.width
            const key = [w, canvas.height, band.y, band.height, band.window].join('|')
            const cached = this.cache[name]
            if (cached && cached.key === key)
                return cached
            const crystals = this.layoutCrystals(name, w, band)
            const tile = {
                key: key,
                fill: this.paintStrip(w, band.height, crystals, false),
                edges: this.paintStrip(w, band.height, crystals, true),
                mask: this.paintMask(name, w, band)
            }
            this.cache[name] = tile
            ++this.builds[name]
            return tile
        },
        // Seeded crystals along a strip of width w: polygons in strip px
        // (bottom band: base on its bottom edge; top band: on its top edge)
        layoutCrystals(name, w, band)
        {
            const config = STYLE.momentumFx.foreground
            let seed = (config.seed + (name == 'top' ? 0x9e3779b9 : 0)) >>> 0
            // mulberry32: the same strip on every run and device
            const random = () =>
            {
                seed = (seed + 0x6D2B79F5) >>> 0
                let t = seed
                t = Math.imul(t ^ t >>> 15, t | 1)
                t ^= t + Math.imul(t ^ t >>> 7, t | 61)
                return ((t ^ t >>> 14) >>> 0) / 4294967296
            }
            const range = r => r[0] + (r[1] - r[0]) * random()
            const crystals = []
            const h = band.height
            const flip = name == 'top'
            const y = v => flip ? h - v : v
            for (let x = range(config.spacing) * w * 0.5; x < w; x += range(config.spacing) * w)
            {
                const tall = range(config.crystalHeight) * h
                const half = range(config.crystalWidth) * band.full / 2
                const lean = (random() * 2 - 1) * config.lean * half
                const shoulderL = 0.55 + random() * 0.25, shoulderR = 0.45 + random() * 0.25
                const base = h + 2
                const outline = [
                    [x - half, y(base)],
                    [x - half * 0.8 + lean * shoulderL, y(h - tall * shoulderL)],
                    [x + lean, y(h - tall)],
                    [x + half * 0.8 + lean * shoulderR, y(h - tall * shoulderR)],
                    [x + half, y(base)]
                ]
                const ridge = x + (random() - 0.5) * half * 0.6
                crystals.push({outline: outline, facet: [outline[0], outline[1], outline[2], [ridge, y(base)]],
                    ridge: [outline[2], [ridge, y(h - tall * 0.15)]], half: half})
            }
            return crystals
        },
        // The crystals (or their outlines) into a w x h strip, wrapped at its
        // ends, painted at 1 / blur of the size and scaled up
        paintStrip(w, h, crystals, edges)
        {
            const config = STYLE.momentumFx.foreground
            const full = document.createElement('canvas')
            full.width = w
            full.height = Math.max(1, h)
            const c = full.getContext('2d')
            const lineWidth = Math.max(1, config.rimWidth * canvas.height / 1080)
            c.lineJoin = 'round'
            c.lineCap = 'round'
            const path = (points, close) =>
            {
                c.beginPath()
                c.moveTo(points[0][0], points[0][1])
                for (let i = 1; i < points.length; ++i)
                    c.lineTo(points[i][0], points[i][1])
                if (close)
                    c.closePath()
            }
            for (const crystal of crystals)
                for (const dx of [-w, 0, w])
                {
                    const left = crystal.outline[0][0] + dx - crystal.half
                    if (left > w || left + 3 * crystal.half < 0)
                        continue
                    c.setTransform(1, 0, 0, 1, dx, 0)
                    if (edges)
                    {
                        // Crystals in front hide the outlines behind them
                        c.globalCompositeOperation = 'destination-out'
                        path(crystal.outline, true)
                        c.fill()
                        c.globalCompositeOperation = 'source-over'
                        c.strokeStyle = '#ffffff'
                        c.lineWidth = lineWidth
                        path(crystal.outline, false)
                        c.stroke()
                        c.lineWidth = lineWidth * 0.5
                        path(crystal.ridge, false)
                        c.stroke()
                    }
                    else
                    {
                        c.fillStyle = config.fill
                        path(crystal.outline, true)
                        c.fill()
                        c.fillStyle = config.facet
                        path(crystal.facet, true)
                        c.fill()
                    }
                }
            const small = document.createElement('canvas')
            small.width = Math.max(1, Math.round(w / config.blur))
            small.height = Math.max(1, Math.round(full.height / config.blur))
            const s = small.getContext('2d')
            s.imageSmoothingEnabled = true
            s.drawImage(full, 0, 0, small.width, small.height)
            c.setTransform(1, 0, 0, 1, 0, 0)
            c.globalCompositeOperation = 'copy'
            c.imageSmoothingEnabled = true
            c.drawImage(small, 0, 0, w, full.height)
            c.globalCompositeOperation = 'source-over'
            return full
        },
        // Alpha of the band's two side windows: 1 at the screen edge, fading
        // to 0 over fadeWidth at the window's inner side; the top band also
        // fades in under the HUD
        paintMask(name, w, band)
        {
            const config = STYLE.momentumFx.foreground
            const mask = document.createElement('canvas')
            mask.width = w
            mask.height = Math.max(1, band.height)
            const c = mask.getContext('2d')
            const fade = Math.min(band.window, Math.round(config.fadeWidth * w))
            const left = c.createLinearGradient(band.window - fade, 0, band.window, 0)
            left.addColorStop(0, '#ffffff')
            left.addColorStop(1, 'rgba(255, 255, 255, 0)')
            c.fillStyle = left
            c.fillRect(0, 0, band.window, mask.height)
            const right = c.createLinearGradient(w - band.window + fade, 0, w - band.window, 0)
            right.addColorStop(0, '#ffffff')
            right.addColorStop(1, 'rgba(255, 255, 255, 0)')
            c.fillStyle = right
            c.fillRect(w - band.window, 0, band.window, mask.height)
            if (name == 'top')
            {
                const down = c.createLinearGradient(0, 0, 0, mask.height * 0.3)
                down.addColorStop(0, 'rgba(255, 255, 255, 0)')
                down.addColorStop(1, '#ffffff')
                c.globalCompositeOperation = 'destination-in'
                c.fillStyle = down
                c.fillRect(0, 0, w, mask.height)
            }
            return mask
        },
        // Reused scratch canvases: the band being composed and the
        // foreground's light (light canvas resolution)
        ensureCanvases(lightmap)
        {
            if (!this.work)
            {
                this.work = document.createElement('canvas')
                this.workCtx = this.work.getContext('2d')
                this.light = document.createElement('canvas')
                this.lightCtx = this.light.getContext('2d')
            }
            const fullHeight = Math.floor(canvas.height * STYLE.momentumFx.foreground.bandHeight)
            if (this.work.width != canvas.width || this.work.height != fullHeight)
            {
                this.work.width = canvas.width
                this.work.height = fullHeight
            }
            const source = lightmap.lightCanvas
            if (this.light.width != source.width || this.light.height != source.height)
            {
                this.light.width = source.width
                this.light.height = source.height
            }
        },
        // The frame's lights reaching rimReach times as far at rimGain (whole
        // 'lighter' passes past alpha 1), unshadowed; false without lights
        fillLight(lightmap)
        {
            const lights = lightmap.getFrameLights()
            if (!lights || !lights.length)
                return false
            const config = STYLE.momentumFx.foreground
            const c = this.lightCtx
            c.setTransform(1, 0, 0, 1, 0, 0)
            c.globalAlpha = 1
            c.globalCompositeOperation = 'source-over'
            c.clearRect(0, 0, this.light.width, this.light.height)
            c.globalCompositeOperation = 'lighter'
            for (const light of lights)
            {
                let radius = light.radius
                let gradient = light.gradient
                if (light.element)
                {
                    radius = STYLE.momentumLight.blueSpread
                        + light.element.circle.radius * scale[version] * 1080 / height
                    gradient = lightmap.getLightGradient(light.color)
                }
                for (let alpha = light.alpha * config.rimGain; alpha > 0; alpha -= 1)
                    lightmap.fillRadialLight(c, light.x, light.y, radius * config.rimReach, gradient,
                        Math.min(1, alpha))
            }
            c.setTransform(1, 0, 0, 1, 0, 0)
            c.globalAlpha = 1
            c.globalCompositeOperation = 'source-over'
            return true
        },
        // Composes source (a strip, its shift wrapped) into the work canvas
        // through the band's windows and mask; lit: masked by the light first
        composeBand(source, band, tile, shift, lit)
        {
            const c = this.workCtx
            const w = canvas.width
            c.save()
            c.setTransform(1, 0, 0, 1, 0, 0)
            c.globalAlpha = 1
            c.globalCompositeOperation = 'source-over'
            c.clearRect(0, 0, w, band.height)
            c.beginPath()
            c.rect(0, 0, band.window, band.height)
            c.rect(w - band.window, 0, band.window, band.height)
            c.clip()
            const offset = ((shift % w) + w) % w
            c.drawImage(source, offset - w, 0)
            c.drawImage(source, offset, 0)
            if (lit)
            {
                // Light px -> canvas px (the light canvas spans the logical viewport)
                const k = canvas.width / LOGICAL_VIEWPORT.width / this.lightScale
                c.globalCompositeOperation = 'source-in'
                c.imageSmoothingEnabled = true
                c.drawImage(this.light, 0, -band.y, this.light.width * k, this.light.height * k)
            }
            c.globalCompositeOperation = 'destination-in'
            c.drawImage(tile.mask, 0, 0)
            c.restore()
        },
        draw()
        {
            if (!this.shouldDraw())
                return
            const lightmap = visualEffects.lightmap
            this.ensureCanvases(lightmap)
            this.lightScale = lightmap.scale
            const shift = this.getShift()
            const bands = this.getBands()
            const lit = this.rimEnabled && this.fillLight(lightmap)
            const w = canvas.width
            this.layout.length = 0
            ctx.save()
            ctx.setTransform(1, 0, 0, 1, 0, 0)
            ctx.globalAlpha = 1
            for (const name of BANDS)
            {
                const band = bands[name]
                if (band.height <= 0 || band.window <= 0)
                    continue
                const tile = this.getTile(name, band)
                this.layout.push({band: name, y: band.y, height: band.height, window: band.window, shift: shift})
                this.composeBand(tile.fill, band, tile, shift, false)
                ctx.globalCompositeOperation = 'source-over'
                ctx.drawImage(this.work, 0, 0, w, band.height, 0, band.y, w, band.height)
                if (!lit)
                    continue
                this.composeBand(tile.edges, band, tile, shift, true)
                ctx.globalCompositeOperation = 'lighter'
                ctx.drawImage(this.work, 0, 0, w, band.height, 0, band.y, w, band.height)
            }
            ctx.restore()
            ++this.frames
        }
    }
})()
