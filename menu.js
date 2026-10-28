function reuseTimeInGame() {
    // A player can start/resume while the host still freezes gameplay.
    // Host release will open the segment once the run is permitted again.
    if (typeof hostPaused !== 'undefined' && hostPaused) return
    if (Number.isFinite(time)) return
    time = Math.floor(new Date().getTime() / 1000)
}
function pauseTimeInGame() {
    let thisTime = Math.floor(new Date().getTime() / 1000)
    let delta = Number.isFinite(time) ? Math.floor(thisTime - time) : 0
    // Pausing/death can be followed by a host pause. Account for this segment
    // once, and exclude time spent in the death offer, menu or advertisement.
    time = null

    if (Number.isFinite(delta) && delta > 0)
        PROGRESS.setTime(PROGRESS.getTime() + delta)
}
function getTimeInGame() {
    return Math.floor(PROGRESS.getTime() / 60)
}

// Test hook: while LAYOUT_PROBE.boxes is an array, UI text and buttons
// push their boxes there in CSS px relative to the canvas, with the CSS
// font size for text. Uses the current transform, so scaled views work.
const LAYOUT_PROBE =
{
    boxes: null,
    toCss(x, y)
    {
        const m = ctx.getTransform()
        // Backing px per CSS px per axis (backing sizes are rounded apart)
        const css = getCanvasCssRect()
        const rx = canvas.width / css.width
        const ry = canvas.height / css.height
        return {x: (m.a * x + m.c * y + m.e) / rx, y: (m.b * x + m.d * y + m.f) / ry}
    },
    rect(kind, name, x, y, w, h)
    {
        if (!this.boxes)
            return
        const a = this.toCss(x, y)
        const b = this.toCss(x + w, y + h)
        this.boxes.push({kind: kind, name: name, x: a.x, y: a.y, width: b.x - a.x, height: b.y - a.y})
    },
    // Text drawn with the current ctx font, align and baseline
    text(name, x, y)
    {
        if (!this.boxes || name === '')
            return
        const t = ctx.measureText(name)
        const a = this.toCss(x - t.actualBoundingBoxLeft, y - t.actualBoundingBoxAscent)
        const b = this.toCss(x + t.actualBoundingBoxRight, y + t.actualBoundingBoxDescent)
        const m = ctx.getTransform()
        const fontPx = parseFloat(ctx.font) * Math.hypot(m.a, m.b) /
            (canvas.width / getCanvasCssRect().width)
        this.boxes.push({kind: 'text', name: String(name), x: a.x, y: a.y,
            width: b.x - a.x, height: b.y - a.y, fontPx: fontPx})
    }
}

class Text
{
    constructor(object)
    {
        this.x = object.x
        this.y = object.y
        
        this.fill       = object.fill
        // Neon tube colour around the letters (titles), else a plain glow
        this.glow       = object.glow
        this.fontSize   = object.fontSize + 'px ' + STYLE.ui.fontFamily
        this.text       = object.text
        this.align      =
        {
            x: object.alignX || 'center',
            y: object.alignY || 'middle'
        }
    }
    draw()
    {
        ctx.save()
        ctx.fillStyle   = this.fill
        ctx.textBaseline= this.align.y
        ctx.textAlign   = this.align.x
        ctx.font        = this.fontSize
        if (this.glow)
            this.strokeNeonTube()
        drawGlowText(this.text, this.x, this.y, this.glow || this.fill, STYLE.ui.textShadowBlur, false)
        LAYOUT_PROBE.text(this.text, this.x, this.y)
        ctx.restore()
    }
    // Halo strokes of the letters in the glow colour, like strokeNeonPath
    strokeNeonTube()
    {
        const size = parseFloat(this.fontSize)

        ctx.strokeStyle = this.glow
        ctx.lineJoin = 'round'
        ctx.globalAlpha = STYLE.ui.titleHaloAlpha * neonPulse
        ctx.lineWidth = size * STYLE.ui.titleHaloWidthRatio
        ctx.strokeText(this.text, this.x, this.y)
        ctx.globalAlpha = STYLE.ui.titleInnerHaloAlpha * neonPulse
        ctx.lineWidth = size * STYLE.ui.titleInnerHaloWidthRatio
        ctx.strokeText(this.text, this.x, this.y)
        ctx.globalAlpha = 1
        ctx.lineWidth = size * STYLE.ui.titleTubeWidthRatio
        ctx.strokeText(this.text, this.x, this.y)
    }
    // Bloom pass (BloomRenderer.drawScreen): the letters in the glow colour
    drawGlow()
    {
        ctx.fillStyle    = this.glow || this.fill
        ctx.textBaseline = this.align.y
        ctx.textAlign    = this.align.x
        ctx.font         = this.fontSize
        ctx.fillText(this.text, this.x, this.y)
    }
}
// Outline of a rect in the game's neon (STYLE.ui.neonUnit), for the menu and
// pause screens drawn in logical units
function strokeNeonRect(x, y, w, h, color, unit)
{
    ctx.save()
    ctx.beginPath()
    ctx.rect(x, y, w, h)
    strokeNeonPath(color, 1, unit)
    ctx.restore()
}
// Centres of rows of the given heights stacked between top and bottom
// with equal gaps
function stackRows(top, bottom, heights)
{
    const gap = (bottom - top - heights.reduce((a, b) => a + b, 0)) / (heights.length + 1)
    let y = top
    return heights.map(h =>
    {
        y += gap + h
        return y - h / 2
    })
}
// Phones: the 44 CSS px touch floor (in logical units) when it outgrows the
// default button height, else 0
function compactTouchSize(buttonHeight)
{
    const touch = minTouchSize()
    return touch > buttonHeight ? touch : 0
}
// Label font size to button height: ascenders stay inside the frame
const buttonLabelHeightRatio = 0.8
function getArcadeFont(size)
{
    return size + 'px ' + STYLE.ui.fontFamily
}
class Button
{
    constructor(background, text, clickFunc, image)
    {
        this.background         = {}
        this.background.x       = background.x - background.width   / 2
        this.background.y       = background.y - background.height  / 2
        this.background.width   = background.width
        this.background.height  = background.height
        this.background.fill    = background.fill   || STYLE.colors.ui.buttonFill
        this.background.stroke  = background.stroke || STYLE.colors.ui.buttonStroke
        
        text.x          = background.x
        text.y          = background.y
        text.fontSize   = this.getFittedTextSize(text.text, this.background.height * buttonLabelHeightRatio)
        
        if (typeof background.clickable == "undefined")
            this.clickable = true
        else
            this.clickable  = background.clickable
        
        this.text = new Text(text)
        
        this.image = image
        // Menu and pause buttons: neon outline (the HUD menu button keeps its glow)
        this.neon = !!background.neon
        
        this.click = clickFunc
    }
    getFittedTextSize(label, maxSize)
    {
        if (!label)
            return maxSize

        const horizontalPadding = this.background.height * STYLE.ui.buttonTextPaddingRatio * 2
        const maxWidth = Math.max(1, this.background.width - horizontalPadding)

        ctx.save()
        ctx.font = getArcadeFont(maxSize)
        const measuredWidth = ctx.measureText(label).width
        ctx.restore()

        if (measuredWidth <= maxWidth)
            return maxSize

        return Math.max(STYLE.ui.buttonMinFontSize, maxSize * maxWidth / measuredWidth)
    }
    draw()
    {
        const inset = Math.min(this.background.width, this.background.height) * STYLE.ui.buttonInsetRatio
        const iconOnly = !!this.image && this.text.text == ''

        ctx.save()
        ctx.fillStyle   = this.background.fill
        ctx.strokeStyle = this.background.stroke
        ctx.lineWidth   = STYLE.ui.buttonLineWidth
        
        ctx.fillRect(this.background.x, this.background.y, this.background.width, this.background.height)
        if (this.neon)
            strokeNeonRect(this.background.x, this.background.y, this.background.width, this.background.height,
                this.background.stroke, STYLE.ui.neonUnit.button)
        else
        {
            const stroke = this.background.stroke
            drawGlowRect('button|' + stroke, this.background.x, this.background.y,
                this.background.width, this.background.height, STYLE.ui.buttonLineWidth, STYLE.ui.buttonShadowBlur,
                (x, y, w, h) =>
            {
                ctx.strokeStyle = stroke
                ctx.lineWidth = STYLE.ui.buttonLineWidth
                ctx.shadowColor = stroke
                ctx.shadowBlur = STYLE.ui.buttonShadowBlur
                ctx.strokeRect(x, y, w, h)
            })
        }
        LAYOUT_PROBE.rect('button', this.text.text || 'icon', this.background.x, this.background.y,
            this.background.width, this.background.height)

        // fade: the Grapple Over HUD yield (CLIMB_UI.drawHud) scales the inset too
        ctx.globalAlpha = 0.58 * (this.fade || 1)
        ctx.strokeRect(
            this.background.x + inset,
            this.background.y + inset,
            this.background.width - inset * 2,
            this.background.height - inset * 2
        )
        ctx.restore()
        
        if (!iconOnly)
            this.text.draw()
        
        if (this.image)
            this.image.draw(this.background.x, this.background.y, this.background.width, this.background.height)
    }
    // Bloom pass: the outline as one plain line
    drawGlow()
    {
        ctx.beginPath()
        ctx.rect(this.background.x, this.background.y, this.background.width, this.background.height)
        strokeNeonPath(this.background.stroke, 1, STYLE.ui.neonUnit.button)
    }
    isClickOnButton(click)
    {
        if (this.clickable)
        {
            if (this.background.x < click.x && click.x < this.background.x + this.background.width &&
                this.background.y < click.y && click.y < this.background.y + this.background.height)
            {
                this.click()
                return true
            }
        }
        return false
    }
}
class Checkbox
{
    constructor(object, clickFunc)
    {
        this.x = object.x
        this.y = object.y
        this.size = object.size
        this.label = object.label
        this.fill = object.fill || STYLE.colors.ui.text
        this.stroke = object.stroke || STYLE.colors.ui.primary
        this.clickable = object.clickable
        this.click = clickFunc
        this.fontSize = object.fontSize + 'px ' + STYLE.ui.fontFamily
    }
    draw()
    {
        const boxX = this.x
        const boxY = this.y - this.size / 2
        const markInset = this.size * 0.24

        ctx.save()
        ctx.font = this.fontSize
        ctx.textAlign = 'start'
        ctx.textBaseline = 'middle'
        ctx.fillStyle = this.fill
        ctx.strokeStyle = this.stroke
        strokeNeonRect(boxX, boxY, this.size, this.size, this.stroke, STYLE.ui.neonUnit.small)
        ctx.globalAlpha = 1
        ctx.lineWidth = STYLE.ui.buttonLineWidth

        if (fpsCounter.enabled)
        {
            const stroke = this.stroke, size = this.size, y = this.y
            const markWidth = Math.max(STYLE.ui.buttonLineWidth, size * 0.12)
            drawGlowSprite('check|' + stroke + '|' + size + '|' + (y - boxY), boxX, boxY, size, size,
                markWidth, STYLE.ui.buttonShadowBlur, () =>
            {
                ctx.strokeStyle = stroke
                ctx.lineWidth = markWidth
                ctx.shadowColor = stroke
                ctx.shadowBlur = STYLE.ui.buttonShadowBlur
                ctx.beginPath()
                ctx.moveTo(boxX + markInset, y)
                ctx.lineTo(boxX + size * 0.43, boxY + size - markInset)
                ctx.lineTo(boxX + size - markInset, boxY + markInset)
                ctx.stroke()
            })
        }

        drawGlowText(this.label, boxX + this.size * 1.55, this.y, this.stroke, STYLE.ui.textShadowBlur, false)
        LAYOUT_PROBE.text(this.label, boxX + this.size * 1.55, this.y)
        if (LAYOUT_PROBE.boxes)
        {
            const hit = this.hitRect()
            LAYOUT_PROBE.rect('button', this.label, hit.x, hit.y, hit.width, hit.height)
        }
        ctx.restore()
    }
    // Bloom pass: the box as one plain line
    drawGlow()
    {
        ctx.beginPath()
        ctx.rect(this.x, this.y - this.size / 2, this.size, this.size)
        strokeNeonPath(this.stroke, 1, STYLE.ui.neonUnit.small)
    }
    // Box and label plus a padding; at least a touch target high
    hitRect()
    {
        ctx.save()
        ctx.font = this.fontSize
        const labelWidth = ctx.measureText(this.label).width
        ctx.restore()

        const padding = this.size * 0.45
        const height = Math.max(this.size * 1.5, minTouchSize())
        return {
            x: this.x - padding,
            y: this.y - height / 2,
            width: this.size * 1.55 + labelWidth + padding * 2,
            height: height
        }
    }
    isClickOnButton(click)
    {
        if (!this.clickable)
            return false

        const r = this.hitRect()
        if (r.x < click.x && click.x < r.x + r.width && r.y < click.y && click.y < r.y + r.height)
        {
            this.click()
            return true
        }
        return false
    }
}
// Legibility floor in CSS px for small iframes (800x450).
const minCssFontPx = 12

class FpsCounter
{
    constructor()
    {
        this.enabled = false
        this.frames = 0
        this.lastSampleTime = 0
        this.value = 0
    }
    toggle()
    {
        this.enabled = !this.enabled
        this.frames = 0
        this.lastSampleTime = 0
    }
    frame(frameTime)
    {
        if (!this.enabled)
            return

        if (!this.lastSampleTime)
            this.lastSampleTime = frameTime

        ++this.frames

        const elapsed = frameTime - this.lastSampleTime

        if (elapsed >= STYLE.ui.fpsUpdateMs)
        {
            this.value = Math.round(this.frames * 1000 / elapsed)
            this.frames = 0
            this.lastSampleTime = frameTime
        }
    }
    draw()
    {
        if (!this.enabled || typeof version == 'undefined')
            return

        const viewWidth = width / scale[version]
        const viewHeight = height / scale[version]
        // Never below the CSS px floor when the iframe is small.
        const cssPerView = getCanvasCssRect().height / viewHeight
        const fontSize = Math.max(viewHeight * STYLE.ui.fpsFontRatio, minCssFontPx / cssPerView)
        const padding = viewHeight * STYLE.ui.fpsPaddingRatio
        const text = I18N.t('hud.fps', {value: this.value})

        ctx.save()
        ctx.font = fontSize + 'px ' + STYLE.ui.fontFamily
        ctx.textAlign = 'start'
        ctx.textBaseline = 'middle'

        const metrics = ctx.measureText(text)
        const panelWidth = metrics.width + padding * 2
        const panelHeight = fontSize + padding * 1.4
        const y = getHudCenterY(viewHeight, version)
        const x = this.getTextX(viewWidth, viewHeight, text, panelWidth, padding)
        const panelX = x - padding
        const panelY = y - panelHeight / 2

        drawGlowRect('fps-panel', panelX, panelY, panelWidth, panelHeight, STYLE.ui.fpsPanelLineWidth,
            STYLE.ui.textShadowBlur, (x, y, w, h) =>
        {
            ctx.fillStyle = STYLE.colors.ui.fpsPanelFill
            ctx.strokeStyle = STYLE.colors.ui.fpsPanelStroke
            ctx.lineWidth = STYLE.ui.fpsPanelLineWidth
            ctx.shadowColor = STYLE.colors.ui.hudGlow
            ctx.shadowBlur = STYLE.ui.textShadowBlur
            ctx.fillRect(x, y, w, h)
            ctx.strokeRect(x, y, w, h)
        })

        ctx.fillStyle = STYLE.colors.ui.hudText
        ctx.strokeStyle = STYLE.colors.ui.hudGlow
        ctx.lineWidth = Math.max(1, STYLE.ui.fpsPanelLineWidth * 0.65)
        drawGlowText(text, x, y, STYLE.colors.ui.hudGlow, STYLE.ui.textShadowBlur, true)
        LAYOUT_PROBE.text(text, x, y)
        ctx.restore()
    }
    getTextX(viewWidth, viewHeight, text, panelWidth, padding)
    {
        const scoreX = viewWidth * STYLE.ui.fpsXRatio
        const scoreValue = scoreText.text + scoreText.count[version]
        const recordValue = scoreText.rtext + scoreText.record[version]
        const gap = Math.max(padding, viewWidth * STYLE.ui.hudBadTextGapRatio)

        ctx.save()
        ctx.font = getHudFontSize(viewWidth, viewHeight, version) + 'px ' + STYLE.ui.fontFamily
        const scoreRight = scoreX + ctx.measureText(scoreValue).width
        const recordX = scoreText.getRecordX(viewWidth)
        const recordWidth = ctx.measureText(recordValue).width
        const recordLeft = recordX - recordWidth
        ctx.restore()

        const preferredX = scoreRight + gap + padding
        const minX = scoreRight + padding * 2
        const maxX = recordLeft - gap - panelWidth + padding

        if (maxX >= preferredX)
            return preferredX

        return Math.max(minX, maxX)
    }
}
// Bloom of the menu and pause controls (BloomRenderer.drawScreen)
function drawScreenGlow(drawShapes)
{
    if (typeof visualEffects != 'undefined' && visualEffects && visualEffects.bloom)
        visualEffects.bloom.drawScreen(drawShapes)
}
class Menu
{
    constructor(w, h)
    {
        this.width  = w
        this.height = h
        
        this.gamePaused = false
        
        this.center = 
        {
            x: this.width  / 2,
            y: this.height / 2,
        }
        
        this.timeInGame = new Text(
            {
            x       : this.center.x                     ,
            y       : 0.82 * this.height                ,
            fontSize: 0.05 * this.height                ,
            fill    : STYLE.colors.ui.mutedText         ,
            text    : I18N.t('menu.timeInGame', {minutes: getTimeInGame()})
        })

        this.pauseFpsCounterCheckbox = new Checkbox(
        {
            x       : this.center.x - 0.15 * this.width,
            y       : 0.68 * this.height,
            size    : 0.09 * this.height,
            fontSize: 0.09 * this.height,
            fill    : STYLE.colors.ui.text,
            stroke  : STYLE.colors.ui.primary,
            label   : I18N.t('menu.fpsCounter'),
            clickable: false
        },
        function()
        {
            fpsCounter.toggle()
            // A fresh frame under the screen, so the tint and glow do not stack
            draw()
            menu.drawPauseScreen()
        })
        
        this.args = 
        [
            {
                text: ''
            },
            function()
            {
                menu.startPause()
            },
            {
                draw: function(x, y, w, h)
                {
                    const lineWidth = Math.round(STYLE.strokes.menuIconWidthRatio * h)
                    drawGlowSprite('menu-icon|' + w + '|' + h, x, y, w, h, lineWidth, STYLE.ui.buttonShadowBlur, () =>
                    {
                        ctx.beginPath()

                        ctx.lineWidth = lineWidth

                        let x1 = x + 0.1 * w, x2 = x + 0.9 * w
                        let y1 = y + 0.3 * h
                        let dy = 0.2 * h
                        ctx.moveTo(x1, y1)
                        ctx.lineTo(x2, y1)

                        ctx.moveTo(x1, y1 + dy)
                        ctx.lineTo(x2, y1 + dy)

                        ctx.moveTo(x1, y1 + dy * 2)
                        ctx.lineTo(x2, y1 + dy * 2)

                        ctx.strokeStyle = STYLE.colors.ui.hudGlow
                        ctx.shadowColor = STYLE.colors.ui.hudGlow
                        ctx.shadowBlur = STYLE.ui.buttonShadowBlur
                        ctx.stroke()
                    })

                    ctx.lineWidth = STYLE.strokes.defaultWidth
                }
            }
        ]
        this.constButton = 
        {
            x       : 0.965 * this.width,
            y       : 0.058 * this.height,
            width   : 0.072 * this.height,
            height  : 0.072 * this.height,
            fill    : STYLE.colors.ui.transparent,
            stroke  : STYLE.colors.ui.hudGlow
        }
        this.resume = new Button(
        {
            x: this.center.x        ,
            y: 0.35 * this.height   ,
            width: 0.4 * this.width ,
            clickable:false         ,
            height: 0.1 * this.height,
            stroke: STYLE.colors.ui.primary,
            neon: true
        },
        {
            text: I18N.t('pause.resume'),
            fill: STYLE.colors.ui.buttonText
        }, function()
        {
            menu.unPause()
        })
        this.modeButtons = ['grapple_over', 'bad', 'classic'].map(mode =>
            new Button(
                {x: 0, y: 0, width: 1, height: 1, clickable: false,
                 stroke: STYLE.colors.ui.buttonDangerStroke, neon: true},
                {text: '', fill: STYLE.colors.ui.buttonText},
                () => this.selectMode(mode)))
        this.relabelPauseSwitch()
    }
    getPausePanel()
    {
        const panelWidth = Math.min(this.width * 0.84, this.width - this.width * STYLE.ui.pauseMarginWidthPercent / 100)
        const panelHeight = Math.min(this.height * 0.76, this.height - this.height * STYLE.ui.pauseMarginHeightPercent / 100)

        return {
            x: (this.width - panelWidth) / 2,
            y: (this.height - panelHeight) / 2,
            width: panelWidth,
            height: panelHeight
        }
    }
    getPauseTitleFontSize(panel)
    {
        const text = I18N.t('game.title')
        const maxWidth = Math.max(1, panel.width - Math.max(this.width * STYLE.ui.pauseMarginWidthPercent / 100, this.width * 0.12))
        const preferredSize = Math.min(this.width * 0.075, panel.height * 0.14)

        ctx.save()
        ctx.font = getArcadeFont(preferredSize)
        const measuredWidth = ctx.measureText(text).width
        ctx.restore()

        if (measuredWidth <= maxWidth)
            return preferredSize

        return Math.max(STYLE.ui.buttonMinFontSize, preferredSize * maxWidth / measuredWidth)
    }
    getPauseTitle(panel)
    {
        return new Text(
        {
            fill    : STYLE.colors.ui.title,
            glow    : STYLE.colors.ui.titleGlow,
            fontSize: this.getPauseTitleFontSize(panel),
            text    : I18N.t('game.title'),
            x       : this.center.x,
            y       : this.pauseTitleY
        })
    }
    layoutPauseButton(button, x, y, width, height)
    {
        button.background.x = x - width / 2
        button.background.y = y - height / 2
        button.background.width = width
        button.background.height = height
        button.text.x = x
        button.text.y = y
        button.text.fontSize = getArcadeFont(button.getFittedTextSize(button.text.text, height * buttonLabelHeightRatio))
    }
    layoutPauseControls(panel)
    {
        const buttonWidth = Math.min(panel.width * 0.48, this.width * 0.42)
        const defaultHeight = Math.min(this.height * 0.1, panel.height * 0.13)
        const touch = compactTouchSize(defaultHeight)
        const buttonHeight = touch || defaultHeight
        const centerX = panel.x + panel.width / 2
        this.pauseTitleY = panel.y + panel.height * 0.14

        this.layoutPauseButton(
            this.resume,
            centerX,
            panel.y + panel.height * 0.30,
            buttonWidth,
            buttonHeight
        )
        const modeWidth = panel.width * 0.29
        this.modeButtons.forEach((button, i) => this.layoutPauseButton(button,
            centerX + (i - 1) * panel.width * 0.32,
            panel.y + panel.height * 0.52, modeWidth, buttonHeight))

        const rowY = panel.y + panel.height * 0.72
        const resumeFontSize = parseFloat(this.resume.text.fontSize)
        const fpsFontSize = Math.min(resumeFontSize, panel.width * 0.09)
        const boxSize = fpsFontSize

        ctx.save()
        ctx.font = getArcadeFont(fpsFontSize)
        const labelWidth = ctx.measureText(this.pauseFpsCounterCheckbox.label).width
        ctx.restore()

        const rowWidth = boxSize * 1.55 + labelWidth
        const rowX = centerX - rowWidth / 2

        this.pauseFpsCounterCheckbox.x = rowX
        this.pauseFpsCounterCheckbox.y = rowY
        this.pauseFpsCounterCheckbox.size = boxSize
        this.pauseFpsCounterCheckbox.fontSize = getArcadeFont(fpsFontSize)

        // Play time under the fps row, fitted to the panel width
        const timeFontSize = this.getPauseTimeFontSize(panel, fpsFontSize * 0.7)
        this.timeInGame.x = centerX
        this.timeInGame.y = panel.y + panel.height * 0.89
        this.timeInGame.fontSize = getArcadeFont(timeFontSize)

        if (!touch)
            return
        const rows = stackRows(panel.y, panel.y + panel.height, [this.getPauseTitleFontSize(panel),
            buttonHeight, buttonHeight, this.pauseFpsCounterCheckbox.hitRect().height, timeFontSize])
        this.pauseTitleY = rows[0]
        this.layoutPauseButton(this.resume, centerX, rows[1], buttonWidth, buttonHeight)
        this.modeButtons.forEach((button, i) => this.layoutPauseButton(button,
            centerX + (i - 1) * panel.width * 0.32, rows[2], modeWidth, buttonHeight))
        this.pauseFpsCounterCheckbox.y = rows[3]
        this.timeInGame.y = rows[4]
    }
    getPauseTimeFontSize(panel, preferredSize)
    {
        const maxWidth = panel.width * 0.9
        ctx.save()
        ctx.font = getArcadeFont(preferredSize)
        const measuredWidth = ctx.measureText(this.timeInGame.text).width
        ctx.restore()

        if (measuredWidth <= maxWidth)
            return preferredSize

        return preferredSize * maxWidth / measuredWidth
    }
    click(coord)
    {
        if (version === 'grapple_over') return CLIMB_UI.buttons.some(b => b.isClickOnButton(coord)) ||
            this.pauseFpsCounterCheckbox.isClickOnButton(coord)
        return  this.resume.isClickOnButton(coord)                  ||
                this.pauseFpsCounterCheckbox.isClickOnButton(coord) ||
                this.modeButtons.some(button => button.isClickOnButton(coord))
    }
    clickToPause(coord)
    {
        return this.button.isClickOnButton(coord)
    }
    changeGamePause(isPaused)
    {
        this.gamePaused = isPaused
        
        this.pauseFpsCounterCheckbox.clickable = isPaused && (version !== 'grapple_over' || CLIMB_UI.showsFps())
        this.resume.clickable                   = isPaused
        this.modeButtons.forEach(button => { button.clickable = isPaused })
    }
    selectMode(mode)
    {
        // Selecting the current mode keeps the paused run intact.
        if (mode === version) return
        PROGRESS.flushClimb(true)
        PROGRESS.save()
        leaveFinishedRun(() =>
        {
            this.changeGamePause(false)
            startRunPausedIfPending(() => startGame(mode))
        })
    }
    relabelPauseSwitch()
    {
        const modes = ['grapple_over', 'bad', 'classic']
        this.modeButtons.forEach((button, i) =>
        {
            button.text.text = I18N.t('mode.' + modes[i])
            button.background.stroke = modes[i] === version ?
                STYLE.colors.ui.primary : STYLE.colors.ui.buttonDangerStroke
        })
    }
    startPause()
    {
        if (version === 'grapple_over')
        {
            gameplayPressOwned = false
            stalePress = pressHeld
        }
        PROGRESS.flushClimb()
        this.relabelPauseSwitch()
        pauseTimeInGame()
        PROGRESS.save()
        this.timeInGame.text = I18N.t('menu.timeInGame', {minutes: getTimeInGame()})

        this.changeGamePause(true)
        PLATFORM.sendLifecycle('level_paused')
        PLATFORM.gameplayStop('pause', version)

        // A fresh frame under the panel: over the death screen its buttons
        // would otherwise show through stale. (A pause during boot has no
        // world to draw yet.)
        if (continueOffer.visible)
        {
            draw()
            continueOffer.draw()
        }
        this.drawPauseScreen()
    }
    // Over the frozen last frame of the run, which stays visible through a
    // light tint and a see-through panel
    drawPauseScreen()
    {
        if (version === 'grapple_over') { CLIMB_UI.drawMenu(); return }
        const panel = this.getPausePanel()
        this.layoutPauseControls(panel)

        ctx.fillStyle = STYLE.colors.ui.pauseOverlay
        ctx.fillRect(0, 0, this.width, this.height)
        
        ctx.save()
        ctx.fillStyle   = STYLE.colors.ui.pausePanelFill
        ctx.fillRect(panel.x, panel.y, panel.width, panel.height)
        strokeNeonRect(panel.x, panel.y, panel.width, panel.height,
            STYLE.colors.ui.pausePanelStroke, STYLE.ui.neonUnit.panel)
        ctx.restore()

        const title = this.getPauseTitle(panel)
        drawScreenGlow(() =>
        {
            title.drawGlow()
            this.resume.drawGlow()
            this.modeButtons.forEach(button => button.drawGlow())
            this.pauseFpsCounterCheckbox.drawGlow()
            LANGUAGE_BUTTON.drawGlow()
        })
        
        title.draw()
        
        this.pauseFpsCounterCheckbox.draw()
        this.timeInGame.draw()
        
        this.resume.draw()
        this.modeButtons.forEach(button => button.draw())
        LANGUAGE_BUTTON.draw()
    }
    unPause()
    {
        if (version === 'grapple_over' && floors[0].climbStats.completed) return
        if (version === 'grapple_over' &&
            (hostPaused || isViewRotated() || document.visibilityState === 'hidden')) return
        CLIMB_UI.offering = false
        menu.changeGamePause(false)
        // Over the death screen the run is over: its clock stays stopped and
        // there is no level to resume
        if (continueOffer.visible)
        {
            draw()
            continueOffer.draw()
            return
        }
        reuseTimeInGame()
        PLATFORM.sendLifecycle('level_resumed')
        PLATFORM.gameplayStart(version)
    }
    opened()
    {
        return menu.gamePaused
    }
}
// Free death choices, shared by every score and ad-support outcome:
// Restart, a switch to the other mode and the fps counter
class ContinueOffer
{
    constructor(w, h, onSwitch, onRestart)
    {
        this.visible = false
        this.adPending = false
        this.switchButton = new Button(
            {x: 0, y: 0, width: 1, height: 1, neon: true},
            {text: '', fill: STYLE.colors.ui.buttonText}, onSwitch)
        this.restartButton = new Button(
            {x: 0, y: 0, width: 1, height: 1, neon: true},
            {text: '', fill: STYLE.colors.ui.buttonText}, onRestart)
        // Same state as the pause screen checkbox: both read fpsCounter
        this.fpsCounterCheckbox = new Checkbox(
        {
            x: 0, y: 0, size: 1, fontSize: 1,
            fill    : STYLE.colors.ui.text,
            stroke  : STYLE.colors.ui.primary,
            label   : I18N.t('menu.fpsCounter'),
            clickable: false
        },
        () =>
        {
            fpsCounter.toggle()
            // A fresh frame under the screen, so the tint does not stack
            draw()
            this.draw()
        })
        this.relabel(w, h)
    }
    // The mode a switch leads to
    otherVersion()
    {
        return version === 'bad' ? 'classic' : 'bad'
    }
    relabel(w, h)
    {
        this.switchButton.text.text = I18N.t(version === 'bad' ? 'menu.chillVersion' : 'menu.mainVersion')
        this.restartButton.text.text = I18N.t('continue.restart')
        this.fpsCounterCheckbox.label = I18N.t('menu.fpsCounter')
        this.layout(w, h)
    }
    layout(w, h)
    {
        this.width = w
        this.height = h
        const buttonHeight = Math.max(h * 0.11, minTouchSize())
        const buttonWidth = Math.min(w * 0.8, h * 0.9)
        const check = this.fpsCounterCheckbox
        menu.layoutPauseButton(this.restartButton, w / 2, h * 0.5, buttonWidth, buttonHeight)
        menu.layoutPauseButton(this.switchButton, w / 2, h * 0.5 + buttonHeight * 1.25, buttonWidth, buttonHeight)

        const fontSize = parseFloat(this.restartButton.text.fontSize)
        ctx.save()
        ctx.font = getArcadeFont(fontSize)
        const labelWidth = ctx.measureText(check.label).width
        ctx.restore()
        check.size = fontSize
        check.fontSize = getArcadeFont(fontSize)
        check.x = w / 2 - (fontSize * 1.55 + labelWidth) / 2
        check.y = h * 0.5 + buttonHeight * 2.5
        this.title = new Text({x:w/2, y:h*0.25, fontSize:h*0.09,
            text:I18N.t('continue.title'), fill:STYLE.colors.ui.title})
        this.score = new Text({x:w/2, y:h*0.36, fontSize:h*0.05,
            text:'', fill:STYLE.colors.ui.mutedText})
        // Phones: the touch-sized rows are stacked evenly below the title
        if (!compactTouchSize(h * 0.11))
            return
        const rows = stackRows(h * 0.03, h * 0.97, [h * 0.09, h * 0.05,
            buttonHeight, buttonHeight, check.hitRect().height])
        this.title.y = rows[0]
        this.score.y = rows[1]
        menu.layoutPauseButton(this.restartButton, w / 2, rows[2], buttonWidth, buttonHeight)
        menu.layoutPauseButton(this.switchButton, w / 2, rows[3], buttonWidth, buttonHeight)
        check.y = rows[4]
    }
    show()
    {
        this.relabel(this.width, this.height)
        this.setVisible(true)
    }
    hide() { this.adPending = false; this.setVisible(false) }
    setVisible(visible) { this.visible = visible; this.updateClickable() }
    setAdPending(pending) { this.adPending = pending; this.updateClickable() }
    updateClickable()
    {
        this.restartButton.clickable = this.switchButton.clickable =
            this.fpsCounterCheckbox.clickable = this.visible && !this.adPending
    }
    click(coord)
    {
        return this.restartButton.isClickOnButton(coord) || this.switchButton.isClickOnButton(coord) ||
            this.fpsCounterCheckbox.isClickOnButton(coord)
    }
    draw()
    {
        ctx.save()
        ctx.fillStyle = STYLE.colors.ui.pauseOverlay
        ctx.fillRect(0, 0, this.width, this.height)
        this.score.text = scoreText.text + scoreText.count[version]
        this.title.draw()
        this.score.draw()
        if (this.adPending) ctx.globalAlpha = 0.4
        this.restartButton.draw()
        this.switchButton.draw()
        this.fpsCounterCheckbox.draw()
        LANGUAGE_BUTTON.draw()
        ctx.restore()
    }
}

// The summit screen's picture (art/win-*.svg, made by tools/make_win_art.py;
// all its text is drawn by CLIMB_UI). The SVGs load on the first Grapple Over
// menu; each is rasterised once per canvas size into a cached canvas, which
// the frames then copy. Until it has loaded the plain overlay is drawn.
const WIN_ART = {
    images: {},
    rasters: {},
    load() {
        for (const variant of ['default', 'long'])
        {
            if (this.images[variant]) continue
            const image = new Image()
            image.onload = () => {
                image.ready = true
                if (version === 'grapple_over' && floors[0]?.climbStats?.completed) redrawOverlays()
            }
            image.src = 'art/win-' + variant + '.svg'
            this.images[variant] = image
        }
    },
    // Cover-fit over the whole menu (w, h); false while the image is loading
    draw(w, h) {
        const variant = floors[0].usedDouble ? 'long' : 'default'
        this.load()
        const image = this.images[variant]
        if (!image.ready) return false
        let raster = this.rasters[variant]
        if (!raster || raster.width !== canvas.width || raster.height !== canvas.height)
        {
            raster = this.rasters[variant] = document.createElement('canvas')
            raster.width = canvas.width
            raster.height = canvas.height
            const fit = Math.max(raster.width / image.width, raster.height / image.height)
            const iw = image.width * fit, ih = image.height * fit
            raster.getContext('2d').drawImage(image, (raster.width - iw) / 2, (raster.height - ih) / 2, iw, ih)
        }
        ctx.drawImage(raster, 0, 0, w, h)
        return true
    }
}

// Climb statistics describe the current simulation; they never move the player.
const CLIMB_UI = {
    confirming: false,
    // The first-death double grapnel offer is up (a pause screen of its own)
    offering: false,
    buttons: [],
    time(ms) { return I18N.t('climb.seconds', {value:(ms / 1000).toFixed(1)}) },
    text(text, x, y, size, alignX = 'center') {
        new Text({text, x, y, fontSize:size, alignX, fill:STYLE.colors.ui.hudText}).draw()
    },
    yieldAlpha: 0.4,
    hudYield: {text: false, button: false},
    // Whether the player, a world element or a drag zone overlaps the view rect grown by pad (game units)
    yields(left, top, right, bottom, pad) {
        const hit = (l, t, r, b) => l + screen.x < right + pad && r + screen.x > left - pad &&
            t + screen.y < bottom + pad && b + screen.y > top - pad
        const r = ninja.radius, out = this.bounds
        if (hit(ninja.x - r, ninja.y - r, ninja.x + r, ninja.y + r)) return true
        for (const list of [floors[0].elements, floors[0].dragZones || []])
            for (const e of list)
            {
                elementBounds(e, out)
                if (hit(out.left, out.top, out.right, out.bottom)) return true
            }
        return false
    },
    bounds: {left: 0, right: 0, top: 0, bottom: 0},
    // The climb section the player is in: the HUD label and the progression
    // telemetry share this lookup, cached per level, simulation step and
    // player position (one lookup a frame)
    sectionCache: {level: null, step: NaN, x: NaN, y: NaN, section: null},
    currentSection() {
        const level = floors[0].level, step = floors[0].elapsedSteps, cache = this.sectionCache
        if (cache.level === level && cache.step === step && cache.x === ninja.x && cache.y === ninja.y) return cache.section
        const section = GRAPPLE_OVER_REPLACEMENT_ACTIVE ? replacementSection() : level.sections.find(s => s.encounters.some(id =>
            level.encounters.find(e => e.id === id)?.elements.some(id => {
                const e = floors[0].byId.get(id)
                return e && Math.abs(e.y - ninja.y) < 300
            }))) || level.sections[0]
        Object.assign(cache, {level, step, x: ninja.x, y: ninja.y, section})
        return section
    },
    // Progression telemetry of the run, one attempt per section: 'Start' on
    // entering a section not yet completed, 'Complete' (once per run) for the
    // section left upward and at the summit, 'Fail' for the section left
    // downward. open: a Start was sent for id with no Complete/Fail yet.
    progression: {id: null, index: -1, open: false, completed: new Set()},
    resetProgression() {
        this.progression = {id: null, index: -1, open: false, completed: new Set()}
    },
    // Called once a frame while playing; sends events only on a section change
    trackSection() {
        if (version !== 'grapple_over' || !floors[0]?.level?.sections?.length || floors[0].climbStats?.completed) return
        const sections = floors[0].level.sections, section = this.currentSection(), p = this.progression
        if (section.id === p.id) return
        const index = sections.indexOf(section)
        if (p.id !== null && p.open)
        {
            if (index > p.index) p.completed.add(p.id)
            ANALYTICS.progression(index > p.index ? 'Complete' : 'Fail', version, p.id)
        }
        p.id = section.id
        p.index = index
        p.open = !p.completed.has(section.id)
        if (p.open) ANALYTICS.progression('Start', version, section.id)
    },
    // Summit: the last section is complete
    completeProgression() {
        this.trackSection()
        const p = this.progression
        if (!p.open) return
        p.open = false
        p.completed.add(p.id)
        ANALYTICS.progression('Complete', version, p.id)
    },
    drawHud(button) {
        const stats = floors[0].climbStats, h = height / scale[version]
        const size = Math.max(h * 0.025, 12 * h / getCanvasCssRect().height)
        const section = this.currentSection()
        const rows = [I18N.t('climb.height', {value:Math.floor(stats.currentHeight)}),
            I18N.t('climb.max', {value:Math.floor(stats.maxHeight)}),
            I18N.t('climb.section', {value:I18N.t(section.labelKey || 'climb.section.' + section.id)}),
            I18N.t('climb.time', {value:this.time(stats.elapsedActiveMs)})]
        if (floors[0].grapnelMode === 'double') rows.push(I18N.t('climb.doubleRange'))
        // Terrain or the player behind a HUD block fades it so targets stay readable
        ctx.save()
        ctx.font = size + 'px ' + STYLE.ui.fontFamily
        const textRight = size + Math.max(...rows.map(text => ctx.measureText(text).width))
        ctx.restore()
        this.hudYield.text = this.yields(size, size * 0.6, textRight, size * (1.5 + (rows.length - 1) * 1.6 + 0.6), size * 0.5)
        ctx.save()
        if (this.hudYield.text) ctx.globalAlpha = this.yieldAlpha
        rows.forEach((text, i) => this.text(text, size, size * (1.5 + i * 1.6), size, 'left'))
        ctx.restore()
        const b = button.background
        this.hudYield.button = this.yields(b.x, b.y, b.x + b.width, b.y + b.height, size * 0.5)
        ctx.save()
        button.fade = this.hudYield.button ? this.yieldAlpha : 1
        ctx.globalAlpha = button.fade
        button.draw()
        button.fade = 1
        ctx.restore()
        if (floors[0].rangeNoticeMs > 0)
            this.text(I18N.t(GRAPPLE_OVER_REPLACEMENT_ACTIVE ? 'climb.previewRangeUpgrade' : 'climb.rangeUpgrade'), width / scale[version] / 2, h * 0.2, size * 1.6)
    },
    complete() {
        const stats = floors[0].climbStats
        if (stats.completed) return
        this.completeProgression()
        stats.completed = true
        FALL_MESSAGE.clear()
        runInProgress = false
        gameplayPressOwned = false
        stalePress = pressHeld
        pauseTimeInGame()
        PLATFORM.sendLifecycle('level_completed', {world:version, elapsedActiveMs:stats.elapsedActiveMs})
        PLATFORM.gameplayStop('complete', version)
        PLATFORM.happyMoment()
        PLATFORM.submitScore('grapple_over_time', Math.round(stats.elapsedActiveMs))
        PROGRESS.flushClimb()
        menu.changeGamePause(true)
    },
    restart() {
        this.confirming = false
        this.offering = false
        PROGRESS.resetClimb()
        this.resetProgression()
        pressHeld = stalePress = gameplayPressOwned = false
        runOver = false
        runInProgress = true
        resetPhysicsTiming()
        PLATFORM.sendLifecycle('level_started', {world:version})
        PLATFORM.gameplayStart(version)
        ANALYTICS.design('restart:' + version)
        menu.unPause()
        draw()
    },
    drawMenu() {
        const w = menu.width, h = menu.height, stats = floors[0].climbStats
        WIN_ART.load()
        if (!(stats.completed && WIN_ART.draw(w, h)))
        {
            ctx.fillStyle = STYLE.colors.ui.pauseOverlay
            ctx.fillRect(0, 0, w, h)
        }
        if (stats.completed && !this.confirming) return this.drawWin(w, h, stats)
        const title = this.offering ? 'climb.offerTitle' : this.confirming ? 'climb.confirm' : 'mode.grapple_over'
        const actions = this.offering ? [
            ['climb.offerContinue', () => menu.unPause()],
            ['climb.offerDouble', () => this.acceptDouble()]
        ] : this.confirming ? [
            ['climb.yes', () => this.restart()],
            ['climb.cancel', () => {this.confirming=false; redrawOverlays()}]
        ] : [
            [stats.completed ? 'climb.replay' : 'pause.resume', () => stats.completed ? this.restart() : menu.unPause()],
            ['climb.restart', () => {this.confirming=true; redrawOverlays()}],
            ['mode.bad', () => menu.selectMode('bad')],
            ['mode.classic', () => menu.selectMode('classic')]
        ]
        // The grapnel toggle goes last (button indexes 0-3 stay as they were);
        // a run in progress keeps its position, time and best across a switch.
        const grapnel = this.showsFps(), note = this.offering || grapnel
        if (grapnel) actions.push([floors[0].grapnelMode === 'double' ? 'climb.grapnelDouble' : 'climb.grapnelSingle',
            () => this.toggleGrapnel()])
        const bh = Math.max(h*(grapnel ? 0.09 : 0.105), minTouchSize()), bw = Math.min(w*0.7, h*1.05)
        const check = menu.pauseFpsCounterCheckbox
        check.clickable = menu.gamePaused && this.showsFps()
        if (check.clickable)
        {
            const size = bh * 0.42
            ctx.save()
            ctx.font = getArcadeFont(size)
            const labelWidth = ctx.measureText(check.label).width
            ctx.restore()
            check.size = size
            check.fontSize = getArcadeFont(size)
            check.x = w/2 - (size * 1.55 + labelWidth) / 2
        }
        // Under the toggle: single grapnel is the intended way to play
        // (and under the offer's two choices)
        const noteText = I18N.t('climb.grapnelNote')
        let noteSize = h*0.026
        ctx.save()
        ctx.font = noteSize + 'px ' + STYLE.ui.fontFamily
        noteSize = Math.min(noteSize, noteSize * w*0.92 / ctx.measureText(noteText).width)
        ctx.restore()
        // With the toggle, the title, buttons, note and fps row share the
        // height evenly, so the 44 CSS px touch floor still fits on phones.
        const rows = note ? stackRows(0, h, [h*0.055, h*0.035, ...actions.map(() => bh),
            noteSize*1.2, ...(grapnel ? [check.hitRect().height] : [])]) : null
        this.text(I18N.t(title), w/2, note ? rows[0] : h*0.16, h*0.055)
        this.text(I18N.t('climb.time', {value:this.time(stats.elapsedActiveMs)}), w/2, note ? rows[1] : h*0.26, h*0.035)
        this.buttons = actions.map(([key, action], i) => new Button(
            {x:w/2, y:note ? rows[2 + i] : h*0.35+i*(bh+h*0.02), width:bw, height:bh, neon:true},
            {text:I18N.t(key), fill:STYLE.colors.ui.buttonText}, action))
        this.buttons.forEach(b => b.draw())
        if (note)
            new Text({text:noteText, x:w/2, y:rows[2 + actions.length], fontSize:noteSize, fill:STYLE.colors.ui.mutedText}).draw()
        // The pause screen's fps checkbox, centred under the action buttons
        if (check.clickable)
        {
            check.y = rows[rows.length - 1]
            check.draw()
        }
        LANGUAGE_BUTTON.draw()
    },
    // Summit screen colours (approved concept artifacts/win-art-3)
    win: {
        title: {default: '#2ee6d6', long: '#c9b8ff'},
        label: '#9fb3e8',
        value: '#ffffff',
        divider: 'rgba(159, 179, 232, 0.35)',
        single: '#3dff4a',
        chipFill: 'rgba(6, 16, 28, 0.82)',
        cta: '#3dff4a'
    },
    // m:ss.t, or h:mm:ss.t past an hour
    winTime(ms) {
        const tenths = Math.floor(ms / 100), s = Math.floor(tenths / 10), m = Math.floor(s / 60), hours = Math.floor(m / 60)
        const ss = String(s % 60).padStart(2, '0') + '.' + tenths % 10
        return hours ? hours + ':' + String(m % 60).padStart(2, '0') + ':' + ss : m + ':' + ss
    },
    // Bold HUD font of the size, letter spaced by spacing (em)
    winFont(size, spacing = 0) {
        ctx.font = 'bold ' + size + 'px ' + STYLE.ui.fontFamily
        ctx.letterSpacing = size * spacing + 'px'
    },
    // The size (at most size) at which text fits maxWidth
    winFit(text, size, maxWidth, spacing = 0) {
        ctx.save()
        this.winFont(size, spacing)
        const width = ctx.measureText(text).width
        ctx.restore()
        return width > maxWidth ? size * maxWidth / width : size
    },
    // Letter-spaced text centred on x (the trailing spacing is not counted)
    winText(text, x, y, size, spacing, fill) {
        ctx.save()
        this.winFont(size, spacing)
        ctx.textAlign = 'center'
        ctx.textBaseline = 'middle'
        ctx.fillStyle = fill
        x += size * spacing / 2
        ctx.fillText(text, x, y)
        LAYOUT_PROBE.text(text, x, y)
        ctx.restore()
    },
    // Neon title: wide faint, mid and core strokes in the colour, a thin white inner line
    winTitle(text, x, y, size, spacing, color) {
        ctx.save()
        this.winFont(size, spacing)
        ctx.textAlign = 'center'
        ctx.textBaseline = 'middle'
        ctx.lineJoin = 'round'
        x += size * spacing / 2
        const unit = size / 90
        ctx.strokeStyle = color
        for (const [width, alpha] of [[14, 0.16], [7, 0.4], [3, 1]])
        {
            ctx.globalAlpha = alpha
            ctx.lineWidth = width * unit
            ctx.strokeText(text, x, y)
        }
        ctx.globalAlpha = 1
        ctx.strokeStyle = '#ffffff'
        ctx.lineWidth = unit
        ctx.strokeText(text, x, y)
        LAYOUT_PROBE.text(text, x, y)
        ctx.restore()
    },
    // Neon chip: a glowing outline and the text in it
    winChip(text, x, y, size, color, textColor) {
        ctx.save()
        this.winFont(size, 0.08)
        const pad = size * 0.7, chipW = ctx.measureText(text).width + pad * 2, chipH = size * 1.9
        ctx.restore()
        const left = x - chipW / 2, top = y - chipH / 2
        ctx.save()
        ctx.fillStyle = this.win.chipFill
        ctx.fillRect(left, top, chipW, chipH)
        strokeNeonRect(left, top, chipW, chipH, color, STYLE.ui.neonUnit.small)
        ctx.restore()
        this.winText(text, x, y, size, 0.08, textColor)
        LAYOUT_PROBE.rect('win', 'badge', left, top, chipW, chipH)
    },
    // Three chevrons pointing dir (-1 left, 1 right) from x towards the label
    winChevrons(x, y, size, dir, color) {
        ctx.save()
        ctx.strokeStyle = color
        ctx.lineWidth = Math.max(1, size * 0.12)
        ctx.lineJoin = ctx.lineCap = 'round'
        ctx.beginPath()
        for (let i = 0; i < 3; i++)
        {
            const tip = x + dir * size * 0.6 * i
            ctx.moveTo(tip - dir * size * 0.3, y - size * 0.45)
            ctx.lineTo(tip, y)
            ctx.lineTo(tip - dir * size * 0.3, y + size * 0.45)
        }
        ctx.globalAlpha = 0.35
        ctx.lineWidth *= 3
        ctx.stroke()
        ctx.globalAlpha = 1
        ctx.lineWidth /= 3
        ctx.stroke()
        ctx.restore()
    },
    // Long run only: back to the intended single grapnel, from a fresh climb
    tryDefault() {
        setGrapnelMode('single')
        this.restart()
    },
    // The completed screen over the summit art: title, subtitle, stats,
    // badge and (long) the try-default call, the end-menu buttons below
    drawWin(w, h, stats) {
        const long = !!floors[0].usedDouble, color = this.win.title[long ? 'long' : 'default']
        // No fps row on the ending (showsFps)
        menu.pauseFpsCounterCheckbox.clickable = false
        // Small text keeps the CSS px legibility floor on phones
        const floor = minCssFontPx * h / getCanvasCssRect().height
        const lang = LANGUAGE_BUTTON.rect()
        // Buttons: 2x2 on wide-ish screens, one row of four on phones in landscape
        const bh = Math.max(h * 0.085, minTouchSize()), gap = bh * 0.25
        const cols = w / h >= 2 ? 4 : 2
        const gridW = Math.min(w * (cols === 4 ? 0.9 : 0.72), h * (cols === 4 ? 2.3 : 1.3))
        const bw = (gridW - gap * (cols - 1)) / cols
        const actions = [
            ['climb.replay', () => this.restart()],
            ['climb.restart', () => {this.confirming=true; redrawOverlays()}],
            ['mode.bad', () => menu.selectMode('bad')],
            ['mode.classic', () => menu.selectMode('classic')]
        ]
        const gridRows = 4 / cols, rows = gridRows + (long ? 1 : 0)
        const bottom = Math.min(h - gap, lang.y - gap)
        const gridTop = bottom - rows * bh - (rows - 1) * gap
        const fitLabel = (b, text, width) => {
            const size = this.winFit(text, b.background.height * 0.6, width)
            b.text.fontSize = getArcadeFont(size)
        }
        this.buttons = actions.map(([key, action], i) => {
            const x = w/2 - gridW/2 + bw/2 + (i % cols) * (bw + gap)
            const y = gridTop + bh/2 + Math.floor(i / cols) * (bh + gap)
            const b = new Button({x, y, width:bw, height:bh, neon:true},
                {text:I18N.t(key), fill:STYLE.colors.ui.buttonText}, action)
            fitLabel(b, b.text.text, bw - bh * STYLE.ui.buttonTextPaddingRatio * 2)
            return b
        })
        let cta = null
        if (long)
        {
            const ctaW = Math.min(w * 0.9, Math.max(gridW, h * 1.3)), y = bottom - bh/2
            cta = new Button({x:w/2, y, width:ctaW, height:bh, neon:true, stroke:this.win.cta, fill:'rgba(4, 22, 12, 0.82)'},
                {text:I18N.t('climb.winTryDefault'), fill:this.win.cta}, () => this.tryDefault())
            this.ctaChevron = bh * 0.32
            // Smaller than the other labels, as in the concept
            const size = this.winFit(cta.text.text, bh * 0.45, ctaW - this.ctaChevron * 2 * 3.2 - bh * STYLE.ui.buttonTextPaddingRatio * 2)
            cta.text.fontSize = getArcadeFont(size)
            this.buttons.push(cta)
        }
        // Header as in the concept (title near 0.18 h, badge near 0.46 h), above
        // the buttons; shrunk to fit short screens
        const headTop = h * 0.07, headBottom = Math.min(h * 0.52, gridTop - gap)
        const titleText = I18N.t('climb.winTitle'), subText = I18N.t(long ? 'climb.winSubLong' : 'climb.winSub')
        let titleSize = this.winFit(titleText, h * 0.125, w * 0.86, 0.3)
        let subSize = this.winFit(subText, Math.max(h * 0.03, floor), w * 0.9, 0.35)
        let labelSize = Math.max(h * 0.018, floor), valueSize = Math.max(h * 0.036, floor * 1.3)
        const badgeText = I18N.t(long ? 'climb.doubleRange' : 'climb.winSingle')
        let badgeSize = Math.max(h * 0.022, floor)
        const heights = () => [titleSize * 1.05, subSize * 1.2, labelSize * 1.3 + valueSize * 1.25, badgeSize * 1.9]
        const sum = heights().reduce((a, b) => a + b, 0), room = (headBottom - headTop) * 0.86
        if (sum > room)
        {
            const k = room / sum
            titleSize *= k; subSize *= k; labelSize *= k; valueSize *= k; badgeSize *= k
        }
        const [titleY, subY, statsY, badgeY] = stackRows(headTop, headBottom, heights())
        this.winTitle(titleText, w/2, titleY, titleSize, 0.3, color)
        LAYOUT_PROBE.rect('win', 'title', ...this.winBox(titleText, w/2, titleY, titleSize, 0.3, 1.05))
        this.winText(subText, w/2, subY, subSize, 0.35, '#ffffff')
        LAYOUT_PROBE.rect('win', 'subtitle', ...this.winBox(subText, w/2, subY, subSize, 0.35, 1.2))
        // Stats: three columns with thin dividers
        const colW = Math.min(w * 0.17, h * 0.3), statsH = labelSize * 1.3 + valueSize * 1.25
        const statsTop = statsY - statsH / 2
        const cells = [['climb.statTime', this.winTime(stats.elapsedActiveMs)],
            ['climb.statFalls', String(stats.falls)], ['climb.statGrapples', String(stats.grapples)]]
        this.winValues = cells.map(c => c[1])
        cells.forEach(([key, value], i) => {
            const x = w/2 + (i - 1) * colW, label = I18N.t(key)
            this.winText(label, x, statsTop + labelSize * 0.65, this.winFit(label, labelSize, colW * 0.9, 0.2), 0.2, this.win.label)
            this.winText(value, x, statsTop + labelSize * 1.3 + valueSize * 0.62, this.winFit(value, valueSize, colW * 0.9), 0, this.win.value)
        })
        ctx.save()
        ctx.strokeStyle = this.win.divider
        ctx.lineWidth = Math.max(1, h * 0.0015)
        ctx.beginPath()
        for (const dx of [-0.5, 0.5])
        {
            ctx.moveTo(w/2 + dx * colW, statsTop)
            ctx.lineTo(w/2 + dx * colW, statsTop + statsH)
        }
        ctx.stroke()
        ctx.restore()
        LAYOUT_PROBE.rect('win', 'stats', w/2 - colW * 1.5, statsTop, colW * 3, statsH)
        // Badge: single grapnel (green) or the long range (lavender)
        badgeSize = this.winFit(badgeText, badgeSize, w * 0.8 - badgeSize * 1.4, 0.08)
        if (long) this.winChip(badgeText, w/2, badgeY, badgeSize, this.win.title.long, '#ffffff')
        else this.winChip(badgeText, w/2, badgeY, badgeSize, this.win.single, this.win.single)
        this.buttons.forEach(b => b.draw())
        if (cta)
        {
            const r = cta.background, c = this.ctaChevron
            this.winChevrons(r.x + bh * 0.3 + c * 0.3 + c * 1.2, r.y + r.height/2, c, -1, this.win.cta)
            this.winChevrons(r.x + r.width - bh * 0.3 - c * 0.3 - c * 1.2, r.y + r.height/2, c, 1, this.win.cta)
        }
        LANGUAGE_BUTTON.draw()
    },
    // [x, y, width, height] of a letter-spaced line centred on (x, y), lineHeight in sizes
    winBox(text, x, y, size, spacing, lineHeight) {
        ctx.save()
        this.winFont(size, spacing)
        const width = ctx.measureText(text).width
        ctx.restore()
        return [x - width / 2, y - size * lineHeight / 2, width, size * lineHeight]
    },
    // On the run's first fall recovery in single mode (recoverClimbFall):
    // the run pauses, its clock stopped, until Continue or Try double.
    offerDouble() {
        this.offering = true
        this.confirming = false
        menu.startPause()
    },
    acceptDouble() {
        this.offering = false
        setGrapnelMode('double')
        PROGRESS.flushClimb()
        menu.unPause()
        redrawOverlays()
    },
    toggleGrapnel() {
        setGrapnelMode(floors[0].grapnelMode === 'double' ? 'single' : 'double')
        PROGRESS.flushClimb()
        redrawOverlays()
    },
    // As on the Classic/Bad pause screen: not on the restart confirmation or the ending
    showsFps() {
        return !this.confirming && !this.offering && !floors[0]?.climbStats?.completed
    }
}
