// Momentum: camera-owned boundary on the vertical side of the view left
// behind by the last shaft the ninja was in (MomentumScreen.backTravel): the
// bottom after going up, the top after going down. Like LeftWall, the local
// origin is the collision face and only that face is playable; inactive (no
// collision, hook or drawing) while backTravel is 0.
class BackWall extends LeftWall
{
    update(camera)
    {
        const w = width / scale[version]
        const h = height / scale[version]
        const inset = height * 0.01 / scale[version]
        // +1: the wall lies below its face, -1: above, 0: inactive
        const side = -Math.sign(camera.backTravel || 0)
        const x = -camera.x
        const y = side > 0 ? h - inset - camera.y : inset - camera.y
        // A side switch jumps the face; anchors only follow the camera, so a
        // grapnel hooked on the old face is released
        const same = side == this.side
        if (!same && this.side && grapnel)
            grapnel.releaseElement(this)
        this.dx = x - this.x
        this.dy = same ? y - this.y : this.cameraY - camera.y
        this.cameraY = camera.y
        this.side = side
        this.x = x
        this.y = y
        const s = side || 1
        this.points = [{x: -w, y: 0}, {x: 2 * w, y: 0},
                       {x: 2 * w, y: s * h}, {x: -w, y: s * h}]
        this.circle = {x: w / 2, y: s * h / 2, radius: Math.hypot(1.5 * w, h / 2)}
        this.leftPointX = -w
        this.rightPointX = 2 * w
        this.lines = null
    }
    isActive()
    {
        return this.side != 0
    }
    getLines()
    {
        return [lineFormula(this.x + this.points[0].x, this.y,
                            this.x + this.points[1].x, this.y)]
    }
    resolve(who)
    {
        if (!this.side || (who.y - this.y) * this.side < -who.radius)
            return false
        // Half-space, the green obstacle response like LeftWall
        const line = this.getLines()[0]
        who.applyBounce({x: who.x, y: this.y, nx: 0, ny: -this.side,
                         approaching: who.speedY * this.side > 0, line: line, element: this})
        return line
    }
    draw()
    {
        if (!this.side)
            return
        ctx.save()
        // Clip to the side beyond the face, outline included
        const top = this.side > 0 ? this.y : this.y + this.points[2].y
        ctx.beginPath()
        ctx.rect(screen.x + this.x + this.points[0].x, screen.y + top,
                 this.points[1].x - this.points[0].x, Math.abs(this.points[2].y))
        ctx.clip()
        this.drawBadVersionPolygon(this.wallFill, this.stroke,
                                   {baseFillStyle: this.fill, coreColor: this.wallCore})
        ctx.restore()
    }
}
