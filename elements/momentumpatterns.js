// Momentum obstacle patterns: the bad frames ported to momentum for the
// right segments (TASK-036 port catalog) and every type of the TASK-013
// vertical and turn catalogs, built from one-time MomentumGreen /
// MomentumBlue pieces, nothing lethal, and their spawning along the course
// (MomentumObstacleFloor). The TASK-012 horizontal types are retired
// (TASK-038): the ported frames replace them.

// Every vertical type of the TASK-013 catalog, for 'up'/'down' segments. A
// type fills the shaft between the two dark-green walls: x 0 = left wall
// face, 1 = right wall face; y 0 = top of a footprint `span` band heights
// long. The layout is the same in both directions (going down, the route is
// run backwards). dirs: the only directions the type is built for.
// Pieces are [kind, x, y, w, h] in those fractions.
const MOMENTUM_PATTERNS_V = Object.freeze([
    {id: 'wall-ladder', difficulty: 1, span: 1.0, dirs: ['up', 'down'], pieces: [
        ['green', 0.0, 0.82, 0.06, 0.16],
        ['green', 0.94, 0.62, 0.06, 0.16],
        ['green', 0.0, 0.42, 0.06, 0.16],
        ['green', 0.94, 0.22, 0.06, 0.16],
        ['green', 0.0, 0.02, 0.06, 0.16]
    ]},
    {id: 'gate-bypass', difficulty: 2, span: 1.0, dirs: ['up', 'down'], pieces: [
        ['blue', 0.3, 0.48, 0.7, 0.08],
        ['green', 0.0, 0.7, 0.06, 0.14],
        ['green', 0.94, 0.2, 0.06, 0.14]
    ]},
    {id: 'trampoline-chimney', difficulty: 2, span: 1.0, dirs: ['up'], pieces: [
        ['green', 0.0, 0.8, 0.35, 0.04],
        ['green', 0.65, 0.55, 0.35, 0.04],
        ['green', 0.0, 0.3, 0.35, 0.04]
    ]},
    {id: 'ricochet-well', difficulty: 3, span: 1.0, dirs: ['down'], pieces: [
        ['green', 0.0, 0.12, 0.3, 0.1],
        ['green', 0.7, 0.38, 0.3, 0.1],
        ['green', 0.0, 0.64, 0.3, 0.1],
        ['green', 0.7, 0.86, 0.3, 0.1],
        ['blue', 0.42, 0.14, 0.16, 0.06],
        ['blue', 0.42, 0.4, 0.16, 0.06],
        ['blue', 0.42, 0.66, 0.16, 0.06]
    ]},
    {id: 'staggered-column', difficulty: 3, span: 1.1, dirs: ['up', 'down'], pieces: [
        ['green', 0.42, 0.7, 0.16, 0.14],
        ['blue', 0.42, 0.46, 0.16, 0.14],
        ['green', 0.42, 0.22, 0.16, 0.14],
        ['blue', 0.42, 0.0, 0.16, 0.1],
        ['green', 0.0, 0.48, 0.05, 0.12],
        ['green', 0.95, 0.3, 0.05, 0.12]
    ]},
    {id: 'needle-shaft', difficulty: 5, span: 1.1, dirs: ['up', 'down'], pieces: [
        ['green', 0.2, 0.84, 0.06, 0.1],
        ['blue', 0.0, 0.84, 0.1, 0.1],
        ['green', 0.72, 0.68, 0.06, 0.1],
        ['blue', 0.9, 0.68, 0.1, 0.1],
        ['green', 0.2, 0.52, 0.06, 0.1],
        ['blue', 0.0, 0.52, 0.1, 0.1],
        ['green', 0.72, 0.36, 0.06, 0.1],
        ['blue', 0.9, 0.36, 0.1, 0.1],
        ['green', 0.2, 0.2, 0.06, 0.1],
        ['blue', 0.0, 0.2, 0.1, 0.1],
        ['green', 0.72, 0.04, 0.06, 0.1],
        ['blue', 0.9, 0.04, 0.1, 0.1]
    ]}

].map(pattern => Object.freeze(pattern)))

// A turn type of the TASK-013 catalog sits on a segment join. Pieces are
// [kind, x, y, w, h] in a 2 x 2 band square drawn for right->up: incoming
// corridor y 0.5..1 (enter at x 0), outgoing shaft x 0.5..1 (leave at y 0),
// inner wall block (0, 0, 0.5, 0.5), course vertex at (0.75, 0.75).
const MOMENTUM_PATTERNS_TURN = Object.freeze([
    {id: 'corner-kicker', difficulty: 1, joins: ['right->up', 'right->down', 'down->right', 'up->right'], pieces: [
        ['green', 0.94, 0.55, 0.06, 0.3],
        ['green', 0.5, 0.15, 0.04, 0.2]
    ]},
    {id: 'apex-net', difficulty: 2, joins: ['right->up', 'up->right'], pieces: [
        ['green', 0.55, 0.95, 0.4, 0.05],
        ['green', 0.95, 0.3, 0.05, 0.15]
    ]},
    {id: 'blue-corner-cut', difficulty: 3, joins: ['right->up', 'right->down', 'down->right', 'up->right'], pieces: [
        ['blue', 0.5, 0.5, 0.14, 0.14],
        ['green', 0.75, 0.94, 0.15, 0.06],
        ['green', 0.94, 0.55, 0.06, 0.15],
        ['green', 0.5, 0.15, 0.04, 0.15]
    ]},
    {id: 'pinwheel', difficulty: 4, joins: ['right->up', 'right->down'], pieces: [
        ['green', 0.2, 0.95, 0.12, 0.05],
        ['green', 0.38, 0.5, 0.12, 0.05],
        ['green', 0.62, 0.95, 0.12, 0.05],
        ['green', 0.95, 0.62, 0.05, 0.12],
        ['green', 0.5, 0.34, 0.04, 0.12],
        ['green', 0.95, 0.2, 0.05, 0.12],
        ['blue', 0.66, 0.66, 0.12, 0.12]
    ]}
].map(pattern => Object.freeze(pattern)))
// The other joins are rigid transforms of the right->up drawing
const MOMENTUM_TURN_TRANSFORMS = Object.freeze({
    'right->up': (x, y) => ({x: x, y: y}),
    'right->down': (x, y) => ({x: x, y: 1 - y}),
    'down->right': (x, y) => ({x: 1 - x, y: y}),
    'up->right': (x, y) => ({x: 1 - x, y: 1 - y})
})

// Bad frames ported to momentum (the TASK-036 port catalog,
// artifacts/TASK-036/catalog-bad-port.json): the right corridor band is the
// bad floor..ceiling band, so the pieces keep their bad world sizes. span =
// footprint length in world units; a piece is a MomentumGreen/MomentumBlue
// .shape spec centred on (x, y): x along from the footprint start, y across
// from the corridor centre line (+ = floor side), motion yMin/yMax across
// as well. Right segments only: the motion is vertical.
const MOMENTUM_PATTERNS_PORT_H = Object.freeze([
    {id: 'bad-frame1', difficulty: 3, span: 2813.5, pieces: [
        {kind: 'green', x: 98.1, y: 38.2, shape: 'rect', w: 196.1, h: 1415.1},
        {kind: 'green', x: 2715.5, y: 38.2, shape: 'rect', w: 196.1, h: 1415.1},
        {kind: 'blue', x: 912.7, y: 565.7, shape: 'rect', w: 577, h: 588.4, motion: {speedY: -1.65, yMin: -972, yMax: 972, gravity: true}}
    ]},
    {id: 'bad-frame3', difficulty: 2, span: 800.2, pieces: [
        {kind: 'blue', x: 400.1, y: -40, shape: 'polygon', points: [[-400.1, -439.9], [400.1, -439.9], [0, 439.8]], motion: {speedY: -0.675, yMin: -961.2, yMax: 961.2, gravity: false}}
    ]},
    {id: 'bad-frame4', difficulty: 4, span: 1007, pieces: [
        {kind: 'green', x: 503.5, y: -39.6, shape: 'rect', w: 1007, h: 199.8},
        {kind: 'blue', x: 533.7, y: -467.7, shape: 'rect', w: 192.3, h: 196.1, motion: {speedY: -1.29, yMin: -972, yMax: -139.5, gravity: true}},
        {kind: 'blue', x: 505.4, y: 490.3, shape: 'polygon', points: [[-196, -215], [196, -215], [0, 215]], motion: {speedY: 0.675, yMin: 71.1, yMax: 961.2, gravity: false}}
    ]},
    {id: 'bad-frame5', difficulty: 2, span: 1742.5, pieces: [
        {kind: 'green', x: 1644.5, y: -397.9, shape: 'rect', w: 196.1, h: 1003.2},
        {kind: 'green', x: 98.1, y: 211.2, shape: 'rect', w: 196.1, h: 1376.6},
        {kind: 'green', x: 437.5, y: -396, shape: 'rect', w: 482.7, h: 162.2}
    ]},
    {id: 'bad-frame6', difficulty: 2, span: 196.1, pieces: [
        {kind: 'blue', x: 98, y: -735.9, shape: 'rect', w: 196.1, h: 472.3},
        {kind: 'blue', x: 98, y: 611.4, shape: 'rect', w: 196.1, h: 721.2}
    ]},
    {id: 'bad-frame7', difficulty: 2, span: 777, pieces: [
        {kind: 'green', x: 388.5, y: 516.7, shape: 'rect', w: 777, h: 531.8},
        {kind: 'blue', x: 388.5, y: -309.2, shape: 'rect', w: 192.4, h: 196.1, motion: {speedY: -0.693, yMin: -972, yMax: 250.8, gravity: true}}
    ]},
    {id: 'bad-frame8', difficulty: 3, span: 2594.8, pieces: [
        {kind: 'blue', x: 1312.5, y: 54.7, shape: 'rect', w: 196.1, h: 648.7},
        {kind: 'green', x: 98, y: -1.9, shape: 'rect', w: 196.1, h: 1003.2},
        {kind: 'green', x: 2496.7, y: 641.2, shape: 'rect', w: 196.2, h: 516.7},
        {kind: 'green', x: 2496.7, y: -641.1, shape: 'rect', w: 196.2, h: 516.7}
    ]},
    {id: 'bad-frame10', difficulty: 3, span: 1497.2, pieces: [
        {kind: 'green', x: 748.6, y: -1.8, shape: 'rect', w: 1497.2, h: 196.1},
        {kind: 'blue', x: 748.6, y: 698.2, shape: 'rect', w: 196.1, h: 547.7},
        {kind: 'blue', x: 748.6, y: -341.3, shape: 'rect', w: 196.1, h: 475.2}
    ]},
    {id: 'bad-frame11', difficulty: 3, span: 1497.2, pieces: [
        {kind: 'green', x: 748.6, y: -1.8, shape: 'rect', w: 1497.2, h: 196.1},
        {kind: 'blue', x: 748.6, y: 337.5, shape: 'rect', w: 196.1, h: 475.2},
        {kind: 'blue', x: 748.6, y: -665.7, shape: 'rect', w: 196.1, h: 475.2}
    ]},
    {id: 'bad-frame12', difficulty: 5, span: 2802.2, pieces: [
        {kind: 'green', x: 98, y: 38.2, shape: 'rect', w: 196.1, h: 1415.1},
        {kind: 'green', x: 2704.2, y: 38.2, shape: 'rect', w: 196.1, h: 1415.1},
        {kind: 'green', x: 1369.5, y: 186.7, shape: 'rect', w: 199.9, h: 426.2},
        {kind: 'blue', x: 705.1, y: -211.2, shape: 'rect', w: 362.1, h: 369.6, motion: {speedY: -1.142, yMin: -972, yMax: 972, gravity: true}},
        {kind: 'blue', x: 2229.4, y: 52.8, shape: 'rect', w: 362.1, h: 369.6, motion: {speedY: -1.366, yMin: -972, yMax: 972, gravity: true}}
    ]},
    {id: 'bad-frame13', difficulty: 4, span: 2689, pieces: [
        {kind: 'green', x: 98, y: 694, shape: 'rect', w: 196.1, h: 411.1},
        {kind: 'green', x: 98, y: -24.5, shape: 'rect', w: 196.1, h: 565.7},
        {kind: 'green', x: 98, y: -741.1, shape: 'rect', w: 196.1, h: 316.8},
        {kind: 'blue', x: 2493, y: 237.6, shape: 'polygon', points: [[-196, -215], [196, -215], [0, 215]], motion: {speedY: -0.675, yMin: -433.7, yMax: 961.2, gravity: false}},
        {kind: 'blue', x: 2491.1, y: -120.7, shape: 'rect', w: 192.3, h: 196.1, motion: {speedY: -0.693, yMin: -972, yMax: 354.1, gravity: true}}
    ]},
    {id: 'bad-frame14', difficulty: 2, span: 1972.4, pieces: [
        {kind: 'green', x: 1874.3, y: 434.2, shape: 'rect', w: 196.1, h: 1075.7},
        {kind: 'green', x: 98, y: -290.4, shape: 'rect', w: 196.1, h: 1218.2},
        {kind: 'green', x: 548.7, y: 237.6, shape: 'rect', w: 705.2, h: 162.2}
    ]}
].map(pattern => Object.freeze(pattern)))

// Builds one vertical catalog type, like the frame factories of
// elements/factory.js
class MomentumVerticalPatternFactory
{
    constructor(pattern)
    {
        this.pattern = pattern
    }
    // Footprint length in world units
    getLength()
    {
        return this.pattern.span * 2 * GAMEPLAY.momentumBorders.halfWidth
    }
    // (x, y): the footprint start on the course centre line, its bottom
    // going up and its top going down; halfWidth: the shaft's own half width
    // (momentumSegmentHalfWidth), the pieces span its inner width
    create(x, y, dir, halfWidth = momentumShaftHalfWidth())
    {
        const band = 2 * halfWidth
        const length = this.getLength()
        const left = x - 0.5 * band
        const top = dir == 'up' ? y - length : y
        return this.pattern.pieces.map(([kind, px, py, w, h]) =>
        {
            const box = kind == 'blue' ? MomentumBlue.box : MomentumGreen.box
            return box(left + px * band, top + py * length, w * band, h * length)
        })
    }
}

// Builds one ported bad frame (MOMENTUM_PATTERNS_PORT_H) in a right segment
class MomentumPortPatternFactory
{
    constructor(pattern)
    {
        this.pattern = pattern
        this.dirs = ['right']
    }
    getLength()
    {
        return this.pattern.span
    }
    // (x, y): the footprint start on the corridor centre line
    create(x, y)
    {
        return this.pattern.pieces.map(piece =>
        {
            const spec = {shape: piece.shape, x: x + piece.x, y: y + piece.y, w: piece.w, h: piece.h}
            if (piece.points)
                spec.points = piece.points.map(([px, py]) => ({x: px, y: py}))
            if (piece.motion)
                spec.motion = {speedY: piece.motion.speedY, yMin: y + piece.motion.yMin,
                               yMax: y + piece.motion.yMax, gravity: piece.motion.gravity}
            return (piece.kind == 'blue' ? MomentumBlue : MomentumGreen).shape(spec)
        })
    }
}

// Builds one turn catalog type
class MomentumTurnPatternFactory
{
    constructor(pattern)
    {
        this.pattern = pattern
    }
    // Sides of the 2 x 2 band square in world units: across the shaft
    // (x) at its own half width shaftHalfWidth, across the right corridor (y)
    // at the base half width
    getSize(shaftHalfWidth = momentumShaftHalfWidth())
    {
        return {x: 4 * shaftHalfWidth, y: 4 * GAMEPLAY.momentumBorders.halfWidth}
    }
    // How far the pieces reach from the course vertex of join, world units:
    // back along the incoming segment and ahead along the outgoing one
    getReach(join, shaftHalfWidth)
    {
        const size = this.getSize(shaftHalfWidth)
        const transform = MOMENTUM_TURN_TRANSFORMS[join]
        const vertex = transform(0.75, 0.75)
        const [from, to] = join.split('->').map(momentumDirection)
        let back = 0, ahead = 0
        for (const [, px, py, w, h] of this.pattern.pieces)
            for (const [u, v] of [[px, py], [px + w, py], [px, py + h], [px + w, py + h]])
            {
                const p = transform(u, v)
                const dx = (p.x - vertex.x) * size.x, dy = (p.y - vertex.y) * size.y
                back = Math.max(back, -(dx * from.x + dy * from.y))
                ahead = Math.max(ahead, dx * to.x + dy * to.y)
            }
        return {back: back, ahead: ahead}
    }
    // (x, y): the course vertex of the join; join: 'right->up' etc.;
    // shaftHalfWidth: the half width of the join's vertical segment
    create(x, y, join, shaftHalfWidth)
    {
        const size = this.getSize(shaftHalfWidth)
        const transform = MOMENTUM_TURN_TRANSFORMS[join]
        const vertex = transform(0.75, 0.75)
        const at = (u, v) =>
        {
            const p = transform(u, v)
            return {x: x + (p.x - vertex.x) * size.x, y: y + (p.y - vertex.y) * size.y}
        }
        return this.pattern.pieces.map(([kind, px, py, w, h]) =>
        {
            const a = at(px, py)
            const b = at(px + w, py + h)
            const left = Math.min(a.x, b.x)
            const top = Math.min(a.y, b.y)
            const box = kind == 'blue' ? MomentumBlue.box : MomentumGreen.box
            return box(left, top, Math.max(a.x, b.x) - left, Math.max(a.y, b.y) - top)
        })
    }
}
// Turn id -> factory, in catalog order; join -> the turn ids built for it
const momentumTurnFactories = Object.freeze(Object.fromEntries(
    MOMENTUM_PATTERNS_TURN.map(pattern => [pattern.id, new MomentumTurnPatternFactory(pattern)])))
const momentumTurnsByJoin = Object.freeze(Object.fromEntries(Object.keys(MOMENTUM_TURN_TRANSFORMS).map(join =>
    [join, Object.freeze(MOMENTUM_PATTERNS_TURN.filter(pattern => pattern.joins.includes(join)).map(pattern => pattern.id))])))

// Catalog id -> factory: the ported bad frames first, in port catalog
// order, then the vertical types
const momentumPatternFactories = Object.freeze(Object.fromEntries([
    ...MOMENTUM_PATTERNS_PORT_H.map(pattern => [pattern.id, new MomentumPortPatternFactory(pattern)]),
    ...MOMENTUM_PATTERNS_V.map(pattern => [pattern.id, new MomentumVerticalPatternFactory(pattern)])
]))
// Segment direction -> the ids spawned there: right segments spawn the
// ported frames only. A vertical type restricted to one direction is only
// registered there.
const momentumPatternsByDir = Object.freeze({
    right: Object.freeze(MOMENTUM_PATTERNS_PORT_H.map(pattern => pattern.id)),
    up: Object.freeze(MOMENTUM_PATTERNS_V.filter(pattern => pattern.dirs.includes('up')).map(pattern => pattern.id)),
    down: Object.freeze(MOMENTUM_PATTERNS_V.filter(pattern => pattern.dirs.includes('down')).map(pattern => pattern.id))
})

// Holds placed patterns, one generation group each, with the group's box
// kept apart from its pieces: a group is scored once it is passed (left of
// the view, or behind it vertically) even when its one-time pieces have
// already faded, and deleted with its pieces past the deletion borders.
class MomentumPatternFloor extends Floor
{
    constructor()
    {
        super(0.2 * height, 2 * height, {min: 0, max: 0}, [], 1)
        this.groups = []
    }
    generatePrimaryElements()
    {
        this.elements = []
        this.groups = []
        this.nextGenerationGroupId = 0
    }
    replenishElements() {}
    place(elements)
    {
        const generationGroupId = this.nextGenerationGroupId++
        const group = {id: generationGroupId, left: Infinity, top: Infinity, right: -Infinity, bottom: -Infinity,
                       scored: false}
        for (const element of elements)
        {
            element.generationGroupId = generationGroupId
            const bounds = getElementBounds(element)
            group.left = Math.min(group.left, bounds.left)
            group.top = Math.min(group.top, bounds.top)
            group.right = Math.max(group.right, bounds.right)
            group.bottom = Math.max(group.bottom, bounds.bottom)
        }
        this.elements.push(...elements)
        this.groups.push(group)
        return generationGroupId
    }
    deleteElements()
    {
        const border = screen.getDeletionBorder()
        const margin = GAMEPLAY.momentumCamera.deletionMarginHeightRatio * screen.getViewHeight()
        const deleted = new Set()
        for (const group of this.groups)
        {
            if (!group.scored && (group.right + screen.x < 0 || screen.isBoxBehind(group.top, group.bottom, 0)))
            {
                group.scored = true
                changeScoreText()
            }
            const behind = screen.isBoxBehind(group.top, group.bottom, margin)
            if (behind || group.right + screen.x < border)
            {
                deleted.add(group.id)
                if (behind)
                    screen.deletedBehind += this.elements.filter(e => e.generationGroupId === group.id).length
            }
        }
        if (!deleted.size)
            return
        this.groups = this.groups.filter(group => !deleted.has(group.id))
        this.elements = this.elements.filter(element => !deleted.has(element.generationGroupId))
    }
}

// The momentum obstacles: catalog patterns spawned along the course ahead of
// the ninja (GAMEPLAY.momentumSpawn). Stretch by stretch (consecutive
// segments of one direction), a turn type may take the join at the stretch
// end (its pieces' reach on both stretches), the rest gets patterns of its
// direction, spaced like the bad obstacle floor
// (Floor.alignBadVersionGeneratedElements). Types are picked with
// integer weights by difficulty (Floor.generateElements), easy types first,
// skipping the options.avoidRecent types placed last in the same direction
// (up and down together; turns: join) while another type is left, and never
// the last one in the same direction or join while there is another type.
class MomentumObstacleFloor extends MomentumPatternFloor
{
    constructor(course)
    {
        super()
        this.course = course
    }
    generatePrimaryElements()
    {
        super.generatePrimaryElements()
        this.arcStarts = [0]
        this.segmentIndex = 0
        this.plan = null
        this.nextClaim = 0
        // Up to options.avoidRecent recently placed type ids (latest last)
        // by direction, 'vertical' (up and down) and turn join
        this.recentIds = {}
        this.replenishElements()
    }
    getViewLength()
    {
        return Math.max(width, height) / scale[version]
    }
    // Course length before segment index
    getArcStart(index)
    {
        while (this.arcStarts.length <= index)
        {
            const i = this.arcStarts.length - 1
            this.arcStarts.push(this.arcStarts[i] + this.course.segment(i).length)
        }
        return this.arcStarts[index]
    }
    // The ninja's course position: its segment start plus its progress along it
    getNinjaArc()
    {
        const index = screen.segmentIndex
        const segment = this.course.segment(index)
        const d = momentumDirection(segment.dir)
        const along = (ninja.x - segment.x0) * d.x + (ninja.y - segment.y0) * d.y
        return this.getArcStart(index) + Math.max(0, Math.min(segment.length, along))
    }
    // Integer weights by difficulty: options.earlyWeights at score 0 moving
    // to options.lateWeights at options.rampScore. Skips the ids in avoid
    // while one is left (the latest one last).
    pickType(ids, difficultyOf, avoid = [])
    {
        const options = GAMEPLAY.momentumSpawn
        for (let i = 0; i < avoid.length; ++i)
        {
            const left = ids.filter(id => !avoid.slice(i).includes(id))
            if (left.length)
            {
                ids = left
                break
            }
        }
        const ramp = Math.min(1, scoreText.count[version] / options.rampScore)
        const weights = ids.map(id =>
        {
            const d = Math.min(difficultyOf(id), options.earlyWeights.length) - 1
            return Math.max(1, Math.round(options.earlyWeights[d] +
                (options.lateWeights[d] - options.earlyWeights[d]) * ramp))
        })
        const total = weights.reduce((sum, weight) => sum + weight, 0)
        const num = Math.min(random(0, total), total - 1)
        let bound = 0
        for (let i = 0; i < ids.length; ++i)
        {
            bound += weights[i]
            if (num < bound)
                return ids[i]
        }
        return ids[ids.length - 1]
    }
    getGap()
    {
        const options = GAMEPLAY.momentumSpawn
        const view = width / scale[version]
        const spacing = obstacleSpacingScale(scoreText.count[version])
        return random(options.gapViewWidths.min * view * spacing, options.gapViewWidths.max * view * spacing)
    }
    // Last segment index of the straight stretch starting at segment index
    // (consecutive segments of one direction)
    getStretchEnd(index)
    {
        const dir = this.course.segment(index).dir
        while (this.course.segment(index + 1).dir == dir)
            ++index
        return index
    }
    // How far patterns keep off a join with segment (the half widths of its
    // corridor, which crosses the stretch there)
    getJoinMargin(segment)
    {
        return GAMEPLAY.momentumSpawn.joinMarginHalfWidths * momentumSegmentHalfWidth(segment)
    }
    // Whether a vertical stretch this long holds a pattern of its direction
    // (its joins are with right segments)
    hasPatternRoom(dir, length)
    {
        const margin = GAMEPLAY.momentumSpawn.joinMarginHalfWidths * GAMEPLAY.momentumBorders.halfWidth
        const shortest = Math.min(...momentumPatternsByDir[dir].map(id => momentumPatternFactories[id].getLength()))
        return length >= 2 * margin + shortest
    }
    // Where patterns of the stretch from segment index may go (course
    // distance from its start) and whether a turn takes the join at its end.
    // Vertical patterns come first: no turn next to a vertical stretch long
    // enough for one (a turn would leave it no room). A turn needs its piece
    // reach (MomentumTurnPatternFactory.getReach) on both stretches, plus the
    // join margin at the far end of the next one; patterns keep the minimum
    // gap off its pieces. Join margins and the turn's square across the
    // shaft follow the shafts' own half widths.
    planStretch(index)
    {
        const options = GAMEPLAY.momentumSpawn
        const last = this.getStretchEnd(index)
        const segment = this.course.segment(index)
        const end = this.course.segment(last)
        const next = this.course.segment(last + 1)
        const nextLast = this.getStretchEnd(last + 1)
        const length = this.getArcStart(last + 1) - this.getArcStart(index)
        const nextLength = this.getArcStart(nextLast + 1) - this.getArcStart(last + 1)
        const margin = this.getJoinMargin(next)
        const nextMargin = this.getJoinMargin(this.course.segment(nextLast + 1))
        const shaftHalfWidth = momentumSegmentHalfWidth(segment.dir == 'right' ? next : end)
        let start = Math.max(index ? this.getJoinMargin(this.course.segment(index - 1)) :
                             GAMEPLAY.momentumSpawn.joinMarginHalfWidths * GAMEPLAY.momentumBorders.halfWidth,
                             this.nextClaim)
        if (index == 0)
            start = Math.max(start, ninja.x - segment.x0 + options.startViewWidths * width / scale[version])
        const join = segment.dir + '->' + next.dir
        const vertical = segment.dir == 'right' ? [next.dir, nextLength] : [segment.dir, length]
        let turn = null, reach = null
        if (momentumTurnsByJoin[join].length && !this.hasPatternRoom(...vertical) &&
            random(0, 100) < options.turnChancePercent)
        {
            turn = this.pickType(momentumTurnsByJoin[join], id => momentumTurnFactories[id].pattern.difficulty,
                                 this.getAvoidedTypes(join))
            reach = momentumTurnFactories[turn].getReach(join, shaftHalfWidth)
            if (start > length - reach.back || nextLength < reach.ahead + nextMargin)
                turn = null
        }
        const gap = options.gapViewWidths.min * width / scale[version]
        return {segment: segment, index: index, last: last, vertex: {x: end.x1, y: end.y1}, cursor: start,
                join: join, turn: turn, shaftHalfWidth: shaftHalfWidth, end: turn ? length - reach.back - gap : length - margin,
                turnArc: turn ? length - reach.back : 0, nextClaim: turn ? reach.ahead + gap : 0, filled: false}
    }
    // Up and down patterns share their types: their recent types are kept
    // together, and the latest one per direction too
    getRecentKey(dir)
    {
        return dir == 'up' || dir == 'down' ? 'vertical' : dir
    }
    placedType(dir, id)
    {
        for (const key of new Set([this.getRecentKey(dir), dir]))
        {
            const recent = (this.recentIds[key] || []).concat(id)
            this.recentIds[key] = recent.slice(Math.max(0, recent.length - GAMEPLAY.momentumSpawn.avoidRecent))
        }
    }
    // For pickType: the recent types of dir (a direction or a turn join), the
    // latest one in dir itself last
    getAvoidedTypes(dir)
    {
        return (this.recentIds[this.getRecentKey(dir)] || []).concat((this.recentIds[dir] || []).slice(-1))
    }
    spawned(id, kind, dir, difficulty, arc)
    {
        if (MomentumObstacleFloor.onSpawn)
        {
            const group = this.groups[this.groups.length - 1]
            MomentumObstacleFloor.onSpawn({id: id, kind: kind, dir: dir, difficulty: difficulty, segment: this.plan.index,
                          arcAhead: arc - this.getNinjaArc(), group: group,
                          lethal: this.elements.filter(e => e.generationGroupId === group.id && isLethalElement(e)).length})
        }
    }
    // Spawns until the next free course position is aheadViewLengths ahead
    // along the course and as many view widths right of the view (the
    // course never goes left, so nothing later can show up in the view)
    replenishElements()
    {
        const ahead = GAMEPLAY.momentumSpawn.aheadViewLengths
        const target = this.getNinjaArc() + ahead * this.getViewLength()
        const targetX = -screen.x + ahead * width / scale[version]
        const reached = (segment, arc) => arc >= target &&
            segment.x0 + momentumDirection(segment.dir).x * (arc - this.getArcStart(this.plan.index)) >= targetX
        for (;;)
        {
            if (!this.plan)
                this.plan = this.planStretch(this.segmentIndex)
            const plan = this.plan
            const segment = plan.segment
            const arc = this.getArcStart(plan.index)
            if (!plan.filled)
            {
                if (reached(segment, arc + plan.cursor))
                    return
                const ids = momentumPatternsByDir[segment.dir]
                const id = this.pickType(ids, id => momentumPatternFactories[id].pattern.difficulty,
                                         this.getAvoidedTypes(segment.dir))
                const factory = momentumPatternFactories[id]
                if (plan.cursor + factory.getLength() > plan.end)
                {
                    plan.filled = true
                    continue
                }
                const d = momentumDirection(segment.dir)
                this.place(factory.create(segment.x0 + d.x * plan.cursor, segment.y0 + d.y * plan.cursor, segment.dir,
                                          momentumSegmentHalfWidth(segment)))
                this.placedType(segment.dir, id)
                this.spawned(id, segment.dir == 'right' ? 'horizontal' : 'vertical', segment.dir,
                             factory.pattern.difficulty, arc + plan.cursor)
                plan.cursor += factory.getLength() + this.getGap()
                continue
            }
            if (plan.turn)
            {
                if (reached(segment, arc + plan.turnArc))
                    return
                const factory = momentumTurnFactories[plan.turn]
                this.place(factory.create(plan.vertex.x, plan.vertex.y, plan.join, plan.shaftHalfWidth))
                this.placedType(plan.join, plan.turn)
                this.spawned(plan.turn, 'turn', plan.join, factory.pattern.difficulty, arc + plan.turnArc)
                plan.turn = null
            }
            this.nextClaim = plan.nextClaim
            this.segmentIndex = plan.last + 1
            this.plan = null
        }
    }
}

// Called with every spawned group (tests and tools)
MomentumObstacleFloor.onSpawn = null

// Places catalog type id on the momentum pattern floor, for tests and
// screenshots. Returns the placed boxes, or null outside momentum and for a
// vertical type in a direction it is not registered for and for a ported
// frame (bad-frameN) outside a right segment. A vertical type spans
// halfWidth (default: a shaft built now, momentumShaftHalfWidth). Elements
// also carry their polygon points, speedY and motion.
function momentumPlacePattern(id, x, y, dir = 'right', halfWidth = momentumShaftHalfWidth())
{
    let factory = momentumPatternFactories[id]
    if (factory instanceof MomentumVerticalPatternFactory && !momentumPatternsByDir[dir]?.includes(id))
        factory = undefined
    if (factory?.dirs && !factory.dirs.includes(dir))
        factory = undefined
    const floor = version == 'momentum' && floors ? floors.find(f => f instanceof MomentumPatternFloor) : null
    if (!factory || !floor)
        return null
    const elements = factory.create(x, y, dir, halfWidth)
    const group = floor.place(elements)
    return {id: id, group: group, length: factory.getLength(), elements: elements.map(element =>
    {
        const bounds = getElementBounds(element)
        return {className: element.constructor.name, lethal: isLethalElement(element),
                left: bounds.left, top: bounds.top, right: bounds.right, bottom: bounds.bottom,
                points: element.getPoints().map(point => [point.x, point.y]), speedY: element.speedY || 0,
                motion: element.motion}
    })}
}
window.momentumPlacePattern = momentumPlacePattern

// Places turn type id on the join at the end of course segment segmentIndex
// (between it and the next segment). Returns the placed boxes, or null
// outside momentum, on a straight join and on a join the type is not built for.
function momentumPlaceTurn(id, segmentIndex)
{
    const factory = momentumTurnFactories[id]
    const floor = version == 'momentum' && floors ? floors.find(f => f instanceof MomentumPatternFloor) : null
    if (!factory || !floor || typeof momentumCourse === 'undefined' || !momentumCourse)
        return null
    const segment = momentumCourse.segment(segmentIndex)
    const join = segment.dir + '->' + momentumCourse.segment(segmentIndex + 1).dir
    if (!factory.pattern.joins.includes(join))
        return null
    const shaft = segment.dir == 'right' ? momentumCourse.segment(segmentIndex + 1) : segment
    const shaftHalfWidth = momentumSegmentHalfWidth(shaft)
    const elements = factory.create(segment.x1, segment.y1, join, shaftHalfWidth)
    const group = floor.place(elements)
    return {id: id, join: join, segment: segmentIndex, group: group, size: factory.getSize(shaftHalfWidth),
            vertex: {x: segment.x1, y: segment.y1}, elements: elements.map(element =>
    {
        const bounds = getElementBounds(element)
        return {className: element.constructor.name, lethal: isLethalElement(element),
                left: bounds.left, top: bounds.top, right: bounds.right, bottom: bounds.bottom}
    })}
}
window.momentumPlaceTurn = momentumPlaceTurn

// Places one green or blue piece (kind 'green' | 'blue') built from a
// MomentumOneTime.shapeObject spec on the momentum pattern floor, for tests
// and screenshots. Returns {group, element}, or null outside momentum.
function momentumPlacePiece(kind, spec)
{
    const floor = version == 'momentum' && floors ? floors.find(f => f instanceof MomentumPatternFloor) : null
    if (!floor)
        return null
    const element = (kind == 'blue' ? MomentumBlue : MomentumGreen).shape(spec)
    return {group: floor.place([element]), element: element}
}
window.momentumPlacePiece = momentumPlacePiece
