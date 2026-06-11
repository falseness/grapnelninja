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
            hexagonStroke: 'rgba(48, 213, 200, 0.10)',
            hexagonAccentStroke: 'rgba(255, 61, 113, 0.06)',
            streak: 'rgba(48, 213, 200, 0.08)',
            depthHexagonStroke: 'rgba(48, 213, 200, 0.16)',
            depthHexagonAccentStroke: 'rgba(255, 61, 113, 0.09)',
            depthStreak: 'rgba(143, 252, 255, 0.13)',
            polygonAccentFill: 'rgba(31, 122, 255, 0.045)',
            polygonAccentStroke: 'rgba(48, 213, 200, 0.18)',
            polygonDangerFill: 'rgba(255, 61, 113, 0.035)',
            polygonDangerStroke: 'rgba(255, 61, 113, 0.12)'
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
            title: '#8ffcff',
            text: '#d8fbff',
            hudText: '#f4feff',
            hudGlow: '#30d5c8',
            hudMuted: 'rgba(31, 122, 255, 0.42)',
            score: '#30d5c8',
            record: '#8ffcff',
            primary: '#30d5c8',
            danger: '#ff3d71',
            buttonFill: 'rgba(5, 9, 20, 0.74)',
            buttonStroke: '#30d5c8',
            buttonDangerStroke: '#ff3d71',
            buttonText: '#d8fbff',
            buttonShadow: 'rgba(48, 213, 200, 0.45)',
            transparent: 'rgba(0, 0, 0, 0)',
            mutedText: 'rgba(143, 252, 255, 0.72)',
            pauseOverlay: 'rgba(3, 5, 16, 0.68)',
            pausePanelFill: 'rgba(5, 9, 20, 0.86)',
            pausePanelStroke: 'rgba(48, 213, 200, 0.82)',
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
        neonGlowWidth: 5,
        grapnelWidthRatio: 0.006,
        menuIconWidthRatio: 0.05,
        checkMarkWidthRatio: 0.03
    }),
    ui: Object.freeze({
        fontFamily: 'Consolas, Monaco, "Courier New", monospace',
        textShadowBlur: 8,
        buttonShadowBlur: 10,
        buttonInsetRatio: 0.08,
        buttonLineWidth: 2,
        pausePanelLineWidth: 2,
        hudTopRatio: 0.06,
        hudFontRatio: 0.042,
        hudLetterSpacing: 4,
        hudStageFontRatio: 0.032,
        hudStageDotRatio: 0.006,
        hudStageGapRatio: 0.031,
        hudStageDiamondRatio: 0.018,
        hudStageLineRatio: 0.0018,
        hudRecordXRatio: 0.91,
        hudClearTopRatio: 0.14
    }),
    lights: Object.freeze({
        resolutionScale: 0.2,
        playerRadius: 110,
        cubeRadius: 104,
        hazardRadius: 126,
        groundRadius: 80,
        alpha: 0.34,
        hazardPulseMinAlpha: 0.22,
        hazardPulseMaxAlpha: 0.56,
        hazardPulseRadiusBoost: 26,
        ambientRadiusRatio: 0.62,
        ambientAlpha: 0.12,
        compositeAlpha: 0.72
    }),
    particles: Object.freeze({
        maxCount: 140,
        spawnBurst: 12,
        lifetimeMs: 360,
        playerEmitCount: 1,
        worldEmitIntervalMs: 160,
        cubeEmitChance: 0.24,
        hazardEmitChance: 0.42,
        minSize: 2,
        maxSize: 4,
        playerSpeed: 1.15,
        cubeSpeed: 0.34,
        hazardSpeed: 0.66,
        playerAlpha: 0.58,
        cubeAlpha: 0.28,
        hazardAlpha: 0.52
    }),
    trails: Object.freeze({
        player: Object.freeze({
            widthRatio: 3.5,
            glowWidthRatio: 7,
            minAlpha: 0.04,
            maxAlpha: 0.48,
            coreAlpha: 0.72,
            minSegmentRatio: 0
        })
    }),
    badVersionEffects: Object.freeze({
        obstacles: Object.freeze({
            fillAlpha: 0.68,
            groundFillAlpha: 0.44,
            groundCapAlpha: 0.18,
            highlightAlpha: 0.74,
            innerHighlightAlpha: 0.18,
            thinStrokeWidth: 1.35,
            outerGlowWidth: 7,
            accentInsetRatio: 0.08,
            hazardFill: 'rgba(36, 4, 16, 0.72)',
            hazardCoreFill: 'rgba(255, 61, 113, 0.14)',
            cubeFill: 'rgba(3, 9, 20, 0.82)',
            cubeHighlightFill: 'rgba(31, 122, 255, 0.12)',
            groundFill: 'rgba(3, 8, 18, 0.56)',
            groundCapFill: 'rgba(48, 213, 200, 0.16)',
            shadow: 'rgba(0, 0, 0, 0.32)'
        }),
        lights: Object.freeze({
            radiusMultiplier: 1.34,
            alphaMultiplier: 1.24,
            hazardRadiusMultiplier: 1.18,
            hazardAlphaMultiplier: 1.16,
            bloomRadiusMultiplier: 1.76,
            bloomAlphaMultiplier: 0.34,
            compositeAlphaMultiplier: 1.12
        }),
        particles: Object.freeze({
            playerEmitMultiplier: 3,
            worldChanceMultiplier: 1.75,
            hazardChanceMultiplier: 1.35,
            hazardEmitCount: 2,
            alphaMultiplier: 1.25,
            sizeMultiplier: 1.18,
            speedMultiplier: 1.2,
            lifetimeMultiplier: 1.18
        }),
        trails: Object.freeze({
            widthMultiplier: 1.36,
            glowWidthMultiplier: 1.85,
            alphaMultiplier: 1.28,
            chunkCount: 6,
            tailPortion: 0.4
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
        shockwaveGlowWidth: 9,
        shockwaveAlpha: 0.72,
        shakeDurationMs: 180,
        shakeMagnitude: 3.5
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
        streakLineWidth: 1.5,
        badVersion: Object.freeze({
            hexagonCount: 8,
            hexagonRadiusRatio: 0.11,
            hexagonRadiusStepRatio: 0.085,
            hexagonLineWidth: 2.35,
            secondaryHexagonCount: 4,
            secondaryHexagonRadiusRatio: 0.09,
            secondaryHexagonRadiusStepRatio: 0.12,
            streakCount: 18,
            streakSpacingRatio: 0.105,
            streakLengthRatio: 0.42,
            streakLineWidth: 1.8,
            parallaxShiftRatio: 0.04,
            accentLineWidth: 1.2,
            accents: Object.freeze([
                Object.freeze({x: 0.16, y: 0.22, radius: 72, sides: 3, rotation: 0.2, danger: false}),
                Object.freeze({x: 0.82, y: 0.30, radius: 92, sides: 4, rotation: 0.72, danger: true}),
                Object.freeze({x: 0.28, y: 0.78, radius: 118, sides: 5, rotation: 0.05, danger: false}),
                Object.freeze({x: 0.72, y: 0.68, radius: 76, sides: 3, rotation: 1.1, danger: false})
            ])
        })
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
    screenShake: true,
    setLowPower: function(enabled)
    {
        const fullQuality = !enabled

        this.lightmap = fullQuality
        this.particles = fullQuality
        this.playerTrail = fullQuality
        this.backgroundMotion = fullQuality
        this.screenShake = fullQuality
    }
}
