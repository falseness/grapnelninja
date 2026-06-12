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
        const rect = super.create(worldX, worldY, worldWidth, worldHeight)

        rect.fill = STYLE.colors.cube.greenFill
        rect.stroke = STYLE.colors.cube.greenStroke

        return [rect]
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
    }
    create(x, y)
    {
        const worldCenterX = this.displayCenterXRatio * height / scale.bad
        const worldCenterY = this.displayCenterYRatio * height / scale.bad
        const worldSide = this.displaySideRatio * height / scale.bad
        const worldHeight = this.displayHeightRatio * height / scale.bad
        const model =
        {
            x       : worldCenterX,
            y       : worldCenterY,
            radius  : worldHeight * 2 / 3,
            yMin    : 0.2 * height,
            yMax    : 2 * height,
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
