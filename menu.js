function reuseTimeInGame() {
    time = Math.floor(new Date().getTime() / 1000)
}
function pauseTimeInGame() {
    let thisTime = Math.floor(new Date().getTime() / 1000)
    let delta = Math.floor(thisTime - time)

    let newTime = delta
    if (!!localStorage.getItem('time')) {
        let oldTime = Number(localStorage.getItem('time'))
        newTime += oldTime
    }
    localStorage.setItem('time', newTime)
}
function getTimeInGame() {
    let t = 0
    if (!!localStorage.getItem('time')) {
        t += Number(localStorage.getItem('time'))
    }
    return Math.floor(t / 60)
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
        ctx.restore()
    }
}
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
        text.fontSize   = this.getFittedTextSize(text.text, this.background.height)
        
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
        ctx.restore()
    }
    isClickOnButton(click)
    {
        if (!this.clickable)
            return false

        ctx.save()
        ctx.font = this.fontSize
        const labelWidth = ctx.measureText(this.label).width
        ctx.restore()

        const padding = this.size * 0.45
        const minX = this.x - padding
        const maxX = this.x + this.size * 1.55 + labelWidth + padding
        const minY = this.y - this.size / 2 - padding
        const maxY = this.y + this.size / 2 + padding

        if (minX < click.x && click.x < maxX && minY < click.y && click.y < maxY)
        {
            this.click()
            return true
        }
        return false
    }
}
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
        const fontSize = viewHeight * STYLE.ui.fpsFontRatio
        const padding = viewHeight * STYLE.ui.fpsPaddingRatio
        const text = 'FPS: ' + this.value

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
            text    : 'Grapnel ninja'   ,
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
            text: 'chill version'
        },
        function(){startGame('classic')})
        this.classicRecord = new Text(
        {
            x       : this.center.x                     ,
            y       : 0.43 * this.height                ,
            fontSize: 0.05 * this.height                ,
            fill    : STYLE.colors.ui.mutedText         ,
            text    : 'record: ' + scoreText.record.classic
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
            text: 'main version'
        },
        function(){startGame('bad')})
        this.badRecord = new Text(
        {
            x       : this.center.x                     ,
            y       : 0.60 * this.height                ,
            fontSize: 0.05 * this.height                ,
            fill    : STYLE.colors.ui.mutedText         ,
            text    : 'record: ' + scoreText.record.bad
        })

        this.mainFpsCounterCheckbox = new Checkbox(
        {
            x       : this.center.x - 0.15 * this.width,
            y       : 0.70 * this.height,
            size    : 0.09 * this.height,
            fontSize: 0.09 * this.height,
            fill    : STYLE.colors.ui.text,
            stroke  : STYLE.colors.ui.primary,
            label   : 'fps counter',
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
            text    : 'time spent in game: ' + getTimeInGame() + ' minutes'
        })

        this.pauseFpsCounterCheckbox = new Checkbox(
        {
            x       : this.center.x - 0.15 * this.width,
            y       : 0.68 * this.height,
            size    : 0.09 * this.height,
            fontSize: 0.09 * this.height,
            fill    : STYLE.colors.ui.text,
            stroke  : STYLE.colors.ui.primary,
            label   : 'fps counter',
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
            text: 'resume',
            fill: STYLE.colors.ui.buttonText
        }, function()
        {
            menu.changeGamePause(false)
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
            text: 'back to menu'    ,
            fill: STYLE.colors.ui.buttonText
        },
        function()
        {
            menu.changeGamePause(false)
    
            menu.setVisible(true)
           
            menu.classicRecord.text = scoreText.rtext    + scoreText.record.classic
            menu.badRecord.text     = scoreText.rtext   + scoreText.record.bad
            
            menu.draw()
            
            cancelAnimationFrame(game)
        })
    }
    getPausePanel()
    {
        const panelWidth = Math.min(this.width * 0.84, this.width - 24)
        const panelHeight = Math.min(this.height * 0.76, this.height - 28)

        return {
            x: (this.width - panelWidth) / 2,
            y: (this.height - panelHeight) / 2,
            width: panelWidth,
            height: panelHeight
        }
    }
    getPauseTitleFontSize(panel)
    {
        const text = 'Grapnel ninja'
        const maxWidth = Math.max(1, panel.width - Math.max(24, this.width * 0.12))
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
            text    : 'Grapnel ninja',
            x       : this.center.x,
            y       : panel.y + panel.height * 0.14
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
        button.text.fontSize = getArcadeFont(button.getFittedTextSize(button.text.text, height))
    }
    layoutPauseControls(panel)
    {
        const buttonWidth = Math.min(panel.width * 0.48, this.width * 0.42)
        const buttonHeight = Math.min(this.height * 0.1, panel.height * 0.13)
        const centerX = panel.x + panel.width / 2

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
        this.timeInGame.text = 'time spent in game: ' + getTimeInGame() + ' minutes'

        this.changeGamePause(true)

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
    }
    unPause()
    {
        reuseTimeInGame()
        menu.changeGamePause(false)
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

        this.mainFpsCounterCheckbox.draw()
        this.timeInGame.draw()
        
    }
}
