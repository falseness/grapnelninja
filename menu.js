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
    constructor(background, text, clickFunc)
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
        
        this.text = new Text(text)
        
        this.click = clickFunc
    }
    draw()
    {
        ctx.fillStyle   = this.background.fill
        ctx.strokeStyle = this.background.stroke
        
        ctx.strokeRect(this.background.x, this.background.y, this.background.width, this.background.height) 
        ctx.fillRect(this.background.x, this.background.y, this.background.width, this.background.height)
        
        this.text.draw()
    }
    isClickOnButton(click)
    {
        if (this.background.x < click.x && click.x < this.background.x + this.background.width &&
            this.background.y < click.y && click.y < this.background.y + this.background.height)
            this.click()
    }
}
class Menu
{
    constructor(w, h)
    {
        this.width  = w
        this.height = h
        
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
            y       : 0.15 * this.height
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
        })
        this.classicRecord = new Text(
        {
            x       : this.center.x                     ,
            y       : 0.43 * this.height                ,
            fontSize: 0.05 * this.height                ,
            fill    : 'rgba(0, 0, 0, 0.5)'              ,
            text    : 'record: ' + scoreText.record
        })
        this.badVersionButton = new Button(
        {
            x: this.center.x        ,
            y: 0.57 * this.height   ,
            width: 0.4 * this.width ,
            height: 0.1 * this.height
        },
        {
            fill: 'red'            ,
            text: 'bad version'
        },
        startBadVersion)
        this.badRecord = new Text(
        {
            x       : this.center.x                     ,
            y       : 0.65 * this.height                ,
            fontSize: 0.05 * this.height                ,
            fill    : 'rgba(0, 0, 0, 0.5)'              ,
            text    : 'record: ' + scoreText.record
        })
        
        this.visualEffectsText = new Text(
        {
            x       : 0.3 * this.width  ,
            y       : 0.75 * this.height ,
            fontSize: 0.1 * this.height , 
            fill    : 'blue'            ,
            text    : 'visual effects'  ,
            alignX  : 'start'
        })
        this.visualEffectsCheckbox = new Button(
        {
            x       : 0.67 * this.width  ,
            y       : 0.75 * this.height ,
            width   : 0.1 * this.height ,
            height  : 0.1 * this.height
        },
        {
            text: ''
        },
        function()
        {
            trackEnabled = !trackEnabled
            menu.draw()
        })
    }
    click(coord)
    {
        this.classicVersionButton.isClickOnButton(coord)
        this.badVersionButton.isClickOnButton(coord)
        this.visualEffectsCheckbox.isClickOnButton(coord)
    }
    draw()
    {
        ctx.clearRect(0, 0, this.width, this.height)
        
        this.mainText.draw()
        
        this.classicVersionButton.draw()
        this.classicRecord.draw()
        
        this.badVersionButton.draw()
        this.badRecord.draw()
        
        this.visualEffectsText.draw()
        this.visualEffectsCheckbox.draw()
        
        if (trackEnabled)
        {
            ctx.beginPath()
            
           /* 0.67 * this.width  ,
            y       : 0.75 * this.height ,
            width   : 0.1 * this.height ,
            height  : 0.1 * this.height*/
            
            let x = 0.645 * this.width
            let y = 0.72 * this.height
            
            ctx.moveTo(x, y)
            ctx.lineTo(x + 0.025 * this.width, y + 0.05 * this.height)
            ctx.lineTo(x + 0.058 * this.width, y - 0.05 * this.height)


            ctx.lineWidth = 0.03 * height
            ctx.strokeStyle = 'blue'
            ctx.stroke()
            ctx.lineWidth = 1
            ctx.closePath()
        }
    }
}
