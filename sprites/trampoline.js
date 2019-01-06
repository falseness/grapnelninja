class Trampoline extends Element
{
    constructor(object)
    {
        super(object)
        
        this.stroke = this.stroke   || 'black'
        this.fill   = this.fill     || '#7bd17b'
        
        this.circle = 
        {
            x: 0,
            y: 0
        }
        
        this.points         = object.points.slice()
        this.rightPointX    = object.points[0].x
        this.leftPointX     = object.points[0].x
        
        for (let i = 0; i < object.points.length; i += 2)
        {
            if (object.points[i].x > this.rightPointX)
                this.rightPointX = object.points[i].x
            if (object.points[i].x < this.leftPointX)
                this.leftPointX = object.points[i].x
            
            this.circle.x += object.points[i].x
            this.circle.y += object.points[i].y
        }
        
        this.circle.x /= (object.points.length)
        this.circle.y /= (object.points.length)
        
        let r = 0
        for (let i = 0; i < object.points.length; ++i)
        {
            let t = Math.pow(object.points[i].x - this.circle.x, 2) +
                    Math.pow(object.points[i].y - this.circle.y, 2)
            if (t > r)
                r = t
        }
        this.circle.radius = Math.sqrt(r)
    }
    getCircumscribedCircle()
    {
        return {x: this.x + this.circle.x, y: this.y + this.circle.y, radius: this.circle.radius}
    }
    getRightPointX()
    {
        return this.x + this.rightPointX
    }
    getLeftPointX()
    {
        return this.x + this.leftPointX
    }
    getPoints()
    {
        let res = []
        for (let i = 0; i < this.points.length; ++i)
            res.push({x: this.points[i].x + this.x, y: this.points[i].y + this.y})
        return res
    }
    collision(who, line)
    {
        if (line.type == 'vertical')
        {
            who.speedX *= -1
        }
        else if (line.type == 'line')
        {
            let lineAngle = line.k

            let xn = -who.speedX
            let yn = -who.speedY

            let x = xn * Math.cos(lineAngle) + yn * Math.sin(lineAngle)
            let y = yn * Math.cos(lineAngle) - xn * Math.sin(lineAngle)

            x = -x

            xn = x * Math.cos(lineAngle) - y * Math.sin(lineAngle)
            yn = y * Math.cos(lineAngle) + x * Math.sin(lineAngle)

            who.speedX = xn
            who.speedY = yn
            who.speedX += GRAVITY * Math.cos(lineAngle) * Math.sin(lineAngle)
            who.speedY -= GRAVITY * Math.pow(Math.cos(lineAngle), 2)
        }
        else
            console.log('collision with trampoline error')
    }
}
function generateTrampolinePoints()
{
    const trampolineRestriction = 
    {
        width:
        {
            min: 0.2 * width,
            max: 0.3 * width
        }, 
        height:
        {
            min: 0.1 * height,
            max: 0.3 * height
        }
    }
    
    let x2 = random(trampolineRestriction.width.min, trampolineRestriction.width.max)
    
    let res = 
    [
        {x: 0,  y: 0                                                                            }, 
        {x: 0,  y: -random(trampolineRestriction.height.min, trampolineRestriction.height.max)  },
        {x: x2, y: -random(trampolineRestriction.height.min, trampolineRestriction.height.max)  },
        {x: x2, y: 0                                                                            }
    ]
    
    return res
    
}
function generateTrampoline(x)
{
    trampolineModel = 
    {
        points: generateTrampolinePoints()
    }
    trampolineModel.x = x
    trampolineModel.y = area[1].y
    elements.push(new Trampoline(createLineByModel(trampolineModel)))
    
    const generatedElementsNumber = 1
    return generatedElementsNumber
}
