const STYLE = Object.freeze({
    colors: Object.freeze({
        background: Object.freeze({
            page: 'black',
            canvas: 'white',
            dark: '#050713',
            darkAccent: '#12102a',
            gradientTop: '#050713',
            gradientMiddle: '#0a1638',
            gradientBottom: '#190a2e',
            vignetteCenter: 'rgba(0, 0, 0, 0)',
            vignetteEdge: 'rgba(0, 0, 0, 0.58)',
            hexagonStroke: 'rgba(48, 213, 200, 0.13)',
            hexagonAccentStroke: 'rgba(255, 61, 113, 0.08)',
            streak: 'rgba(48, 213, 200, 0.11)'
        }),
        player: Object.freeze({
            fill: '#0000ff',
            stroke: '#000000',
            trail: '#0000ff',
            cyan: '#30d5c8'
        }),
        cube: Object.freeze({
            fill: '#0000ff',
            platformFill: '#f0f0f0',
            trampolineFill: '#3e1170',
            stroke: '#000000',
            blue: '#0000ff'
        }),
        hazard: Object.freeze({
            fill: '#ff0000',
            harmlessFill: '#30d5c8',
            stroke: '#000000',
            red: '#ff0000'
        }),
        ground: Object.freeze({
            fill: '#f0f0f0',
            stroke: '#000000',
            line: '#f0f0f0'
        }),
        ui: Object.freeze({
            title: '#0000ff',
            text: '#0000ff',
            score: '#0000ff',
            primary: '#008000',
            danger: '#ff0000',
            buttonFill: '#ffffff',
            buttonStroke: '#000000',
            transparent: 'rgba(0, 0, 0, 0)',
            mutedText: 'rgba(0, 0, 0, 0.5)',
            pauseOverlay: 'rgba(245, 245, 245, 0.52)',
            pausePanelFill: '#ffffff',
            debug: '#008000',
            debugAccent: '#ff0000'
        })
    }),
    alpha: Object.freeze({
        track: 0.5,
        multipointTrack: 0.5,
        full: 1
    }),
    strokes: Object.freeze({
        defaultWidth: 1,
        seamWidth: 10,
        grapnelWidthRatio: 0.006,
        menuIconWidthRatio: 0.05,
        checkMarkWidthRatio: 0.03
    }),
    lights: Object.freeze({
        playerRadius: 120,
        cubeRadius: 120,
        hazardRadius: 140,
        groundRadius: 80,
        alpha: 0.45
    }),
    particles: Object.freeze({
        maxCount: 120,
        spawnBurst: 12,
        lifetimeMs: 450
    }),
    timing: Object.freeze({
        inputUntouchMs: 100,
        trailPoints: 100,
        cubeTrailPoints: 50,
        triangleTrailPoints: 75,
        backgroundRotationMs: 18000,
        backgroundStreakMs: 5200
    }),
    backgroundGeometry: Object.freeze({
        hexagonCount: 5,
        hexagonRadiusRatio: 0.16,
        hexagonRadiusStepRatio: 0.115,
        hexagonLineWidth: 2,
        streakCount: 12,
        streakSpacingRatio: 0.14,
        streakLengthRatio: 0.28,
        streakLineWidth: 1.5
    }),
    features: Object.freeze({
        background: true,
        lightmap: true,
        particles: true,
        playerTrail: true,
        screenEffects: true,
        uiStyling: true
    })
})

const QUALITY = {
    lightmap: true,
    particles: true,
    playerTrail: true,
    backgroundMotion: true,
    screenShake: true
}
