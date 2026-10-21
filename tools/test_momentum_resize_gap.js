// TASK-152: opposite shafts after a mid-run resize. A shaft built at width
// 2520 keeps its half width; after a resize to 1920 a 2500-unit corridor
// then an opposite shaft must leave the earlier shaft's wall body (thickness
// + backing past its inner face) clear of the new shaft's corridor, or the
// course flips the new shaft to the same direction.
// Loads the real gameoptions.js, elements/momentumcourse.js,
// elements/momentumborders.js and index.html's course wiring in a VM.
// Usage: node tools/test_momentum_resize_gap.js [repo root]
const fs = require('fs'), path = require('path'), vm = require('vm')
const root = path.resolve(process.argv[2] || path.join(__dirname, '..'))
const read = f => fs.readFileSync(path.join(root, f), 'utf8')
const draws = []
const ctx = {console, Object, JSON, Math: Object.create(Math)}
ctx.Math.random = () => {
    if (!draws.length)
        throw new Error('out of scripted draws')
    return draws.shift()
}
vm.createContext(ctx)
vm.runInContext(`var height = 1080, width = 2520
var scale = {classic: 1, bad: 1 / 2.2, momentum: 1 / 2.2}
class Ground {}; class SideFloor {}`, ctx)
const options = read('gameoptions.js')
vm.runInContext(options.slice(options.indexOf('const GAMEPLAY'), options.indexOf('const defaultEqualityTolerance'))
    .replace('const GAMEPLAY', 'var GAMEPLAY'), ctx)
for (const f of ['elements/momentumcourse.js', 'elements/momentumborders.js'])
    vm.runInContext(read(f).replace(/^class (\w+)/mg, 'var $1 = class $1'), ctx)
// index.html startMomentumVersion: the oppositeShaftGap callback and the
// MomentumCourse construction, verbatim
const html = read('index.html')
const wiring = html.slice(html.indexOf('const oppositeShaftGap'), html.indexOf('screen = new MomentumScreen'))
if (!wiring.includes('new MomentumCourse'))
    throw new Error('course wiring not found in index.html')
vm.runInContext(`var borders = GAMEPLAY.momentumBorders, firstMinLen = 0, momentumCourse
${wiring}
this.course = momentumCourse`, ctx)
const course = ctx.course
const co = ctx.GAMEPLAY.momentumCourse, bo = ctx.GAMEPLAY.momentumBorders
const corridor = 2500
const lengthDraw = len => (len - co.minLen) / (co.maxLen - co.minLen)
// seg 0 right, seg 1 up, seg 2 right corridor, seg 3 the opposite shaft (down), seg 4 right
draws.push(lengthDraw(co.minLen),
           0.99, 0.0, lengthDraw(co.minLen),
           lengthDraw(corridor))
course.segment(2)
// The borders build the up shaft while the view is 2520 wide
ctx.momentumSegmentBorderLines(course, 1)
const shaftHalfWidthBefore = ctx.momentumShaftHalfWidth()
vm.runInContext('width = 1920', ctx)
const shaftHalfWidthNow = ctx.momentumShaftHalfWidth()
draws.push(0.99, 0.99, lengthDraw(co.minLen), lengthDraw(co.minLen))
course.segment(4)
const segs = course.segments
const first = segs[1], second = segs[3]
const gap = segs[2].x1 - first.x0
const checkGap = ctx.momentumCourse.oppositeShaftGap(first)
const out = {gapRule: 'x(new shaft) - x(earlier shaft) >= oppositeShaftGap(earlier shaft)',
             widthBuilt: 2520, widthNow: 1920, shaftHalfWidthBefore, shaftHalfWidthNow,
             corridor: segs[2].length, gap, oppositeShaftGapNow: checkGap,
             first: {dir: first.dir, x: first.x0, halfWidth: ctx.momentumSegmentHalfWidth(first)},
             second: {dir: second.dir, x: second.x0, halfWidth: ctx.momentumSegmentHalfWidth(second)}}
let pass
if (second.dir == first.dir)
{
    out.result = 'flipped: the new shaft goes ' + second.dir + ' like the earlier one'
    // What an opposite shaft here would have left between the faces
    out.clearanceIfOpposite = gap - out.first.halfWidth - out.second.halfWidth - bo.thickness - bo.backing
    pass = true
}
else
{
    // Inner faces from the real border lines; the wall body reaches
    // thickness + backing past its inner face
    const face = (index, outward) => {
        const lines = ctx.momentumSegmentBorderLines(course, index)
        const xs = lines.map(l => l.x0)
        return outward > 0 ? Math.max(...xs) : Math.min(...xs)
    }
    const body = bo.thickness + bo.backing
    const firstRight = face(1, 1), secondLeft = face(3, -1)
    out.firstRightFace = firstRight
    out.secondLeftFace = secondLeft
    out.wallBody = body
    // earlier shaft's body vs the new corridor, and the new body vs the earlier corridor
    out.clearance = Math.min(secondLeft - (firstRight + body), (secondLeft - body) - firstRight)
    pass = out.clearance >= 0
}
out.pass = pass
console.log(JSON.stringify(out))
console.log(pass ? 'PASS: opposite shafts clear after resize' + (out.clearance !== undefined ? ' (clearance ' + out.clearance + ')' : ' (direction flipped, clearance if opposite ' + out.clearanceIfOpposite + ')')
                 : 'FAIL: clearance ' + out.clearance + ' < 0: the earlier shaft wall body sits inside the new shaft')
process.exit(pass ? 0 : 1)
