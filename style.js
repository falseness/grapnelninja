const STYLE = Object.freeze({
    colors: Object.freeze({
        background: Object.freeze({
            page: 'black',
            canvas: 'white',
            dark: '#0d1468',
            darkAccent: '#2a1470',
            gradientTop: '#0a0f58',
            gradientMiddle: '#1d1378',
            gradientBottom: '#4a1688',
            vignetteCenter: 'rgba(0, 0, 0, 0)',
            vignetteEdge: 'rgba(8, 4, 40, 0.5)',
            // Far crystal layer: back row (lighter, see-through), front row
            // and the rock along the edges; each shard has a shadow and a lit facet
            crystalBackShadow: 'rgba(65, 48, 151, 0.20)',
            crystalBackLit: 'rgba(98, 74, 192, 0.22)',
            crystalFrontShadow: 'rgba(66, 46, 142, 0.26)',
            crystalFrontLit: 'rgba(100, 72, 183, 0.26)',
            crystalEdge: 'rgba(170, 140, 255, 0.12)',
            crystalRock: 'rgba(67, 45, 137, 0.22)',
            crystalRockLit: 'rgba(94, 63, 166, 0.24)',
            // Depth haze over the far layer: a faint lavender at the top (the
            // cave roof stays deep navy), magenta at the bottom, clear in the middle
            hazeTop: 'rgba(150, 112, 255, 0.08)',
            hazeUpper: 'rgba(128, 96, 236, 0.02)',
            hazeMiddle: 'rgba(110, 80, 220, 0)',
            hazeLower: 'rgba(200, 70, 240, 0.08)',
            hazeBottom: 'rgba(230, 70, 220, 0.24)',
            // Near rocks: translucent violet facets; size and parallax carry depth
            nearShadow: 'rgba(70, 47, 139, 0.26)',
            nearMid: 'rgba(86, 56, 155, 0.26)',
            nearLit: 'rgba(108, 72, 179, 0.24)',
            nearRim: 'rgba(208, 125, 236, 0.18)',
            nearRock: 'rgba(70, 47, 139, 0.26)'
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
            greenStroke: '#3dff4a'
        }),
        hazard: Object.freeze({
            fill: '#21070f',
            classicTriangleFill: '#071426',
            classicTriangleStroke: '#8fdcff',
            harmlessFill: '#071c12',
            stroke: '#ff2d95',
            harmlessStroke: '#3dff4a',
            trail: '#ff3d71',
            red: '#ff3d71'
        }),
        // Classic floor/ceiling strips: same green neon edge as bad mode
        ground: Object.freeze({
            fill: '#06101c',
            stroke: '#3dff4a',
            line: '#c4ffd8'
        }),
        ui: Object.freeze({
            title: '#eafeff',
            // Neon tube around the title letters (ninja cyan)
            titleGlow: '#30d5c8',
            text: '#d8fbff',
            hudText: '#f4feff',
            hudGlow: '#30d5c8',
            hudMuted: 'rgba(31, 122, 255, 0.42)',
            score: '#30d5c8',
            record: '#8ffcff',
            primary: '#30d5c8',
            danger: '#ff3d71',
            buttonFill: 'rgba(6, 3, 26, 0.72)',
            buttonStroke: '#30d5c8',
            buttonDangerStroke: '#ff3d71',
            buttonText: '#d8fbff',
            buttonShadow: 'rgba(48, 213, 200, 0.45)',
            transparent: 'rgba(0, 0, 0, 0)',
            mutedText: 'rgba(143, 252, 255, 0.72)',
            // Light enough that the frozen run stays visible behind the panel
            pauseOverlay: 'rgba(4, 0, 24, 0.3)',
            pausePanelFill: 'rgba(8, 3, 34, 0.5)',
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
        // look the same. Inner light and core are plain strokes, no shadowBlur.
        innerGlow: Object.freeze({
            widths: Object.freeze([2, 4, 8]),
            alphas: Object.freeze([0.28, 0.14, 0.06])
        }),
        neonOutline: Object.freeze({
            width: screenHeightPercent(100 * 7 / 1080),
            coreWidthRatio: 0.36,
            coreColor: '#ffffff',
            // Pale tint of the tube colour for the hot core: a white core on
            // green blows out to cyan after bloom and the grade
            coreColors: Object.freeze({
                '#3dff4a': '#d8ffd8',
                '#ff2d95': '#ffd6ea'
            }),
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
        // Menu and pause outlines use the game's neon (strokeNeonPath) at
        // these parts of its width; small controls get a thinner tube
        neonUnit: Object.freeze({
            button: 0.55,
            panel: 0.45,
            small: 0.3
        }),
        // Neon tube around the title letters, as parts of the font size
        titleHaloWidthRatio: 0.16,
        titleInnerHaloWidthRatio: 0.07,
        titleTubeWidthRatio: 0.03,
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
        touchResolutionScale: 0.15,
        cubeRadius: 140,
        hazardRadius: 150,
        // Cap on the block-size bonus, so the huge classic blocks do not flood the screen
        maxElementRadius: 170,
        cubeAlpha: 0.45,
        hazardAlpha: 0.5,
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
        // green on the blue rock); keep it faint and behind all gameplay art.
        // There is no player light: its cyan disc hid the cave around the ring.
        compositeAlpha: 0.3,
        compositeOperation: 'hard-light'
    }),
    // Bloom: the emissive shapes (outlines, rope, player trail,
    // sparks) are redrawn into a low-resolution glow canvas, blurred by a
    // downsample chain and added over the frame before the HUD.
    bloom: Object.freeze({
        // Glow canvas size per axis, as a part of the backing store (<= 1/4)
        resolutionScale: 0.25,
        touchResolutionScale: 0.2,
        // Each blur level halves the previous one: 1/4, 1/8, 1/16, 1/32 of the backing
        blurLevels: 4,
        // Added alpha of each level (sharp to wide) and overall strength. The
        // sharp level is weak so the lines keep their colour instead of going white.
        levelAlphas: Object.freeze([0.12, 0.2, 0.33, 0.45]),
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
        moteMinSpeed: 1,
        moteMaxSpeed: 3,
        moteRiseRatio: 0.7,
        // Part of the camera movement the motes follow (depth parallax)
        moteParallax: 0.25,
        moteMinAlpha: 0.5,
        moteMaxAlpha: 0.95,
        // Each mote fades in and out over its own period (ms)
        moteMinTwinkleMs: 6000,
        moteMaxTwinkleMs: 12000,
        moteColors: Object.freeze(['#9feaff', '#c9a8ff', '#e6f6ff', '#7fc4ff']),
        // Neon halo and bloom brightness swing by +-pulseAmount over pulsePeriodMs
        pulsePeriodMs: 2000,
        pulseAmount: 0.08
    }),
    // Final colour grade over the world (under the HUD), toward the cover art:
    // a multiply that cuts mostly red deepens the shadows into blue (violet at
    // the bottom) while keeping the green neon green, a soft-light pass pushes the bright areas toward magenta, and a
    // dark navy vignette closes the corners. Off (features.colorGrade): it
    // dimmed the whole frame by about a quarter and turned the green neon teal.
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
        // Sparse deterministic beats also bound each seeded obstacle's 5 s count.
        embers: Object.freeze({
            hazardIntervalMs: 3000,
            badHazardIntervalMs: 350,
            cubeIntervalMs: 5000,
            badCubeIntervalMs: 2000,
            minLifetimeMs: 1500,
            maxLifetimeMs: 2000,
            fadeInMs: 300,
            fadeOutMs: 600,
            alpha: 0.38,
            cubeAlpha: 0.38,
            minSize: screenHeightPercent(100 * 4 / 1080),
            maxSize: screenHeightPercent(100 * 6 / 1080),
            riseSpeed: screenHeightPercent(100 * 0.012 / 1080),
            sway: screenHeightPercent(100 * 3 / 1080),
            swayPeriodMs: 450,
            radiusRatio: 1.05,
            hazardColor: '#ff547f',
            cubeColor: '#559dff'
        }),
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
            minScreenWidth: screenHeightPercent(100 * 30 / 1080),
            haloWidthRatio: 2.1,
            haloAlpha: 0.38,
            bodyLayers: 3,
            bodyAlpha: 0.45,
            coreWidthRatio: 0.3,
            coreAlpha: 0.8,
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
            // Halo strokes in place of the shadowBlur glow: extra width in
            // glowBlur units (canvas px) and alpha, wide to narrow
            haloWidths: Object.freeze([2.4, 1.2]),
            haloAlphas: Object.freeze([0.07, 0.1]),
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
            greenFill: 'rgba(10, 64, 36, 0.8)',
            greenHighlightFill: 'rgba(90, 255, 140, 0.3)',
            groundFill: '#030812',
            groundCapFill: '#102b1b',
            groundStroke: '#3dff4a',
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
            widthMultiplier: 1,
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
        // Pre-overhaul size (e430f92): see Ninja.getRingOuterRadius
        minScreenRadius: screenHeightPercent(100 * 6 / 1080),
        ringWidthRatio: 0.38,
        ringCoreWidthRatio: 0.35,
        rimWidthRatio: 0.22,
        rimAlpha: 0.85,
        // Sprite margin for the ring's antialiasing: nothing is drawn outside the ball
        spriteRadiusRatio: 1.05,
        innerRimAlpha: 0.18,
        innerRimWidths: Object.freeze([6, 4, 2]),
        innerRimAlphas: Object.freeze([0.18, 0.35, 1]),
        maxSpritePixelScale: 3
    }),
    // Ratios of the rounded rope width (STYLE.strokes.grapnelWidthHeightPercent).
    grapnelVisuals: Object.freeze({
        minScreenWidth: screenHeightPercent(100 * 6 / 1080),
        haloWidthRatio: 4,
        haloAlpha: 0.45,
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
        sideAlpha: 0.62,
        edgeAlpha: 0.9,
        edgeWidth: screenHeightPercent(100 * 1.5 / 1080)
    }),
    screenEffects: Object.freeze({
        shockwaveDurationMs: 420,
        shockwaveStartRadius: screenHeightPercent(100 * 8 / 1080),
        shockwaveEndRadius: screenHeightPercent(100 * 170 / 1080),
        shockwaveLineWidth: screenHeightPercent(100 * 3 / 1080),
        shockwaveGlowWidth: screenHeightPercent(100 * 9 / 1080),
        // Halo strokes in place of the shadowBlur glow: extra width in
        // shockwaveGlowWidth units (canvas px) and alpha, wide to narrow
        shockwaveHaloWidths: Object.freeze([2.4, 1.2]),
        shockwaveHaloAlphas: Object.freeze([0.12, 0.2]),
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
    }),
    caveLayers: Object.freeze({
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
            // Fraction of world translation; no time-driven cave sway.
            cameraParallaxXRatio: 0.08,
            cameraParallaxYRatio: 0.015,
            // Highest offscreen pixels per logical unit
            maxPixelScale: 1
        }),
        // Near rocks: large translucent low-poly boulders along the bottom edge with
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
            cameraParallaxXRatio: 0.25,
            cameraParallaxYRatio: 0.04,
            maxShiftYRatio: 0.03,
            maxPixelScale: 1
        }),
    }),
    visualStability: Object.freeze({
        stableBrightness: true,
        freezeBadVersionBackground: false,
        effectCompositeOperation: 'source-over',
        stableEffectAlphaMultiplier: 0.42
    }),
    features: Object.freeze({
        innerGlow: true,
        extrusion: false,
        background: true,
        lightmap: true,
        particles: true,
        playerTrail: true,
        screenEffects: true,
        uiStyling: true,
        bloom: false,
        ambient: true,
        colorGrade: false
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
