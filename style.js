const STYLE = Object.freeze({
    colors: Object.freeze({
        background: Object.freeze({
            page: 'black',
            canvas: 'white',
            dark: '#050713',
            darkAccent: '#12102a',
            gradientTop: '#050713',
            gradientMiddle: '#07102a',
            gradientBottom: '#120720',
            vignetteCenter: 'rgba(0, 0, 0, 0)',
            vignetteEdge: 'rgba(0, 0, 0, 0.66)',
            hexagonStroke: 'rgba(48, 213, 200, 0.10)',
            hexagonAccentStroke: 'rgba(255, 61, 113, 0.06)',
            streak: 'rgba(48, 213, 200, 0.08)',
            depthHexagonStroke: 'rgba(48, 213, 200, 0.095)',
            depthHexagonAccentStroke: 'rgba(255, 61, 113, 0.055)',
            depthStreak: 'rgba(143, 252, 255, 0.075)',
            flashBlue: 'rgba(31, 122, 255, 0.62)',
            flashBlueGlow: 'rgba(31, 122, 255, 0.16)',
            flashMagenta: 'rgba(255, 61, 113, 0.72)',
            flashMagentaGlow: 'rgba(255, 61, 113, 0.18)',
            triangleSilhouetteFill: 'rgba(31, 122, 255, 0.028)',
            triangleSilhouetteStroke: 'rgba(143, 252, 255, 0.12)',
            polygonAccentFill: 'rgba(31, 122, 255, 0.025)',
            polygonAccentStroke: 'rgba(48, 213, 200, 0.11)',
            polygonDangerFill: 'rgba(255, 61, 113, 0.022)',
            polygonDangerStroke: 'rgba(255, 61, 113, 0.075)'
        }),
        player: Object.freeze({
            fill: '#125dff',
            stroke: '#30d5c8',
            core: '#6fa8ff',
            highlight: '#b8f7ff',
            trail: '#30d5c8',
            cyan: '#30d5c8'
        }),
        cube: Object.freeze({
            fill: '#071425',
            platformFill: '#15181d',
            trampolineFill: '#071c12',
            stroke: '#30d5c8',
            accentStroke: '#1f7aff',
            trail: '#30d5c8',
            blue: '#1f7aff',
            blueFill: '#061234',
            blueStroke: '#1f7aff',
            grayFill: '#171a1f',
            grayStroke: '#b9c2c9',
            greenFill: '#071c12',
            greenStroke: '#64e379'
        }),
        hazard: Object.freeze({
            fill: '#21070f',
            harmlessFill: '#071c12',
            stroke: '#ff3d71',
            harmlessStroke: '#64e379',
            trail: '#ff3d71',
            red: '#ff3d71'
        }),
        ground: Object.freeze({
            fill: '#071c12',
            stroke: '#64e379',
            line: '#a8ffb2'
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
            fpsPanelFill: 'rgba(3, 8, 18, 0.76)',
            fpsPanelStroke: 'rgba(48, 213, 200, 0.7)',
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
        hudClearTopRatio: 0.14,
        fpsXRatio: 0.03,
        fpsYRatio: 0.125,
        fpsFontRatio: 0.026,
        fpsPaddingRatio: 0.012,
        fpsPanelLineWidth: 1.5,
        fpsUpdateMs: 250
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
        trampolineSplashCount: 38,
        trampolineSplashSpeed: 0,
        trampolineSplashDispersionRatio: 0.1,
        trampolineSplashAlpha: 0.98,
        trampolineSplashSizeMultiplier: 2.05,
        trampolineSplashLifetimeMultiplier: 3,
        trampolineSplashCooldownMs: 1000,
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
        }),
        hazard: Object.freeze({
            minAlpha: 0.04,
            maxAlpha: 0.22,
            outlineAlpha: 0.36,
            envelopeAlpha: 0.16,
            envelopeGlowAlpha: 0.18,
            envelopeLineWidth: 1.5,
            envelopeGlowWidth: 5,
            glowBlur: 8,
            sampleStep: 3
        })
    }),
    badVersionEffects: Object.freeze({
        obstacles: Object.freeze({
            fillAlpha: 0.68,
            groundFillAlpha: 0.44,
            groundCapAlpha: 0.18,
            highlightAlpha: 0.74,
            innerHighlightAlpha: 0.18,
            hazardInnerScale: 0.58,
            hazardInnerStrokeAlpha: 0.46,
            thinStrokeWidth: 1.35,
            outerGlowWidth: 7,
            accentInsetRatio: 0.08,
            innerCopyInsetRatio: 0.16,
            innerCopyFillAlpha: 0.18,
            hazardFill: 'rgba(36, 4, 16, 0.72)',
            hazardCoreFill: 'rgba(255, 61, 113, 0.14)',
            cubeFill: 'rgba(3, 9, 20, 0.82)',
            cubeHighlightFill: 'rgba(31, 122, 255, 0.12)',
            grayFill: 'rgba(18, 21, 26, 0.82)',
            grayHighlightFill: 'rgba(185, 194, 201, 0.13)',
            greenFill: 'rgba(4, 28, 18, 0.82)',
            greenHighlightFill: 'rgba(100, 227, 121, 0.14)',
            groundFill: 'rgba(3, 8, 18, 0.56)',
            groundCapFill: 'rgba(100, 227, 121, 0.16)',
            shadow: 'rgba(0, 0, 0, 0.32)'
        }),
        lights: Object.freeze({
            radiusMultiplier: 1.08,
            alphaMultiplier: 0.92,
            hazardRadiusMultiplier: 1.02,
            hazardAlphaMultiplier: 0.9,
            bloomRadiusMultiplier: 1.24,
            bloomAlphaMultiplier: 0.2,
            compositeAlphaMultiplier: 0.86
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
        rotationMarkerWidthRatio: 0.22,
        rotationMarkerLengthRatio: 1.05,
        rotationMarkerOffsetRatio: 0.16,
        rotationMarkerAlpha: 0.55,
        minScreenRadius: 6,
        bodyShadowBlurRatio: 0.85,
        innerHighlightRadiusRatio: 0.42,
        innerHighlightAlpha: 0.34
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
            hexagonCount: 2,
            hexagonRadiusRatio: 0.18,
            hexagonRadiusStepRatio: 0.125,
            hexagonLineWidth: 2.15,
            secondaryHexagonCount: 0,
            secondaryHexagonRadiusRatio: 0.09,
            secondaryHexagonRadiusStepRatio: 0.12,
            streakCount: 8,
            streakSpacingRatio: 0.19,
            streakLengthRatio: 0.34,
            streakLineWidth: 1.45,
            parallaxShiftRatio: 0.006,
            cameraParallaxXRatio: 0.012,
            cameraParallaxYRatio: 0.008,
            motionTimeScale: 0.16,
            streakTimeScale: 0.12,
            flashMotionRatio: 0.006,
            triangleRotationScale: 0.05,
            rectangleRotationScale: 0.04,
            accentLineWidth: 1.2,
            flashAlpha: 0.58,
            stableFlashAlpha: 0.44,
            flashGlowWidth: 9,
            flashLineWidth: 2.4,
            flashLengthRatio: 0.28,
            triangleSilhouetteLineWidth: 1.15,
            flashes: Object.freeze([
                Object.freeze({x: 0.11, y: 0.22, length: 0.18, color: 'blue'}),
                Object.freeze({x: 0.28, y: 0.33, length: 0.24, color: 'magenta'}),
                Object.freeze({x: 0.70, y: 0.24, length: 0.20, color: 'magenta'}),
                Object.freeze({x: 0.84, y: 0.58, length: 0.28, color: 'magenta'}),
                Object.freeze({x: 0.49, y: 0.76, length: 0.16, color: 'blue'})
            ]),
            triangles: Object.freeze([
                Object.freeze({x: 0.12, y: 0.68, radius: 62, rotation: -0.62, alpha: 0.76}),
                Object.freeze({x: 0.25, y: 0.42, radius: 42, rotation: 0.48, alpha: 0.52}),
                Object.freeze({x: 0.42, y: 0.18, radius: 78, rotation: 0.12, alpha: 0.42}),
                Object.freeze({x: 0.61, y: 0.74, radius: 54, rotation: -0.22, alpha: 0.58}),
                Object.freeze({x: 0.77, y: 0.38, radius: 88, rotation: 0.78, alpha: 0.48}),
                Object.freeze({x: 0.91, y: 0.66, radius: 48, rotation: -0.88, alpha: 0.64})
            ]),
            rectangles: Object.freeze([
                Object.freeze({x: 0.18, y: 0.24, width: 12, height: 5, rotation: 0.15, danger: true}),
                Object.freeze({x: 0.34, y: 0.70, width: 9, height: 4, rotation: -0.35, danger: false}),
                Object.freeze({x: 0.52, y: 0.28, width: 6, height: 6, rotation: 0.1, danger: false}),
                Object.freeze({x: 0.73, y: 0.62, width: 14, height: 5, rotation: 0.58, danger: true}),
                Object.freeze({x: 0.86, y: 0.34, width: 7, height: 7, rotation: -0.2, danger: false})
            ])
        })
    }),
    visualStability: Object.freeze({
        stableBrightness: true,
        freezeHazardPulse: true,
        freezeBackgroundParallax: true,
        useDistantBackgroundMotion: true,
        freezeBadVersionBackground: true,
        backgroundCompositeOperation: 'source-over',
        effectCompositeOperation: 'source-over',
        stableEffectAlphaMultiplier: 0.42,
        stableLightCompositeMultiplier: 0.5
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

function getHudCenterY(viewHeight, selectedVersion)
{
    const ratio = selectedVersion == 'bad'
        ? STYLE.ui.hudClearTopRatio / 2
        : STYLE.ui.hudTopRatio

    return viewHeight * ratio
}

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
