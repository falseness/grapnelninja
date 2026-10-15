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

        ctx.globalAlpha = 0.58
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
        if (version === 'grapple_over') return CLIMB_UI.buttons.some(b => b.isClickOnButton(coord))
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
        
        this.pauseFpsCounterCheckbox.clickable = isPaused
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

// Climb statistics describe the current simulation; they never move the player.
const CLIMB_UI = {
    confirming: false,
    buttons: [],
    time(ms) { return I18N.t('climb.seconds', {value:(ms / 1000).toFixed(1)}) },
    text(text, x, y, size, alignX = 'center') {
        new Text({text, x, y, fontSize:size, alignX, fill:STYLE.colors.ui.hudText}).draw()
    },
    drawHud() {
        const stats = floors[0].climbStats, h = height / scale[version]
        const size = Math.max(h * 0.025, 12 * h / getCanvasCssRect().height)
        const section = floors[0].level.sections.find(s => s.encounters.some(id =>
            floors[0].level.encounters.find(e => e.id === id)?.elements.some(id => {
                const e = floors[0].byId.get(id)
                return e && Math.abs(e.y - ninja.y) < 300
            }))) || floors[0].level.sections[0]
        const rows = [I18N.t('climb.height', {value:Math.floor(stats.currentHeight)}),
            I18N.t('climb.max', {value:Math.floor(stats.maxHeight)}),
            I18N.t('climb.section', {value:I18N.t('climb.section.' + section.id)}),
            I18N.t('climb.time', {value:this.time(stats.elapsedActiveMs)})]
        rows.forEach((text, i) => this.text(text, size, size * (1.5 + i * 1.6), size, 'left'))
    },
    complete() {
        const stats = floors[0].climbStats
        if (stats.completed) return
        stats.completed = true
        runInProgress = false
        gameplayPressOwned = false
        stalePress = pressHeld
        pauseTimeInGame()
        PLATFORM.sendLifecycle('level_completed', {world:version, elapsedActiveMs:stats.elapsedActiveMs})
        PROGRESS.flushClimb()
        menu.changeGamePause(true)
    },
    restart() {
        this.confirming = false
        PROGRESS.resetClimb()
        pressHeld = stalePress = gameplayPressOwned = false
        runOver = false
        runInProgress = true
        resetPhysicsTiming()
        PLATFORM.sendLifecycle('level_started', {world:version})
        menu.unPause()
        draw()
    },
    drawMenu() {
        const w = menu.width, h = menu.height, stats = floors[0].climbStats
        ctx.fillStyle = STYLE.colors.ui.pauseOverlay
        ctx.fillRect(0, 0, w, h)
        const title = this.confirming ? 'climb.confirm' : stats.completed ? 'climb.complete' : 'mode.grapple_over'
        this.text(I18N.t(title), w/2, h*0.16, h*0.055)
        this.text(I18N.t('climb.time', {value:this.time(stats.elapsedActiveMs)}), w/2, h*0.26, h*0.035)
        const actions = this.confirming ? [
            ['climb.yes', () => this.restart()],
            ['climb.cancel', () => {this.confirming=false; redrawOverlays()}]
        ] : [
            [stats.completed ? 'climb.replay' : 'pause.resume', () => stats.completed ? this.restart() : menu.unPause()],
            ['climb.restart', () => {this.confirming=true; redrawOverlays()}],
            ['mode.bad', () => menu.selectMode('bad')],
            ['mode.classic', () => menu.selectMode('classic')]
        ]
        const bh = Math.max(h*0.105, minTouchSize()), bw = Math.min(w*0.7, h*1.05)
        this.buttons = actions.map(([key, action], i) => new Button(
            {x:w/2, y:h*0.35+i*(bh+h*0.02), width:bw, height:bh, neon:true},
            {text:I18N.t(key), fill:STYLE.colors.ui.buttonText}, action))
        this.buttons.forEach(b => b.draw())
        LANGUAGE_BUTTON.draw()
    }
}
