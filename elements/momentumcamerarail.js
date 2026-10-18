// Momentum camera rail: the path the camera travels (MomentumScreen). It is the course centre line (elements/momentumcourse.js
// segments) with every turn join replaced by a quarter circle of radius
// GAMEPLAY.momentumCamera.railRadius view heights, at most half of either
// adjacent segment, so the tangent is continuous. A straight join stays a
// line. s is the arc length from the course start (x0, y0).
// Pieces are built from the segments the course already has; a query past
// them generates the next segment (course.segment), like the course growing.
class MomentumCameraRail
{
    constructor(course, radius = GAMEPLAY.momentumCamera.railRadius * height / scale.momentum)
    {
        this.course = course
        this.radius = radius
        // {type: 'line', s0, length, x, y, ux, uy} /
        // {type: 'arc', s0, length, cx, cy, r, ux, uy, wx, wy}: the arc turns
        // from direction u to w around centre c
        this.pieces = []
        // Final length; past it only the provisional tail along the last segment
        this.length = 0
        // Start of the not yet built line and how many joins are built
        this.x = course.x0
        this.y = course.y0
        this.joins = 0
        // s of each built join: its arc middle, or the shared end point
        this.joinS = []
    }

    static direction(segment)
    {
        return {x: segment.x1 - segment.x0, y: segment.y1 - segment.y0, length: segment.length}
    }

    // Builds the pieces up to join index (segment index -> index + 1)
    extend(index)
    {
        while (this.joins <= index)
        {
            const a = this.course.segment(this.joins), b = this.course.segment(this.joins + 1)
            const da = MomentumCameraRail.direction(a), db = MomentumCameraRail.direction(b)
            const ux = da.x / da.length, uy = da.y / da.length
            const wx = db.x / db.length, wy = db.y / db.length
            const r = ux == wx && uy == wy ? 0 : Math.min(this.radius, a.length / 2, b.length / 2)
            this.line(a.x1 - ux * r, a.y1 - uy * r)
            this.joinS.push(this.length + Math.PI / 4 * r)
            if (r > 0)
            {
                const length = Math.PI / 2 * r
                this.pieces.push({type: 'arc', s0: this.length, length: length,
                                  cx: this.x + wx * r, cy: this.y + wy * r, r: r, ux: ux, uy: uy, wx: wx, wy: wy})
                this.length += length
                this.x = a.x1 + wx * r
                this.y = a.y1 + wy * r
            }
            ++this.joins
        }
    }

    line(x, y)
    {
        const length = Math.hypot(x - this.x, y - this.y)
        if (length > 0)
        {
            this.pieces.push({type: 'line', s0: this.length, length: length, x: this.x, y: this.y,
                              ux: (x - this.x) / length, uy: (y - this.y) / length})
            this.length += length
        }
        this.x = x
        this.y = y
    }

    // s of join index (segment index -> index + 1): its arc middle
    joinAt(index)
    {
        this.extend(index)
        return this.joinS[index]
    }

    // The piece holding s (built as far as needed)
    pieceAt(s)
    {
        while (s >= this.length)
            this.extend(this.joins)
        let lo = 0, hi = this.pieces.length - 1
        while (lo < hi)
        {
            const mid = (lo + hi + 1) >> 1
            if (this.pieces[mid].s0 <= s)
                lo = mid
            else
                hi = mid - 1
        }
        return lo
    }

    // Point and unit tangent of piece at d along it
    static sample(piece, d)
    {
        if (piece.type == 'line')
            return {x: piece.x + piece.ux * d, y: piece.y + piece.uy * d, tx: piece.ux, ty: piece.uy}
        const phi = d / piece.r, c = Math.cos(phi), n = Math.sin(phi)
        return {x: piece.cx + piece.r * (piece.ux * n - piece.wx * c),
                y: piece.cy + piece.r * (piece.uy * n - piece.wy * c),
                tx: piece.ux * c + piece.wx * n, ty: piece.uy * c + piece.wy * n}
    }

    pointAt(s)
    {
        s = Math.max(0, s)
        const piece = this.pieces[this.pieceAt(s)]
        const p = MomentumCameraRail.sample(piece, s - piece.s0)
        return {x: p.x, y: p.y}
    }

    tangentAt(s)
    {
        s = Math.max(0, s)
        const piece = this.pieces[this.pieceAt(s)]
        const p = MomentumCameraRail.sample(piece, s - piece.s0)
        return {x: p.tx, y: p.ty}
    }

    // s of the rail point nearest to (x, y), searched forward from hint over
    // ahead world units (default two view heights), never below hint
    project(x, y, hint = 0, ahead = 2 * height / scale.momentum)
    {
        hint = Math.max(0, hint)
        const end = hint + ahead
        this.pieceAt(end)
        let best = hint, bestDist = Infinity
        for (let i = this.pieceAt(hint); i < this.pieces.length && this.pieces[i].s0 <= end; ++i)
        {
            const piece = this.pieces[i]
            let d
            if (piece.type == 'line')
                d = (x - piece.x) * piece.ux + (y - piece.y) * piece.uy
            else
            {
                const dx = x - piece.cx, dy = y - piece.cy
                d = piece.r * Math.atan2(dx * piece.ux + dy * piece.uy, -(dx * piece.wx + dy * piece.wy))
            }
            d = Math.min(piece.length, Math.max(hint - piece.s0, 0, Math.min(d, end - piece.s0)))
            const p = MomentumCameraRail.sample(piece, d)
            const dist = Math.hypot(x - p.x, y - p.y)
            if (dist < bestDist - 1e-9)
            {
                bestDist = dist
                best = piece.s0 + d
            }
        }
        return best
    }
}
