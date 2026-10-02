const widthHeightRatio = 1.8250950570342206
// Logical viewport: height is always 1080 units, width follows the window
// aspect clamped to [4:3, 21:9]. The canvas CSS box letterboxes that aspect.
const LOGICAL_HEIGHT = 1080
const minViewportAspect = 4 / 3
const maxViewportAspect = 21 / 9
function computeLogicalWidth()
{
    const aspect = Math.min(maxViewportAspect, Math.max(minViewportAspect, window.innerWidth / window.innerHeight))
    return Math.round(LOGICAL_HEIGHT * aspect)
}
const height    = LOGICAL_HEIGHT
// Mutable: a live window resize recomputes it (see updateLogicalViewport).
let width       = computeLogicalWidth()
let LOGICAL_VIEWPORT = Object.freeze({width: width, height: height})

// Recomputes the logical width from the window; returns true if it changed.
function updateLogicalViewport()
{
    const nextWidth = computeLogicalWidth()

    if (nextWidth == width)
        return false

    width = nextWidth
    LOGICAL_VIEWPORT = Object.freeze({width: width, height: height})
    return true
}

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
    cameraBorderWidthPercent: 35,
    cameraTopHeightPercent: 60,
    cameraBottomHeightPercent: 40,
    cameraCenterHeightPercent: 50,
    cameraMoveRatio: 1.5,
    triangleUpwardChancePercent: 50,
    // Numerical separation, not a visible clearance: intentionally unscaled.
    cubeContactEpsilon: 1e-7
})
const defaultEqualityTolerance = 1

// Largest centred CSS rectangle of the logical aspect that fits the window.
function getCanvasCssRect()
{
    const fit = Math.min(window.innerWidth / width, window.innerHeight / height)
    const cssWidth = width * fit
    const cssHeight = height * fit

    return {
        left: (window.innerWidth - cssWidth) / 2,
        top: (window.innerHeight - cssHeight) / 2,
        width: cssWidth,
        height: cssHeight
    }
}

// Sizes the CSS box and backing store (CSS size * DPR) and applies the base
// transform so all drawing code works in logical units.
function configureCanvasViewport(canvas, context)
{
    const rect = getCanvasCssRect()
    const dpr = window.devicePixelRatio || 1

    canvas.style.position = 'fixed'
    canvas.style.left = rect.left + 'px'
    canvas.style.top = rect.top + 'px'
    canvas.style.width = rect.width + 'px'
    canvas.style.height = rect.height + 'px'
    canvas.width = Math.max(1, Math.round(rect.width * dpr))
    canvas.height = Math.max(1, Math.round(rect.height * dpr))

    context.setTransform(canvas.width / width, 0, 0, canvas.height / height, 0, 0)
}

function viewportCoordsToCanvasCoords(coord)
{
    const rect = canvas.getBoundingClientRect()

    return {
        x: (coord.x - rect.left) * width / rect.width,
        y: (coord.y - rect.top) * height / rect.height
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
