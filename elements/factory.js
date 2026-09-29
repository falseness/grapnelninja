// Frame templates store screen percentages, before bad-mode camera zoom.
// Original SVG units used a 630-high canvas. At 1920x1080 its equivalent
// width is 1120 (1920 * 630 / 1080), preserving the original layout exactly.
const FRAME_REFERENCE = Object.freeze({width: 1120, height: 630})
function frameWidthPercent(percent) { return screenWidthPercent(percent) / scale.bad }
function frameHeightPercent(percent) { return screenHeightPercent(percent) / scale.bad }

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
        this.widthPercent = 100 * (52 / FRAME_REFERENCE.width)
        this.topHeightPercent = 100 * (164.5 / FRAME_REFERENCE.height)
        this.heightPercent = 100 * (266 / FRAME_REFERENCE.height)
    }
    create(x, y)
    {
        const worldWidth = frameWidthPercent(this.widthPercent)
        const worldHeight = frameHeightPercent(this.heightPercent)
        const worldX = (width / scale.bad - worldWidth) / 2
        const worldY = frameHeightPercent(this.topHeightPercent)
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
        this.verticalRects =
        [
            {
                // Doubled gap after the horizontal segment (ends at ~573.47).
                x: 100 * (688.5 + 115.03) / FRAME_REFERENCE.width,
                y: 100 * 76.5 / FRAME_REFERENCE.height,
                width: 100 * 52 / FRAME_REFERENCE.width,
                height: 100 * 266 / FRAME_REFERENCE.height
            },
            {
                x: 100 * 333.5 / FRAME_REFERENCE.width,
                y: 100 * 188.5 / FRAME_REFERENCE.height,
                width: 100 * 52 / FRAME_REFERENCE.width,
                height: 100 * 365 / FRAME_REFERENCE.height
            }
        ]
        this.horizontalRect =
        {
            x: 100 * 386.935 / FRAME_REFERENCE.width,
            y: 100 * 232.654 / FRAME_REFERENCE.height,
            width: 100 * 42.9148 / FRAME_REFERENCE.height,
            height: 100 * 186.553 / FRAME_REFERENCE.height,
            rotation: -90.5738
        }
    }
    createGreenTrampolineRect(rect)
    {
        const worldWidth = frameWidthPercent(rect.width)
        const worldHeight = frameHeightPercent(rect.height)
        const model =
        {
            x       : frameWidthPercent(rect.x),
            y       : frameHeightPercent(rect.y),
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
        // Rotate local height percentages uniformly, then add the W/H position.
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
                x: frameWidthPercent(rect.x) + frameHeightPercent(point.x * cos - point.y * sin),
                y: frameHeightPercent(rect.y + point.x * sin + point.y * cos)
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
        this.rects =
        [
            {
                x: 100 * 359.5 / FRAME_REFERENCE.width,
                y: 100 * 76.5 / FRAME_REFERENCE.height,
                width: 100 * 52 / FRAME_REFERENCE.width,
                height: 100 * 106 / FRAME_REFERENCE.height
            },
            {
                x: 100 * 359.5 / FRAME_REFERENCE.width,
                y: 100 * 381.5 / FRAME_REFERENCE.height,
                width: 100 * 52 / FRAME_REFERENCE.width,
                height: 100 * 172 / FRAME_REFERENCE.height
            }
        ]
    }
    createFrameRect(rect)
    {
        return super.create(
            frameWidthPercent(rect.x),
            frameHeightPercent(rect.y),
            frameWidthPercent(rect.width),
            frameHeightPercent(rect.height)
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
        this.greenSegment =
        {
            x: 100 * 252 / FRAME_REFERENCE.width,
            y: 100 * 331 / FRAME_REFERENCE.height,
            width: 100 * 53 / FRAME_REFERENCE.height,
            height: 100 * 267 / FRAME_REFERENCE.height,
            rotation: -90
        }
        this.blueSquare =
        {
            x: 100 * 368 / FRAME_REFERENCE.width,
            y: 100 * 165 / FRAME_REFERENCE.height,
            width: 100 * 51 / FRAME_REFERENCE.width,
            height: 100 * 52 / FRAME_REFERENCE.height
        }
        this.triangle =
        {
            centerX: 100 * 386 / FRAME_REFERENCE.width,
            topY: 100 * 388 / FRAME_REFERENCE.height,
            bottomY: 100 * 502 / FRAME_REFERENCE.height,
            side: 100 * (437.962 - 334.038) / FRAME_REFERENCE.height
        }
    }
    createGreenSegment()
    {
        const rect = this.greenSegment
        const angle = rect.rotation * Math.PI / 180
        const cos = Math.cos(angle)
        const sin = Math.sin(angle)
        // Rotate local height percentages uniformly, then add the W/H position.
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
                x: frameWidthPercent(rect.x) + frameHeightPercent(point.x * cos - point.y * sin),
                y: frameHeightPercent(rect.y + point.x * sin + point.y * cos)
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
        const x = frameWidthPercent(rect.x)
        const y = frameHeightPercent(rect.y)
        const result = new JumpingCube(
        {
            x       : x,
            y       : y,
            width   : frameWidthPercent(rect.width),
            height  : frameHeightPercent(rect.height),
            fill    : STYLE.colors.cube.blueFill,
            stroke  : STYLE.colors.cube.blueStroke
        })

        // Undo constructor warm-up steps run before the green segment existed.
        result.x = x
        result.y = y
        result.speedY = 0
        result.track.pos = []
        result.track.addPos(result.x + result.circle.x, result.y, true)

        return result
    }
    createTriangle(y)
    {
        const triangle = this.triangle
        const worldHeight = frameHeightPercent(triangle.bottomY - triangle.topY)
        const model =
        {
            x       : frameWidthPercent(triangle.centerX),
            y       : frameHeightPercent(triangle.topY) + worldHeight / 3,
            radius  : worldHeight * 2 / 3,
            // Stay below the horizontal trampoline, with the master factory clearance.
            yMin    : frameHeightPercent(this.greenSegment.y) + 0.01 * height,
            yMax    : y.max - 0.01 * height,
            fill    : STYLE.colors.hazard.fill,
            stroke  : STYLE.colors.hazard.stroke
        }
        const result = new Triangle(model)

        result.side = frameHeightPercent(triangle.side)
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
            this.createTriangle(y)
        ]
    }
}
class Frame7ElementsFactory extends RectFactory
{
    constructor()
    {
        super()
        this.launchArcHeightPercent = 100 * 60 / FRAME_REFERENCE.height
        this.greenRect =
        {
            x: 100 * 285.5 / FRAME_REFERENCE.width,
            y: 100 * 381.5 / FRAME_REFERENCE.height,
            width: 100 * 206 / FRAME_REFERENCE.width,
            height: 100 * 141 / FRAME_REFERENCE.height
        }
        this.blueSquare =
        {
            x: 100 * 363 / FRAME_REFERENCE.width,
            y: 100 * 207 / FRAME_REFERENCE.height,
            width: 100 * 51 / FRAME_REFERENCE.width,
            height: 100 * 52 / FRAME_REFERENCE.height
        }
    }
    createGreenRect()
    {
        const rect = this.greenRect
        const worldWidth = frameWidthPercent(rect.width)
        const worldHeight = frameHeightPercent(rect.height)

        return new Trampoline(
        {
            x       : frameWidthPercent(rect.x),
            y       : frameHeightPercent(rect.y),
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
        const x = frameWidthPercent(rect.x)
        const y = frameHeightPercent(rect.y)
        const width = frameWidthPercent(rect.width)
        const height = frameHeightPercent(rect.height)
        const result = new JumpingCube(
        {
            x       : x,
            y       : y,
            width   : width,
            height  : height,
            fill    : STYLE.colors.cube.blueFill,
            stroke  : STYLE.colors.cube.blueStroke
        })

        result.x = x
        result.y = y
        // Height-based launch arc uses the existing gravity.
        result.speedY = -Math.sqrt(2 * GRAVITY * frameHeightPercent(this.launchArcHeightPercent))
        result.track.pos = []
        result.track.addPos(result.x + result.circle.x, result.y, true)

        return result
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
        this.grayRect =
        {
            // Doubled gap after the left green rect.
            x: 100 * (333.5 + 135) / FRAME_REFERENCE.width,
            y: 100 * 243.5 / FRAME_REFERENCE.height,
            width: 100 * 52 / FRAME_REFERENCE.width,
            height: 100 * 172 / FRAME_REFERENCE.height
        }
        this.greenRects =
        [
            {
                x: 100 * 146.5 / FRAME_REFERENCE.width,
                y: 100 * 181.5 / FRAME_REFERENCE.height,
                width: 100 * 52 / FRAME_REFERENCE.width,
                height: 100 * 266 / FRAME_REFERENCE.height
            },
            {
                x: 100 * (516.5 + 135 + 131) / FRAME_REFERENCE.width,
                y: 100 * 416.5 / FRAME_REFERENCE.height,
                width: 100 * 52 / FRAME_REFERENCE.width,
                height: 100 * 137 / FRAME_REFERENCE.height
            },
            {
                x: 100 * (516.5 + 135 + 131) / FRAME_REFERENCE.width,
                y: 100 * 76.5 / FRAME_REFERENCE.height,
                width: 100 * 52 / FRAME_REFERENCE.width,
                height: 100 * 137 / FRAME_REFERENCE.height
            }
        ]
    }
    createFrameRect(rect, fill, stroke)
    {
        const result = super.create(
            frameWidthPercent(rect.x),
            frameHeightPercent(rect.y),
            frameWidthPercent(rect.width),
            frameHeightPercent(rect.height)
        )

        result.fill = fill
        result.stroke = stroke

        return result
    }
    createGreenTrampolineRect(rect)
    {
        const worldWidth = frameWidthPercent(rect.width)
        const worldHeight = frameHeightPercent(rect.height)

        return new Trampoline(
        {
            x       : frameWidthPercent(rect.x),
            y       : frameHeightPercent(rect.y),
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
    create(x, y)
    {
        return [
            this.createFrameRect(this.grayRect, STYLE.colors.cube.grayFill, STYLE.colors.cube.grayStroke),
            ...this.greenRects.map(rect => this.createGreenTrampolineRect(rect))
        ]
    }
}
class Frame9ElementsFactory extends RectFactory
{
    constructor()
    {
        super()
        this.launchArcHeightPercent = 100 * 60 / FRAME_REFERENCE.height
        this.greenRects =
        [
            {
                x: 100 * 141.5 / FRAME_REFERENCE.width,
                y: 100 * 444.5 / FRAME_REFERENCE.height,
                width: 100 * 52 / FRAME_REFERENCE.width,
                height: 100 * 109 / FRAME_REFERENCE.height
            },
            {
                x: 100 * 141.5 / FRAME_REFERENCE.width,
                y: 100 * 233.5 / FRAME_REFERENCE.height,
                width: 100 * 52 / FRAME_REFERENCE.width,
                height: 100 * 150 / FRAME_REFERENCE.height
            },
            {
                x: 100 * 141.5 / FRAME_REFERENCE.width,
                y: 100 * 76.5 / FRAME_REFERENCE.height,
                width: 100 * 52 / FRAME_REFERENCE.width,
                height: 100 * 84 / FRAME_REFERENCE.height
            }
        ]
        this.triangle =
        {
            // Doubled gap after the green column (triangle left edge 454.038).
            centerX: 100 * (506 + 260.538) / FRAME_REFERENCE.width,
            topY: 100 * 157 / FRAME_REFERENCE.height,
            bottomY: 100 * 271 / FRAME_REFERENCE.height,
            side: 100 * (557.962 - 454.038) / FRAME_REFERENCE.height
        }
        this.blueSquare =
        {
            x: 100 * (480 + 260.538) / FRAME_REFERENCE.width,
            y: 100 * 441 / FRAME_REFERENCE.height,
            width: 100 * 51 / FRAME_REFERENCE.width,
            height: 100 * 52 / FRAME_REFERENCE.height
        }
    }
    createFrameRect(rect, fill, stroke)
    {
        const result = super.create(
            frameWidthPercent(rect.x),
            frameHeightPercent(rect.y),
            frameWidthPercent(rect.width),
            frameHeightPercent(rect.height)
        )

        result.fill = fill
        result.stroke = stroke

        return result
    }
    createGreenTrampolineRect(rect)
    {
        const worldWidth = frameWidthPercent(rect.width)
        const worldHeight = frameHeightPercent(rect.height)

        return new Trampoline(
        {
            x       : frameWidthPercent(rect.x),
            y       : frameHeightPercent(rect.y),
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
        const x = frameWidthPercent(rect.x)
        const y = frameHeightPercent(rect.y)
        const width = frameWidthPercent(rect.width)
        const height = frameHeightPercent(rect.height)
        const result = new JumpingCube(
        {
            x       : x,
            y       : y,
            width   : width,
            height  : height,
            fill    : STYLE.colors.cube.blueFill,
            stroke  : STYLE.colors.cube.blueStroke
        })

        result.x = x
        result.y = y
        // Height-based launch arc uses the existing gravity.
        result.speedY = -Math.sqrt(2 * GRAVITY * frameHeightPercent(this.launchArcHeightPercent))
        result.track.pos = []
        result.track.addPos(result.x + result.circle.x, result.y, true)

        return result
    }
    createTriangle(y)
    {
        const triangle = this.triangle
        const worldHeight = frameHeightPercent(triangle.bottomY - triangle.topY)
        const model =
        {
            x       : frameWidthPercent(triangle.centerX),
            y       : frameHeightPercent(triangle.topY) + worldHeight / 3,
            radius  : worldHeight * 2 / 3,
            // Move above the initial footprint, away from the cube below.
            yMin    : y.min + 0.01 * height,
            yMax    : frameHeightPercent(triangle.bottomY),
            fill    : STYLE.colors.hazard.fill,
            stroke  : STYLE.colors.hazard.stroke
        }
        const result = new Triangle(model)

        result.side = frameHeightPercent(triangle.side)
        result.height = worldHeight
        result.track = (trackEnabled)?(new MultipointTrackLine(result.side, result.stroke, STYLE.timing.triangleTrailPoints)):(new Empty())
        result.track.addPos(result.getPoints(), true)

        return result
    }
    create(x, y)
    {
        return [
            ...this.greenRects.map(rect => this.createGreenTrampolineRect(rect)),
            this.createTriangle(y),
            this.createBlueSquare()
        ]
    }
}
class Frame10ElementsFactory extends RectFactory
{
    constructor()
    {
        super()
        this.greenRect =
        {
            x: 100 * 119.5 / FRAME_REFERENCE.width,
            y: 100 * 288.5 / FRAME_REFERENCE.height,
            width: 100 * 397 / FRAME_REFERENCE.width,
            height: 100 * 52 / FRAME_REFERENCE.height
        }
        this.grayRects =
        [
            {
                x: 100 * 464.5 / FRAME_REFERENCE.width,
                y: 100 * 427.5 / FRAME_REFERENCE.height,
                width: 100 * 52 / FRAME_REFERENCE.width,
                height: 100 * 126 / FRAME_REFERENCE.height
            },
            {
                x: 100 * 464.5 / FRAME_REFERENCE.width,
                y: 100 * 161.5 / FRAME_REFERENCE.height,
                width: 100 * 52 / FRAME_REFERENCE.width,
                height: 100 * 126 / FRAME_REFERENCE.height
            }
        ]
    }
    createFrameRect(rect, fill, stroke)
    {
        const result = super.create(
            frameWidthPercent(rect.x),
            frameHeightPercent(rect.y),
            frameWidthPercent(rect.width),
            frameHeightPercent(rect.height)
        )

        result.fill = fill
        result.stroke = stroke

        return result
    }
    createGreenTrampolineRect(rect)
    {
        const worldWidth = frameWidthPercent(rect.width)
        const worldHeight = frameHeightPercent(rect.height)

        return new Trampoline(
        {
            x       : frameWidthPercent(rect.x),
            y       : frameHeightPercent(rect.y),
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
    create(x, y)
    {
        return [
            this.createGreenTrampolineRect(this.greenRect),
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
        this.greenRect =
        {
            x: 100 * 119.5 / FRAME_REFERENCE.width,
            y: 100 * 288.5 / FRAME_REFERENCE.height,
            width: 100 * 397 / FRAME_REFERENCE.width,
            height: 100 * 52 / FRAME_REFERENCE.height
        }
        this.grayRects =
        [
            {
                x: 100 * 464.5 / FRAME_REFERENCE.width,
                y: 100 * 341.5 / FRAME_REFERENCE.height,
                width: 100 * 52 / FRAME_REFERENCE.width,
                height: 100 * 126 / FRAME_REFERENCE.height
            },
            {
                x: 100 * 464.5 / FRAME_REFERENCE.width,
                y: 100 * 75.5 / FRAME_REFERENCE.height,
                width: 100 * 52 / FRAME_REFERENCE.width,
                height: 100 * 126 / FRAME_REFERENCE.height
            }
        ]
    }
    createFrameRect(rect, fill, stroke)
    {
        const result = super.create(
            frameWidthPercent(rect.x),
            frameHeightPercent(rect.y),
            frameWidthPercent(rect.width),
            frameHeightPercent(rect.height)
        )

        result.fill = fill
        result.stroke = stroke

        return result
    }
    createGreenTrampolineRect(rect)
    {
        const worldWidth = frameWidthPercent(rect.width)
        const worldHeight = frameHeightPercent(rect.height)

        return new Trampoline(
        {
            x       : frameWidthPercent(rect.x),
            y       : frameHeightPercent(rect.y),
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
    create(x, y)
    {
        return [
            this.createGreenTrampolineRect(this.greenRect),
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
        this.centerWidthPercent = 100 * 385.5 / FRAME_REFERENCE.width
        this.centerHeightPercent = 100 * ((187.75 + (421 - 187.75) / 3)) / FRAME_REFERENCE.height
        // Triangle side/radius keep one height scale for their collision shape.
        this.sideHeightPercent = 100 * ((491.588 - 279.412)) / FRAME_REFERENCE.height
        this.heightPercent = 100 * ((421 - 187.75)) / FRAME_REFERENCE.height
        this.topHeightPercent = 100 * 187.75 / FRAME_REFERENCE.height
        this.bottomHeightPercent = 100 * 421 / FRAME_REFERENCE.height
    }
    create(x, y)
    {
        const worldCenterX = frameWidthPercent(this.centerWidthPercent)
        const worldCenterY = frameHeightPercent(this.centerHeightPercent)
        const worldSide = frameHeightPercent(this.sideHeightPercent)
        const worldHeight = frameHeightPercent(this.heightPercent)
        const model =
        {
            x       : worldCenterX,
            y       : worldCenterY,
            radius  : worldHeight * 2 / 3,
            yMin    : y.min + 0.01 * height,
            yMax    : y.max - 0.01 * height,
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
