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
            fill: '#06151d',
            stroke: '#30d5c8',
            core: '#8ffcff',
            trail: '#30d5c8',
            cyan: '#30d5c8'
        }),
        cube: Object.freeze({
            fill: '#071425',
            platformFill: '#09111e',
            trampolineFill: '#120b22',
            stroke: '#30d5c8',
            accentStroke: '#1f7aff',
            trail: '#30d5c8',
            blue: '#1f7aff'
        }),
        hazard: Object.freeze({
            fill: '#21070f',
            harmlessFill: '#06201d',
            stroke: '#ff3d71',
            harmlessStroke: '#30d5c8',
            trail: '#ff3d71',
            red: '#ff3d71'
        }),
        ground: Object.freeze({
            fill: '#050914',
            stroke: '#30d5c8',
            line: '#8ffcff'
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
        neonWidth: 2,
        neonGlowWidth: 6,
        grapnelWidthRatio: 0.006,
        menuIconWidthRatio: 0.05,
        checkMarkWidthRatio: 0.03
    }),
    lights: Object.freeze({
        resolutionScale: 0.25,
        playerRadius: 120,
        cubeRadius: 120,
        hazardRadius: 140,
        groundRadius: 80,
        alpha: 0.45,
        hazardPulseMinAlpha: 0.26,
        hazardPulseMaxAlpha: 0.72,
        hazardPulseRadiusBoost: 36,
        ambientRadiusRatio: 0.62,
        ambientAlpha: 0.18,
        compositeAlpha: 0.85
    }),
    particles: Object.freeze({
        maxCount: 120,
        spawnBurst: 12,
        lifetimeMs: 450,
        playerEmitCount: 2,
        worldEmitIntervalMs: 120,
        cubeEmitChance: 0.32,
        hazardEmitChance: 0.55,
        minSize: 2,
        maxSize: 5,
        playerSpeed: 1.4,
        cubeSpeed: 0.42,
        hazardSpeed: 0.82
    }),
    trails: Object.freeze({
        player: Object.freeze({
            widthRatio: 3.5,
            glowWidthRatio: 9,
            minAlpha: 0.04,
            maxAlpha: 0.62,
            coreAlpha: 0.82,
            minSegmentRatio: 0
        })
    }),
    playerVisuals: Object.freeze({
        rotationSpeed: 0.032,
        rotationMinSpeed: 0.03,
        rotationMarkerWidthRatio: 0.4,
        rotationMarkerLengthRatio: 1.35,
        rotationMarkerOffsetRatio: 0.16,
        rotationMarkerAlpha: 0.9
    }),
    screenEffects: Object.freeze({
        shockwaveDurationMs: 420,
        shockwaveStartRadius: 8,
        shockwaveEndRadius: 170,
        shockwaveLineWidth: 3,
        shockwaveGlowWidth: 12,
        shockwaveAlpha: 0.9,
        shakeDurationMs: 180,
        shakeMagnitude: 5
    }),
    timing: Object.freeze({
        inputUntouchMs: 100,
        trailPoints: 100,
        cubeTrailPoints: 50,
        triangleTrailPoints: 75,
        backgroundRotationMs: 18000,
        backgroundStreakMs: 5200,
        hazardPulseMs: 1300
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
