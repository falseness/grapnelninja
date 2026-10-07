class Floor
{
    constructor(topBorder, bottomBorder, elementsIntervalX, creations, primaryElementsQuantity)
    {
        this.bottom             = bottomBorder
        this.top                = topBorder

        this.creations          = creations
        this.elementsIntervalX  = elementsIntervalX
        this.primaryElementsQuantity = primaryElementsQuantity || 8

        this.elements           = []
        this.nextGenerationGroupId = 0
    }
    // Live viewport resize: existing elements stay, new spawn spacing follows the new width.
    rescaleSpacing(ratio)
    {
        this.elementsIntervalX = {min: this.elementsIntervalX.min * ratio, max: this.elementsIntervalX.max * ratio}
    }
    generatePrimaryElements()
    {
        if (version == 'bad' && this.primaryElementsQuantity == 1)
        {
            this.elements = []
            this.nextGenerationGroupId = 0
        }
        const firstPrimaryElementX      = 0.2 * width
        const primaryElementsQuantity   = this.primaryElementsQuantity

        let nextElementX                = firstPrimaryElementX

        for (let i = 0; i < primaryElementsQuantity; ++i)
        {
            this.generateElements(nextElementX)
            try
            {
            nextElementX = this.elements[this.elements.length - 1].getRightPointX()
            }
            catch(e)
            {
                console.log('err')
            }
        }
        this.replenishElements()
    }
    replenishElements()
    {
        if (version != 'bad' || this.primaryElementsQuantity != 1)
            return

        const viewportWidth = width / scale.bad
        const targetRight = -screen.x + 2 * viewportWidth
        let right = this.elements.length
            ? this.getGenerationGroup(this.elements.length - 1).rightPointX : 0.2 * width
        while (right < targetRight)
        {
            if (!this.generateElements(right))
                break
            right = this.getGenerationGroup(this.elements.length - 1).rightPointX
        }
    }
    generateElements(x)
    {
        // Bad mode draws an integer ticket below the total integer weight and
        // compares against exclusive bounds, so equal weights are exactly equal.
        // Math.random() * total can round up to total, hence the clamp.
        const exclusiveBounds = version == 'bad' && this.primaryElementsQuantity == 1
        const totalChance = this.creations.reduce((sum, creation) => sum + creation.chance, 0)
        let num = exclusiveBounds ? Math.min(random(0, totalChance), totalChance - 1) : random()

        let sumChances = 0
        for (let i = 0; i < this.creations.length; ++i)
        {
            const bound = this.creations[i].chance + sumChances
            if (exclusiveBounds ? num < bound : num <= bound)
            {
                const generatedElements = elementsFactory.create(
                    {min: x + this.elementsIntervalX.min, max: x + this.elementsIntervalX.max},
                    {min: this.top, max: this.bottom}   , this.creations[i].type)
                this.alignBadVersionGeneratedElements(generatedElements, x)
                const generationGroupId = this.nextGenerationGroupId++

                for (let j = 0; j < generatedElements.length; ++j)
                {
                    generatedElements[j].generationGroupId = generationGroupId
                }

                this.elements.push(...generatedElements)

                return generatedElements.length
            }
            sumChances += this.creations[i].chance
        }
        console.log('generation element on floor error')
        return 0
    }
    alignBadVersionGeneratedElements(generatedElements, nextElementX)
    {
        if (version != 'bad' || this.primaryElementsQuantity != 1)
            return

        const firstPrimaryElementX = 0.2 * width
        let offsetX = nextElementX + this.elementsIntervalX.min - firstPrimaryElementX
        if (this.nextGenerationGroupId > 0 && generatedElements.length)
        {
            const leftPointX = Math.min(...generatedElements.map(element => element.getLeftPointX()))
            // The last member need not be the rightmost member of its frame.
            // If deletion emptied the queue, nextElementX carries that group's bound.
            const precedingRightX = this.elements.length
                ? this.getGenerationGroup(this.elements.length - 1).rightPointX : nextElementX
            offsetX = precedingRightX + random(0.20 * width / scale.bad, 0.30 * width / scale.bad) - leftPointX
        }

        if (!offsetX)
            return

        for (let i = 0; i < generatedElements.length; ++i)
        {
            generatedElements[i].x += offsetX
            this.resetElementTrack(generatedElements[i])
        }
    }
    resetElementTrack(element)
    {
        if (!element.track || !element.track.pos || !element.getPoints)
            return

        element.track.pos = []
        if (element instanceof JumpingCube)
            element.track.addPos(element.x + element.circle.x, element.y + element.circle.y, true)
        else
            element.track.addPos(element.getPoints(), true)
    }
    getGenerationGroup(index)
    {
        const element = this.elements[index]
        const generationGroupId = element.generationGroupId
        let rightPointX = element.getRightPointX()
        let indexes = []

        for (let i = 0; i < this.elements.length; ++i)
        {
            if (this.elements[i].generationGroupId != generationGroupId)
                continue

            rightPointX = Math.max(rightPointX, this.elements[i].getRightPointX())
            indexes.push(i)
        }

        return {indexes, rightPointX}
    }
    // getGenerationGroup(index).rightPointX without the index list, for the
    // per-step scan in deleteElements
    getGenerationGroupRightPointX(index)
    {
        const generationGroupId = this.elements[index].generationGroupId
        let rightPointX = this.elements[index].getRightPointX()

        for (let i = 0; i < this.elements.length; ++i)
        {
            if (this.elements[i].generationGroupId == generationGroupId)
                rightPointX = Math.max(rightPointX, this.elements[i].getRightPointX())
        }

        return rightPointX
    }
    markGenerationGroupScored(indexes)
    {
        for (let i = 0; i < indexes.length; ++i)
        {
            this.elements[indexes[i]].scored = true
        }
    }
    deleteElements()
    {
        let newElements = 0
        for (let i = 0; i < this.elements.length - newElements; ++i)
        {
            // The group reaches at least as far right as the element, so an
            // element past both borders needs no group scan
            const ownRightX = this.elements[i].getRightPointX() + screen.x
            if (ownRightX >= 0 && ownRightX >= screen.getDeletionBorder())
                continue

            const rightPointX = this.getGenerationGroupRightPointX(i)

            if (!this.elements[i].scored &&
                rightPointX + screen.x < 0)
            {
                const group = this.getGenerationGroup(i)
                this.markGenerationGroupScored(group.indexes)

                changeScoreText()
            }
            else if (rightPointX + screen.x < screen.getDeletionBorder())
            {
                const group = this.getGenerationGroup(i)
                let nextElementX = group.rightPointX
                this.elements = this.elements.filter(function(element, index)
                {
                    return group.indexes.indexOf(index) == -1
                })

                for (const element of this.elements)
                    nextElementX = Math.max(nextElementX, element.getRightPointX())

                if (version != 'bad' || this.primaryElementsQuantity != 1)
                    newElements += this.generateElements(nextElementX)

                --i
            }
        }
    }
    moveElements()
    {
        for (let i = 0; i < this.elements.length; ++i)
        {
            this.elements[i].move()
        }
    }
    draw()
    {
        const cullRect = getCullRect()
        for (let i = 0; i < this.elements.length; ++i)
        {
            const element = this.elements[i]
            if (isCullBoxVisible(getElementCullBox(element), cullRect))
                element.draw()
            else if (element.syncTrackStyle)
                element.syncTrackStyle()
        }
    }
    drawGlow()
    {
        const cullRect = getCullRect()
        for (let i = 0; i < this.elements.length; ++i)
        {
            const element = this.elements[i]
            if (isCullBoxVisible(getElementCullBox(element), cullRect))
                element.drawGlow()
        }
    }
    drawExtrusions()
    {
        const cullRect = getCullRect()
        for (let i = 0; i < this.elements.length; ++i)
        {
            const element = this.elements[i]
            if (element.drawExtrusion && isCullBoxVisible(getElementCullBox(element), cullRect))
                element.drawExtrusion()
        }
    }
    drawTracks()
    {
        if (trackEnabled)
        {
            const cullRect = getCullRect()
            for (let i = 0; i < this.elements.length; ++i)
            {
                const track = this.elements[i].track
                if (isCullBoxVisible(getTrackCullBox(track), cullRect))
                    track.draw()
            }
        }
    }
}
// Glow sprite builders (drawGlowRect) of the ground strips: the only shadowBlur here
function drawBadGroundGlowRect(x, y, w, h)
{
    const obstacleStyle = STYLE.badVersionEffects.obstacles
    drawGlowRect('bad-ground', x, y, w, h, obstacleStyle.thinStrokeWidth, obstacleStyle.outerGlowWidth,
        strokeBadGroundRect)
}
function drawClassicGroundGlowRect(x, y, w, h)
{
    drawGlowRect('classic-ground', x, y, w, h, STYLE.strokes.neonWidth, STYLE.strokes.neonGlowWidth,
        strokeClassicGroundRect)
}
function drawClassicShellGlowRect(x, y, w, h)
{
    drawGlowRect('classic-shell', x, y, w, h, Math.max(1, STYLE.strokes.neonWidth) + STYLE.strokes.neonWidth,
        STYLE.strokes.neonGlowWidth, drawClassicGroundShell)
}
// Run start (warmGlowSprites): a strip larger than the sprite core
function warmGroundGlowSprites()
{
    if (version == 'bad')
        drawBadGroundGlowRect(0, 0, height, height)
    else
    {
        drawClassicGroundGlowRect(0, 0, height, height)
        drawClassicShellGlowRect(0, 0, height, height)
    }
}
function strokeBadGroundRect(x, y, w, h)
{
    const obstacleStyle = STYLE.badVersionEffects.obstacles
    ctx.strokeStyle = obstacleStyle.groundStroke
    ctx.lineWidth = obstacleStyle.thinStrokeWidth
    ctx.globalAlpha = obstacleStyle.groundFillAlpha
    ctx.shadowColor = obstacleStyle.groundLine
    ctx.shadowBlur = obstacleStyle.outerGlowWidth
    ctx.strokeRect(x, y, w, h)
}
function strokeClassicGroundRect(x, y, w, h)
{
    ctx.strokeStyle = STYLE.colors.ground.stroke
    ctx.lineWidth = STYLE.strokes.neonWidth
    ctx.shadowColor = STYLE.colors.ground.line
    ctx.shadowBlur = STYLE.strokes.neonGlowWidth
    ctx.strokeRect(x, y, w, h)
}
function drawClassicGroundShell(x, y, w, h)
{
    const bar = Math.max(1, STYLE.strokes.neonWidth)
    ctx.strokeStyle = STYLE.colors.ground.line
    ctx.lineWidth = STYLE.strokes.neonWidth
    ctx.globalAlpha = 0.58
    ctx.shadowColor = STYLE.colors.ground.line
    ctx.shadowBlur = STYLE.strokes.neonGlowWidth
    ctx.strokeRect(x, y, w, h)

    ctx.globalAlpha = 0.2
    ctx.fillStyle = STYLE.colors.ground.line
    ctx.fillRect(x, y, w, bar)
    ctx.fillRect(x, y + h - bar, w, bar)
}
class SideFloor extends Floor
{
    constructor(bottomBorder, topBorder, creations)
    {
        super(bottomBorder, topBorder, {min: 0, max: 0}, creations)

        this.leftPointX = screen.getDeletionBorder()
    }
    generatePrimaryElements()
    {
        const firstPrimaryElementX      = this.leftPointX
        const primaryElementsQuantity   = 6

        let nextElementX                = firstPrimaryElementX

        for (let i = 0; i < primaryElementsQuantity; ++i)
        {
            this.generateElements(nextElementX)
            let t = this.elements[this.elements.length - 1]
            nextElementX = t.getRightPointX()
        }
        this.replenishElements()
    }
    replenishElements()
    {
        // Obstacles are generated up to 2 viewports ahead and a group can stick
        // out by up to one more, so the surface must reach 3 viewports ahead;
        // otherwise cubes spawned past its end fall out of the world.
        const targetRight = -screen.x + 3 * width / scale[version]
        while (this.elements[this.elements.length - 1].getRightPointX() < targetRight)
        {
            this.generateElements(this.elements[this.elements.length - 1].getRightPointX())
        }
    }
    deleteElements()
    {
        if (this.elements[0].getRightPointX() + screen.x < this.leftPointX)
        {
            this.elements.splice(0, 1)
            this.generateElements(this.elements[this.elements.length - 1].getRightPointX())
        }
    }
    moveElements()
    {

    }
    draw()
    {
        if (!this.elements.length)
            return

        if (version == 'bad' && this.elements[0].isInHudClearZone && this.elements[0].isInHudClearZone())
        {
            this.drawHudZoneCeilingBoundary()
            return
        }

        this.drawContinuousSurface()
    }
    // Bloom pass: only the boundary line of the strip glows
    drawGlow()
    {
        if (!this.elements.length)
            return

        const bounds = this.getContinuousSurfaceBounds()
        if (version == 'bad')
            this.drawContinuousNeonBoundary(bounds)
        else
            this.drawClassicContinuousBoundary(bounds)
    }
    getContinuousSurfaceBounds()
    {
        let left = this.elements[0].getLeftPointX()
        let right = this.elements[0].getRightPointX()
        let top = Infinity
        let bottom = -Infinity
        let boundaryY = 0

        for (let i = 0; i < this.elements.length; ++i)
        {
            const element = this.elements[i]
            left = Math.min(left, element.getLeftPointX())
            right = Math.max(right, element.getRightPointX())

            const points = element.getPoints()
            for (let j = 0; j < points.length; ++j)
            {
                top = Math.min(top, points[j].y)
                bottom = Math.max(bottom, points[j].y)
            }
        }

        if (top > height / 2)
            boundaryY = top
        else
            boundaryY = bottom

        return {left, right, top, bottom, boundaryY}
    }
    drawContinuousSurface()
    {
        if (version != 'bad')
        {
            this.drawClassicContinuousSurface()
            return
        }

        const bounds = this.getContinuousSurfaceBounds()
        const obstacleStyle = STYLE.badVersionEffects.obstacles
        const x = bounds.left + screen.x
        const y = bounds.top + screen.y
        const surfaceWidth = bounds.right - bounds.left
        const surfaceHeight = bounds.bottom - bounds.top
        const boundaryY = bounds.boundaryY + screen.y
        const capHeight = Math.max(2, screenHeightPercent(STYLE.spriteGeometry.capHeightPercent))
        const isLowerSurface = bounds.boundaryY == bounds.top
        const capY = isLowerSurface ? boundaryY : boundaryY - capHeight

        ctx.save()
        ctx.fillStyle = obstacleStyle.groundFill
        ctx.fillRect(x, y, surfaceWidth, surfaceHeight)

        ctx.fillStyle = obstacleStyle.groundCapFill
        ctx.fillRect(x, capY, surfaceWidth, capHeight)

        drawBadGroundGlowRect(x, y, surfaceWidth, surfaceHeight)
        ctx.restore()

        this.drawContinuousNeonBoundary(bounds)
    }
    drawClassicContinuousSurface()
    {
        const bounds = this.getContinuousSurfaceBounds()
        const x = bounds.left + screen.x
        const y = bounds.top + screen.y
        const surfaceWidth = bounds.right - bounds.left
        const surfaceHeight = bounds.bottom - bounds.top

        ctx.save()
        ctx.fillStyle = STYLE.colors.ground.fill
        ctx.fillRect(x, y, surfaceWidth, surfaceHeight)

        drawClassicGroundGlowRect(x, y, surfaceWidth, surfaceHeight)
        ctx.restore()

        this.drawClassicSurfaceShell(bounds)
        this.drawClassicContinuousBoundary(bounds)
    }
    drawClassicSurfaceShell(bounds)
    {
        const x = bounds.left + screen.x
        const y = bounds.top + screen.y
        const surfaceWidth = bounds.right - bounds.left
        const surfaceHeight = bounds.bottom - bounds.top
        const inset = Math.max(STYLE.strokes.neonGlowWidth, surfaceHeight * STYLE.badVersionEffects.obstacles.innerCopyInsetRatio)
        const shellWidth = Math.max(0, surfaceWidth - inset * 2)
        const shellHeight = Math.max(0, surfaceHeight - inset * 2)

        if (shellWidth <= 0 || shellHeight <= 0)
            return

        drawClassicShellGlowRect(x + inset, y + inset, shellWidth, shellHeight)
    }
    drawClassicContinuousBoundary(bounds)
    {
        const y = bounds.boundaryY + screen.y

        ctx.save()
        ctx.beginPath()

        ctx.moveTo(bounds.left + screen.x, y)
        ctx.lineTo(bounds.right + screen.x, y)
        strokeNeonPath(STYLE.colors.ground.stroke)

        ctx.restore()
    }
    drawContinuousNeonBoundary(bounds)
    {
        const obstacleStyle = STYLE.badVersionEffects.obstacles
        const y = bounds.boundaryY + screen.y

        ctx.save()
        ctx.beginPath()

        ctx.moveTo(bounds.left + screen.x, y)
        ctx.lineTo(bounds.right + screen.x, y)
        strokeNeonPath(obstacleStyle.groundStroke)

        ctx.restore()
    }
    drawHudZoneCeilingBoundary()
    {
        const bounds = this.getContinuousSurfaceBounds()
        const obstacleStyle = STYLE.badVersionEffects.obstacles
        const x = bounds.left + screen.x
        const y = bounds.boundaryY + screen.y
        const surfaceY = bounds.top + screen.y
        const surfaceWidth = bounds.right - bounds.left
        const surfaceHeight = bounds.bottom - bounds.top
        const capHeight = Math.max(2, screenHeightPercent(STYLE.spriteGeometry.capHeightPercent))

        ctx.save()
        ctx.fillStyle = obstacleStyle.groundFill
        ctx.fillRect(x, surfaceY, surfaceWidth, surfaceHeight)

        ctx.fillStyle = obstacleStyle.groundCapFill
        ctx.fillRect(x, y - capHeight, surfaceWidth, capHeight)

        ctx.beginPath()

        ctx.moveTo(bounds.left + screen.x, y)
        ctx.lineTo(bounds.right + screen.x, y)
        strokeNeonPath(obstacleStyle.groundStroke)

        ctx.restore()
    }
}
