function reuseTimeInGame() {
    time = Math.floor(new Date().getTime() / 1000)
}
function pauseTimeInGame() {
    let thisTime = Math.floor(new Date().getTime() / 1000)
    let delta = Math.floor(thisTime - time)

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
        const css = canvas.getBoundingClientRect()
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
            (canvas.width / canvas.getBoundingClientRect().width)
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
        this.fontSize   = object.fontSize + 'px ' + STYLE.ui.fontFamily
        this.text       = object.text
        this.align      =
        {
            x: object.alignX || 'center',
            y: object.alignY || 'middle'
        }
    }
    getWidth()
    {
        ctx.font = this.fontSize
        return ctx.measureText(this.text).width
    }
    draw()
    {
        ctx.save()
        ctx.fillStyle   = this.fill
        ctx.textBaseline= this.align.y
        ctx.textAlign   = this.align.x
        ctx.font        = this.fontSize
        ctx.shadowColor = this.fill
        ctx.shadowBlur  = STYLE.ui.textShadowBlur
        
        
        ctx.fillText(this.text, this.x, this.y)
        LAYOUT_PROBE.text(this.text, this.x, this.y)
        ctx.restore()
    }
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
    const touch = MUTE_BUTTON.minSize()
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
        ctx.shadowColor = this.background.stroke
        ctx.shadowBlur  = STYLE.ui.buttonShadowBlur
        
        ctx.fillRect(this.background.x, this.background.y, this.background.width, this.background.height)
        ctx.strokeRect(this.background.x, this.background.y, this.background.width, this.background.height)
        LAYOUT_PROBE.rect('button', this.text.text || 'icon', this.background.x, this.background.y,
            this.background.width, this.background.height)

        ctx.shadowBlur = 0
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
    isClickOnButton(click)
    {
        if (this.clickable)
        {
            if (this.background.x < click.x && click.x < this.background.x + this.background.width &&
                this.background.y < click.y && click.y < this.background.y + this.background.height)
            {
                AUDIO.play('click')
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
        ctx.lineWidth = STYLE.ui.buttonLineWidth
        ctx.shadowColor = this.stroke
        ctx.shadowBlur = STYLE.ui.buttonShadowBlur
        ctx.strokeRect(boxX, boxY, this.size, this.size)

        if (fpsCounter.enabled)
        {
            ctx.beginPath()
            ctx.moveTo(boxX + markInset, this.y)
            ctx.lineTo(boxX + this.size * 0.43, boxY + this.size - markInset)
            ctx.lineTo(boxX + this.size - markInset, boxY + markInset)
            ctx.stroke()
        }

        ctx.shadowBlur = STYLE.ui.textShadowBlur
        ctx.fillText(this.label, boxX + this.size * 1.55, this.y)
        LAYOUT_PROBE.text(this.label, boxX + this.size * 1.55, this.y)
        if (LAYOUT_PROBE.boxes)
        {
            const hit = this.hitRect()
            LAYOUT_PROBE.rect('button', this.label, hit.x, hit.y, hit.width, hit.height)
        }
        ctx.restore()
    }
    // Box and label plus a padding; at least a touch target high
    hitRect()
    {
        ctx.save()
        ctx.font = this.fontSize
        const labelWidth = ctx.measureText(this.label).width
        ctx.restore()

        const padding = this.size * 0.45
        const height = Math.max(this.size * 1.5, MUTE_BUTTON.minSize())
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
            AUDIO.play('click')
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
        const cssPerView = canvas.getBoundingClientRect().height / viewHeight
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

        ctx.fillStyle = STYLE.colors.ui.fpsPanelFill
        ctx.strokeStyle = STYLE.colors.ui.fpsPanelStroke
        ctx.lineWidth = STYLE.ui.fpsPanelLineWidth
        ctx.shadowColor = STYLE.colors.ui.hudGlow
        ctx.shadowBlur = STYLE.ui.textShadowBlur
        ctx.fillRect(panelX, panelY, panelWidth, panelHeight)
        ctx.strokeRect(panelX, panelY, panelWidth, panelHeight)

        ctx.fillStyle = STYLE.colors.ui.hudText
        ctx.strokeStyle = STYLE.colors.ui.hudGlow
        ctx.lineWidth = Math.max(1, STYLE.ui.fpsPanelLineWidth * 0.65)
        ctx.strokeText(text, x, y)
        ctx.fillText(text, x, y)
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
class Menu
{
    constructor(w, h)
    {
        this.width  = w
        this.height = h
        
        this.gamePaused = false
        
        this.visible= true   
        
        this.center = 
        {
            x: this.width  / 2,
            y: this.height / 2,
        }
        
        this.mainText = new Text(
        {
            fill    : STYLE.colors.ui.title,
            fontSize: 0.075 * this.width,
            text    : I18N.t('game.title'),
            x       : this.center.x     ,
            y       : 0.2 * this.height
        })
        
        this.classicVersionButton = new Button(
        {
            x: this.center.x        ,
            y: 0.35 * this.height   ,
            width: 0.4 * this.width ,
            height: 0.1 * this.height,
            stroke: STYLE.colors.ui.primary
        },
        {
            fill: STYLE.colors.ui.buttonText,
            text: I18N.t('menu.chillVersion')
        },
        function(){startGame('classic')})
        this.classicRecord = new Text(
        {
            x       : this.center.x                     ,
            y       : 0.43 * this.height                ,
            fontSize: 0.05 * this.height                ,
            fill    : STYLE.colors.ui.mutedText         ,
            text    : I18N.t('menu.record', {value: scoreText.record.classic})
        })
        this.badVersionButton = new Button(
        {
            x: this.center.x        ,
            y: 0.52 * this.height   ,
            width: 0.4 * this.width ,
            height: 0.1 * this.height,
            stroke: STYLE.colors.ui.buttonDangerStroke
        },
        {
            fill: STYLE.colors.ui.buttonText,
            text: I18N.t('menu.mainVersion')
        },
        function(){startGame('bad')})
        this.badRecord = new Text(
        {
            x       : this.center.x                     ,
            y       : 0.60 * this.height                ,
            fontSize: 0.05 * this.height                ,
            fill    : STYLE.colors.ui.mutedText         ,
            text    : I18N.t('menu.record', {value: scoreText.record.bad})
        })

        this.mainFpsCounterCheckbox = new Checkbox(
        {
            x       : this.center.x,
            y       : 0.70 * this.height,
            size    : 0.05 * this.height,
            fontSize: 0.05 * this.height,
            fill    : STYLE.colors.ui.text,
            stroke  : STYLE.colors.ui.primary,
            label   : I18N.t('menu.fpsCounter'),
            clickable: true
        },
        function()
        {
            fpsCounter.toggle()
            menu.draw()
        })

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
                    ctx.beginPath()

                    ctx.lineWidth = Math.round(STYLE.strokes.menuIconWidthRatio * h)

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
                    ctx.shadowBlur = 0

                    ctx.lineWidth = STYLE.strokes.defaultWidth

                    ctx.closePath()
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
            stroke: STYLE.colors.ui.primary
        },
        {
            text: I18N.t('pause.resume'),
            fill: STYLE.colors.ui.buttonText
        }, function()
        {
            menu.unPause()
        })
        this.backToMenu = new Button(
        {
            x: this.center.x        ,
            y: 0.52 * this.height   ,
            width: 0.4 * this.width ,
            clickable: false        ,
            height: 0.1 * this.height,
            stroke: STYLE.colors.ui.buttonDangerStroke
        },
        {
            text: I18N.t('pause.backToMenu'),
            fill: STYLE.colors.ui.buttonText
        },
        function()
        {
            PROGRESS.save()
            // After a death the game over interstitial plays first
            leaveFinishedRun(function()
            {
                menu.changeGamePause(false)
                continueOffer.hide()

                menu.setVisible(true)

                menu.classicRecord.text = I18N.t('menu.record', {value: scoreText.record.classic})
                menu.badRecord.text     = I18N.t('menu.record', {value: scoreText.record.bad})

                menu.draw()

                cancelAnimationFrame(game)
            })
        })
        this.layoutMainFpsCheckbox()
        this.compactLayout()
    }
    // The fps label is no taller than the record text (but stays readable,
    // >= buttonMinFontSize CSS px) and the box + label row is centred on the
    // menu column
    layoutMainFpsCheckbox()
    {
        const check = this.mainFpsCounterCheckbox
        const recordSize = parseFloat(this.classicRecord.fontSize)
        const height = (m) => m.actualBoundingBoxAscent + m.actualBoundingBoxDescent

        ctx.save()
        ctx.font = this.classicRecord.fontSize
        const recordHeight = height(ctx.measureText(this.classicRecord.text))
        ctx.font = getArcadeFont(recordSize)
        const label = ctx.measureText(check.label)
        ctx.restore()

        const cssHeight = getCanvasCssRect().height
        const minSize = cssHeight > 0 ? STYLE.ui.buttonMinFontSize * this.height / cssHeight : 0
        const size = Math.max(Math.min(recordSize, minSize),
            recordSize * Math.min(1, recordHeight / height(label)))
        const rowWidth = size * 1.55 + label.width * size / recordSize

        check.size = size
        check.fontSize = getArcadeFont(size)
        check.x = this.center.x - rowWidth / 2
    }
    // Phones: buttons grow to the touch floor and the rows are stacked
    // evenly below the corner buttons (language, mute)
    compactLayout()
    {
        const touch = compactTouchSize(0.1 * this.height)
        if (!touch)
            return
        const margin = MUTE_BUTTON.marginRatio * this.height
        const top = 2 * margin + Math.max(MUTE_BUTTON.sizeRatio * this.height, touch)
        const recordSize = parseFloat(this.classicRecord.fontSize)
        const check = this.mainFpsCounterCheckbox
        const rows = stackRows(top, this.height - margin, [parseFloat(this.mainText.fontSize),
            touch, recordSize, touch, recordSize, check.hitRect().height, recordSize])

        this.mainText.y = rows[0]
        this.layoutPauseButton(this.classicVersionButton, this.center.x, rows[1], 0.4 * this.width, touch)
        this.classicRecord.y = rows[2]
        this.layoutPauseButton(this.badVersionButton, this.center.x, rows[3], 0.4 * this.width, touch)
        this.badRecord.y = rows[4]
        check.y = rows[5]
        this.timeInGame.y = rows[6]
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
    drawPauseTitle(panel)
    {
        const pauseTitle = new Text(
        {
            fill    : STYLE.colors.ui.title,
            fontSize: this.getPauseTitleFontSize(panel),
            text    : I18N.t('game.title'),
            x       : this.center.x,
            y       : this.pauseTitleY
        })

        pauseTitle.draw()
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
        this.layoutPauseButton(
            this.backToMenu,
            centerX,
            panel.y + panel.height * 0.52,
            buttonWidth,
            buttonHeight
        )

        const rowY = panel.y + panel.height * 0.72
        const backToMenuFontSize = parseFloat(this.backToMenu.text.fontSize)
        const fpsFontSize = Math.min(backToMenuFontSize, panel.width * 0.09)
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

        if (!touch)
            return
        const rows = stackRows(panel.y, panel.y + panel.height, [this.getPauseTitleFontSize(panel),
            buttonHeight, buttonHeight, this.pauseFpsCounterCheckbox.hitRect().height])
        this.pauseTitleY = rows[0]
        this.layoutPauseButton(this.resume, centerX, rows[1], buttonWidth, buttonHeight)
        this.layoutPauseButton(this.backToMenu, centerX, rows[2], buttonWidth, buttonHeight)
        this.pauseFpsCounterCheckbox.y = rows[3]
    }
    click(coord)
    {
        return  this.classicVersionButton.isClickOnButton(coord)    ||
                this.badVersionButton.isClickOnButton(coord)        ||
                this.resume.isClickOnButton(coord)                  ||
                this.mainFpsCounterCheckbox.isClickOnButton(coord)  ||
                this.pauseFpsCounterCheckbox.isClickOnButton(coord) ||
                this.backToMenu.isClickOnButton(coord)
    }
    clickToPause(coord)
    {
        return (this.visible)?false:this.button.isClickOnButton(coord)   
    }
    setVisible(visible)
    {
        this.visible = visible
        
        this.classicVersionButton.clickable     = visible
        this.badVersionButton.clickable         = visible
        this.mainFpsCounterCheckbox.clickable   = visible
    }
    changeGamePause(isPaused)
    {
        this.gamePaused = isPaused
        
        this.pauseFpsCounterCheckbox.clickable = isPaused
        this.resume.clickable                   = isPaused
        this.backToMenu.clickable               = isPaused
    }
    startPause()
    {
        pauseTimeInGame()
        PROGRESS.save()
        this.timeInGame.text = I18N.t('menu.timeInGame', {minutes: getTimeInGame()})

        this.changeGamePause(true)
        PLATFORM.sendLifecycle('level_paused')

        this.drawPauseScreen()
    }
    drawPauseScreen()
    {
        const panel = this.getPausePanel()
        this.layoutPauseControls(panel)

        ctx.fillStyle = STYLE.colors.ui.pauseOverlay
        ctx.fillRect(0, 0, this.width, this.height)
        
        ctx.save()
        ctx.fillStyle   = STYLE.colors.ui.pausePanelFill
        ctx.strokeStyle = STYLE.colors.ui.pausePanelStroke
        ctx.lineWidth = STYLE.ui.pausePanelLineWidth
        ctx.shadowColor = STYLE.colors.ui.pausePanelStroke
        ctx.shadowBlur = STYLE.ui.buttonShadowBlur
        ctx.fillRect(panel.x, panel.y, panel.width, panel.height)
        ctx.strokeRect(panel.x, panel.y, panel.width, panel.height)
        ctx.restore()
        
        this.drawPauseTitle(panel)
        
        this.pauseFpsCounterCheckbox.draw()
        
        this.resume.draw()
        this.backToMenu.draw()

        MUTE_BUTTON.draw('pause')
    }
    unPause()
    {
        reuseTimeInGame()
        menu.changeGamePause(false)
        PLATFORM.sendLifecycle('level_resumed')
    }
    opened()
    {
        return menu.gamePaused || menu.visible
    }
    pause()
    {
        /*
        Добавь функцию clickOn/off для button
        добавь кнопку resume и back to menu
        добавь прыгающий куб в classic
        */
        
    }
    draw()
    {
        if (typeof visualEffects != 'undefined' && visualEffects && visualEffects.background)
            visualEffects.background.drawMenuBackground()
        else
            ctx.clearRect(0, 0, this.width, this.height)
        
        this.mainText.draw()
        
        this.classicVersionButton.draw()
        this.classicRecord.draw()
        
        this.badVersionButton.draw()
        this.badRecord.draw()

        this.layoutMainFpsCheckbox()
        this.mainFpsCounterCheckbox.draw()
        this.timeInGame.draw()

        MUTE_BUTTON.draw('menu')
        LANGUAGE_BUTTON.draw()
    }
}
// Offered after an eligible lethal death: two equally sized and styled
// buttons, a rewarded continue and a plain restart. The continue button
// carries an 'AD' badge and the line above it names the reward.
class ContinueOffer
{
    constructor(w, h, onContinue, onRestart)
    {
        this.visible = false
        // Rewarded ad state: ads may be unavailable for the whole run
        // (adblock, no SDK), fail for this offer, or be playing right now.
        this.adsAvailable = true
        this.adFailed = false
        this.adPending = false
        this.continueButton = new Button(
            {x: 0, y: 0, width: 1, height: 1, stroke: STYLE.colors.ui.primary, clickable: false},
            {text: '', fill: STYLE.colors.ui.buttonText},
            onContinue)
        this.restartButton = new Button(
            {x: 0, y: 0, width: 1, height: 1, stroke: STYLE.colors.ui.primary, clickable: false},
            {text: '', fill: STYLE.colors.ui.buttonText},
            onRestart)
        this.relabel(w, h)
    }
    // Labels in the current language, then a layout that fits them
    relabel(w, h)
    {
        this.continueButton.text.text = I18N.t('continue.watch')
        this.restartButton.text.text = I18N.t('continue.restart')
        this.adBadgeLabel = I18N.t('continue.adBadge')
        this.rewardLabel = I18N.t('continue.reward')
        this.layout(w, h)
    }
    layout(w, h)
    {
        this.width = w
        this.height = h
        // Phones: touch-sized buttons, rows stacked evenly in a wider panel
        const touch = compactTouchSize(h * 0.11)
        this.panel =
        {
            width: touch ? w * 0.96 : Math.min(w * 0.84, h * 1.3),
            height: h * 0.7
        }
        this.panel.x = (w - this.panel.width) / 2
        this.panel.y = (h - this.panel.height) / 2

        const centerX = w / 2
        const buttonWidth = this.panel.width * 0.7
        const buttonHeight = touch || h * 0.11
        const buttons = [this.continueButton, this.restartButton]
        // Names the reward above the watch button
        const rewardFontSize = Math.min(h * 0.045,
            this.fittedFontSize(this.rewardLabel, h * 0.045, this.panel.width * (touch ? 0.94 : 0.9)))
        const y = touch
            ? stackRows(this.panel.y, this.panel.y + this.panel.height,
                [h * 0.09, h * 0.05, rewardFontSize, buttonHeight, buttonHeight])
            : [0.16, 0.33, 0.42, 0.56, 0.78].map(f => this.panel.y + this.panel.height * f)

        for (let i = 0; i < buttons.length; ++i)
            menu.layoutPauseButton(buttons[i], centerX, y[3 + i], buttonWidth, buttonHeight)
        this.clearAdBadge()

        // Equal prominence: both labels share the smaller fitted size
        const fontSize = Math.min(...buttons.map(b => parseFloat(b.text.fontSize)))
        for (let i = 0; i < buttons.length; ++i)
            buttons[i].text.fontSize = getArcadeFont(fontSize)

        this.title = new Text(
        {
            fill    : STYLE.colors.ui.title,
            fontSize: h * 0.09,
            text    : I18N.t('continue.title'),
            x       : centerX,
            y       : y[0]
        })
        this.score = new Text(
        {
            fill    : STYLE.colors.ui.mutedText,
            fontSize: h * 0.05,
            text    : '',
            x       : centerX,
            y       : y[1]
        })
        this.rewardText = new Text(
        {
            fill    : STYLE.colors.ui.buttonText,
            fontSize: rewardFontSize,
            text    : this.rewardLabel,
            x       : centerX,
            y       : y[2]
        })
        // Takes the watch button's place when there is no ad to offer
        this.noticeText = new Text(
        {
            fill    : STYLE.colors.ui.mutedText,
            fontSize: h * 0.05,
            text    : '',
            x       : centerX,
            y       : y[3]
        })
    }
    // A label that would run under the badge ('Продолжить' next to
    // 'РЕКЛАМА') is centred and fitted in the space right of it
    clearAdBadge()
    {
        const button = this.continueButton
        const b = button.background
        const badge = this.adBadge()
        const left = badge.x + badge.width + b.height * 0.15
        const right = b.x + b.width - b.height * 0.22
        const size = parseFloat(button.text.fontSize)

        ctx.save()
        ctx.font = button.text.fontSize
        const textLeft = button.text.x - ctx.measureText(button.text.text).width / 2
        ctx.restore()
        if (textLeft >= left)
            return

        button.text.x = (left + right) / 2
        button.text.fontSize = getArcadeFont(Math.max(STYLE.ui.buttonMinFontSize,
            this.fittedFontSize(button.text.text, size, right - left)))
    }
    fittedFontSize(label, size, maxWidth)
    {
        ctx.save()
        ctx.font = getArcadeFont(size)
        const measured = ctx.measureText(label).width
        ctx.restore()
        return measured <= maxWidth ? size : size * maxWidth / measured
    }
    // Badge box inside the continue button's left edge
    adBadge()
    {
        const b = this.continueButton.background
        const height = b.height * 0.56
        // Wide enough for a longer label ('РЕКЛАМА')
        ctx.save()
        ctx.font = getArcadeFont(height * 0.7)
        const width = Math.max(height * 1.5, ctx.measureText(this.adBadgeLabel).width + height * 0.4)
        ctx.restore()
        return {x: b.x + b.height * 0.22, y: b.y + (b.height - height) / 2, width: width, height: height}
    }
    drawAdBadge()
    {
        const badge = this.adBadge()
        ctx.save()
        ctx.fillStyle = STYLE.colors.ui.primary
        ctx.fillRect(badge.x, badge.y, badge.width, badge.height)
        ctx.fillStyle = STYLE.colors.ui.buttonFill
        ctx.font = getArcadeFont(badge.height * 0.7)
        ctx.textAlign = 'center'
        ctx.textBaseline = 'middle'
        ctx.fillText(this.adBadgeLabel, badge.x + badge.width / 2, badge.y + badge.height / 2)
        LAYOUT_PROBE.text(this.adBadgeLabel, badge.x + badge.width / 2, badge.y + badge.height / 2)
        ctx.restore()
    }
    show()
    {
        this.adFailed = false
        this.adPending = false
        this.setVisible(true)
    }
    hide()
    {
        this.adPending = false
        this.setVisible(false)
    }
    setVisible(visible)
    {
        this.visible = visible
        this.updateClickable()
    }
    watchVisible()
    {
        return this.adsAvailable && !this.adFailed
    }
    setAdsAvailable(available)
    {
        this.adsAvailable = available
        this.updateClickable()
    }
    // While an ad is requested both buttons ignore clicks until a callback
    setAdPending(pending)
    {
        this.adPending = pending
        this.updateClickable()
    }
    showAdError()
    {
        this.adPending = false
        this.adFailed = true
        this.updateClickable()
    }
    updateClickable()
    {
        const enabled = this.visible && !this.adPending
        this.continueButton.clickable = enabled && this.watchVisible()
        this.restartButton.clickable = enabled
    }
    notice()
    {
        if (!this.adsAvailable)
            return I18N.t('continue.adsUnavailable')
        if (this.adFailed)
            return I18N.t('continue.adUnavailable')
        return ''
    }
    click(coord)
    {
        return this.continueButton.isClickOnButton(coord) ||
               this.restartButton.isClickOnButton(coord)
    }
    draw()
    {
        this.score.text = scoreText.text + scoreText.count[version]

        ctx.save()
        ctx.fillStyle = STYLE.colors.ui.pauseOverlay
        ctx.fillRect(0, 0, this.width, this.height)
        ctx.fillStyle   = STYLE.colors.ui.pausePanelFill
        ctx.strokeStyle = STYLE.colors.ui.pausePanelStroke
        ctx.lineWidth = STYLE.ui.pausePanelLineWidth
        ctx.shadowColor = STYLE.colors.ui.pausePanelStroke
        ctx.shadowBlur = STYLE.ui.buttonShadowBlur
        ctx.fillRect(this.panel.x, this.panel.y, this.panel.width, this.panel.height)
        ctx.strokeRect(this.panel.x, this.panel.y, this.panel.width, this.panel.height)
        ctx.restore()

        this.title.draw()
        this.score.draw()

        ctx.save()
        if (this.adPending)
            ctx.globalAlpha = 0.4
        if (this.watchVisible())
        {
            this.rewardText.draw()
            this.continueButton.draw()
            this.drawAdBadge()
        }
        else
        {
            this.noticeText.text = this.notice()
            this.noticeText.draw()
        }
        this.restartButton.draw()
        ctx.restore()
    }
}
