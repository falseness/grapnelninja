const widthHeightRatio = 1.8250950570342206
// Logical viewport: height is always 1080 units, width follows the window
// aspect clamped to [4:3, 2:1] on desktop (play field at most 2:1).
// Touch-first devices are not capped: a landscape phone (about 2.2:1, wider
// with the browser bars) gets the whole screen (full screen on mobile).
// The canvas CSS box letterboxes that aspect.
const LOGICAL_HEIGHT = 1080
const minViewportAspect = 4 / 3
const maxViewportAspect = 2
function isTouchFirstDevice()
{
    return !!(window.matchMedia && window.matchMedia('(pointer: coarse)').matches)
}
// A phone held upright plays in landscape: the stage (the game canvas and
// the letterbox bars) is turned 90 degrees clockwise.
function isViewRotated()
{
    return isTouchFirstDevice() && window.innerWidth < window.innerHeight
}
// The window as the stage sees it: width and height swap when rotated
function getViewSize()
{
    return isViewRotated()
        ? {width: window.innerHeight, height: window.innerWidth}
        : {width: window.innerWidth, height: window.innerHeight}
}
function computeLogicalWidth()
{
    const touch = isTouchFirstDevice()
    const view = getViewSize()
    const aspect = Math.min(touch ? Infinity : maxViewportAspect,
                            Math.max(minViewportAspect, view.width / view.height))
    // Touch: never round wider than the window, so the canvas fits by height
    // and keeps the 44 CSS px touch floor exact (see minTouchSize)
    return (touch ? Math.floor : Math.round)(LOGICAL_HEIGHT * aspect)
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

// A lethal death offers a continue once per run, from this score on.
const CONTINUE_MIN_SCORE = 5
// After a continue the ninja ignores lethal hits for this much physics time
// and blinks; the respawn zone is kept clear for a margin beyond it.
const RESPAWN_INVULNERABLE_MS = 2000
const RESPAWN_SAFE_MARGIN_MS = 1000
const RESPAWN_BLINK_MS = 125
const RESPAWN_BLINK_ALPHA = 0.25

// Largest centred CSS rectangle of the logical aspect that fits the view,
// in stage coordinates (the window's own when the stage is not rotated).
function getCanvasCssRect()
{
    const view = getViewSize()
    const fit = Math.min(view.width / width, view.height / height)
    const cssWidth = width * fit
    const cssHeight = height * fit

    return {
        left: (view.width - cssWidth) / 2,
        top: (view.height - cssHeight) / 2,
        width: cssWidth,
        height: cssHeight
    }
}

// Touch targets are never smaller than this many CSS pixels
const MIN_TOUCH_CSS_PX = 44
// Logical units per CSS pixel turn the CSS floor into a logical size
function minTouchSize()
{
    const cssHeight = getCanvasCssRect().height
    return cssHeight > 0 ? MIN_TOUCH_CSS_PX * height / cssHeight : 0
}

// Covers the window with the stage, turned about the window centre when
// the view is rotated.
function configureStage()
{
    const stage = document.getElementById('stage')
    const view = getViewSize()

    stage.style.left = (window.innerWidth - view.width) / 2 + 'px'
    stage.style.top = (window.innerHeight - view.height) / 2 + 'px'
    stage.style.width = view.width + 'px'
    stage.style.height = view.height + 'px'
    stage.style.transform = isViewRotated() ? 'rotate(90deg)' : ''
}

// Sizes the CSS box and backing store (CSS size * DPR) and applies the base
// transform so all drawing code works in logical units.
function configureCanvasViewport(canvas, context)
{
    configureStage()
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

// Window (client) point -> stage point; the stage turns clockwise about
// the window centre when rotated.
function viewportCoordsToStageCoords(coord)
{
    if (!isViewRotated())
        return {x: coord.x, y: coord.y}

    const view = getViewSize()
    const offsetX = coord.x - window.innerWidth / 2
    const offsetY = coord.y - window.innerHeight / 2

    return {x: view.width / 2 + offsetY, y: view.height / 2 - offsetX}
}

function viewportCoordsToCanvasCoords(coord)
{
    const rect = getCanvasCssRect()
    const point = viewportCoordsToStageCoords(coord)

    return {
        x: (point.x - rect.left) * width / rect.width,
        y: (point.y - rect.top) * height / rect.height
    }
}

// Logical canvas point -> window (client) point
function canvasCoordsToViewportCoords(coord)
{
    const rect = getCanvasCssRect()
    const x = rect.left + coord.x * rect.width / width
    const y = rect.top + coord.y * rect.height / height

    if (!isViewRotated())
        return {x: x, y: y}

    const view = getViewSize()
    return {x: window.innerWidth / 2 - (y - view.height / 2),
            y: window.innerHeight / 2 + (x - view.width / 2)}
}

let scale = 
{
    classic : 1         ,
    bad     : 1 / 2.2   ,
}

const cyclesPerTick = 8
const physicsTicksPerSecond = 60
const physicsStepMs = 1000 / physicsTicksPerSecond
const physicsStepEpsilonMs = 0.000001
const physicsSnapMs = 2
const maxPhysicsStepsPerFrame = 2

// state: {lastFrameTime, accumulatorMs}; returns how many physics steps to run
function computePhysicsSteps(state, frameTime)
{
    if (!state.lastFrameTime)
    {
        state.lastFrameTime = frameTime
        state.accumulatorMs = physicsStepMs / 2
        return 1
    }

    let elapsedMs = Math.max(0, frameTime - state.lastFrameTime)
    state.lastFrameTime = frameTime

    const wholeSteps = Math.round(elapsedMs / physicsStepMs)
    if (wholeSteps >= 1 && Math.abs(elapsedMs - wholeSteps * physicsStepMs) <= physicsSnapMs)
        elapsedMs = wholeSteps * physicsStepMs

    state.accumulatorMs += elapsedMs
    const steps = Math.floor((state.accumulatorMs + physicsStepEpsilonMs) / physicsStepMs)
    state.accumulatorMs = Math.max(0, state.accumulatorMs - steps * physicsStepMs)

    return Math.min(steps, maxPhysicsStepsPerFrame)
}

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
