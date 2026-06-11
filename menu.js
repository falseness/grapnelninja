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
        text.fontSize   = this.background.height
        
        if (typeof background.clickable == "undefined")
            this.clickable = true
        else
            this.clickable  = background.clickable
        
        this.text = new Text(text)
        
        this.image = image
        
        this.click = clickFunc
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
        const x = viewWidth * STYLE.ui.fpsXRatio
        const y = viewHeight * STYLE.ui.fpsYRatio
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
            text: 'classic version'
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
            text: 'bad version'
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

        this.timeInGame = new Text(
            {
            x       : this.center.x                     ,
            y       : 0.8 * this.height                ,
            fontSize: 0.05 * this.height                ,
            fill    : STYLE.colors.ui.mutedText         ,
            text    : 'time spent in game: ' + getTimeInGame() + ' minutes'
        })

        let checkMark = 
        {
            x: 0.645 * width,
            y: 0.67 * height,
            p1:
            {
                x: 0.025 * width,
                y: 0.05 * height
            },
            p2:
            {
                x: 0.058 * width,
                y: -0.05 * height
            },
            lineWidth: STYLE.strokes.checkMarkWidthRatio * height,
            fill: STYLE.colors.ui.text
        }
        this.visualEffectsText = new Text(
        {
            x       : this.center.x - 0.2 * this.width  ,
            y       : 0.7 * this.height,
            fontSize: 0.1 * this.height , 
            fill    : STYLE.colors.ui.text,
            text    : 'visual effects'  ,
            alignX  : 'start'
        })
        this.visualEffectsCheckbox = new Button(
        {
            x       : Math.max(this.center.x + 0.17 * this.width, 0.05 * this.width + this.visualEffectsText.getWidth()),
            y       : 0.7 * this.height,
            width   : 0.1 * this.height ,
            height  : 0.1 * this.height,
            stroke  : STYLE.colors.ui.primary
        },
        {
            text: ''
        },
        function()
        {
            trackEnabled = !trackEnabled
            ctx.clearRect(Math.min(menu.visualEffectsCheckbox.background.x, checkMark.x - checkMark.lineWidth * 2),
                          Math.min(menu.visualEffectsCheckbox.background.y, checkMark.y - checkMark.lineWidth,
                                  checkMark.y - checkMark.lineWidth + checkMark.p1.y, 
                                   checkMark.y - checkMark.lineWidth + checkMark.p2.y), 
                          Math.max(menu.visualEffectsCheckbox.background.width,
                                  checkMark.p1.x + checkMark.lineWidth, checkMark.p2.x + checkMark.lineWidth + checkMark.x - Math.min(menu.visualEffectsCheckbox.background.x, checkMark.x - checkMark.lineWidth * 2)),
                          Math.max(menu.visualEffectsCheckbox.background.height,
                                  checkMark.p1.y + checkMark.lineWidth, checkMark.p2.y + checkMark.lineWidth))
            
            menu.visualEffectsCheckbox.draw()
                
        }, 
        {
            draw: function()
            {
                if (trackEnabled)
                {
                    ctx.beginPath()
                    
                    let x = checkMark.x//0.645 * width
                    let y = checkMark.y

                    ctx.moveTo(x, y)
                    ctx.lineTo(x + checkMark.p1.x, y + checkMark.p1.y)
                    ctx.lineTo(x + checkMark.p2.x, y + checkMark.p2.y)


                    ctx.lineWidth = checkMark.lineWidth
                    ctx.strokeStyle = checkMark.fill
                    ctx.shadowColor = checkMark.fill
                    ctx.shadowBlur = STYLE.ui.textShadowBlur
                    ctx.stroke()
                    ctx.shadowBlur = 0
                    ctx.lineWidth = STYLE.strokes.defaultWidth
                    ctx.closePath()
                }
            }
        })
        this.fpsCounterText = new Text(
        {
            x       : this.center.x - 0.2 * this.width,
            y       : 0.62 * this.height,
            fontSize: 0.1 * this.height,
            fill    : STYLE.colors.ui.text,
            text    : 'fps counter',
            alignX  : 'start'
        })
        this.fpsCounterButton = new Button(
        {
            x       : this.center.x + 0.19 * this.width,
            y       : 0.62 * this.height,
            width   : 0.17 * this.width,
            height  : 0.078 * this.height,
            stroke  : STYLE.colors.ui.primary,
            clickable: false
        },
        {
            text: 'off',
            fill: STYLE.colors.ui.buttonText
        },
        function()
        {
            fpsCounter.toggle()
            menu.updateFpsCounterButtonText()
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
    click(coord)
    {
        return  this.classicVersionButton.isClickOnButton(coord)    ||
                this.badVersionButton.isClickOnButton(coord)        ||
                this.resume.isClickOnButton(coord)                  ||
                this.visualEffectsCheckbox.isClickOnButton(coord)   ||
                this.fpsCounterButton.isClickOnButton(coord)        ||
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
        this.visualEffectsCheckbox.clickable    = visible
    }
    changeGamePause(isPaused)
    {
        this.gamePaused = isPaused
        
        this.visualEffectsCheckbox.clickable    = isPaused
        this.fpsCounterButton.clickable         = isPaused
        this.resume.clickable                   = isPaused
        this.backToMenu.clickable               = isPaused
    }
    updateFpsCounterButtonText()
    {
        this.fpsCounterButton.text.text = fpsCounter.enabled ? 'on' : 'off'
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
        ctx.fillStyle = STYLE.colors.ui.pauseOverlay
        ctx.fillRect(0, 0, this.width, this.height)
        
        ctx.save()
        ctx.fillStyle   = STYLE.colors.ui.pausePanelFill
        ctx.strokeStyle = STYLE.colors.ui.pausePanelStroke
        ctx.lineWidth = STYLE.ui.pausePanelLineWidth
        ctx.shadowColor = STYLE.colors.ui.pausePanelStroke
        ctx.shadowBlur = STYLE.ui.buttonShadowBlur
        ctx.fillRect(this.width * 0.28, this.height * 0.1, this.width * 0.44, this.height * 0.7)
        ctx.strokeRect(this.width * 0.28, this.height * 0.1, this.width * 0.44, this.height * 0.7)
        ctx.restore()
        
        this.mainText.draw()
        
        this.visualEffectsText.draw()
        this.visualEffectsCheckbox.draw()
        this.fpsCounterText.draw()
        this.updateFpsCounterButtonText()
        this.fpsCounterButton.draw()
        
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
        ctx.clearRect(0, 0, this.width, this.height)
        
        this.mainText.draw()
        
        this.classicVersionButton.draw()
        this.classicRecord.draw()
        
        this.badVersionButton.draw()
        this.badRecord.draw()

        this.timeInGame.draw()
        
        this.visualEffectsText.draw()
        this.visualEffectsCheckbox.draw()
    }
}
