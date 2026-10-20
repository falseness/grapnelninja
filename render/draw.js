const NO_SHAKE = Object.freeze({x: 0, y: 0})
// Counts game draw() calls: per-frame layouts shared by several layers
// (ambient motes and their bloom copy) are keyed on it
let drawFrameId = 0

function drawBackgroundLayer()
{
    // Grapple Over only: the section palette under the camera centre, painted
    // over the cave backdrop by the background renderer (also into the window
    // bars and the fast backdrop)
    visualEffects.background.palette = version === 'grapple_over' ?
        grappleOverBackdropPalette(height / scale[version] / 2 - screen.y) : null
    visualEffects.background.draw()
}

// Palette at world y cameraY (negative is up): {from, to, t} indices into
// GRAPPLE_OVER_THEME.palettes. Inside a band core from == to and t == 0;
// within blendHalfSpan of a band boundary t is a smoothstep from the lower
// band's palette to the upper one's.
function grappleOverBackdropPalette(cameraY)
{
    const theme = GRAPPLE_OVER_THEME
    const last = theme.palettes.length - 1
    const rise = Number.isFinite(cameraY) ? -cameraY : 0
    const boundary = Math.min(last, Math.max(1, Math.round(rise / theme.bandHeight)))
    const offset = rise - boundary * theme.bandHeight
    if (Math.abs(offset) >= theme.blendHalfSpan)
    {
        const band = Math.min(last, Math.max(0, Math.floor(rise / theme.bandHeight)))
        const core = grappleOverBackdropPalette.cores ||
            (grappleOverBackdropPalette.cores = theme.palettes.map((p, i) => Object.freeze({from: i, to: i, t: 0})))
        return core[band]
    }
    const x = (offset + theme.blendHalfSpan) / (2 * theme.blendHalfSpan)
    return {from: boundary - 1, to: boundary, t: x * x * (3 - 2 * x)}
}

// Wash and horizon glow over bounds (logical units), from gradients built
// once per palette (no shadowBlur). The wash is a source-over at tintAlpha,
// done as a black fill at tintAlpha plus the palette colours added with
// 'lighter': a blend adds both neighbours weighted by 1 - t and t, which
// mixes them exactly (gradient stops would round each mixed colour to 8 bits
// and step visibly during a slow climb).
function drawGrappleOverPalette(context, bounds, palette)
{
    const theme = GRAPPLE_OVER_THEME
    let cache = drawGrappleOverPalette.cache
    if (!cache || cache.context !== context || cache.y !== bounds.y || cache.height !== bounds.height)
        cache = drawGrappleOverPalette.cache = {context, y: bounds.y, height: bounds.height, gradients: []}
    const gradients = index =>
    {
        if (cache.gradients[index])
            return cache.gradients[index]
        const p = theme.palettes[index]
        const wash = context.createLinearGradient(0, bounds.y, 0, bounds.y + bounds.height)
        wash.addColorStop(0, p.top)
        wash.addColorStop(1, p.bottom)
        const glow = context.createLinearGradient(0, bounds.y + bounds.height * theme.glowTop,
            0, bounds.y + bounds.height)
        glow.addColorStop(0, '#000000')
        glow.addColorStop(1, p.glow)
        return cache.gradients[index] = {wash, glow}
    }
    const layers = palette.t > 0 ? [[palette.from, 1 - palette.t], [palette.to, palette.t]] : [[palette.from, 1]]
    const glowY = bounds.y + bounds.height * theme.glowTop
    context.save()
    context.shadowBlur = 0
    context.globalCompositeOperation = 'source-over'
    context.globalAlpha = theme.tintAlpha
    context.fillStyle = '#000000'
    context.fillRect(bounds.x, bounds.y, bounds.width, bounds.height)
    context.globalCompositeOperation = 'lighter'
    for (const [index, weight] of layers)
    {
        context.globalAlpha = theme.tintAlpha * weight
        context.fillStyle = gradients(index).wash
        context.fillRect(bounds.x, bounds.y, bounds.width, bounds.height)
        context.globalAlpha = theme.glowAlpha * weight
        context.fillStyle = gradients(index).glow
        context.fillRect(bounds.x, glowY, bounds.width, bounds.y + bounds.height - glowY)
    }
    context.restore()
}

function drawLightsLayer(gameState)
{
    visualEffects.lightmap.clear(gameState)
    visualEffects.lightmap.draw(gameState)
    visualEffects.lightmap.composite(gameState)
}

function drawWorldLayer()
{
    drawAcquisitionCircle()
    grapnel.draw()

    // All back faces first, so no extrusion covers a neighbour's front face
    if (STYLE.features.extrusion)
        for (let i = 1; i < floors.length - 1; ++i)
        {
            floors[i].drawExtrusions()
        }

    for (let i = 1; i < floors.length - 1; ++i)
    {
        floors[i].draw()
    }
    floors[0].draw()
    floors[floors.length - 1].draw()
    if (version === 'grapple_over')
        drawGrappleOverRoleDetail(floors[0])

    if (screen.leftWall) screen.leftWall.draw()
    screen.draw()
    grapnel.drawHook()
}

// Distance guide only: obstacles still determine whether a hook can attach.
function drawAcquisitionCircle()
{
    if (version !== 'grapple_over' || !runInProgress)
        return

    ctx.save()
    ctx.globalAlpha = 0.20
    ctx.globalCompositeOperation = 'source-over'
    ctx.strokeStyle = '#00ffff'
    ctx.shadowBlur = 0
    ctx.shadowOffsetX = ctx.shadowOffsetY = 0
    ctx.setLineDash([])
    ctx.lineWidth = width / getCanvasCssRect().width / scale[version]
    ctx.beginPath()
    ctx.arc(ninja.x + screen.x, ninja.y + screen.y,
        grappleOverAcquisitionRadius(), 0, Math.PI * 2)
    ctx.stroke()
    ctx.restore()
}

function drawPlayerTrailLayer(gameState)
{
    visualEffects.playerTrail.draw(gameState)
}

function drawBehindForegroundParticlesLayer(gameState)
{
    visualEffects.particles.update(gameState)
    visualEffects.particles.drawAmbientMotes()
    visualEffects.particles.drawBehindForeground()
}

function drawParticlesAndTrailsLayer(gameState)
{
    visualEffects.particles.draw(gameState)
    visualEffects.screenEffects.draw(gameState)
}

// Glow halo of the emissive shapes, added before the HUD so text stays crisp
function drawBloomLayer(gameState)
{
    const screenEffects = visualEffects.screenEffects
    visualEffects.bloom.draw(gameState, screenEffects.isShaking ? screenEffects.shakeOffset : NO_SHAKE)
}

function drawPlayerGlowLayer(gameState)
{
    const effects = visualEffects.screenEffects
    visualEffects.playerGlow.draw(gameState, effects.isShaking ? effects.shakeOffset : NO_SHAKE)
}

// The ball goes over particles, bloom and colour grade, so its blue body and
// cyan ring stay readable at the small pre-overhaul size
function drawPlayerLayer()
{
    ninja.draw()
}

// Colour grade and vignette over the world, under the player and HUD
function drawColorGradeLayer()
{
    visualEffects.colorGrade.draw()
}

// First-run control hint: above the world and the player, under the HUD
function drawTutorialHintLayer()
{
    TUTORIAL_HINT.draw(ctx, TUTORIAL_HINT.alpha, TUTORIAL_HINT.time)
}

function drawUILayer(gameState)
{
    visualEffects.ui.draw(gameState)
}

function drawFpsCounterLayer(gameState)
{
    visualEffects.ui.drawFpsCounter(gameState)
}

// Run start: draws the HUD and the ground strips once into a scratch canvas
// in the game transform, so their glow sprites (render/glowsprites.js) are
// built here and the first frames do no shadowBlur work
function warmGlowSprites()
{
    if (!warmGlowSprites.ctx)
        warmGlowSprites.ctx = document.createElement('canvas').getContext('2d')

    const mainCtx = ctx
    const scratch = warmGlowSprites.ctx
    const boxes = LAYOUT_PROBE.boxes
    scratch.setTransform(mainCtx.getTransform())
    scratch.scale(scale[version], scale[version])
    LAYOUT_PROBE.boxes = null
    ctx = scratch
    try
    {
        if (visualEffects.ui.shouldDraw())
        {
            scoreText.draw()
            menu.button.draw()
        }
        warmGroundGlowSprites()
    }
    finally
    {
        ctx = mainCtx
        LAYOUT_PROBE.boxes = boxes
    }
}

function draw()
{
    ++drawFrameId
    BACKDROP.observe(performance.now())
    // Slow canvases: background, light spill and mote glow go into the
    // reduced-resolution backdrop (render/backdrop.js)
    const backdrop = BACKDROP.begin()
    drawBackgroundLayer()

    ctx.scale(scale[version], scale[version])

    const gameState = visualEffects.getGameState()
    updateNeonPulse()
    visualEffects.screenEffects.begin(gameState)
    if (backdrop)
        BACKDROP.syncTransform()

    drawLightsLayer(gameState)
    if (backdrop)
        BACKDROP.end()
    drawBehindForegroundParticlesLayer(gameState)
    drawPlayerTrailLayer(gameState)
    drawWorldLayer()
    drawParticlesAndTrailsLayer(gameState)
    if (STYLE.features.bloom)
        drawBloomLayer(gameState)
    drawPlayerGlowLayer(gameState)
    drawColorGradeLayer()
    drawPlayerLayer()
    if (TUTORIAL_HINT.visible && !(version === 'grapple_over' && menu.gamePaused))
        drawTutorialHintLayer()
    drawUILayer(gameState)
    drawFpsCounterLayer(gameState)

    visualEffects.screenEffects.end(gameState)

    ctx.scale(1 / scale[version], 1 / scale[version])
    if (version === 'grapple_over' && floors[0].climbStats.completed) CLIMB_UI.drawMenu()

}
