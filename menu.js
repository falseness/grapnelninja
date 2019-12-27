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
    console.log(newTime)
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
        this.fontSize   = object.fontSize + 'px ' + 'Calibri'
        this.text       = object.text
        this.align      =
        {
            x: object.alignX || 'center',
            y: object.alignY || 'middle'
        }
    }
    getWidth()
    {
        ctx.font = this.fontSize + 'px ' + 'Calibri'
        return ctx.measureText(this.text).width
    }
    draw()
    {
        ctx.fillStyle   = this.fill
        ctx.textBaseline= this.align.y
        ctx.textAlign   = this.align.x
        ctx.font        = this.fontSize + 'px ' + 'Calibri'
        
        
        ctx.fillText(this.text, this.x, this.y)
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
        this.background.fill    = background.fill   || 'white'
        this.background.stroke  = background.stroke || 'black'
        
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
        ctx.fillStyle   = this.background.fill
        ctx.strokeStyle = this.background.stroke
        
        ctx.strokeRect(this.background.x, this.background.y, this.background.width, this.background.height) 
        ctx.fillRect(this.background.x, this.background.y, this.background.width, this.background.height)
        
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
            fill    : 'blue'            ,
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
            height: 0.1 * this.height
        },
        {
            fill: 'green'         ,
            text: 'classic version'
        },
        function(){startGame('classic')})
        this.classicRecord = new Text(
        {
            x       : this.center.x                     ,
            y       : 0.43 * this.height                ,
            fontSize: 0.05 * this.height                ,
            fill    : 'rgba(0, 0, 0, 0.5)'              ,
            text    : 'record: ' + scoreText.record.classic
        })
        this.badVersionButton = new Button(
        {
            x: this.center.x        ,
            y: 0.52 * this.height   ,
            width: 0.4 * this.width ,
            height: 0.1 * this.height
        },
        {
            fill: 'red'            ,
            text: 'bad version'
        },
        function(){startGame('bad')})
        this.badRecord = new Text(
        {
            x       : this.center.x                     ,
            y       : 0.60 * this.height                ,
            fontSize: 0.05 * this.height                ,
            fill    : 'rgba(0, 0, 0, 0.5)'              ,
            text    : 'record: ' + scoreText.record.bad
        })

        this.timeInGame = new Text(
            {
            x       : this.center.x                     ,
            y       : 0.8 * this.height                ,
            fontSize: 0.05 * this.height                ,
            fill    : 'rgba(0, 0, 0, 0.5)'              ,
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
            lineWidth: 0.03 * height,
            fill: 'blue'
        }
        this.visualEffectsText = new Text(
        {
            x       : this.center.x - 0.2 * this.width  ,
            y       : 0.7 * this.height,
            fontSize: 0.1 * this.height , 
            fill    : 'blue'            ,
            text    : 'visual effects'  ,
            alignX  : 'start'
        })
        this.visualEffectsCheckbox = new Button(
        {
            x       : Math.max(this.center.x + 0.17 * this.width, 0.05 * this.width + this.visualEffectsText.getWidth()),
            y       : 0.7 * this.height,
            width   : 0.1 * this.height ,
            height  : 0.1 * this.height
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
                    ctx.stroke()
                    ctx.lineWidth = 1
                    ctx.closePath()
                }
            }
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

                    ctx.lineWidth = Math.round(0.05 * h)

                    let x1 = x + 0.1 * w, x2 = x + 0.9 * w
                    let y1 = y + 0.3 * h
                    let dy = 0.2 * h
                    ctx.moveTo(x1, y1)
                    ctx.lineTo(x2, y1)

                    ctx.moveTo(x1, y1 + dy)
                    ctx.lineTo(x2, y1 + dy)

                    ctx.moveTo(x1, y1 + dy * 2)
                    ctx.lineTo(x2, y1 + dy * 2)

                    ctx.strokeStyle = 'blue'
                    ctx.stroke()

                    ctx.lineWidth = 1

                    ctx.closePath()
                }
            }
        ]
        this.constButton = 
        {
            x       : 0.96  * this.width,
            y       : 0.05 * this.height,
            width   : 0.1  * this.height,
            height  : 0.09  * this.height,
            fill    : 'rgb(0, 0, 0, 0)'
        }
        this.resume = new Button(
        {
            x: this.center.x        ,
            y: 0.35 * this.height   ,
            width: 0.4 * this.width ,
            clickable:false         ,
            height: 0.1 * this.height
        },
        {
            text: 'resume',
            fill: 'green'
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
            height: 0.1 * this.height
        },
        {
            fill: 'blue'            ,
            text: 'back to menu'    ,
            fill: 'red'
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
        this.resume.clickable                   = isPaused
        this.backToMenu.clickable               = isPaused
    }
    startPause()
    {
        pauseTimeInGame()
        this.timeInGame.text = 'time spent in game: ' + getTimeInGame() + ' minutes'

        this.changeGamePause(true)
        
        ctx.fillStyle = 'rgba(245, 245, 245, 0.52)'
        ctx.fillRect(0, 0, this.width, this.height)
        
        ctx.fillStyle   = 'white'
        ctx.strokeStyle = 'black'
        ctx.fillRect(this.width * 0.28, this.height * 0.1, this.width * 0.44, this.height * 0.7)
        ctx.strokeRect(this.width * 0.28, this.height * 0.1, this.width * 0.44, this.height * 0.7)
        
        this.mainText.draw()
        
        this.visualEffectsText.draw()
        this.visualEffectsCheckbox.draw()
        
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