// Momentum obstacle patterns: every type of the TASK-012 horizontal and the
// TASK-013 vertical catalog, built from one-time MomentumGreen / MomentumBlue
// boxes, nothing lethal.
// A horizontal type fills the whole corridor band (v 0 = ceiling face, 1 = floor face)
// over a footprint `span` band heights long (u 0..1 along the travel
// direction). Pieces are [kind, u, v, w, h] in those fractions.
const MOMENTUM_PATTERNS_H = Object.freeze([
    {id: 'green-ladder', difficulty: 1, span: 1.1, pieces: [
        ['green', 0.0545, 0.8, 0.0909, 0.05],
        ['green', 0.2455, 0.15, 0.0909, 0.05],
        ['green', 0.4364, 0.8, 0.0909, 0.05],
        ['green', 0.6273, 0.15, 0.0909, 0.05],
        ['green', 0.8182, 0.8, 0.0909, 0.05]
    ]},
    {id: 'pillar-gate', difficulty: 1, span: 1.0, pieces: [
        ['green', 0.08, 0.16, 0.06, 0.72],
        ['blue', 0.4, 0.62, 0.2, 0.28],
        ['green', 0.86, 0.16, 0.06, 0.72]
    ]},
    {id: 'falling-wedge', difficulty: 2, span: 1.0, pieces: [
        ['blue', 0.28, 0.22, 0.44, 0.1],
        ['blue', 0.35, 0.32, 0.3, 0.12],
        ['blue', 0.42, 0.44, 0.16, 0.12],
        ['blue', 0.47, 0.56, 0.06, 0.1],
        ['green', 0.24, 0.88, 0.12, 0.04],
        ['green', 0.64, 0.88, 0.12, 0.04]
    ]},
    {id: 'blue-curtain', difficulty: 2, span: 1.0, pieces: [
        ['blue', 0.46, 0.0, 0.08, 0.78],
        ['green', 0.62, 0.9, 0.12, 0.04],
        ['green', 0.84, 0.9, 0.12, 0.04]
    ]},
    {id: 'split-shelf', difficulty: 3, span: 1.0, pieces: [
        ['green', 0.1, 0.48, 0.2, 0.05],
        ['green', 0.3, 0.48, 0.55, 0.05],
        ['blue', 0.48, 0.2, 0.08, 0.28],
        ['green', 0.3, 0.9, 0.1, 0.04],
        ['green', 0.62, 0.9, 0.1, 0.04]
    ]},
    {id: 'cube-shuffle', difficulty: 3, span: 1.0, pieces: [
        ['green', 0.26, 0.55, 0.16, 0.06],
        ['blue', 0.45, 0.25, 0.1, 0.12],
        ['blue', 0.45, 0.64, 0.1, 0.26],
        ['green', 0.58, 0.55, 0.16, 0.06],
        ['green', 0.86, 0.2, 0.1, 0.04]
    ]},
    {id: 'stair-run', difficulty: 3, span: 1.1, pieces: [
        ['green', 0.0364, 0.3, 0.0909, 0.04],
        ['green', 0.1818, 0.48, 0.0909, 0.04],
        ['green', 0.3273, 0.66, 0.0909, 0.04],
        ['blue', 0.4545, 0.82, 0.0909, 0.18],
        ['green', 0.5818, 0.66, 0.0909, 0.04],
        ['green', 0.7273, 0.48, 0.0909, 0.04],
        ['green', 0.8727, 0.3, 0.0909, 0.04]
    ]},
    {id: 'double-dare', difficulty: 4, span: 1.0, pieces: [
        ['green', 0.04, 0.04, 0.06, 0.26],
        ['green', 0.04, 0.7, 0.06, 0.26],
        ['green', 0.3, 0.16, 0.1, 0.04],
        ['blue', 0.47, 0.36, 0.06, 0.28],
        ['green', 0.62, 0.16, 0.1, 0.04],
        ['green', 0.9, 0.04, 0.06, 0.26],
        ['green', 0.9, 0.7, 0.06, 0.26]
    ]},
    {id: 'needle-streak', difficulty: 5, span: 1.1, pieces: [
        ['green', 0.0364, 0.7, 0.0727, 0.04],
        ['blue', 0.0364, 0.0, 0.0727, 0.2],
        ['green', 0.2, 0.3, 0.0727, 0.04],
        ['blue', 0.2, 0.8, 0.0727, 0.2],
        ['green', 0.3636, 0.7, 0.0727, 0.04],
        ['blue', 0.3636, 0.0, 0.0727, 0.2],
        ['green', 0.5273, 0.3, 0.0727, 0.04],
        ['blue', 0.5273, 0.8, 0.0727, 0.2],
        ['green', 0.6909, 0.7, 0.0727, 0.04],
        ['blue', 0.6909, 0.0, 0.0727, 0.2],
        ['green', 0.8545, 0.3, 0.0727, 0.04],
        ['blue', 0.8545, 0.8, 0.0727, 0.2]
    ]}
].map(pattern => Object.freeze(pattern)))

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

// Builds one catalog type, like the frame factories of elements/factory.js
class MomentumPatternFactory
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
    // (x, y): the footprint start on the course centre line; dir: the course
    // segment direction. Side +1 (v = 1) is the floor of a right segment,
    // as in elements/momentumborders.js.
    create(x, y, dir = 'right')
    {
        const band = 2 * GAMEPLAY.momentumBorders.halfWidth
        const length = this.getLength()
        const d = momentumDirection(dir)
        const n = momentumSideNormal(dir, 1)
        const at = (u, v) => ({
            x: x + u * length * d.x + (v - 0.5) * band * n.x,
            y: y + u * length * d.y + (v - 0.5) * band * n.y
        })
        return this.pattern.pieces.map(([kind, u, v, w, h]) =>
        {
            const a = at(u, v)
            const b = at(u + w, v + h)
            const left = Math.min(a.x, b.x)
            const top = Math.min(a.y, b.y)
            const box = kind == 'blue' ? MomentumBlue.box : MomentumGreen.box
            return box(left, top, Math.max(a.x, b.x) - left, Math.max(a.y, b.y) - top)
        })
    }
}

// Builds one vertical catalog type
class MomentumVerticalPatternFactory extends MomentumPatternFactory
{
    // (x, y): the footprint start on the course centre line, its bottom
    // going up and its top going down
    create(x, y, dir)
    {
        const band = 2 * GAMEPLAY.momentumBorders.halfWidth
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

// Builds one turn catalog type
class MomentumTurnPatternFactory
{
    constructor(pattern)
    {
        this.pattern = pattern
    }
    // Side of the 2 x 2 band square in world units
    getSize()
    {
        return 4 * GAMEPLAY.momentumBorders.halfWidth
    }
    // (x, y): the course vertex of the join; join: 'right->up' etc.
    create(x, y, join)
    {
        const size = this.getSize()
        const transform = MOMENTUM_TURN_TRANSFORMS[join]
        const vertex = transform(0.75, 0.75)
        const at = (u, v) =>
        {
            const p = transform(u, v)
            return {x: x + (p.x - vertex.x) * size, y: y + (p.y - vertex.y) * size}
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

// Catalog id -> factory, horizontal types first, in catalog order
const momentumPatternFactories = Object.freeze(Object.fromEntries([
    ...MOMENTUM_PATTERNS_H.map(pattern => [pattern.id, new MomentumPatternFactory(pattern)]),
    ...MOMENTUM_PATTERNS_V.map(pattern => [pattern.id, new MomentumVerticalPatternFactory(pattern)])
]))
// Segment direction -> the ids built for it. A vertical type restricted to
// one direction is only registered there.
const momentumPatternsByDir = Object.freeze({
    right: Object.freeze(MOMENTUM_PATTERNS_H.map(pattern => pattern.id)),
    up: Object.freeze(MOMENTUM_PATTERNS_V.filter(pattern => pattern.dirs.includes('up')).map(pattern => pattern.id)),
    down: Object.freeze(MOMENTUM_PATTERNS_V.filter(pattern => pattern.dirs.includes('down')).map(pattern => pattern.id))
})

// Holds placed patterns, one generation group each. Nothing spawns here on
// its own yet; deletion and scoring work like the obstacle floor's.
class MomentumPatternFloor extends Floor
{
    constructor()
    {
        super(0.2 * height, 2 * height, {min: 0, max: 0}, [], 1)
    }
    generatePrimaryElements()
    {
        this.elements = []
        this.nextGenerationGroupId = 0
    }
    replenishElements() {}
    place(elements)
    {
        const generationGroupId = this.nextGenerationGroupId++
        for (const element of elements)
            element.generationGroupId = generationGroupId
        this.elements.push(...elements)
        return generationGroupId
    }
    deleteElements()
    {
        super.deleteElements()
        screen.deleteBehind(this, false)
    }
}

// Places catalog type id on the momentum pattern floor, for tests and
// screenshots. Returns the placed boxes, or null outside momentum and for a
// vertical type in a direction it is not registered for.
function momentumPlacePattern(id, x, y, dir = 'right')
{
    let factory = momentumPatternFactories[id]
    if (factory instanceof MomentumVerticalPatternFactory && !momentumPatternsByDir[dir]?.includes(id))
        factory = undefined
    const floor = version == 'momentum' && floors ? floors.find(f => f instanceof MomentumPatternFloor) : null
    if (!factory || !floor)
        return null
    const elements = factory.create(x, y, dir)
    const group = floor.place(elements)
    return {id: id, group: group, length: factory.getLength(), elements: elements.map(element =>
    {
        const bounds = getElementBounds(element)
        return {className: element.constructor.name, lethal: isLethalElement(element),
                left: bounds.left, top: bounds.top, right: bounds.right, bottom: bounds.bottom}
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
    const elements = factory.create(segment.x1, segment.y1, join)
    const group = floor.place(elements)
    return {id: id, join: join, segment: segmentIndex, group: group, size: factory.getSize(),
            vertex: {x: segment.x1, y: segment.y1}, elements: elements.map(element =>
    {
        const bounds = getElementBounds(element)
        return {className: element.constructor.name, lethal: isLethalElement(element),
                left: bounds.left, top: bounds.top, right: bounds.right, bottom: bounds.bottom}
    })}
}
window.momentumPlaceTurn = momentumPlaceTurn
