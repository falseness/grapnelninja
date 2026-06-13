function changeScoreText()
{
    if (++scoreText.count[version] > scoreText.record[version])
        scoreText.record[version] = scoreText.count[version]
}
class ElementsFactory
{
    constructor()
    {
        this.factories = 
        {
            ground              : new GroundFactory()               , 
            side                : new SideFactory()                 ,
            frame2Rect          : new Frame2RectFactory()           ,
            frame3Triangle      : new Frame3TriangleFactory()       ,
            frame4Elements      : new Frame4ElementsFactory()       ,
            frame5Rects         : new Frame5RectFactory()           ,
            frame6Rects         : new Frame6RectFactory()           ,
            frame7Elements      : new Frame7ElementsFactory()       ,
            frame8Elements      : new Frame8ElementsFactory()       ,
            frame9Elements      : new Frame9ElementsFactory()       ,
            frame10Elements     : new Frame10ElementsFactory()      ,
            frame11Elements     : new Frame11ElementsFactory()      ,
            horizontalTopRect   : new HorizontalTopRectFactory()    ,
            verticalGroundRect  : new VerticalGroundRectFactory()   ,
            verticalPairRects   : new VerticalPairRectsFactory()    ,
            trampoline          : new TrampolineFactory()           ,
            triangle            : new TriangleFactory()             ,
            harmlessTriangle    : new HarmlessTriangleFactory()     ,
            jumpingCube         : new JumpingCubeFactory()          ,
            jumpingCubeWithCeiling: new JumpingCubeWithHorizontalTopRectFactory(),
            twoTrampolines      : new VerticalPairTrampolineFactory()
        }
    }
    create(x, y, type)
    {
        return this.factories[type].create(x, y)
    }
}

class GroundFactory
{
    constructor()
    {
        this.width  = width
    }
    create(x, y)
    {
        let h = y.max - y.min
        let model =
        {
            x       : x.min         , 
            y       : y.min         ,
            points  : [{x: 0, y: 0}, {x: 0, y: h}, {x: this.width, y: h}, {x: this.width, y: 0}]
        }
        
        return [new Ground(model)]
    }
}
class SideFactory
{
    constructor()
    {
        this.width = width
    }
    create(x, y)
    {
        let h = y.max - y.min
        let model = 
        {
            x       : x.min     ,
            y       : y.min     ,
            width   : this.width,
            height  : h         ,
            fill    : STYLE.colors.ground.fill,
            stroke  : STYLE.colors.ground.stroke
        }
        return [new Side(model)]
    }
}
class HorizontalRectFactory
{
    constructor()
    {
        this.width =
        {
            min: 0.3 * width,
            max: 0.6 * width
        }
        this.height =
        {
            min: 0.1 * height,
            max: 0.2 * height
        }
    }
    getPoints(w, h)
    {
        let res = 
        [
            {x: 0, y: 0},
            {x: 0, y: h},
            {x: w, y: h},
            {x: w, y: 0}
        ]
        
        return res
    }
    create(x, y, w, h)
    {
        let model = 
        {
            x       : x                     ,     
            y       : y                     ,
            points  : this.getPoints(w, h)  ,
            fill    : STYLE.colors.cube.greenFill,
            stroke  : STYLE.colors.cube.greenStroke
        }
        
        return [new Trampoline(model)]
    }
}
class HorizontalTopRectFactory extends HorizontalRectFactory
{
    constructor()
    {
        super()
    }
    create(x, y)
    {
        return [...super.create(random(x.min, x.max), y.min, 
            random(this.width.min, this.width.max), random(this.height.min, this.height.max))]
    }
}
class RectFactory 
{
    constructor()
    {
        this.width =
        {
            min: 0.075 * width,
            max: 0.1 * width
        }
        this.height = 
        {
            min: 0.4 * height,
            max: 0.5 * height
        }
    }
    create(x, y, w, h, isPairElement)
    {
        let model =
        {
            x               : x             ,
            y               : y             ,
            width           : w             ,
            height          : h             ,
            fill            : STYLE.colors.cube.grayFill,
            stroke          : STYLE.colors.cube.grayStroke,
            isPairElement   : isPairElement
        }
        
        return new Rect(model)
    }
}
class VerticalPairRectsFactory extends RectFactory
{
    constructor()
    {
        super()
        this.width = 0.05 * width
    }
    create(x, y)
    {
        x = random(x.min, x.max)
        let wayHeight = (y.max - y.min) * 4 / 8
        let rectHeight = random(0.1 * height, y.max - y.min - wayHeight - 0.1 * height)

        let model1 = 
        [
            x, y.min, this.width, rectHeight,
        ]
        let model2 =
        [
            x, y.min + rectHeight + wayHeight,
            this.width, y.max - y.min - rectHeight - wayHeight
        ]

        return [super.create(...model1, function(){return true}), super.create(...model2, function(){return true})]
    }
}



class VerticalGroundRectFactory extends RectFactory
{
    constructor()
    {
        super()
    }
    create(x, y)
    {
        let w = random(this.width.min, this.width.max)
        let h = random(this.height.min, this.height.max)
        
        return [super.create(random(x.min, x.max), y.max - h, w, h)]
    }
}
class Frame2RectFactory extends RectFactory
{
    constructor()
    {
        super()
        this.displayWidthRatio = 52 / 630
        this.displayTopRatio = 164.5 / 630
        this.displayHeightRatio = 266 / 630
    }
    create(x, y)
    {
        const worldWidth = this.displayWidthRatio * height / scale.bad
        const worldHeight = this.displayHeightRatio * height / scale.bad
        const worldX = (width / scale.bad - worldWidth) / 2
        const worldY = this.displayTopRatio * height / scale.bad
        const model =
        {
            x       : worldX,
            y       : worldY,
            points  :
            [
                {x: 0, y: 0},
                {x: 0, y: worldHeight},
                {x: worldWidth, y: worldHeight},
                {x: worldWidth, y: 0}
            ],
            fill    : STYLE.colors.cube.greenFill,
            stroke  : STYLE.colors.cube.greenStroke
        }

        return [new Trampoline(model)]
    }
}
class Frame5RectFactory extends RectFactory
{
    constructor()
    {
        super()
        this.frameHeight = 630
        this.verticalRects =
        [
            {x: 688.5, y: 76.5, width: 52, height: 266},
            {x: 333.5, y: 188.5, width: 52, height: 365}
        ]
        this.horizontalRect =
        {
            x: 386.935,
            y: 232.654,
            width: 42.9148,
            height: 186.553,
            rotation: -90.5738
        }
    }
    displayToWorld(value)
    {
        return value / this.frameHeight * height / scale.bad
    }
    createGreenTrampolineRect(rect)
    {
        const worldWidth = this.displayToWorld(rect.width)
        const worldHeight = this.displayToWorld(rect.height)
        const model =
        {
            x       : this.displayToWorld(rect.x),
            y       : this.displayToWorld(rect.y),
            points  :
            [
                {x: 0, y: 0},
                {x: 0, y: worldHeight},
                {x: worldWidth, y: worldHeight},
                {x: worldWidth, y: 0}
            ],
            fill    : STYLE.colors.cube.greenFill,
            stroke  : STYLE.colors.cube.greenStroke
        }

        return new Trampoline(model)
    }
    createHorizontalSegment()
    {
        const rect = this.horizontalRect
        const angle = rect.rotation * Math.PI / 180
        const cos = Math.cos(angle)
        const sin = Math.sin(angle)
        const displayPoints =
        [
            {x: 0, y: 0},
            {x: rect.width, y: 0},
            {x: rect.width, y: rect.height},
            {x: 0, y: rect.height}
        ]

        const points = displayPoints.map(point =>
        {
            return {
                x: this.displayToWorld(rect.x + point.x * cos - point.y * sin),
                y: this.displayToWorld(rect.y + point.x * sin + point.y * cos)
            }
        })

        return new Trampoline(
        {
            x       : 0,
            y       : 0,
            points  : points,
            fill    : STYLE.colors.cube.greenFill,
            stroke  : STYLE.colors.cube.greenStroke
        })
    }
    create(x, y)
    {
        return [
            this.createGreenTrampolineRect(this.verticalRects[0]),
            this.createGreenTrampolineRect(this.verticalRects[1]),
            this.createHorizontalSegment()
        ]
    }
}
class Frame6RectFactory extends RectFactory
{
    constructor()
    {
        super()
        this.frameHeight = 630
        this.rects =
        [
            {x: 359.5, y: 76.5, width: 52, height: 106},
            {x: 359.5, y: 381.5, width: 52, height: 172}
        ]
    }
    displayToWorld(value)
    {
        return value / this.frameHeight * height / scale.bad
    }
    createFrameRect(rect)
    {
        return super.create(
            this.displayToWorld(rect.x),
            this.displayToWorld(rect.y),
            this.displayToWorld(rect.width),
            this.displayToWorld(rect.height)
        )
    }
    create(x, y)
    {
        return this.rects.map(rect => this.createFrameRect(rect))
    }
}
class Frame4ElementsFactory extends RectFactory
{
    constructor()
    {
        super()
        this.frameHeight = 630
        this.greenSegment =
        {
            x: 252,
            y: 331,
            width: 53,
            height: 267,
            rotation: -90
        }
        this.blueSquare =
        {
            x: 368,
            y: 165,
            width: 51,
            height: 52
        }
        this.triangle =
        {
            centerX: 386,
            topY: 388,
            bottomY: 502,
            side: 437.962 - 334.038
        }
    }
    displayToWorld(value)
    {
        return value / this.frameHeight * height / scale.bad
    }
    createGreenSegment()
    {
        const rect = this.greenSegment
        const angle = rect.rotation * Math.PI / 180
        const cos = Math.cos(angle)
        const sin = Math.sin(angle)
        const displayPoints =
        [
            {x: 0, y: 0},
            {x: rect.width, y: 0},
            {x: rect.width, y: rect.height},
            {x: 0, y: rect.height}
        ]

        const points = displayPoints.map(point =>
        {
            return {
                x: this.displayToWorld(rect.x + point.x * cos - point.y * sin),
                y: this.displayToWorld(rect.y + point.x * sin + point.y * cos)
            }
        })

        return new Trampoline(
        {
            x       : 0,
            y       : 0,
            points  : points,
            fill    : STYLE.colors.cube.greenFill,
            stroke  : STYLE.colors.cube.greenStroke
        })
    }
    createBlueSquare()
    {
        const rect = this.blueSquare
        const result = super.create(
            this.displayToWorld(rect.x),
            this.displayToWorld(rect.y),
            this.displayToWorld(rect.width),
            this.displayToWorld(rect.height)
        )

        result.fill = STYLE.colors.cube.blueFill
        result.stroke = STYLE.colors.cube.blueStroke

        return result
    }
    createTriangle()
    {
        const triangle = this.triangle
        const worldHeight = this.displayToWorld(triangle.bottomY - triangle.topY)
        const model =
        {
            x       : this.displayToWorld(triangle.centerX),
            y       : this.displayToWorld(triangle.topY) + worldHeight / 3,
            radius  : worldHeight * 2 / 3,
            yMin    : this.displayToWorld(triangle.topY),
            yMax    : this.displayToWorld(triangle.bottomY),
            fill    : STYLE.colors.hazard.fill,
            stroke  : STYLE.colors.hazard.stroke
        }
        const result = new Triangle(model)

        result.side = this.displayToWorld(triangle.side)
        result.height = worldHeight
        result.track = (trackEnabled)?(new MultipointTrackLine(result.side, result.stroke, STYLE.timing.triangleTrailPoints)):(new Empty())
        result.track.addPos(result.getPoints(), true)

        return result
    }
    create(x, y)
    {
        return [
            this.createGreenSegment(),
            this.createBlueSquare(),
            this.createTriangle()
        ]
    }
}
class Frame7ElementsFactory extends RectFactory
{
    constructor()
    {
        super()
        this.frameHeight = 630
        this.greenRect =
        {
            x: 285.5,
            y: 381.5,
            width: 206,
            height: 141
        }
        this.blueSquare =
        {
            x: 363,
            y: 207,
            width: 51,
            height: 52
        }
    }
    displayToWorld(value)
    {
        return value / this.frameHeight * height / scale.bad
    }
    createGreenRect()
    {
        const rect = this.greenRect
        const worldWidth = this.displayToWorld(rect.width)
        const worldHeight = this.displayToWorld(rect.height)

        return new Trampoline(
        {
            x       : this.displayToWorld(rect.x),
            y       : this.displayToWorld(rect.y),
            points  :
            [
                {x: 0, y: 0},
                {x: 0, y: worldHeight},
                {x: worldWidth, y: worldHeight},
                {x: worldWidth, y: 0}
            ],
            fill    : STYLE.colors.cube.greenFill,
            stroke  : STYLE.colors.cube.greenStroke
        })
    }
    createBlueSquare()
    {
        const rect = this.blueSquare

        return new JumpingCube(
        {
            x       : this.displayToWorld(rect.x),
            y       : this.displayToWorld(rect.y),
            width   : this.displayToWorld(rect.width),
            height  : this.displayToWorld(rect.height),
            fill    : STYLE.colors.cube.blueFill,
            stroke  : STYLE.colors.cube.blueStroke
        })
    }
    create(x, y)
    {
        return [
            this.createGreenRect(),
            this.createBlueSquare()
        ]
    }
}
class Frame8ElementsFactory extends RectFactory
{
    constructor()
    {
        super()
        this.frameHeight = 630
        this.grayRect =
        {
            x: 333.5,
            y: 243.5,
            width: 52,
            height: 172
        }
        this.greenRects =
        [
            {x: 146.5, y: 181.5, width: 52, height: 266},
            {x: 516.5, y: 416.5, width: 52, height: 137},
            {x: 516.5, y: 76.5, width: 52, height: 137}
        ]
    }
    displayToWorld(value)
    {
        return value / this.frameHeight * height / scale.bad
    }
    createFrameRect(rect, fill, stroke)
    {
        const result = super.create(
            this.displayToWorld(rect.x),
            this.displayToWorld(rect.y),
            this.displayToWorld(rect.width),
            this.displayToWorld(rect.height)
        )

        result.fill = fill
        result.stroke = stroke

        return result
    }
    create(x, y)
    {
        return [
            this.createFrameRect(this.grayRect, STYLE.colors.cube.grayFill, STYLE.colors.cube.grayStroke),
            ...this.greenRects.map(rect =>
                this.createFrameRect(rect, STYLE.colors.cube.greenFill, STYLE.colors.cube.greenStroke))
        ]
    }
}
class Frame9ElementsFactory extends RectFactory
{
    constructor()
    {
        super()
        this.frameHeight = 630
        this.greenRects =
        [
            {x: 141.5, y: 444.5, width: 52, height: 109},
            {x: 141.5, y: 233.5, width: 52, height: 150},
            {x: 141.5, y: 76.5, width: 52, height: 84}
        ]
        this.triangle =
        {
            centerX: 506,
            topY: 157,
            bottomY: 271,
            side: 557.962 - 454.038
        }
        this.blueSquare =
        {
            x: 480,
            y: 441,
            width: 51,
            height: 52
        }
        this.grapnelMarker =
        {
            segments:
            [
                [{x: 505.548, y: 473.803}, {x: 506.255, y: 384}],
                [{x: 506.255, y: 384}, {x: 534.539, y: 412.284}],
                [{x: 506.255, y: 384}, {x: 479.385, y: 410.87}]
            ],
            strokeWidth: 5
        }
    }
    displayToWorld(value)
    {
        return value / this.frameHeight * height / scale.bad
    }
    createFrameRect(rect, fill, stroke)
    {
        const result = super.create(
            this.displayToWorld(rect.x),
            this.displayToWorld(rect.y),
            this.displayToWorld(rect.width),
            this.displayToWorld(rect.height)
        )

        result.fill = fill
        result.stroke = stroke

        return result
    }
    createTriangle()
    {
        const triangle = this.triangle
        const worldHeight = this.displayToWorld(triangle.bottomY - triangle.topY)
        const model =
        {
            x       : this.displayToWorld(triangle.centerX),
            y       : this.displayToWorld(triangle.topY) + worldHeight / 3,
            radius  : worldHeight * 2 / 3,
            yMin    : 0.2 * height,
            yMax    : 2 * height,
            fill    : STYLE.colors.hazard.fill,
            stroke  : STYLE.colors.hazard.stroke
        }
        const result = new Triangle(model)

        result.side = this.displayToWorld(triangle.side)
        result.height = worldHeight
        result.track = (trackEnabled)?(new MultipointTrackLine(result.side, result.stroke, STYLE.timing.triangleTrailPoints)):(new Empty())
        result.track.addPos(result.getPoints(), true)

        return result
    }
    createGrapnelMarker()
    {
        return this.grapnelMarker.segments.map(segment =>
        {
            const start = segment[0]
            const end = segment[1]
            const x1 = this.displayToWorld(start.x)
            const y1 = this.displayToWorld(start.y)
            const x2 = this.displayToWorld(end.x)
            const y2 = this.displayToWorld(end.y)
            const dx = x2 - x1
            const dy = y2 - y1
            const length = Math.sqrt(dx * dx + dy * dy)
            const halfWidth = this.displayToWorld(this.grapnelMarker.strokeWidth) / 2
            const normalX = -dy / length * halfWidth
            const normalY = dx / length * halfWidth

            return new Trampoline(
            {
                x       : 0,
                y       : 0,
                points  :
                [
                    {x: x1 + normalX, y: y1 + normalY},
                    {x: x2 + normalX, y: y2 + normalY},
                    {x: x2 - normalX, y: y2 - normalY},
                    {x: x1 - normalX, y: y1 - normalY}
                ],
                fill    : 'black',
                stroke  : 'black'
            })
        })
    }
    create(x, y)
    {
        return [
            ...this.greenRects.map(rect =>
                this.createFrameRect(rect, STYLE.colors.cube.greenFill, STYLE.colors.cube.greenStroke)),
            this.createTriangle(),
            this.createFrameRect(this.blueSquare, STYLE.colors.cube.blueFill, STYLE.colors.cube.blueStroke),
            ...this.createGrapnelMarker()
        ]
    }
}
class Frame10ElementsFactory extends RectFactory
{
    constructor()
    {
        super()
        this.frameHeight = 630
        this.greenRect =
        {
            x: 119.5,
            y: 288.5,
            width: 397,
            height: 52
        }
        this.grayRects =
        [
            {x: 464.5, y: 427.5, width: 52, height: 126},
            {x: 464.5, y: 161.5, width: 52, height: 126}
        ]
    }
    displayToWorld(value)
    {
        return value / this.frameHeight * height / scale.bad
    }
    createFrameRect(rect, fill, stroke)
    {
        const result = super.create(
            this.displayToWorld(rect.x),
            this.displayToWorld(rect.y),
            this.displayToWorld(rect.width),
            this.displayToWorld(rect.height)
        )

        result.fill = fill
        result.stroke = stroke

        return result
    }
    create(x, y)
    {
        return [
            this.createFrameRect(this.greenRect, STYLE.colors.cube.greenFill, STYLE.colors.cube.greenStroke),
            ...this.grayRects.map(rect =>
                this.createFrameRect(rect, STYLE.colors.cube.grayFill, STYLE.colors.cube.grayStroke))
        ]
    }
}
class Frame11ElementsFactory extends RectFactory
{
    constructor()
    {
        super()
        this.frameHeight = 630
        this.greenRect =
        {
            x: 119.5,
            y: 288.5,
            width: 397,
            height: 52
        }
        this.grayRects =
        [
            {x: 464.5, y: 341.5, width: 52, height: 126},
            {x: 464.5, y: 75.5, width: 52, height: 126}
        ]
    }
    displayToWorld(value)
    {
        return value / this.frameHeight * height / scale.bad
    }
    createFrameRect(rect, fill, stroke)
    {
        const result = super.create(
            this.displayToWorld(rect.x),
            this.displayToWorld(rect.y),
            this.displayToWorld(rect.width),
            this.displayToWorld(rect.height)
        )

        result.fill = fill
        result.stroke = stroke

        return result
    }
    create(x, y)
    {
        return [
            this.createFrameRect(this.greenRect, STYLE.colors.cube.greenFill, STYLE.colors.cube.greenStroke),
            ...this.grayRects.map(rect =>
                this.createFrameRect(rect, STYLE.colors.cube.grayFill, STYLE.colors.cube.grayStroke))
        ]
    }
}
class TrampolineFactory
{
    constructor()
    {
        this.width = 
        {
            min: 0.3 * width,
            max: 0.4 * width
        }
        this.height =
        {
            min: 0.1 * height,
            max: 0.3 * height
        }
    }
    generatePoints()
    {
        let x   = random(this.width.min, this.width.max)
        let y1  = -random(this.height.min, this.height.max)
        let y2  = -random(this.height.min, this.height.max)
        
        let res = 
        [
            {x: 0,  y: 0    }, 
            {x: 0,  y: y1   },
            {x: x,  y: y2   },
            {x: x,  y: 0    }
        ]

        return res
    }
    create(x, y)
    {
        let model = {
            x       : random(x.min, x.max)  ,
            y       : y.max                 ,
            points  : this.generatePoints() ,
            fill    : STYLE.colors.cube.greenFill,
            stroke  : STYLE.colors.cube.greenStroke
        }

        
        return [new Trampoline(model)]
    }
}

class VerticalPairTrampolineFactory extends TrampolineFactory {
    constructor() {
        super()
        this.width =
        {
            min: 2 * width,
            max: 2.5 * width
        }
    }
    create(x, y) {
        let wayHeight = (y.max - y.min) * 4 / 8
        let rectHeight = random(0.25 * height, y.max - y.min - wayHeight - 0.1 * height)
        this.height.min = this.height.max = rectHeight

        let trampoline1 = super.create(x, y)[0]
        //return [trampoline1]
        let dt = -(y.max - (-trampoline1.y + wayHeight))

        let _x = trampoline1.points[2].x
        let _y = trampoline1.points[1].y// - wayHeight - rectHeight

        let points =
        [
            {x: 0,  y: 0 },
            {x: 0,  y: _y + dt   },
            {x: _x, y: _y + dt  },
            {x: _x, y: 0    }
        ]


        let model = {
            x       : trampoline1.x                         ,
            y       : trampoline1.y - wayHeight - rectHeight,
            points  : points                                ,
            fill    : STYLE.colors.cube.greenFill,
            stroke  : STYLE.colors.cube.greenStroke
        }

        let trampoline2 = new Trampoline(model)

        trampoline1.isPairElement = trampoline2.isPairElement = function() {return true}
        return [trampoline1, trampoline2]//[trampoline1, trampoline2]
        /*
        let model1 =
            [
                x, y.min, this.width, rectHeight,
            ]
        let model2 =
            [
                x, y.min + rectHeight + wayHeight,
                this.width, y.max - y.min - rectHeight - wayHeight
            ]

        return [super.create(...model1, function(){return true}), super.create(...model2, function(){return true})]*/
    }
}

class JumpingCubeFactory
{
    constructor()
    {
        this.width = 
        {
            min: 0.1 * width,
            max: 0.2 * width
        }
        this.height = 
        {
            min: 0.2 * height,
            max: 0.3 * height
        }
    }
    create(x, y, isOnMiddle)
    {
        let w = random(this.width.min, this.width.max)
        let model =
        {
            x       : random(x.min, x.max)  ,
            y       : y.min                 ,
            width   : w                     ,
            height  : w                     ,
            fill    : STYLE.colors.cube.blueFill,
            stroke  : STYLE.colors.cube.blueStroke
        }
        if (isOnMiddle)
            model.x -= model.width / 2
        return [new JumpingCube(model)]
    }
}
class JumpingCubeWithHorizontalTopRectFactory
{
    constructor()
    {
        
    }
    create(x, y)
    {
        let rect = elementsFactory.factories.horizontalTopRect.create(x, y)[0]
        
        let points = rect.getPoints()
        let yMin = points[0].y
        for (let i = 1; i < points.length; ++i)
        {
            if (points[i].y > yMin)
                yMin = points[i].y
        }
        
        x = 
        {
            min: (rect.getLeftPointX() + rect.getRightPointX()) / 2
        }
        x.max = x.min
        y.min = yMin
        
        
        let cube = elementsFactory.factories.jumpingCube.create(x, y, true)[0]
        let maxCubeSpeedY = Math.sqrt(2 * GRAVITY * (y.max - y.min - cube.height))
        cube.speedY = (cube.speedY > 0)?maxCubeSpeedY:-maxCubeSpeedY
        
        cube.isPairElement = function(){return true}
        
        return [cube, rect]
    }
}
class TriangleFactory
{
    constructor()
    {
        this.radius =  height * 0.25 / Math.sqrt(3)
    }
    getModel(x, y) {
        let yPositionMin = y.min + 0.01 * height
        let yPositionMax = y.max - 0.01 * height

        let yGenerateMin = yPositionMin + this.radius * 0.5
        let yGenerateMax = yPositionMax - this.radius

        return {
            x       : random(x.min, x.max) + this.radius * Math.sqrt(3)  ,
            y       : random(yGenerateMin, yGenerateMax)            ,
            radius  : this.radius                                   ,
            yMin    : yPositionMin                                  ,
            yMax    : yPositionMax                                  ,
            fill    : STYLE.colors.hazard.fill                      ,
            stroke  : STYLE.colors.hazard.stroke
        }
    }
    create(x, y)
    {
        let model = this.getModel(x, y)
        
        return [new Triangle(model)]
    }
}
class Frame3TriangleFactory extends TriangleFactory
{
    constructor()
    {
        super()
        this.displayCenterXRatio = 385.5 / 630
        this.displayCenterYRatio = (187.75 + (421 - 187.75) / 3) / 630
        this.displaySideRatio = (491.588 - 279.412) / 630
        this.displayHeightRatio = (421 - 187.75) / 630
        this.displayTopRatio = 187.75 / 630
        this.displayBottomRatio = 421 / 630
    }
    create(x, y)
    {
        const worldCenterX = this.displayCenterXRatio * height / scale.bad
        const worldCenterY = this.displayCenterYRatio * height / scale.bad
        const worldSide = this.displaySideRatio * height / scale.bad
        const worldHeight = this.displayHeightRatio * height / scale.bad
        const worldTop = this.displayTopRatio * height / scale.bad
        const worldBottom = this.displayBottomRatio * height / scale.bad
        const model =
        {
            x       : worldCenterX,
            y       : worldCenterY,
            radius  : worldHeight * 2 / 3,
            yMin    : worldTop,
            yMax    : worldBottom,
            fill    : STYLE.colors.hazard.fill,
            stroke  : STYLE.colors.hazard.stroke
        }
        const triangle = new Triangle(model)

        triangle.side = worldSide
        triangle.height = worldHeight
        triangle.track = (trackEnabled)?(new MultipointTrackLine(triangle.side, triangle.stroke, STYLE.timing.triangleTrailPoints)):(new Empty())
        triangle.track.addPos(triangle.getPoints(), true)

        return [triangle]
    }
}
class HarmlessTriangleFactory extends TriangleFactory {
    create(x, y) {
        let model = this.getModel(x, y)
        model.fill = STYLE.colors.hazard.harmlessFill
        model.stroke = STYLE.colors.hazard.harmlessStroke

        return [new HarmlessTriangle(model)]
    }
}
