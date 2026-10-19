// Momentum obstacle patterns: the bad frames ported to momentum (TASK-036
// port catalog) for the right segments, rotated for the up/down shafts and
// placed at a join as turn types, built from one-time MomentumGreen /
// MomentumBlue pieces, nothing lethal, and their spawning along the course
// (MomentumObstacleFloor). The TASK-012 horizontal and TASK-013 vertical and
// turn types are retired (TASK-038..040): the ported frames replace them.

// Bad frames ported to momentum (the TASK-036 port catalog,
// artifacts/TASK-036/catalog-bad-port.json): the right corridor band is the
// bad floor..ceiling band, so the pieces keep their bad world sizes. span =
// footprint length in world units; a piece is a MomentumGreen/MomentumBlue
// .shape spec centred on (x, y): x along from the footprint start, y across
// from the corridor centre line (+ = floor side), motion yMin/yMax across
// as well. Right segments only: the motion is vertical. The wall-flush rects
// of bad-frame6/10/14 sit 0.05 off the catalog centre so they end at the
// band edge (972) instead of 0.05 inside the wall (TASK-043).
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
        {kind: 'blue', x: 98, y: -735.85, shape: 'rect', w: 196.1, h: 472.3},
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
        {kind: 'blue', x: 748.6, y: 698.15, shape: 'rect', w: 196.1, h: 547.7},
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
        {kind: 'green', x: 1874.3, y: 434.15, shape: 'rect', w: 196.1, h: 1075.7},
        {kind: 'green', x: 98, y: -290.4, shape: 'rect', w: 196.1, h: 1218.2},
        {kind: 'green', x: 548.7, y: 237.6, shape: 'rect', w: 705.2, h: 162.2}
    ]}
].map(pattern => Object.freeze(pattern)))

// Vertical variants of the static ported frames (the catalog's `vertical`
// lists): the bad frame rotated 90 deg. Per direction the pieces are rects
// centred on (x, y) in world units at the base half width: x across from
// the shaft centre line, y along from the footprint start (- = up). In a
// shaft they are scaled uniformly by its half width over the base one, so
// they span it wall to wall as the frame spans floor..ceiling in bad. wall
// '-'/'+': flush with the wall on the side of its centre. dirs: the only
// directions the variant is built for.
const MOMENTUM_PATTERNS_PORT_V = Object.freeze([
    {id: 'bad-frame5-v', source: 'bad-frame5', difficulty: 2, span: 1742.5, dirs: ['up', 'down'], pieces: {
        up: [
            {kind: 'green', x: -397.9, y: -1644.5, w: 1003.2, h: 196.1},
            {kind: 'green', x: 211.2, y: -98.1, w: 1376.6, h: 196.1},
            {kind: 'green', x: -396, y: -437.5, w: 162.2, h: 482.7}
        ],
        down: [
            {kind: 'green', x: 397.9, y: 1644.5, w: 1003.2, h: 196.1},
            {kind: 'green', x: -211.2, y: 98.1, w: 1376.6, h: 196.1},
            {kind: 'green', x: 396, y: 437.5, w: 162.2, h: 482.7}
        ]
    }},
    {id: 'bad-frame6-v', source: 'bad-frame6', difficulty: 2, span: 196.1, dirs: ['up', 'down'], pieces: {
        up: [
            {kind: 'blue', x: -735.9, y: -98, w: 472.3, h: 196.1, wall: '-'},
            {kind: 'blue', x: 611.4, y: -98, w: 721.2, h: 196.1, wall: '+'}
        ],
        down: [
            {kind: 'blue', x: 735.9, y: 98, w: 472.3, h: 196.1, wall: '-'},
            {kind: 'blue', x: -611.4, y: 98, w: 721.2, h: 196.1, wall: '+'}
        ]
    }},
    {id: 'bad-frame8-v', source: 'bad-frame8', difficulty: 3, span: 2594.8, dirs: ['up', 'down'], pieces: {
        up: [
            {kind: 'blue', x: 54.7, y: -1312.5, w: 648.7, h: 196.1},
            {kind: 'green', x: -1.9, y: -98, w: 1003.2, h: 196.1},
            {kind: 'green', x: 641.2, y: -2496.7, w: 516.7, h: 196.2},
            {kind: 'green', x: -641.1, y: -2496.7, w: 516.7, h: 196.2}
        ],
        down: [
            {kind: 'blue', x: -54.7, y: 1312.5, w: 648.7, h: 196.1},
            {kind: 'green', x: 1.9, y: 98, w: 1003.2, h: 196.1},
            {kind: 'green', x: -641.2, y: 2496.7, w: 516.7, h: 196.2},
            {kind: 'green', x: 641.1, y: 2496.7, w: 516.7, h: 196.2}
        ]
    }},
    {id: 'bad-frame10-v', source: 'bad-frame10', difficulty: 3, span: 1497.2, dirs: ['up', 'down'], pieces: {
        up: [
            {kind: 'green', x: -1.8, y: -748.6, w: 196.1, h: 1497.2},
            {kind: 'blue', x: 698.2, y: -748.6, w: 547.7, h: 196.1, wall: '+'},
            {kind: 'blue', x: -341.3, y: -748.6, w: 475.2, h: 196.1}
        ],
        down: [
            {kind: 'green', x: 1.8, y: 748.6, w: 196.1, h: 1497.2},
            {kind: 'blue', x: -698.2, y: 748.6, w: 547.7, h: 196.1, wall: '+'},
            {kind: 'blue', x: 341.3, y: 748.6, w: 475.2, h: 196.1}
        ]
    }},
    {id: 'bad-frame11-v', source: 'bad-frame11', difficulty: 3, span: 1497.2, dirs: ['up', 'down'], pieces: {
        up: [
            {kind: 'green', x: -1.8, y: -748.6, w: 196.1, h: 1497.2},
            {kind: 'blue', x: 337.5, y: -748.6, w: 475.2, h: 196.1},
            {kind: 'blue', x: -665.7, y: -748.6, w: 475.2, h: 196.1}
        ],
        down: [
            {kind: 'green', x: 1.8, y: 748.6, w: 196.1, h: 1497.2},
            {kind: 'blue', x: -337.5, y: 748.6, w: 475.2, h: 196.1},
            {kind: 'blue', x: 665.7, y: 748.6, w: 475.2, h: 196.1}
        ]
    }},
    {id: 'bad-frame14-v', source: 'bad-frame14', difficulty: 2, span: 1972.4, dirs: ['up', 'down'], pieces: {
        up: [
            {kind: 'green', x: 434.2, y: -1874.3, w: 1075.7, h: 196.1, wall: '+'},
            {kind: 'green', x: -290.4, y: -98, w: 1218.2, h: 196.1},
            {kind: 'green', x: 237.6, y: -548.7, w: 162.2, h: 705.2}
        ],
        down: [
            {kind: 'green', x: -434.2, y: 1874.3, w: 1075.7, h: 196.1, wall: '+'},
            {kind: 'green', x: 290.4, y: 98, w: 1218.2, h: 196.1},
            {kind: 'green', x: -237.6, y: 548.7, w: 162.2, h: 705.2}
        ]
    }}
].map(pattern => Object.freeze(pattern)))

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
        const pieces = this.pattern.pieces
        const elements = pieces.map(piece =>
        {
            const spec = {shape: piece.shape, x: x + piece.x, y: y + piece.y, w: piece.w, h: piece.h}
            if (piece.points)
                spec.points = piece.points.map(([px, py]) => ({x: px, y: py}))
            if (piece.motion)
                spec.motion = {speedY: piece.motion.speedY, yMin: y + piece.motion.yMin,
                               yMax: y + piece.motion.yMax, gravity: piece.motion.gravity}
            return (piece.kind == 'blue' ? MomentumBlue : MomentumGreen).shape(spec)
        })
        pieces.forEach((piece, index) =>
        {
            if (!piece.motion)
                return
            for (const side of ['yMin', 'yMax'])
            {
                const candidates = MomentumPortPatternFactory.boundCandidates(pieces, index, side)
                if (candidates)
                    elements[index].setMotionCandidates(side, candidates.map(candidate =>
                        candidate.index === undefined ? {value: y + candidate.value} :
                        pieces[candidate.index].motion ?
                            {element: elements[candidate.index], face: side == 'yMax' ? 'top' : 'bottom', gap: candidate.gap} :
                            {element: elements[candidate.index], value: y + candidate.value}))
            }
        })
        return elements
    }
    // Catalog box of a piece: {left, right, top, bottom} around (0, 0)
    static pieceBox(piece)
    {
        if (piece.shape == 'rect')
            return {left: piece.x - piece.w / 2, right: piece.x + piece.w / 2,
                    top: piece.y - piece.h / 2, bottom: piece.y + piece.h / 2}
        const xs = piece.points.map(point => piece.x + point[0])
        const ys = piece.points.map(point => piece.y + point[1])
        return {left: Math.min(...xs), right: Math.max(...xs), top: Math.min(...ys), bottom: Math.max(...ys)}
    }
    // Where the moving piece index may go on side 'yMin' | 'yMax' once the
    // piece its catalog bound sits on (the support: the nearest sibling
    // overlapping it in x on that side, its facing edge within
    // MOMENTUM_SUPPORT_GAP of the bound) is used: null for a side without a
    // support (the catalog corridor bound stays), else every sibling in its
    // path nearest first ({index, value, gap}: the face less the support's
    // gap; the support's value is the catalog bound itself), then the
    // corridor limit ({value}: the opposite catalog bound mirrored)
    static boundCandidates(pieces, index, side)
    {
        const piece = pieces[index]
        const box = MomentumPortPatternFactory.pieceBox(piece)
        const sign = side == 'yMax' ? 1 : -1
        const path = []
        pieces.forEach((sibling, j) =>
        {
            if (j == index)
                return
            const other = MomentumPortPatternFactory.pieceBox(sibling)
            if (other.right <= box.left || other.left >= box.right)
                return
            const face = side == 'yMax' ? other.top : other.bottom
            if (sign * (face - (side == 'yMax' ? box.bottom : box.top)) >= 0)
                path.push({index: j, face: face})
        })
        path.sort((a, b) => sign * (a.face - b.face))
        const bound = piece.motion[side]
        const support = path[0]
        if (!support)
            return null
        const gap = sign * (support.face - bound)
        if (gap < 0 || gap > MOMENTUM_SUPPORT_GAP)
            return null
        const opposite = side == 'yMax' ? 'yMin' : 'yMax'
        return [...path.map(entry => ({index: entry.index, gap: gap,
                                       value: entry === support ? bound : entry.face - sign * gap})),
                {value: -piece.motion[opposite]}]
    }
}
// Largest gap between a ported frame's motion bound and the face it sits on
// (the bad frames leave 0.01 * height, 10.8 at the base height 1080)
const MOMENTUM_SUPPORT_GAP = 21.6

// The user's picked concept frames for the right corridor (TASK-102 catalog,
// artifacts/TASK-102/catalog-m.json), everything in W = the corridor's
// interior width, never in pixels: span = footprint length; a piece is a
// MomentumGreen/MomentumBlue .shape spec centred on (x, y), x along from the
// footprint start, y across from the centre line (+ = floor side), polygon
// points relative to (x, y); motion {axis, min, max, speed}: the range of the
// top/left edge (min) and bottom/right edge (max), speed per cycle before
// momentumMotionScale. Placeable (momentumPlacePattern), not spawned yet.
const MOMENTUM_FRAMES_H = Object.freeze([
    {id: 'M04', difficulty: 2, span: 1.095833, pieces: [
        {kind: 'green', shape: 'rect', x: 0.141667, y: 0.177083, w: 0.083333, h: 0.416667},
        {kind: 'green', shape: 'rect', x: 0.954167, y: 0.177083, w: 0.083333, h: 0.416667},
        {kind: 'blue', shape: 'rect', x: 0.55, y: 0.09375, w: 0.125, h: 0.125, motion: {axis: 'y', min: -0.427083, max: 0.489583, speed: 0.006597}}
    ]},
    {id: 'M23', difficulty: 1, span: 0.929167, pieces: [
        {kind: 'green', shape: 'polygon', x: 0.322222, y: 0.440972, points: [[-0.222222, 0.059028], [0.111111, 0.059028], [0.111111, -0.118056]]},
        {kind: 'blue', shape: 'rect', x: 0.745833, y: 0.333333, w: 0.166667, h: 0.333333}
    ]},
    {id: 'M24', difficulty: 2, span: 0.845833, pieces: [
        {kind: 'green', shape: 'polygon', x: 0.308333, y: -0.447917, points: [[-0.208333, -0.052083], [0.104167, -0.052083], [0.104167, 0.104167]]},
        {kind: 'blue', shape: 'rect', x: 0.704167, y: -0.234375, w: 0.083333, h: 0.53125}
    ]}
].map(pattern => Object.freeze(pattern)))

// Builds one concept frame (MOMENTUM_FRAMES_H) in a right segment: the
// pieces scaled by the live corridor W, then built like a ported frame
// (MomentumPortPatternFactory, with its support candidates)
class MomentumFrameFactory
{
    constructor(pattern)
    {
        this.pattern = pattern
        this.dirs = ['right']
    }
    getUnit()
    {
        return 2 * GAMEPLAY.momentumBorders.halfWidth
    }
    getLength()
    {
        return this.pattern.span * this.getUnit()
    }
    // (x, y): the footprint start on the corridor centre line
    create(x, y)
    {
        const W = this.getUnit()
        const pieces = this.pattern.pieces.map(piece =>
        {
            const scaled = {kind: piece.kind, shape: piece.shape, x: piece.x * W, y: piece.y * W}
            if (piece.shape == 'rect')
            {
                scaled.w = piece.w * W
                scaled.h = piece.h * W
            }
            else
                scaled.points = piece.points.map(([px, py]) => [px * W, py * W])
            if (piece.motion)
                scaled.motion = {speedY: -piece.motion.speed * W, yMin: piece.motion.min * W,
                                 yMax: piece.motion.max * W, gravity: false}
            return scaled
        })
        return new MomentumPortPatternFactory({span: this.getLength(), pieces: pieces}).create(x, y)
    }
}

// Builds one vertical port (MOMENTUM_PATTERNS_PORT_V) in an up/down shaft
class MomentumPortVerticalPatternFactory
{
    constructor(pattern)
    {
        this.pattern = pattern
        this.dirs = pattern.dirs
    }
    // World units per catalog unit in a shaft of half width halfWidth
    getScale(halfWidth = momentumShaftHalfWidth())
    {
        return halfWidth / GAMEPLAY.momentumBorders.halfWidth
    }
    // Footprint length in world units
    getLength(halfWidth = momentumShaftHalfWidth())
    {
        return this.pattern.span * this.getScale(halfWidth)
    }
    // (x, y): the footprint start on the shaft centre line, its bottom going
    // up and its top going down; halfWidth: the shaft's own half width
    // (momentumSegmentHalfWidth)
    create(x, y, dir, halfWidth = momentumShaftHalfWidth())
    {
        const k = this.getScale(halfWidth)
        return this.pattern.pieces[dir].map(piece =>
        {
            const w = piece.w * k
            const across = piece.wall ? Math.sign(piece.x) * (halfWidth - w / 2) : piece.x * k
            const spec = {shape: 'rect', x: x + across, y: y + piece.y * k, w: w, h: piece.h * k}
            return (piece.kind == 'blue' ? MomentumBlue : MomentumGreen).shape(spec)
        })
    }
}

// Turn types: the port catalog's turn candidates (turnJoins), each a ported
// bad frame (MOMENTUM_PATTERNS_PORT_H, by source id) placed whole in the
// right corridor at the join: before the corner box on right->up/down, after
// it on up/down->right, never in it, so the corner itself stays open.
const MOMENTUM_PATTERNS_TURN = Object.freeze([
    {id: 'bad-frame3-turn', source: 'bad-frame3', joins: ['right->up', 'right->down']},
    {id: 'bad-frame6-turn', source: 'bad-frame6', joins: ['right->up', 'right->down', 'down->right', 'up->right']},
    {id: 'bad-frame7-turn', source: 'bad-frame7', joins: ['right->up', 'right->down']},
    {id: 'bad-frame10-turn', source: 'bad-frame10', joins: ['down->right', 'up->right']},
    {id: 'bad-frame11-turn', source: 'bad-frame11', joins: ['down->right', 'up->right']}
].map(turn =>
{
    const frame = MOMENTUM_PATTERNS_PORT_H.find(pattern => pattern.id == turn.source)
    return Object.freeze({...turn, difficulty: frame.difficulty, span: frame.span, pieces: frame.pieces})
}))

// Builds one turn type
class MomentumTurnPatternFactory
{
    constructor(pattern)
    {
        this.pattern = pattern
        this.frame = new MomentumPortPatternFactory(pattern)
    }
    // Footprint start of the frame along the right corridor, from the course
    // vertex of join: the corner box (the shaft, half width shaftHalfWidth,
    // across the corridor) plus the clearance lies between them
    getOffset(join, shaftHalfWidth = momentumShaftHalfWidth())
    {
        const clear = shaftHalfWidth +
            GAMEPLAY.momentumSpawn.turnClearanceHalfWidths * GAMEPLAY.momentumBorders.halfWidth
        return join.startsWith('right->') ? -clear - this.pattern.span : clear
    }
    // How far the pieces reach from the course vertex of join, world units:
    // back along the incoming segment and ahead along the outgoing one
    getReach(join, shaftHalfWidth)
    {
        const offset = this.getOffset(join, shaftHalfWidth)
        return join.startsWith('right->') ? {back: -offset, ahead: 0} : {back: 0, ahead: offset + this.pattern.span}
    }
    // (x, y): the course vertex of the join; join: 'right->up' etc.;
    // shaftHalfWidth: the half width of the join's vertical segment
    create(x, y, join, shaftHalfWidth)
    {
        return this.frame.create(x + this.getOffset(join, shaftHalfWidth), y)
    }
}
// Turn id -> factory, in catalog order; join -> the turn ids built for it
const momentumTurnFactories = Object.freeze(Object.fromEntries(
    MOMENTUM_PATTERNS_TURN.map(pattern => [pattern.id, new MomentumTurnPatternFactory(pattern)])))
const momentumTurnsByJoin = Object.freeze(Object.fromEntries(['right->up', 'right->down', 'down->right', 'up->right'].map(join =>
    [join, Object.freeze(MOMENTUM_PATTERNS_TURN.filter(pattern => pattern.joins.includes(join)).map(pattern => pattern.id))])))

// Catalog id -> factory: the ported bad frames first, in port catalog
// order, then their vertical variants (bad-frameN-v), then the concept
// frames (placeable only: not in momentumPatternsByDir)
const momentumPatternFactories = Object.freeze(Object.fromEntries([
    ...MOMENTUM_PATTERNS_PORT_H.map(pattern => [pattern.id, new MomentumPortPatternFactory(pattern)]),
    ...MOMENTUM_PATTERNS_PORT_V.map(pattern => [pattern.id, new MomentumPortVerticalPatternFactory(pattern)]),
    ...MOMENTUM_FRAMES_H.map(pattern => [pattern.id, new MomentumFrameFactory(pattern)])
]))
// Segment direction -> the ids spawned there: right segments spawn the
// ported frames, shafts their vertical variants only. A variant restricted
// to one direction is only registered there.
const momentumPatternsByDir = Object.freeze({
    right: Object.freeze(MOMENTUM_PATTERNS_PORT_H.map(pattern => pattern.id)),
    up: Object.freeze(MOMENTUM_PATTERNS_PORT_V.filter(pattern => pattern.dirs.includes('up')).map(pattern => pattern.id)),
    down: Object.freeze(MOMENTUM_PATTERNS_PORT_V.filter(pattern => pattern.dirs.includes('down')).map(pattern => pattern.id))
})

// Holds placed patterns, one generation group each, with the group's box
// kept apart from its pieces: a group is scored once it is passed (left of
// the view, or behind it vertically) even when its one-time pieces have
// already faded, and deleted with its pieces past the deletion borders. A
// group placed for course segment index counts as behind vertically only
// once the camera has reached that segment: screen.verticalTravel keeps the
// last shaft's direction, so after an up shaft a down shaft's patterns
// spawned ahead, below the view, would look behind.
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
    place(elements, segment = -Infinity)
    {
        const generationGroupId = this.nextGenerationGroupId++
        const group = {id: generationGroupId, left: Infinity, top: Infinity, right: -Infinity, bottom: -Infinity,
                       scored: false, segment: segment}
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
            const reached = group.segment <= screen.segmentIndex
            if (!group.scored && (group.right + screen.x < 0 || reached && screen.isBoxBehind(group.top, group.bottom, 0)))
            {
                group.scored = true
                changeScoreText()
            }
            const behind = reached && screen.isBoxBehind(group.top, group.bottom, margin)
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
    // Where patterns of the stretch from segment index may go (course
    // distance from its start) and whether a turn takes the join at its end.
    // A turn lies in the right corridor only (before or after the corner
    // box), so it leaves the shaft's room to its vertical patterns. It needs
    // its piece reach (MomentumTurnPatternFactory.getReach) on both
    // stretches, plus the join margin at the far end of the next one;
    // patterns keep the minimum gap off its pieces. Join margins and the turn's square across the
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
        // Only the turn types whose pieces fit both stretches, never the
        // latest one of the join again
        const latest = (this.recentIds[join] || []).slice(-1)[0]
        const turns = momentumTurnsByJoin[join].filter(id =>
        {
            if (id === latest)
                return false
            const reach = momentumTurnFactories[id].getReach(join, shaftHalfWidth)
            return start <= length - reach.back && nextLength >= reach.ahead + nextMargin
        })
        let turn = null, reach = null
        if (turns.length && random(0, 100) < options.turnChancePercent)
        {
            turn = this.pickType(turns, id => momentumTurnFactories[id].pattern.difficulty, this.getAvoidedTypes(join))
            reach = momentumTurnFactories[turn].getReach(join, shaftHalfWidth)
        }
        const gap = options.gapViewWidths.min * width / scale[version]
        return {segment: segment, index: index, last: last, vertex: {x: end.x1, y: end.y1}, cursor: start,
                join: join, turn: turn, shaftHalfWidth: shaftHalfWidth,
                end: turn ? Math.min(length - margin, length - reach.back - gap) : length - margin,
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
                // Only the types that fit the room left (the long ported
                // frames, and in wide shafts their scaled variants, may
                // never fit a short stretch), never the latest one of the
                // direction again
                const halfWidth = momentumSegmentHalfWidth(segment)
                const latest = (this.recentIds[segment.dir] || []).slice(-1)[0]
                const ids = momentumPatternsByDir[segment.dir].filter(id => id !== latest &&
                    plan.cursor + momentumPatternFactories[id].getLength(halfWidth) <= plan.end)
                if (!ids.length)
                {
                    plan.filled = true
                    continue
                }
                const id = this.pickType(ids, id => momentumPatternFactories[id].pattern.difficulty,
                                         this.getAvoidedTypes(segment.dir))
                const factory = momentumPatternFactories[id]
                const d = momentumDirection(segment.dir)
                this.place(factory.create(segment.x0 + d.x * plan.cursor, segment.y0 + d.y * plan.cursor, segment.dir,
                                          halfWidth), plan.last)
                this.placedType(segment.dir, id)
                this.spawned(id, segment.dir == 'right' ? 'horizontal' : 'vertical', segment.dir,
                             factory.pattern.difficulty, arc + plan.cursor)
                plan.cursor += factory.getLength(halfWidth) + this.getGap()
                continue
            }
            if (plan.turn)
            {
                if (reached(segment, arc + plan.turnArc))
                    return
                const factory = momentumTurnFactories[plan.turn]
                this.place(factory.create(plan.vertex.x, plan.vertex.y, plan.join, plan.shaftHalfWidth),
                           plan.join.startsWith('right->') ? plan.last : plan.last + 1)
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
// pattern in a direction it is not registered for (a ported frame
// bad-frameN outside a right segment, a vertical variant bad-frameN-v
// outside its shaft directions). A vertical variant spans halfWidth
// (default: a shaft built now, momentumShaftHalfWidth). Elements
// also carry their polygon points, speedY and motion (the effective
// bounds, MomentumOneTime.getMotionBound).
function momentumPlacePattern(id, x, y, dir = 'right', halfWidth = momentumShaftHalfWidth())
{
    let factory = momentumPatternFactories[id]
    if (factory && factory.dirs && !factory.dirs.includes(dir))
        factory = undefined
    const floor = version == 'momentum' && floors ? floors.find(f => f instanceof MomentumPatternFloor) : null
    if (!factory || !floor)
        return null
    const elements = factory.create(x, y, dir, halfWidth)
    const group = floor.place(elements)
    return {id: id, group: group, length: factory.getLength(halfWidth), elements: elements.map(element =>
    {
        const bounds = getElementBounds(element)
        return {className: element.constructor.name, lethal: isLethalElement(element),
                left: bounds.left, top: bounds.top, right: bounds.right, bottom: bounds.bottom,
                points: element.getPoints().map(point => [point.x, point.y]), speedY: element.speedY || 0,
                motion: element.motion && {yMin: element.getMotionBound('yMin'), yMax: element.getMotionBound('yMax'),
                                           gravity: element.motion.gravity}}
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
    const offset = factory.getOffset(join, shaftHalfWidth)
    return {id: id, join: join, segment: segmentIndex, group: group, shaftHalfWidth: shaftHalfWidth,
            footprint: {x0: segment.x1 + offset, x1: segment.x1 + offset + factory.pattern.span},
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
