// Momentum obstacle patterns: every type of the TASK-012 horizontal catalog,
// built from one-time MomentumGreen / MomentumBlue boxes, nothing lethal.
// A type fills the whole corridor band (v 0 = ceiling face, 1 = floor face)
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

// Catalog id -> factory
const momentumPatternFactories = Object.freeze(Object.fromEntries(
    MOMENTUM_PATTERNS_H.map(pattern => [pattern.id, new MomentumPatternFactory(pattern)])))

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
// screenshots. Returns the placed boxes, or null outside momentum.
function momentumPlacePattern(id, x, y, dir = 'right')
{
    const factory = momentumPatternFactories[id]
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
