const STYLE = Object.freeze({
    colors: Object.freeze({
        background: Object.freeze({
            page: 'black',
            canvas: 'white',
            dark: '#0d1468',
            darkAccent: '#2a1470',
            gradientTop: '#1a2ca0',
            gradientMiddle: '#2c1f96',
            gradientBottom: '#4a1688',
            vignetteCenter: 'rgba(0, 0, 0, 0)',
            vignetteEdge: 'rgba(8, 4, 40, 0.5)',
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
            triangleSilhouetteBlueFill: 'rgba(31, 122, 255, 0.032)',
            triangleSilhouetteBlueStroke: 'rgba(143, 252, 255, 0.13)',
            triangleSilhouetteMagentaFill: 'rgba(255, 61, 113, 0.03)',
            triangleSilhouetteMagentaStroke: 'rgba(255, 93, 176, 0.12)',
            polygonAccentFill: 'rgba(31, 122, 255, 0.025)',
            polygonAccentStroke: 'rgba(48, 213, 200, 0.11)',
            polygonDangerFill: 'rgba(255, 61, 113, 0.022)',
            polygonDangerStroke: 'rgba(255, 61, 113, 0.075)',
            washBlueCore: 'rgba(31, 122, 255, 0.34)',
            washBlueMid: 'rgba(48, 213, 200, 0.12)',
            washRedCore: 'rgba(255, 61, 113, 0.52)',
            washRedMid: 'rgba(168, 55, 255, 0.2)',
            washCenter: 'rgba(44, 31, 150, 0)',
            // Far crystal layer: back row (lighter, see-through), front row
            // and the rock along the edges; each shard has a shadow and a lit facet
            crystalBackShadow: 'rgba(52, 34, 150, 0.62)',
            crystalBackLit: 'rgba(98, 70, 210, 0.58)',
            crystalFrontShadow: '#1a1158',
            crystalFrontLit: '#3a2899',
            crystalEdge: 'rgba(170, 140, 255, 0.34)',
            crystalRock: '#150e4a',
            crystalRockLit: '#21166a',
            // Depth haze over the far layer: lavender at the top and bottom,
            // where the crystals are, clear in the middle of the field
            hazeTop: 'rgba(150, 112, 255, 0.24)',
            hazeUpper: 'rgba(128, 96, 236, 0.08)',
            hazeMiddle: 'rgba(110, 80, 220, 0)',
            hazeLower: 'rgba(140, 92, 240, 0.12)',
            hazeBottom: 'rgba(176, 116, 255, 0.3)',
            // Near rocks: darker than the far layer and every gameplay fill
            nearShadow: '#06031a',
            nearMid: '#0c0729',
            nearLit: '#150d40',
            nearRim: 'rgba(150, 112, 255, 0.4)',
            nearRock: '#06031a'
        }),
        player: Object.freeze({
            fill: '#0a1446',
            stroke: '#38e8ff',
            core: '#6fa8ff',
            highlight: '#b8f7ff',
            centre: '#050a2e',
            halo: '#22c8ff',
            trail: '#30d5c8',
            cyan: '#30d5c8'
        }),
        grapnel: Object.freeze({
            rope: '#38e8ff',
            core: '#d8fbff',
            halo: '#22c8ff',
            anchorFill: '#050a2e'
        }),
        playerTrail: Object.freeze({
            halo: '#1f8fff',
            body: '#36b8ff',
            core: '#d8fbff',
            spark: '#5ff0ff',
            sparkHalo: '#22c8ff'
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
            blueStroke: '#2f86ff',
            grayFill: '#081a26',
            grayStroke: '#22d8ff',
            greenFill: '#071c12',
            greenStroke: '#2bff7a'
        }),
        hazard: Object.freeze({
            fill: '#21070f',
            classicTriangleFill: '#21070f',
            classicTriangleStroke: '#ff2d95',
            harmlessFill: '#071c12',
            stroke: '#ff2d95',
            harmlessStroke: '#2bff7a',
            trail: '#ff3d71',
            red: '#ff3d71'
        }),
        // Classic floor/ceiling strips: same green neon edge as bad mode
        ground: Object.freeze({
            fill: '#06101c',
            stroke: '#2bff7a',
            line: '#c4ffd8'
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
    // Sprite thickness and isotropic sizes use logical canvas height.
    // Values remain in the existing world/screen space of each consumer.
    spriteGeometry: Object.freeze({
        capHeightPercent: 1.2,
        bandHeightPercent: 1,
        seamInset: screenHeightPercent(100 / 1080)
    }),
    strokes: Object.freeze({
        defaultWidth: screenHeightPercent(100 * 1 / 1080),
        seamWidth: screenHeightPercent(100 * 10 / 1080),
        neonWidth: screenHeightPercent(100 * 2 / 1080),
        neonGlowWidth: screenHeightPercent(100 * 5 / 1080),
        // Bold obstacle and floor outlines (strokeNeonPath). Widths are screen
        // pixels at 1080: divided by scale[version] when drawn, so both versions
        // look the same. Halo and core are plain strokes, no shadowBlur.
        neonOutline: Object.freeze({
            width: screenHeightPercent(100 * 7 / 1080),
            haloWidth: screenHeightPercent(100 * 26 / 1080),
            haloAlpha: 0.16,
            innerHaloWidth: screenHeightPercent(100 * 14 / 1080),
            innerHaloAlpha: 0.32,
            coreWidthRatio: 0.36,
            coreColor: '#ffffff',
            coreAlpha: 0.55,
            innerWidth: screenHeightPercent(100 * 3 / 1080),
            groundAlpha: 0.5
        }),
        grapnelWidthHeightPercent: 0.6,
        menuIconWidthRatio: 0.05,
        checkMarkWidthRatio: 0.03
    }),
    ui: Object.freeze({
        fontFamily: 'Consolas, Monaco, "Courier New", monospace',
        textShadowBlur: screenHeightPercent(100 * 8 / 1080),
        buttonShadowBlur: screenHeightPercent(100 * 10 / 1080),
        buttonInsetRatio: 0.08,
        buttonLineWidth: screenHeightPercent(100 * 2 / 1080),
        buttonTextPaddingRatio: 0.34,
        buttonMinFontSize: 12, // Minimum readable pixel font size; intentionally unscaled.
        hudExtraShadowBlur: screenHeightPercent(100 * 5 / 1080),
        stageExtraShadowBlur: screenHeightPercent(100 * 4 / 1080),
        pauseMarginWidthPercent: 100 * 24 / 1920,
        pauseMarginHeightPercent: 100 * 28 / 1080,
        pausePanelLineWidth: screenHeightPercent(100 * 2 / 1080),
        hudTopRatio: 0.06,
        hudFontRatio: 0.042,
        hudBadMaxFontWidthRatio: 0.078,
        hudLetterSpacing: screenWidthPercent(100 * 4 / 1920),
        hudStageFontRatio: 0.032,
        hudStageDotRatio: 0.006,
        hudStageGapRatio: 0.031,
        hudStageDiamondRatio: 0.018,
        hudStageLineRatio: 0.0018,
        hudRecordXRatio: 0.91,
        hudBadRecordXRatio: 0.865,
        hudBadTextGapRatio: 0.025,
        hudBadTextBackingPaddingRatio: 0.005,
        hudBadMenuButtonSizeRatio: 0.052,
        hudBadMenuButtonMaxWidthRatio: 0.09,
        hudBadMenuButtonMarginRatio: 0.025,
        hudClearTopRatio: 0.14,
        badCeilingBandRatio: 0.2,
        fpsXRatio: 0.03,
        fpsYRatio: 0.125,
        fpsFontRatio: 0.026,
        fpsPaddingRatio: 0.012,
        fpsPanelLineWidth: screenHeightPercent(100 * 1.5 / 1080),
        fpsUpdateMs: 250
    }),
    // Coloured light spill on the crystal background (LightmapRenderer).
    // Radii are screen px at 1080 (the same size in both modes); block lights
    // also grow by the block's own radius.
    lights: Object.freeze({
        resolutionScale: 0.2,
        playerRadius: 210,
        cubeRadius: 140,
        hazardRadius: 150,
        // Cap on the block-size bonus, so the huge classic blocks do not flood the screen
        maxElementRadius: 170,
        playerAlpha: 0.85,
        cubeAlpha: 0.65,
        hazardAlpha: 0.75,
        // Blocks wider than this part of the view light only from their edge
        // facing the view centre, fading over edgeFadeViewRatio of the view width
        maxBlockViewWidthRatio: 0.9,
        edgeFadeViewRatio: 0.15,
        // Gradient stops [offset, alpha]: a bright middle with a soft edge
        falloff: Object.freeze([
            Object.freeze([0, 1]),
            Object.freeze([0.35, 0.55]),
            Object.freeze([0.7, 0.16]),
            Object.freeze([1, 0])
        ]),
        // hard-light pushes the crystals toward the light's hue (green stays
        // green on the blue rock); 'lighter' would only brighten them to cyan
        compositeAlpha: 1,
        compositeOperation: 'hard-light'
    }),
    // Bloom: the emissive shapes (outlines, ninja ring, rope, player trail,
    // sparks) are redrawn into a low-resolution glow canvas, blurred by a
    // downsample chain and added over the frame before the HUD.
    bloom: Object.freeze({
        // Glow canvas size per axis, as a part of the backing store (<= 1/4)
        resolutionScale: 0.25,
        // Each blur level halves the previous one: 1/4, 1/8, 1/16, 1/32 of the backing
        blurLevels: 4,
        // Added alpha of each level (sharp to wide) and overall strength. The
        // sharp level is weak so the lines keep their colour instead of going white.
        levelAlphas: Object.freeze([0.22, 0.4, 0.65, 0.9]),
        strength: 1,
        // Outline width in the glow pass, screen px at 1080 (divided by scale[version])
        lineWidth: 14,
        compositeOperation: 'lighter'
    }),
    // Ambient life: tiny motes drifting over the background and a slow neon
    // pulse. Both are pure functions of the page clock (frozen in the
    // captures), so they never flicker and draw no random numbers per frame.
    ambient: Object.freeze({
        moteCount: 40,
        moteSeed: 186,
        // Screen px at 1080 (divided by scale[version])
        moteMinSize: 4,
        moteMaxSize: 10,
        moteHaloRatio: 3.5,
        moteHaloAlpha: 0.3,
        // Drift speed in screen px at 1080 per second; motes rise slowly
        moteMinSpeed: 10,
        moteMaxSpeed: 28,
        moteRiseRatio: 0.7,
        // Part of the camera movement the motes follow (depth parallax)
        moteParallax: 0.25,
        moteMinAlpha: 0.5,
        moteMaxAlpha: 0.95,
        // Each mote fades in and out over its own period (ms)
        moteMinTwinkleMs: 2200,
        moteMaxTwinkleMs: 4200,
        moteColors: Object.freeze(['#9feaff', '#c9a8ff', '#e6f6ff', '#7fc4ff']),
        // Neon halo and bloom brightness swing by +-pulseAmount over pulsePeriodMs
        pulsePeriodMs: 2000,
        pulseAmount: 0.08
    }),
    // Final colour grade over the world (under the HUD), toward the cover art:
    // a multiply that cuts mostly red deepens the shadows into blue (violet at
    // the bottom) while keeping the green neon green, a soft-light pass pushes the bright areas toward magenta, and a
    // dark navy vignette closes the corners.
    colorGrade: Object.freeze({
        shadowOperation: 'multiply',
        shadowTop: 'rgba(110, 215, 255, 0.5)',
        shadowBottom: 'rgba(150, 200, 255, 0.5)',
        highlightOperation: 'soft-light',
        highlightCenterX: 0.5,
        highlightCenterY: 0.55,
        highlightCenter: 'rgba(255, 60, 190, 0.22)',
        highlightEdge: 'rgba(255, 60, 190, 0.1)',
        // Inner radius of the clear centre, as a part of the half-diagonal
        vignetteInner: 0.3,
        vignetteEdge: 'rgba(3, 0, 22, 0.88)'
    }),
    particles: Object.freeze({
        maxCount: 140,
        spawnBurst: 12,
        lifetimeMs: 360,
        playerEmitCount: 1,
        worldEmitIntervalMs: 160,
        cubeEmitChance: 0.24,
        hazardEmitChance: 0.42,
        minSize: screenHeightPercent(100 * 2 / 1080),
        maxSize: screenHeightPercent(100 * 4 / 1080),
        // Radial velocities keep one height scale to preserve emission angles.
        playerMinSpeed: screenHeightPercent(100 * 0.08 / 1080),
        playerSpeed: screenHeightPercent(100 * 1.15 / 1080),
        cubeSpeed: screenHeightPercent(100 * 0.34 / 1080),
        hazardSpeed: screenHeightPercent(100 * 0.66 / 1080),
        trampolineSplashCount: 38,
        trampolineSplashSpeed: 0,
        trampolineSplashDispersionX: screenWidthPercent(100 * 57.5 / 1920),
        trampolineSplashDispersionY: screenHeightPercent(100 * 57.5 / 1080),
        trampolineSplashAlpha: 0.98,
        trampolineSplashSizeMultiplier: 2.05,
        trampolineSplashLifetimeMultiplier: 3,
        playerAlpha: 0.58,
        cubeAlpha: 0.28,
        hazardAlpha: 0.52
    }),
    trails: Object.freeze({
        // Widths are ratios of the track line width (1.5 ninja radii).
        player: Object.freeze({
            widthRatio: 4.2,
            minScreenWidth: screenHeightPercent(100 * 16 / 1080),
            haloWidthRatio: 2.1,
            haloAlpha: 0.24,
            bodyLayers: 3,
            bodyAlpha: 0.3,
            coreWidthRatio: 0.3,
            coreAlpha: 0.6,
            coreStartRatio: 0.4,
            maxAlpha: 1,
            headWidthRatio: 1,
            tailWidthRatio: 0.15,
            minPointDistanceRatio: 0.42,
            minSegmentRatio: 0,
            // Square sparks scattered along the ribbon (ParticleSystem).
            sparkRatePerMs: 0.05,
            sparkMinSpeedRatio: 0.35,
            sparkLifetimeMs: 700,
            sparkMinScreenSize: screenHeightPercent(100 * 5 / 1080),
            sparkMaxScreenSize: screenHeightPercent(100 * 10 / 1080),
            sparkSpeed: screenHeightPercent(100 * 0.05 / 1080),
            sparkAlpha: 0.95,
            sparkHaloRatio: 2.2,
            sparkHaloAlpha: 0.3,
            sparkTailRatio: 0.1,
            sparkHeadRatio: 0.8
        }),
        hazard: Object.freeze({
            minAlpha: 0.04,
            maxAlpha: 0.22,
            outlineAlpha: 0.36,
            envelopeAlpha: 0.16,
            envelopeGlowAlpha: 0.18,
            envelopeLineWidth: screenHeightPercent(100 * 1.5 / 1080),
            envelopeGlowWidth: screenHeightPercent(100 * 5 / 1080),
            glowBlur: screenHeightPercent(100 * 8 / 1080),
            sampleStep: 3
        })
    }),
    badVersionEffects: Object.freeze({
        obstacles: Object.freeze({
            fillAlpha: 0.68,
            groundFillAlpha: 0.44,
            groundCapAlpha: 0.18,
            innerHighlightAlpha: 0.18,
            hazardInnerScale: 0.58,
            hazardInnerStrokeAlpha: 0.46,
            thinStrokeWidth: screenHeightPercent(100 * 1.35 / 1080),
            outerGlowWidth: screenHeightPercent(100 * 7 / 1080),
            accentInsetRatio: 0.08,
            innerCopyInsetRatio: 0.16,
            innerCopyFillAlpha: 0.18,
            hazardFill: 'rgba(36, 4, 16, 0.72)',
            hazardCoreFill: 'rgba(255, 61, 113, 0.14)',
            cubeFill: 'rgba(3, 9, 20, 0.82)',
            cubeHighlightFill: 'rgba(31, 122, 255, 0.12)',
            grayFill: 'rgba(6, 20, 30, 0.82)',
            grayHighlightFill: 'rgba(34, 216, 255, 0.13)',
            greenFill: 'rgba(4, 28, 18, 0.82)',
            greenHighlightFill: 'rgba(100, 227, 121, 0.14)',
            groundFill: '#030812',
            groundCapFill: '#102b1b',
            groundStroke: '#2bff7a',
            groundLine: '#c4ffd8',
            shadow: 'rgba(0, 0, 0, 0.32)'
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
            widthMultiplier: 0.48,
            alphaMultiplier: 1
        })
    }),
    playerVisuals: Object.freeze({
        rotationSpeed: 0.032,
        rotationMinSpeed: screenHeightPercent(100 * 0.03 / 1080),
        rotationMarkerWidthRatio: 0.22,
        rotationMarkerLengthRatio: 1.05,
        rotationMarkerOffsetRatio: 0.16,
        rotationMarkerAlpha: 0.55,
        minScreenRadius: screenHeightPercent(100 * 6 / 1080),
        ringWidthRatio: 0.25,
        ringCoreWidthRatio: 0.35,
        haloRadiusRatio: 2.6,
        haloBlurRatio: 0.9,
        haloAlpha: 1,
        haloGlowAlpha: 0.45,
        maxSpritePixelScale: 3
    }),
    // Ratios of the rounded rope width (STYLE.strokes.grapnelWidthHeightPercent).
    grapnelVisuals: Object.freeze({
        minScreenWidth: screenHeightPercent(100 * 4 / 1080),
        haloWidthRatio: 4,
        haloAlpha: 0.32,
        coreWidthRatio: 0.38,
        anchorRadiusRatio: 1.8,
        anchorWidthRatio: 0.85,
        tipRadiusRatio: 2.2,
        tipCoreRadiusRatio: 1.05
    }),
    // Fake-3D back face of rectangles, cubes and green blocks: one shared light
    // direction (back face up-right). The front face stays on the hitbox.
    // depth is in screen pixels (divided by scale[version] in world units).
    extrusion: Object.freeze({
        depth: screenHeightPercent(100 * 34 / 1080),
        maxDepthRatio: 0.35,
        directionX: 1,
        directionY: -0.8,
        baseFill: '#040817',
        sideAlpha: 0.42,
        edgeAlpha: 0.9,
        edgeWidth: screenHeightPercent(100 * 1.5 / 1080)
    }),
    screenEffects: Object.freeze({
        shockwaveDurationMs: 420,
        shockwaveStartRadius: screenHeightPercent(100 * 8 / 1080),
        shockwaveEndRadius: screenHeightPercent(100 * 170 / 1080),
        shockwaveLineWidth: screenHeightPercent(100 * 3 / 1080),
        shockwaveGlowWidth: screenHeightPercent(100 * 9 / 1080),
        shockwaveAlpha: 0.72,
        shakeDurationMs: 180,
        shakeMagnitudeX: screenWidthPercent(100 * 3.5 / 1920),
        shakeMagnitudeY: screenHeightPercent(100 * 3.5 / 1080)
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
        hexagonLineWidth: screenHeightPercent(100 * 2 / 1080),
        streakCount: 12,
        streakSpacingRatio: 0.14,
        streakLengthRatio: 0.28,
        streakLineWidth: screenHeightPercent(100 * 1.5 / 1080),
        classicMotionTimeScale: 0.01,
        // Far crystal spires along the bottom and hanging from the top: one
        // seeded tile per viewport size, scrolled with the camera and tiled
        // horizontally. Heights are in logical units (the viewport is 1080 high)
        crystals: Object.freeze({
            seed: 177,
            bottomBackCount: 9,
            bottomFrontCount: 12,
            topBackCount: 8,
            topFrontCount: 10,
            bottomBackHeight: Object.freeze([330, 520]),
            bottomFrontHeight: Object.freeze([190, 360]),
            topBackHeight: Object.freeze([230, 380]),
            topFrontHeight: Object.freeze([150, 270]),
            halfWidth: Object.freeze([42, 96]),
            rockCount: 7,
            rockHeight: Object.freeze([80, 150]),
            rockHalfWidth: Object.freeze([120, 230]),
            edgeLineWidth: 2,
            // Fraction of the camera shift the layer follows and the slow
            // drift amplitude (of the viewport size); both ignore the classic
            // motion time scale, so the chill version drifts too
            cameraParallaxXRatio: 0.12,
            cameraParallaxYRatio: 0.03,
            driftRatio: 0.02,
            // Highest offscreen pixels per logical unit
            maxPixelScale: 1
        }),
        // Near rocks: large dark low-poly boulders along the bottom edge with
        // a few tall outcrops, and short ones hanging from the top. Most of
        // them sit under the HUD band and the ground strip; they follow more
        // of the camera than the far crystals, so they read as closer
        nearRocks: Object.freeze({
            seed: 178,
            bottomCount: 7,
            bottomHeight: Object.freeze([140, 250]),
            bottomHalfWidth: Object.freeze([130, 260]),
            outcropCount: 2,
            outcropHeight: Object.freeze([300, 400]),
            outcropHalfWidth: Object.freeze([90, 150]),
            topCount: 4,
            topHeight: Object.freeze([110, 190]),
            topHalfWidth: Object.freeze([110, 210]),
            rimLineWidth: 2.5,
            cameraParallaxXRatio: 0.4,
            cameraParallaxYRatio: 0.08,
            driftRatio: 0.07,
            maxShiftYRatio: 0.03,
            maxPixelScale: 1
        }),
        badVersion: Object.freeze({
            hexagonCount: 2,
            hexagonRadiusRatio: 0.18,
            hexagonRadiusStepRatio: 0.125,
            hexagonLineWidth: screenHeightPercent(100 * 2.15 / 1080),
            secondaryHexagonCount: 0,
            secondaryHexagonRadiusRatio: 0.09,
            secondaryHexagonRadiusStepRatio: 0.12,
            streakCount: 8,
            streakSpacingRatio: 0.19,
            streakLengthRatio: 0.34,
            streakLineWidth: screenHeightPercent(100 * 1.45 / 1080),
            parallaxShiftRatio: 0.009,
            cameraParallaxXRatio: 0.018,
            cameraParallaxYRatio: 0.012,
            motionTimeScale: 0.24,
            hexagonRotationTimeScale: 0.45,
            streakTimeScale: 0.18,
            flashMotionRatio: 0.000,
            triangleRotationScale: 0.05,
            rectangleRotationScale: 0.04,
            accentLineWidth: screenHeightPercent(100 * 1.2 / 1080),
            flashAlpha: 0.58,
            stableFlashAlpha: 0.44,
            flashGlowWidth: screenHeightPercent(100 * 9 / 1080),
            flashLineWidth: screenHeightPercent(100 * 2.4 / 1080),
            flashLengthRatio: 0.28,
            flashColorSplitRatio: 0.5,
            washRadiusRatio: 0.82,
            washLeftXRatio: 0.05,
            washRightXRatio: 0.88,
            washYRatio: 0.54,
            triangleSilhouetteLineWidth: screenHeightPercent(100 * 1.15 / 1080),
            flashes: Object.freeze([
                Object.freeze({x: 0.08, y: 0.20, length: 0.16, angle: -35, width: screenHeightPercent(100 * 1.6 / 1080), glowWidth: screenHeightPercent(100 * 6 / 1080), alpha: 0.72}),
                Object.freeze({x: 0.24, y: 0.38, length: 0.28, angle: -48, width: screenHeightPercent(100 * 3.2 / 1080), glowWidth: screenHeightPercent(100 * 12 / 1080), alpha: 1, form: 'broken',
                    segments: Object.freeze([
                        Object.freeze({start: 0, end: 0.34}),
                        Object.freeze({start: 0.48, end: 0.67}),
                        Object.freeze({start: 0.80, end: 1})
                    ])
                }),
                Object.freeze({x: 0.63, y: 0.18, length: 0.21, angle: -28, width: screenHeightPercent(100 * 2.1 / 1080), glowWidth: screenHeightPercent(100 * 8 / 1080), alpha: 0.82, form: 'fragments',
                    fragments: Object.freeze([
                        Object.freeze({x: 0, y: 0, length: 0.24, angleOffset: 0}),
                        Object.freeze({x: 0.07, y: 0.03, length: 0.14, angleOffset: 0.32}),
                        Object.freeze({x: -0.04, y: 0.08, length: 0.10, angleOffset: -0.42})
                    ])
                }),
                Object.freeze({x: 0.79, y: 0.62, length: 0.34, angle: -57, width: screenHeightPercent(100 * 2.7 / 1080), glowWidth: screenHeightPercent(100 * 13 / 1080), alpha: 0.94}),
                Object.freeze({x: 0.45, y: 0.79, length: 0.13, angle: -40, width: screenHeightPercent(100 * 1.4 / 1080), glowWidth: screenHeightPercent(100 * 5 / 1080), alpha: 0.62, form: 'fragments',
                    fragments: Object.freeze([
                        Object.freeze({x: 0, y: 0, length: 0.20, angleOffset: 0}),
                        Object.freeze({x: 0.10, y: -0.04, length: 0.13, angleOffset: -0.24}),
                        Object.freeze({x: -0.06, y: 0.05, length: 0.09, angleOffset: 0.5})
                    ])
                }),
                Object.freeze({x: 0.92, y: 0.34, length: 0.12, angle: -68, width: screenHeightPercent(100 * 1.8 / 1080), glowWidth: screenHeightPercent(100 * 7 / 1080), alpha: 0.56, form: 'broken',
                    segments: Object.freeze([
                        Object.freeze({start: 0, end: 0.42}),
                        Object.freeze({start: 0.62, end: 1})
                    ])
                }),
                Object.freeze({x: 0.15, y: 0.55, length: 0.18, angle: -62, width: screenHeightPercent(100 * 1.7 / 1080), glowWidth: screenHeightPercent(100 * 7 / 1080), alpha: 0.58, form: 'broken',
                    segments: Object.freeze([
                        Object.freeze({start: 0, end: 0.30}),
                        Object.freeze({start: 0.46, end: 0.63}),
                        Object.freeze({start: 0.78, end: 1})
                    ])
                }),
                Object.freeze({x: 0.35, y: 0.12, length: 0.11, angle: -24, width: screenHeightPercent(100 * 1.3 / 1080), glowWidth: screenHeightPercent(100 * 5 / 1080), alpha: 0.48, form: 'fragments',
                    fragments: Object.freeze([
                        Object.freeze({x: 0, y: 0, length: 0.18, angleOffset: 0}),
                        Object.freeze({x: 0.08, y: 0.05, length: 0.11, angleOffset: 0.42}),
                        Object.freeze({x: -0.06, y: 0.03, length: 0.09, angleOffset: -0.36})
                    ])
                }),
                Object.freeze({x: 0.68, y: 0.47, length: 0.16, angle: -36, width: screenHeightPercent(100 * 1.6 / 1080), glowWidth: screenHeightPercent(100 * 7 / 1080), alpha: 0.52}),
                Object.freeze({x: 0.84, y: 0.84, length: 0.20, angle: -52, width: screenHeightPercent(100 * 2 / 1080), glowWidth: screenHeightPercent(100 * 9 / 1080), alpha: 0.6, form: 'broken',
                    segments: Object.freeze([
                        Object.freeze({start: 0, end: 0.24}),
                        Object.freeze({start: 0.38, end: 0.58}),
                        Object.freeze({start: 0.74, end: 1})
                    ])
                })
            ]),
            triangles: Object.freeze([
                Object.freeze({
                    x: 0.12, y: 0.68, radius: 62, rotation: -0.62, alpha: 0.76,
                    points: Object.freeze([
                        Object.freeze({x: -0.82, y: 0.58}),
                        Object.freeze({x: 0.52, y: 0.46}),
                        Object.freeze({x: 0.16, y: -1.02})
                    ])
                }),
                Object.freeze({
                    x: 0.25, y: 0.42, radius: 42, rotation: 0.48, alpha: 0.52,
                    points: Object.freeze([
                        Object.freeze({x: -0.68, y: 0.76}),
                        Object.freeze({x: 0.84, y: 0.18}),
                        Object.freeze({x: -0.04, y: -0.78})
                    ])
                }),
                Object.freeze({
                    x: 0.42, y: 0.18, radius: 78, rotation: 0.12, alpha: 0.42,
                    points: Object.freeze([
                        Object.freeze({x: -0.98, y: 0.38}),
                        Object.freeze({x: 0.74, y: 0.70}),
                        Object.freeze({x: 0.34, y: -0.78})
                    ])
                }),
                Object.freeze({
                    x: 0.61, y: 0.74, radius: 54, rotation: -0.22, alpha: 0.58,
                    points: Object.freeze([
                        Object.freeze({x: -0.62, y: 0.88}),
                        Object.freeze({x: 0.72, y: 0.18}),
                        Object.freeze({x: -0.10, y: -0.96})
                    ])
                }),
                Object.freeze({
                    x: 0.77, y: 0.38, radius: 88, rotation: 0.78, alpha: 0.48,
                    points: Object.freeze([
                        Object.freeze({x: -0.72, y: 0.42}),
                        Object.freeze({x: 0.92, y: 0.62}),
                        Object.freeze({x: 0.08, y: -0.94})
                    ])
                }),
                Object.freeze({
                    x: 0.91, y: 0.66, radius: 48, rotation: -0.88, alpha: 0.64,
                    points: Object.freeze([
                        Object.freeze({x: -0.92, y: 0.12}),
                        Object.freeze({x: 0.58, y: 0.82}),
                        Object.freeze({x: 0.10, y: -0.74})
                    ])
                }),
                Object.freeze({
                    x: 0.06, y: 0.31, radius: 36, rotation: 0.92, alpha: 0.44,
                    points: Object.freeze([
                        Object.freeze({x: -0.70, y: 0.64}),
                        Object.freeze({x: 0.86, y: 0.30}),
                        Object.freeze({x: 0.02, y: -0.86})
                    ])
                }),
                Object.freeze({
                    x: 0.33, y: 0.86, radius: 64, rotation: -1.08, alpha: 0.38,
                    points: Object.freeze([
                        Object.freeze({x: -0.86, y: 0.34}),
                        Object.freeze({x: 0.66, y: 0.76}),
                        Object.freeze({x: 0.22, y: -0.90})
                    ])
                }),
                Object.freeze({
                    x: 0.56, y: 0.31, radius: 34, rotation: 1.34, alpha: 0.36,
                    points: Object.freeze([
                        Object.freeze({x: -0.58, y: 0.82}),
                        Object.freeze({x: 0.74, y: 0.28}),
                        Object.freeze({x: -0.20, y: -0.78})
                    ])
                }),
                Object.freeze({
                    x: 0.84, y: 0.16, radius: 58, rotation: -0.34, alpha: 0.40,
                    points: Object.freeze([
                        Object.freeze({x: -0.76, y: 0.50}),
                        Object.freeze({x: 0.88, y: 0.44}),
                        Object.freeze({x: 0.18, y: -0.98})
                    ])
                })
            ]),
            rectangles: Object.freeze([
                Object.freeze({x: 0.18, y: 0.24, width: 12, height: 5, rotation: 0.15, danger: true}),
                Object.freeze({x: 0.34, y: 0.70, width: 9, height: 4, rotation: -0.35, danger: false}),
                Object.freeze({x: 0.52, y: 0.28, width: 6, height: 6, rotation: 0.1, danger: false}),
                Object.freeze({x: 0.73, y: 0.62, width: 14, height: 5, rotation: 0.58, danger: true}),
                Object.freeze({x: 0.86, y: 0.34, width: 7, height: 7, rotation: -0.2, danger: false})
            ])
        }),
        menu: Object.freeze({
            hexagonCount: 3,
            hexagonRadiusRatio: 0.2,
            hexagonRadiusStepRatio: 0.13,
            streakCount: 9,
            streakSpacingRatio: 0.17,
            streakLengthRatio: 0.36,
            flashAlpha: 0.7,
            stableFlashAlpha: 0.62,
            flashGlowWidth: screenHeightPercent(100 * 12 / 1080),
            flashLineWidth: screenHeightPercent(100 * 2.7 / 1080),
            flashColorSplitRatio: 0.5,
            washLeftXRatio: 0.12,
            washRightXRatio: 0.88,
            washYRatio: 0.5,
            triangleSilhouetteLineWidth: screenHeightPercent(100 * 1.35 / 1080),
            flashes: Object.freeze([
                Object.freeze({x: 0.07, y: 0.18, length: 0.24, angle: -38, width: screenHeightPercent(100 * 2.2 / 1080), glowWidth: screenHeightPercent(100 * 9 / 1080), alpha: 0.86}),
                Object.freeze({x: 0.20, y: 0.80, length: 0.22, angle: -56, width: screenHeightPercent(100 * 2.6 / 1080), glowWidth: screenHeightPercent(100 * 11 / 1080), alpha: 0.74, form: 'broken',
                    segments: Object.freeze([
                        Object.freeze({start: 0, end: 0.28}),
                        Object.freeze({start: 0.44, end: 0.72}),
                        Object.freeze({start: 0.86, end: 1})
                    ])
                }),
                Object.freeze({x: 0.72, y: 0.21, length: 0.27, angle: -31, width: screenHeightPercent(100 * 2.4 / 1080), glowWidth: screenHeightPercent(100 * 10 / 1080), alpha: 0.9, form: 'fragments',
                    fragments: Object.freeze([
                        Object.freeze({x: 0, y: 0, length: 0.25, angleOffset: 0}),
                        Object.freeze({x: 0.08, y: 0.04, length: 0.16, angleOffset: 0.26}),
                        Object.freeze({x: -0.05, y: 0.08, length: 0.11, angleOffset: -0.34})
                    ])
                }),
                Object.freeze({x: 0.88, y: 0.68, length: 0.20, angle: -63, width: screenHeightPercent(100 * 2 / 1080), glowWidth: screenHeightPercent(100 * 8 / 1080), alpha: 0.72}),
                Object.freeze({x: 0.44, y: 0.88, length: 0.16, angle: -43, width: screenHeightPercent(100 * 1.7 / 1080), glowWidth: screenHeightPercent(100 * 7 / 1080), alpha: 0.58, form: 'fragments',
                    fragments: Object.freeze([
                        Object.freeze({x: 0, y: 0, length: 0.22, angleOffset: 0}),
                        Object.freeze({x: 0.10, y: -0.04, length: 0.12, angleOffset: -0.2}),
                        Object.freeze({x: -0.04, y: 0.06, length: 0.10, angleOffset: 0.42})
                    ])
                })
            ]),
            triangles: Object.freeze([
                Object.freeze({
                    x: 0.10, y: 0.62, radius: 78, rotation: -0.52, alpha: 0.82,
                    points: Object.freeze([
                        Object.freeze({x: -0.82, y: 0.58}),
                        Object.freeze({x: 0.56, y: 0.40}),
                        Object.freeze({x: 0.08, y: -1.05})
                    ])
                }),
                Object.freeze({
                    x: 0.23, y: 0.25, radius: 46, rotation: 0.36, alpha: 0.56,
                    points: Object.freeze([
                        Object.freeze({x: -0.74, y: 0.68}),
                        Object.freeze({x: 0.82, y: 0.14}),
                        Object.freeze({x: -0.02, y: -0.84})
                    ])
                }),
                Object.freeze({
                    x: 0.76, y: 0.32, radius: 90, rotation: 0.72, alpha: 0.58,
                    points: Object.freeze([
                        Object.freeze({x: -0.74, y: 0.38}),
                        Object.freeze({x: 0.90, y: 0.64}),
                        Object.freeze({x: 0.08, y: -0.96})
                    ])
                }),
                Object.freeze({
                    x: 0.89, y: 0.78, radius: 54, rotation: -0.86, alpha: 0.72,
                    points: Object.freeze([
                        Object.freeze({x: -0.92, y: 0.12}),
                        Object.freeze({x: 0.58, y: 0.82}),
                        Object.freeze({x: 0.10, y: -0.74})
                    ])
                })
            ]),
            rectangles: Object.freeze([
                Object.freeze({x: 0.16, y: 0.34, width: 10, height: 5, rotation: 0.18, danger: true}),
                Object.freeze({x: 0.36, y: 0.84, width: 8, height: 4, rotation: -0.42, danger: false}),
                Object.freeze({x: 0.66, y: 0.16, width: 7, height: 7, rotation: 0.2, danger: false}),
                Object.freeze({x: 0.84, y: 0.56, width: 13, height: 5, rotation: 0.54, danger: true})
            ])
        })
    }),
    visualStability: Object.freeze({
        stableBrightness: true,
        freezeBackgroundParallax: true,
        useDistantBackgroundMotion: true,
        freezeBadVersionBackground: false,
        backgroundCompositeOperation: 'source-over',
        effectCompositeOperation: 'source-over',
        stableEffectAlphaMultiplier: 0.42
    }),
    features: Object.freeze({
        background: true,
        lightmap: true,
        particles: true,
        playerTrail: true,
        screenEffects: true,
        uiStyling: true,
        bloom: true,
        ambient: true,
        colorGrade: true
    })
})

function getHudCenterY(viewHeight, selectedVersion)
{
    if (selectedVersion == 'bad')
        return getBadHudCeilingBoundaryY(viewHeight, selectedVersion) / 2

    return viewHeight * STYLE.ui.hudTopRatio
}

function getBadHudCeilingBoundaryY(viewHeight, selectedVersion)
{
    const versionScale = typeof scale != 'undefined' && scale[selectedVersion]
        ? scale[selectedVersion]
        : 1

    return viewHeight * STYLE.ui.badCeilingBandRatio * versionScale
}

function getHudFontSize(viewWidth, viewHeight, selectedVersion)
{
    const heightSize = viewHeight * STYLE.ui.hudFontRatio
    const size = selectedVersion == 'bad'
        ? Math.min(heightSize, viewWidth * STYLE.ui.hudBadMaxFontWidthRatio)
        : heightSize
    // Never below the CSS px floor in a small canvas (phones)
    const cssHeight = getCanvasCssRect().height
    return cssHeight > 0 ? Math.max(size, minCssFontPx * viewHeight / cssHeight) : size
}

function getHudMenuButtonLayout(viewWidth, viewHeight, selectedVersion, fallbackButton)
{
    if (selectedVersion != 'bad')
    {
        return {
            x: fallbackButton.x,
            y: fallbackButton.y,
            width: fallbackButton.width,
            height: fallbackButton.height
        }
    }

    const size = Math.min(
        viewHeight * STYLE.ui.hudBadMenuButtonSizeRatio,
        viewWidth * STYLE.ui.hudBadMenuButtonMaxWidthRatio
    )
    const margin = viewWidth * STYLE.ui.hudBadMenuButtonMarginRatio

    return {
        x: viewWidth - margin - size / 2,
        y: getHudCenterY(viewHeight, selectedVersion),
        width: size,
        height: size
    }
}

function getFpsCounterCenterY(viewWidth, viewHeight, selectedVersion, fontSize, panelHeight)
{
    const preferredY = viewHeight * STYLE.ui.fpsYRatio
    const hudBottom = getHudCenterY(viewHeight, selectedVersion)
        + getHudFontSize(viewWidth, viewHeight, selectedVersion) * 0.8
    const minY = hudBottom + panelHeight / 2 + viewHeight * STYLE.ui.hudBadTextGapRatio

    return Math.max(preferredY, minY)
}

const QUALITY = {
    lightmap: true,
    particles: true,
    playerTrail: true,
    backgroundMotion: true,
    screenShake: true,
    bloom: true,
    ambient: true,
    setLowPower: function(enabled)
    {
        const fullQuality = !enabled

        this.lightmap = fullQuality
        this.particles = fullQuality
        this.playerTrail = fullQuality
        this.backgroundMotion = fullQuality
        this.screenShake = fullQuality
        this.bloom = fullQuality
        this.ambient = fullQuality
    }
}
