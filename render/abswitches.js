// URL A/B switches for measuring draw cost in a real browser. Drawing only:
// gameplay and physics never change, and nothing is sent anywhere.
//   ?off=<names>  comma list of draw() layers to skip, by the PERF_PROFILE
//                 names (e.g. off=lights,colorGrade,playerGlow)
//   ?scale=<s>    0.25..1, multiplies the canvas backing-store resolution
//                 (DPR); the CSS size, layout and input mapping stay the same
// Unknown names or an out-of-range scale are ignored with one console.warn.
// Works with or without ?perf=1; loaded after render/perfprofile.js so a
// skipped layer shows up there with 0 samples.
(function()
{
    const LAYERS = {
        background: 'drawBackgroundLayer',
        lights: 'drawLightsLayer',
        behindForegroundParticles: 'drawBehindForegroundParticlesLayer',
        playerTrail: 'drawPlayerTrailLayer',
        world: 'drawWorldLayer',
        particlesAndTrails: 'drawParticlesAndTrailsLayer',
        bloom: 'drawBloomLayer',
        playerGlow: 'drawPlayerGlowLayer',
        colorGrade: 'drawColorGradeLayer',
        player: 'drawPlayerLayer',
        tutorialHint: 'drawTutorialHintLayer',
        ui: 'drawUILayer',
        fpsCounter: 'drawFpsCounterLayer',
    }
    const MIN_SCALE = 0.25
    const MAX_SCALE = 1
    const params = new URLSearchParams(location.search)
    const ignored = []

    const off = []
    for (const name of (params.get('off') || '').split(',').map(s => s.trim()).filter(Boolean))
    {
        if (Object.prototype.hasOwnProperty.call(LAYERS, name))
        {
            if (!off.includes(name))
                off.push(name)
        }
        else
            ignored.push('off=' + name)
    }
    for (const name of off)
        window[LAYERS[name]] = function() {}

    let scale = 1
    if (params.has('scale'))
    {
        const raw = params.get('scale')
        const value = Number(raw)
        if (raw.trim() !== '' && value >= MIN_SCALE && value <= MAX_SCALE)
            scale = value
        else
            ignored.push('scale=' + raw)
    }
    if (scale !== 1)
    {
        const configure = window.configureCanvasViewport
        window.configureCanvasViewport = function(canvas, context)
        {
            configure(canvas, context)
            canvas.width = Math.max(1, Math.round(canvas.width * scale))
            canvas.height = Math.max(1, Math.round(canvas.height * scale))
            context.setTransform(canvas.width / width, 0, 0, canvas.height / height, 0, 0)
        }
    }

    if (ignored.length)
        console.warn('A/B switches ignored (unknown layer or scale outside ' + MIN_SCALE + '..' +
            MAX_SCALE + '): ' + ignored.join(', '))

    window.AB_SWITCHES = {off, scale}
})()
