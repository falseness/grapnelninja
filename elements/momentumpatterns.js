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
// centred on (x, y) in world units at the base half width
// (GAMEPLAY.momentumBorders.shaftReferenceHalfWidth): x across from
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
// momentumMotionScale. Spawned (momentumPatternsByDir) and placeable (momentumPlacePattern).
const MOMENTUM_FRAMES_H = Object.freeze([
    {id: 'M04', difficulty: 2, span: 1.095833, pieces: [
        {kind: 'green', shape: 'rect', x: 0.141667, y: 0.177083, w: 0.083333, h: 0.416667},
        {kind: 'green', shape: 'rect', x: 0.954167, y: 0.177083, w: 0.083333, h: 0.416667},
        {kind: 'blue', shape: 'rect', x: 0.55, y: 0.09375, w: 0.125, h: 0.125, motion: {axis: 'y', min: -0.427083, max: 0.489583, speed: 0.000942}}
    ]},
    {id: 'M23', difficulty: 1, span: 0.929167, pieces: [
        {kind: 'green', shape: 'polygon', x: 0.322222, y: 0.440972, points: [[-0.222222, 0.059028], [0.111111, 0.059028], [0.111111, -0.118056]]},
        {kind: 'blue', shape: 'rect', x: 0.745833, y: 0.333333, w: 0.166667, h: 0.333333}
    ]},
    {id: 'M24', difficulty: 2, span: 0.845833, pieces: [
        {kind: 'green', shape: 'polygon', x: 0.308333, y: -0.447917, points: [[-0.208333, -0.052083], [0.104167, -0.052083], [0.104167, 0.104167]]},
        {kind: 'blue', shape: 'rect', x: 0.704167, y: -0.234375, w: 0.083333, h: 0.53125}
    ]},
    // M46, M66: the thin green cap is its own piece lying on the blue's top
    {id: 'M46', difficulty: 2, span: 1.095833, pieces: [
        {kind: 'green', shape: 'polygon', x: 0.308333, y: 0.444444, points: [[-0.208333, 0.055556], [0.104167, 0.055556], [0.104167, -0.111111]]},
        {kind: 'blue', shape: 'rect', x: 0.870833, y: 0.333333, w: 0.25, h: 0.333333},
        {kind: 'green', shape: 'rect', x: 0.870833, y: 0.14375, w: 0.25, h: 0.045833}
    ]},
    {id: 'M47', difficulty: 2, span: 0.929167, pieces: [
        {kind: 'green', shape: 'polygon', x: 0.225, y: 0.427083, points: [[-0.125, 0.072917], [-0.125, -0.145833], [0.25, 0.072917]]},
        {kind: 'blue', shape: 'rect', x: 0.777083, y: -0.1875, w: 0.104167, h: 0.625}
    ]},
    {id: 'M66', difficulty: 4, span: 1.054167, pieces: [
        {kind: 'green', shape: 'polygon', x: 0.308333, y: 0.440972, points: [[-0.208333, 0.059028], [0.104167, 0.059028], [0.104167, -0.118056]]},
        {kind: 'blue', shape: 'rect', x: 0.860417, y: 0.1875, w: 0.1875, h: 0.625},
        {kind: 'green', shape: 'rect', x: 0.860417, y: -0.147917, w: 0.1875, h: 0.045833}
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

// The user's picked concept frames for the shafts (TASK-102 catalog), in W =
// the shaft's interior width (2 x its half width), never in pixels: span =
// footprint length; a piece is a rect centred on (x, y), x across from the
// shaft centre line (+ = right), y along from the footprint's top end (screen
// down). The -up entries are the down frames mirrored along the shaft (the
// caps end up under the ledges: the user's mirror decision), so going up the
// pieces are met in the order and at the distances they are met falling down.
// motion {axis: 'x', min, max, speed}: the bounds of the left (min) and
// right (max) edge across from the centre line, speed per cycle before
// momentumMotionScale. Spawned (momentumPatternsByDir) and placeable (momentumPlacePattern).
const MOMENTUM_FRAMES_V = Object.freeze([
    // M11, M30: a flat blue bar sweeping left and right between the walls
    {id: 'M11', dirs: ['down'], difficulty: 3, span: 1.033333, pieces: [
        {kind: 'blue', shape: 'rect', x: 0, y: 0.50625, w: 0.416667, h: 0.0625, motion: {axis: 'x', min: -0.5, max: 0.5, speed: 0.000694}},
        {kind: 'green', shape: 'rect', x: -0.477083, y: 0.225, w: 0.045833, h: 0.25},
        {kind: 'green', shape: 'rect', x: 0.477083, y: 0.808333, w: 0.045833, h: 0.25}
    ]},
    {id: 'M30', dirs: ['down'], difficulty: 3, span: 0.679167, pieces: [
        {kind: 'green', shape: 'rect', x: 0.354167, y: 0.122917, w: 0.291667, h: 0.045833},
        {kind: 'blue', shape: 'rect', x: -0.15625, y: 0.547917, w: 0.375, h: 0.0625, motion: {axis: 'x', min: -0.5, max: 0.5, speed: 0.000744}}
    ]},
    // Capped blue ledges from alternating walls: the green cap is its own piece
    {id: 'M93', dirs: ['down'], difficulty: 3, span: 0.7875, pieces: [
        {kind: 'blue', shape: 'rect', x: -0.1875, y: 0.177083, w: 0.625, h: 0.0625},
        {kind: 'green', shape: 'rect', x: -0.1875, y: 0.122917, w: 0.625, h: 0.045833},
        {kind: 'blue', shape: 'rect', x: 0.1875, y: 0.65625, w: 0.625, h: 0.0625},
        {kind: 'green', shape: 'rect', x: 0.1875, y: 0.602083, w: 0.625, h: 0.045833}
    ]},
    {id: 'M110', dirs: ['down'], difficulty: 4, span: 1.141667, pieces: [
        {kind: 'blue', shape: 'rect', x: -0.229167, y: 0.177083, w: 0.541667, h: 0.0625},
        {kind: 'green', shape: 'rect', x: -0.229167, y: 0.122917, w: 0.541667, h: 0.045833},
        {kind: 'blue', shape: 'rect', x: 0.229167, y: 0.59375, w: 0.541667, h: 0.0625},
        {kind: 'green', shape: 'rect', x: 0.229167, y: 0.539583, w: 0.541667, h: 0.045833},
        {kind: 'blue', shape: 'rect', x: -0.229167, y: 1.010417, w: 0.541667, h: 0.0625},
        {kind: 'green', shape: 'rect', x: -0.229167, y: 0.95625, w: 0.541667, h: 0.045833}
    ]},
    {id: 'M11-up', dirs: ['up'], difficulty: 3, span: 1.033333, pieces: [
        {kind: 'blue', shape: 'rect', x: 0, y: 0.527083, w: 0.416667, h: 0.0625, motion: {axis: 'x', min: -0.5, max: 0.5, speed: 0.000694}},
        {kind: 'green', shape: 'rect', x: -0.477083, y: 0.808333, w: 0.045833, h: 0.25},
        {kind: 'green', shape: 'rect', x: 0.477083, y: 0.225, w: 0.045833, h: 0.25}
    ]},
    {id: 'M30-up', dirs: ['up'], difficulty: 3, span: 0.679167, pieces: [
        {kind: 'green', shape: 'rect', x: 0.354167, y: 0.55625, w: 0.291667, h: 0.045833},
        {kind: 'blue', shape: 'rect', x: -0.15625, y: 0.13125, w: 0.375, h: 0.0625, motion: {axis: 'x', min: -0.5, max: 0.5, speed: 0.000744}}
    ]},
    {id: 'M93-up', dirs: ['up'], difficulty: 3, span: 0.7875, pieces: [
        {kind: 'blue', shape: 'rect', x: -0.1875, y: 0.610417, w: 0.625, h: 0.0625},
        {kind: 'green', shape: 'rect', x: -0.1875, y: 0.664583, w: 0.625, h: 0.045833},
        {kind: 'blue', shape: 'rect', x: 0.1875, y: 0.13125, w: 0.625, h: 0.0625},
        {kind: 'green', shape: 'rect', x: 0.1875, y: 0.185417, w: 0.625, h: 0.045833}
    ]},
    {id: 'M110-up', dirs: ['up'], difficulty: 4, span: 1.141667, pieces: [
        {kind: 'blue', shape: 'rect', x: -0.229167, y: 0.964584, w: 0.541667, h: 0.0625},
        {kind: 'green', shape: 'rect', x: -0.229167, y: 1.01875, w: 0.541667, h: 0.045833},
        {kind: 'blue', shape: 'rect', x: 0.229167, y: 0.547917, w: 0.541667, h: 0.0625},
        {kind: 'green', shape: 'rect', x: 0.229167, y: 0.602084, w: 0.541667, h: 0.045833},
        {kind: 'blue', shape: 'rect', x: -0.229167, y: 0.13125, w: 0.541667, h: 0.0625},
        {kind: 'green', shape: 'rect', x: -0.229167, y: 0.185417, w: 0.541667, h: 0.045833}
    ]}
].map(pattern => Object.freeze(pattern)))

// Builds one concept frame (MOMENTUM_FRAMES_V) in an up/down shaft, scaled by
// the live shaft W
class MomentumFrameVerticalFactory
{
    constructor(pattern)
    {
        this.pattern = pattern
        this.dirs = pattern.dirs
    }
    getUnit(halfWidth = momentumShaftHalfWidth())
    {
        return 2 * halfWidth
    }
    getLength(halfWidth = momentumShaftHalfWidth())
    {
        return this.pattern.span * this.getUnit(halfWidth)
    }
    // (x, y): the footprint start on the shaft centre line, its top going
    // down and its bottom going up; halfWidth: the shaft's own half width
    // (momentumSegmentHalfWidth). A rect is cut at the wall faces, so a
    // ledge reaching from a wall ends on its face despite catalog rounding;
    // an axis-x sweeper reverses at the bounds centre + min/max x W.
    create(x, y, dir, halfWidth = momentumShaftHalfWidth())
    {
        const W = this.getUnit(halfWidth)
        const top = dir == 'up' ? y - this.getLength(halfWidth) : y
        return this.pattern.pieces.map(piece =>
        {
            const left = Math.max(-halfWidth, (piece.x - piece.w / 2) * W)
            const right = Math.min(halfWidth, (piece.x + piece.w / 2) * W)
            const spec = {shape: 'rect', x: x + (left + right) / 2, y: top + piece.y * W, w: right - left, h: piece.h * W}
            if (piece.motion)
                spec.motion = {axis: 'x', speedX: piece.motion.speed * W,
                               xMin: x + piece.motion.min * W, xMax: x + piece.motion.max * W}
            return (piece.kind == 'blue' ? MomentumBlue : MomentumGreen).shape(spec)
        })
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
    // World units per catalog unit in a shaft of half width halfWidth (the
    // catalog is in the shafts' reference half width, TASK-128)
    getScale(halfWidth = momentumShaftHalfWidth())
    {
        return halfWidth / GAMEPLAY.momentumBorders.shaftReferenceHalfWidth
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
// Turn id -> factory, in catalog order (placeable only: not spawned)
const momentumTurnFactories = Object.freeze(Object.fromEntries(
    MOMENTUM_PATTERNS_TURN.map(pattern => [pattern.id, new MomentumTurnPatternFactory(pattern)])))

// The user's picked corner frames (TASK-102 catalog), anchored at the course
// vertex (where the two corridor centre lines meet) and free to use the
// corner box: join '<incoming>-<outgoing>'; a piece is centred on (x, y)
// from the vertex, x in shaft W (2 x the shaft's half width), y in corridor
// W (2 x GAMEPLAY.momentumBorders.halfWidth), sizes and polygon points
// scaled the same per axis; reach {in, out}: how far the pieces extend back
// along the incoming corridor and ahead along the outgoing one (+ 0.1 W), in
// W of that corridor's travel axis. motion {axis: 'x', min, max, speed} as in
// MOMENTUM_FRAMES_V, across from the vertex in shaft W; {axis: 'y', ...} the
// top / bottom edge bounds from the vertex in corridor W. Spawned per join
// (momentumTurnsByJoin), placeable with momentumPlaceTurn / momentumPlaceCorner.
const MOMENTUM_FRAMES_TURN = Object.freeze([
    // M18 Kicker: a green wedge in the outer bottom corner kicks the run up
    {id: 'M18', join: 'right-up', difficulty: 2, reach: {in: 0.583333, out: 0.572917}, pieces: [
        {kind: 'green', shape: 'polygon', x: 0.404861, y: 0.432639, points: [[-0.190278, 0.067361], [0.095139, 0.067361], [0.095139, -0.134722]]},
        {kind: 'blue', shape: 'rect', x: -0.420833, y: -0.410417, w: 0.125, h: 0.125}
    ]},
    // M60 Lip Kicker: a green wedge on the floor's lip, a blue bar sweeping the shaft
    {id: 'M60', join: 'right-down', difficulty: 3, reach: {in: 0.822917, out: 0.6}, pieces: [
        {kind: 'green', shape: 'polygon', x: -0.574306, y: 0.458333, points: [[-0.148611, 0.041667], [0.074306, 0.041667], [0.074306, -0.083333]]},
        {kind: 'blue', shape: 'rect', x: 0.235417, y: 0.458333, w: 0.375, h: 0.0625, motion: {axis: 'x', min: -0.5, max: 0.5, speed: 0.000744}}
    ]},
    // M39 Ramp Exit: a green slope at the shaft bottom, an elevator patrolling the exit corridor
    {id: 'M39', join: 'down-right', difficulty: 2, reach: {in: 0.53125, out: 0.81875}, pieces: [
        {kind: 'green', shape: 'polygon', x: -0.302083, y: 0.404861, points: [[-0.197917, 0.095139], [0.395833, 0.095139], [-0.197917, -0.190278]]},
        {kind: 'blue', shape: 'rect', x: 0.65625, y: -0.36875, w: 0.125, h: 0.125, motion: {axis: 'y', min: -0.5, max: 0.5, speed: 0.001042}}
    ]},
    // M117 Slope Window: the bottom slope, a blue wall across the exit with one window
    {id: 'M117', join: 'down-right', difficulty: 3, reach: {in: 0.6, out: 0.860417}, pieces: [
        {kind: 'green', shape: 'polygon', x: -0.302083, y: 0.404861, points: [[-0.197917, 0.095139], [0.395833, 0.095139], [-0.197917, -0.190278]]},
        {kind: 'blue', shape: 'rect', x: 0.71875, y: -0.34375, w: 0.083333, h: 0.3125},
        {kind: 'blue', shape: 'rect', x: 0.71875, y: 0.34375, w: 0.083333, h: 0.3125}
    ]},
    // M134 Double Window: the bottom slope, two blue walls with offset 0.5 W windows
    {id: 'M134', join: 'down-right', difficulty: 4, reach: {in: 0.6, out: 0.964583}, pieces: [
        {kind: 'green', shape: 'polygon', x: -0.302083, y: 0.404861, points: [[-0.197917, 0.095139], [0.395833, 0.095139], [-0.197917, -0.190278]]},
        {kind: 'blue', shape: 'rect', x: 0.604167, y: -0.361458, w: 0.0625, h: 0.277083},
        {kind: 'blue', shape: 'rect', x: 0.604167, y: 0.388542, w: 0.0625, h: 0.222917},
        {kind: 'blue', shape: 'rect', x: 0.833333, y: -0.444792, w: 0.0625, h: 0.110417},
        {kind: 'blue', shape: 'rect', x: 0.833333, y: 0.305208, w: 0.0625, h: 0.389583}
    ]},
    // M40 Corner Deflector: a green triangle in the outer top corner turns the climb right, an elevator in the exit
    {id: 'M40', join: 'up-right', difficulty: 4, reach: {in: 0.56875, out: 0.860417}, pieces: [
        {kind: 'green', shape: 'polygon', x: -0.371528, y: -0.371528, points: [[-0.128472, -0.128472], [0.256944, -0.128472], [-0.128472, 0.256944]]},
        {kind: 'blue', shape: 'rect', x: 0.697917, y: -0.385417, w: 0.125, h: 0.125, motion: {axis: 'y', min: -0.5, max: 0.5, speed: 0.001042}},
        {kind: 'blue', shape: 'rect', x: 0.395833, y: 0.395833, w: 0.145833, h: 0.145833}
    ]},
    // M98 Deflect Window: the corner triangle, a blue wall across the exit with one 0.5 W window
    {id: 'M98', join: 'up-right', difficulty: 4, reach: {in: 0.6, out: 0.902083}, pieces: [
        {kind: 'green', shape: 'polygon', x: -0.371528, y: -0.371528, points: [[-0.128472, -0.128472], [0.256944, -0.128472], [-0.128472, 0.256944]]},
        {kind: 'blue', shape: 'rect', x: 0.75, y: -0.385417, w: 0.104167, h: 0.229167},
        {kind: 'blue', shape: 'rect', x: 0.75, y: 0.364583, w: 0.104167, h: 0.270833}
    ]},
    // M136 Deflect Two Windows: the corner triangle, two blue walls with offset 0.5 W windows
    {id: 'M136', join: 'up-right', difficulty: 4, reach: {in: 0.6, out: 0.985417}, pieces: [
        {kind: 'green', shape: 'polygon', x: -0.371528, y: -0.371528, points: [[-0.128472, -0.128472], [0.256944, -0.128472], [-0.128472, 0.256944]]},
        {kind: 'blue', shape: 'rect', x: 0.625, y: -0.453125, w: 0.0625, h: 0.09375},
        {kind: 'blue', shape: 'rect', x: 0.625, y: 0.296875, w: 0.0625, h: 0.40625},
        {kind: 'blue', shape: 'rect', x: 0.854167, y: -0.401042, w: 0.0625, h: 0.197917},
        {kind: 'blue', shape: 'rect', x: 0.854167, y: 0.348958, w: 0.0625, h: 0.302083}
    ]}
].map(pattern => Object.freeze(pattern)))

// A corner frame coordinate (in W from the vertex) within 1e-5 of a corridor
// wall face (+-0.5) is that face
function momentumSnapWallFace(v)
{
    return Math.abs(Math.abs(v) - 0.5) < 1e-5 ? Math.sign(v) * 0.5 : v
}

// Builds one corner frame (MOMENTUM_FRAMES_TURN) at a join vertex, scaled
// per axis by the live shaft W (x) and corridor W (y)
class MomentumCornerFrameFactory
{
    constructor(pattern)
    {
        this.pattern = pattern
        this.join = pattern.join.replace('-', '->')
    }
    getUnits(shaftHalfWidth = momentumShaftHalfWidth())
    {
        return {x: 2 * shaftHalfWidth, y: 2 * GAMEPLAY.momentumBorders.halfWidth}
    }
    // Reach from the vertex in world units: a right corridor runs along x
    // (shaft W), a shaft along y (corridor W)
    getReach(join = this.join, shaftHalfWidth = momentumShaftHalfWidth())
    {
        const W = this.getUnits(shaftHalfWidth)
        const [incoming, outgoing] = join.split('->')
        return {in: this.pattern.reach.in * (incoming == 'right' ? W.x : W.y),
                out: this.pattern.reach.out * (outgoing == 'right' ? W.x : W.y)}
    }
    // (x, y): the course vertex; shaftHalfWidth: the half width of the
    // join's vertical segment
    create(x, y, shaftHalfWidth = momentumShaftHalfWidth())
    {
        const W = this.getUnits(shaftHalfWidth)
        return this.pattern.pieces.map(piece =>
        {
            const spec = {shape: piece.shape, x: x + piece.x * W.x, y: y + piece.y * W.y}
            if (piece.shape == 'rect')
            {
                // A rect edge on a corridor wall face (+-0.5 W from the
                // vertex) lands on it exactly: the catalog's 6 decimals
                // put e.g. M136's -0.401042 - 0.197917 / 2 a 1e-3 world
                // unit inside the wall body (TASK-113)
                const [x0, x1] = [piece.x - piece.w / 2, piece.x + piece.w / 2].map(momentumSnapWallFace)
                const [y0, y1] = [piece.y - piece.h / 2, piece.y + piece.h / 2].map(momentumSnapWallFace)
                spec.x = x + (x0 + x1) / 2 * W.x
                spec.y = y + (y0 + y1) / 2 * W.y
                spec.w = (x1 - x0) * W.x
                spec.h = (y1 - y0) * W.y
            }
            else
                spec.points = piece.points.map(([px, py]) => ({x: px * W.x, y: py * W.y}))
            if (piece.motion && piece.motion.axis == 'x')
                spec.motion = {axis: 'x', speedX: piece.motion.speed * W.x,
                               xMin: x + piece.motion.min * W.x, xMax: x + piece.motion.max * W.x}
            else if (piece.motion)
                spec.motion = {speedY: -piece.motion.speed * W.y, yMin: y + piece.motion.min * W.y,
                               yMax: y + piece.motion.max * W.y, gravity: false}
            return (piece.kind == 'blue' ? MomentumBlue : MomentumGreen).shape(spec)
        })
    }
}
// Corner frame id -> factory; join -> the corner frame ids spawned there
const momentumCornerFrameFactories = Object.freeze(Object.fromEntries(
    MOMENTUM_FRAMES_TURN.map(pattern => [pattern.id, new MomentumCornerFrameFactory(pattern)])))
const momentumTurnsByJoin = Object.freeze(Object.fromEntries(['right->up', 'right->down', 'down->right', 'up->right'].map(join =>
    [join, Object.freeze(MOMENTUM_FRAMES_TURN.filter(pattern => pattern.join.replace('-', '->') == join).map(pattern => pattern.id))])))

// Catalog id -> factory: the ported bad frames first, in port catalog
// order, then their vertical variants (bad-frameN-v), then the concept
// frames
const momentumPatternFactories = Object.freeze(Object.fromEntries([
    ...MOMENTUM_PATTERNS_PORT_H.map(pattern => [pattern.id, new MomentumPortPatternFactory(pattern)]),
    ...MOMENTUM_PATTERNS_PORT_V.map(pattern => [pattern.id, new MomentumPortVerticalPatternFactory(pattern)]),
    ...MOMENTUM_FRAMES_H.map(pattern => [pattern.id, new MomentumFrameFactory(pattern)]),
    ...MOMENTUM_FRAMES_V.map(pattern => [pattern.id, new MomentumFrameVerticalFactory(pattern)])
]))
// Segment direction -> the ids spawned there: the user's picked concept
// frames only (MOMENTUM_FRAMES_H / _V, each shaft frame in its own
// direction). The ported bad frames and their vertical variants stay
// placeable (momentumPlacePattern) but no longer spawn.
const momentumPatternsByDir = Object.freeze({
    right: Object.freeze(MOMENTUM_FRAMES_H.map(pattern => pattern.id)),
    up: Object.freeze(MOMENTUM_FRAMES_V.filter(pattern => pattern.dirs.includes('up')).map(pattern => pattern.id)),
    down: Object.freeze(MOMENTUM_FRAMES_V.filter(pattern => pattern.dirs.includes('down')).map(pattern => pattern.id))
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
// segments of one direction), a corner frame may take the join at the stretch
// end (its pieces' reach on both stretches), the rest gets patterns of its
// direction, spaced like the bad obstacle floor
// (Floor.alignBadVersionGeneratedElements). Types are picked with
// integer weights by difficulty (Floor.generateElements), easy types first,
// skipping the options.avoidRecent types placed last in the same direction
// (up and down together; corners: join) while another type is left, and never
// the last one in the same direction or join while there is another type (a
// join with a single corner frame may repeat it).
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
    // distance from its start) and whether a corner frame takes the join at
    // its end. A corner frame sits at the course vertex and claims its piece
    // reach (MomentumCornerFrameFactory.getReach) back along this stretch
    // and ahead along the next one, plus the join margin at the far end of
    // the next one; the straight patterns of both stretches keep the
    // minimum gap off that reach. Without a corner frame the join margins
    // apply. Join margins and the corner box follow the shafts' own half
    // widths.
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
        // Only the corner frames whose pieces fit both stretches, never the
        // latest one of the join again while the join has another
        const candidates = momentumTurnsByJoin[join] || []
        const latest = candidates.length > 1 ? (this.recentIds[join] || []).slice(-1)[0] : undefined
        const turns = candidates.filter(id =>
        {
            if (id === latest)
                return false
            const reach = momentumCornerFrameFactories[id].getReach(join, shaftHalfWidth)
            return start <= length - reach.in && nextLength >= reach.out + nextMargin
        })
        let turn = null, reach = null
        if (turns.length && random(0, 100) < options.turnChancePercent)
        {
            turn = this.pickType(turns, id => momentumCornerFrameFactories[id].pattern.difficulty,
                                 candidates.length > 1 ? this.getAvoidedTypes(join) : [])
            reach = momentumCornerFrameFactories[turn].getReach(join, shaftHalfWidth)
        }
        const gap = options.gapViewWidths.min * width / scale[version]
        return {segment: segment, index: index, last: last, vertex: {x: end.x1, y: end.y1}, cursor: start,
                join: join, turn: turn, shaftHalfWidth: shaftHalfWidth,
                end: turn ? Math.min(length - margin, length - reach.in - gap) : length - margin,
                turnArc: turn ? length - reach.in : 0, nextClaim: turn ? reach.out + gap : 0, filled: false}
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
                // Only the types that fit the room left (a long frame, and
                // in a wide shaft any shaft frame, may never fit a short
                // stretch), never the latest one of the direction again
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
                // Its group belongs to the outgoing segment: the pieces
                // reach into it, so they only count as behind vertically
                // once the camera has turned the corner
                const factory = momentumCornerFrameFactories[plan.turn]
                this.place(factory.create(plan.vertex.x, plan.vertex.y, plan.shaftHalfWidth), plan.last + 1)
                this.placedType(plan.join, plan.turn)
                this.spawned(plan.turn, 'corner', plan.join, factory.pattern.difficulty, arc + plan.turnArc)
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
// bounds, MomentumOneTime.getMotionBound; axis x: xMin, xMax, speedX).
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
                motion: element.motion && (element.motion.axis == 'x' ?
                    {axis: 'x', xMin: element.motion.xMin, xMax: element.motion.xMax, speedX: element.speedX} :
                    {yMin: element.getMotionBound('yMin'), yMax: element.getMotionBound('yMax'),
                     gravity: element.motion.gravity})}
    })}
}
window.momentumPlacePattern = momentumPlacePattern

// Places turn type id on the join at the end of course segment segmentIndex
// (between it and the next segment). Returns the placed boxes, or null
// outside momentum, on a straight join and on a join the type is not built for.
// A corner frame id (MOMENTUM_FRAMES_TURN) is placed by momentumPlaceCorner.
function momentumPlaceTurn(id, segmentIndex)
{
    if (momentumCornerFrameFactories[id])
        return momentumPlaceCorner(id, segmentIndex)
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

// Places corner frame id at the vertex of the join at the end of course
// segment segmentIndex. Returns the vertex, the per-axis W, the reach (world
// units) and the placed pieces (bounds, points, x or y motion), or null
// outside momentum and on any other join than the frame's.
function momentumPlaceCorner(id, segmentIndex)
{
    const factory = momentumCornerFrameFactories[id]
    const floor = version == 'momentum' && floors ? floors.find(f => f instanceof MomentumPatternFloor) : null
    if (!factory || !floor || typeof momentumCourse === 'undefined' || !momentumCourse)
        return null
    const segment = momentumCourse.segment(segmentIndex)
    const join = segment.dir + '->' + momentumCourse.segment(segmentIndex + 1).dir
    if (join != factory.join)
        return null
    const shaft = segment.dir == 'right' ? momentumCourse.segment(segmentIndex + 1) : segment
    const shaftHalfWidth = momentumSegmentHalfWidth(shaft)
    const W = factory.getUnits(shaftHalfWidth)
    const elements = factory.create(segment.x1, segment.y1, shaftHalfWidth)
    const group = floor.place(elements)
    return {id: id, join: join, segment: segmentIndex, group: group, vertex: {x: segment.x1, y: segment.y1},
            shaftW: W.x, corridorW: W.y, reach: factory.getReach(join, shaftHalfWidth), elements: elements.map(element =>
    {
        const bounds = getElementBounds(element)
        return {className: element.constructor.name, lethal: isLethalElement(element),
                left: bounds.left, top: bounds.top, right: bounds.right, bottom: bounds.bottom,
                points: element.getPoints().map(point => [point.x, point.y]),
                motion: !element.motion ? null : element.motion.axis == 'x' ?
                    {axis: 'x', xMin: element.motion.xMin, xMax: element.motion.xMax, speedX: element.speedX} :
                    {axis: 'y', yMin: element.motion.yMin, yMax: element.motion.yMax, speedY: element.speedY}}
    })}
}
window.momentumPlaceCorner = momentumPlaceCorner

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
