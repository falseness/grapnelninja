// Momentum course: an endless chain of segments in world units. Each segment
// starts where the previous one ends. The first one runs right and every
// vertical segment is followed by a right one, so up and down never touch.
// Segments are generated lazily; Math.random is only drawn in generate().
class MomentumCourse
{
    constructor(x0 = 0, y0 = 0, options = GAMEPLAY.momentumCourse)
    {
        this.options = options
        this.x0 = x0
        this.y0 = y0
        this.segments = []
    }

    // The segment at index, generating the course up to it if needed
    segment(index)
    {
        while (this.segments.length <= index)
            this.generate()
        return this.segments[index]
    }

    // The first count segments
    take(count)
    {
        if (count > 0)
            this.segment(count - 1)
        return this.segments.slice(0, count)
    }

    generate()
    {
        const options = this.options
        const last = this.segments[this.segments.length - 1]
        let dir = 'right'
        if (last !== undefined && last.dir == 'right' &&
            Math.random() * 100 >= options.rightAfterRightChancePercent)
            dir = Math.random() * 100 < options.upChancePercent ? 'up' : 'down'
        const length = options.minLen + Math.random() * (options.maxLen - options.minLen)

        const x0 = last === undefined ? this.x0 : last.x1
        const y0 = last === undefined ? this.y0 : last.y1
        const segment = {
            dir: dir,
            length: length,
            x0: x0,
            y0: y0,
            x1: dir == 'right' ? x0 + length : x0,
            // World y grows downwards, like the canvas
            y1: dir == 'up' ? y0 - length : dir == 'down' ? y0 + length : y0
        }
        this.segments.push(segment)
        return segment
    }
}
