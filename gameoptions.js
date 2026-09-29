const widthHeightRatio = 1.8250950570342206
const viewportWidth = window.innerWidth
const viewportHeight = window.innerHeight
const forceLandscapeViewport = viewportWidth < viewportHeight
const height    = forceLandscapeViewport ? viewportWidth : viewportHeight
const width     = forceLandscapeViewport ? viewportHeight : viewportWidth//height * widthHeightRatio

// Logical canvas percentages; baseline gameplay was measured at 1920 x 1080.
function screenWidthPercent(percent) { return width * (percent / 100) }
function screenHeightPercent(percent) { return height * (percent / 100) }

const GAMEPLAY = Object.freeze({
    gravityHeightPercent: 0.006297229219143577,
    // Direction-vector magnitudes use one height scale to preserve aim angles.
    grapnelThrowHeightPercent: 20,
    grapplePullHeightPercent: 0.025188916876574307,
    triangleSpeedHeightPercent: 0.5,
    ninjaMaxSpeedHeightPercent: 2,
    cornerToleranceHeightPercent: 100 * 6 / 1080,
    firstPointToleranceHeightPercent: 100 * 50 / 1080,
    coordinateToleranceHeightPercent: 100 / 1080,
    cameraBorderWidthPercent: Object.freeze({ classic: 35, bad: 45 }),
    cameraTopHeightPercent: 60,
    cameraBottomHeightPercent: 40,
    cameraCenterHeightPercent: 50,
    cameraMoveRatio: 1.5,
    triangleUpwardChancePercent: 50,
    // Numerical separation, not a visible clearance: intentionally unscaled.
    cubeContactEpsilon: 1e-7
})
const defaultEqualityTolerance = 1

function configureCanvasViewport(canvas)
{
    canvas.style.position = 'fixed'
    canvas.style.left = '50%'
    canvas.style.top = '50%'
    canvas.style.width = width + 'px'
    canvas.style.height = height + 'px'
    canvas.style.transformOrigin = 'center center'
    canvas.style.transform = forceLandscapeViewport ? 'translate(-50%, -50%) rotate(90deg)' : 'translate(-50%, -50%)'
}

function viewportCoordsToCanvasCoords(coord)
{
    const rect = canvas.getBoundingClientRect()

    if (!forceLandscapeViewport)
    {
        return {
            x: (coord.x - rect.left) * canvas.width / rect.width,
            y: (coord.y - rect.top) * canvas.height / rect.height
        }
    }

    const centerX = rect.left + rect.width / 2
    const centerY = rect.top + rect.height / 2
    const offsetX = coord.x - centerX
    const offsetY = coord.y - centerY

    return {
        x: offsetY + canvas.width / 2,
        y: canvas.height / 2 - offsetX
    }
}

let scale = 
{
    classic : 1         ,
    bad     : 1 / 2.2   ,
}

const cyclesPerTick = 8
const physicsTicksPerSecond = 60
const physicsStepMs = 1000 / physicsTicksPerSecond
const maxPhysicsFrameMs = physicsStepMs * 5
const physicsStepEpsilonMs = 0.000001

function random(min, max)
{
    min = min || 0
    max = max || 100
    return Math.floor(Math.random() * (max - min)) + min
}
function isEqually(a, b, eps)
{
    eps = eps || defaultEqualityTolerance
    return (Math.abs(a - b) < eps)
}
function isMore(a, b, eps)
{
    eps = eps || defaultEqualityTolerance
    return (a - b > -eps)
}
function isLess(a, b, eps)
{
    eps = eps || defaultEqualityTolerance
    return (a - b < eps)
}
function isPointsEqually(p1, p2, eps)
{
    eps = eps || defaultEqualityTolerance
    return (Math.pow(p1[0] - p2[0], 2) + Math.pow(p1[1] - p2[1], 2) < Math.pow(eps, 2))
}
function abs(a)
{
    return Math.abs(a)
}
const blueSpriteDensity = 0.001
