// Camera-owned boundary: never part of a procedural floor. Local origin is
// the collision face, so resizing its offscreen body cannot shift an anchor.
class LeftWall extends Trampoline
{
    constructor(camera)
    {
        super({x: 0, y: 0, points: [{x: -1, y: -1}, {x: 0, y: -1},
                                  {x: 0, y: 1}, {x: -1, y: 1}]})
        this.update(camera)
        this.dx = this.dy = 0
    }
    update(camera)
    {
        const x = height * 0.01 / scale[version] - camera.x
        const y = -camera.y
        this.dx = x - this.x
        this.dy = y - this.y
        this.x = x
        this.y = y
        const w = width / scale[version]
        const h = height / scale[version]
        this.points = [{x: -w, y: -h}, {x: 0, y: -h},
                       {x: 0, y: 2 * h}, {x: -w, y: 2 * h}]
        this.circle = {x: -w / 2, y: h / 2, radius: Math.hypot(w / 2, 1.5 * h)}
        this.leftPointX = -w
        this.rightPointX = 0
        this.lines = null
    }
    // Only the playable face can catch a hook; the other edges are offscreen.
    getLines()
    {
        return [lineFormula(this.x, this.y + this.points[1].y,
                            this.x, this.y + this.points[2].y)]
    }
    resolve(who)
    {
        if (who.x - who.radius > this.x)
            return false
        // An infinite half-space recovers deep overlap without selecting a
        // back edge. Reuse the green obstacle response, including effects.
        const line = this.getLines()[0]
        who.applyBounce({x: this.x, y: who.y, nx: 1, ny: 0,
                         approaching: who.speedX < 0, line: line, element: this})
        return line
    }
    drawExtrusion() {}
}
