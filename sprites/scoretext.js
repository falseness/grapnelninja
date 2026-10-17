let scoreText = 
{
    get text() { return I18N.t('hud.score') },
    count: 
    {
        bad     : 0                     ,
        momentum: 0                     ,
        classic : 0
    }                                   ,                
    get rtext() { return I18N.t('hud.record') },
    // Reset at each run start; a new record is announced once per run
    recordAnnounced: false            ,
    record: 
    {
        bad     : 0,
        momentum: 0,
        classic : 0
    }                                   ,
    x: Math.floor(0.1 * width)       ,
    rx: 0.8 * width                     ,
    y: Math.floor(0.1 * height / 2)  ,
    fontSize: 0.05 * height ,
    fontFamily: STYLE.ui.fontFamily     ,
    fill: STYLE.colors.ui.hudText       ,
    recordFill: STYLE.colors.ui.hudText ,
    draw: function()
    {
        const viewWidth = width / scale[version]
        const viewHeight = height / scale[version]
        const topY = getHudCenterY(viewHeight, version)
        const fontSize = getHudFontSize(viewWidth, viewHeight, version)

        ctx.save()
        ctx.textBaseline = 'middle'
        ctx.font = fontSize + 'px ' + this.fontFamily
        ctx.lineWidth = Math.max(1, viewHeight * STYLE.ui.hudStageLineRatio)
        ctx.fillStyle = this.fill
        ctx.strokeStyle = STYLE.colors.ui.hudGlow
        const scoreTextValue = this.text + this.count[version]
        const recordText = this.rtext + this.record[version]
        const scoreX = viewWidth * 0.03
        const recordX = this.getRecordX(viewWidth)
        const recordFontSize = this.getRecordFontSize(recordText, scoreTextValue, scoreX, recordX, fontSize, viewWidth)
        const recordY = this.getRecordCenterY(recordText, topY)

        this.drawHudText(scoreTextValue, scoreX, topY, 'start')

        ctx.font = recordFontSize + 'px ' + this.fontFamily

        this.drawHudText(recordText, recordX, recordY, 'end')

        if (version == 'momentum')
            this.drawMomentumHud(viewWidth, topY, fontSize)

        ctx.restore()
    },
    // Momentum hp and green streak, read from momentumState
    getMomentumHudState: function()
    {
        const hp = momentumState.hp
        const asHearts = hp <= STYLE.momentum.hudMaxHearts
        return {
            hp: hp,
            hearts: asHearts ? hp : 1,
            hpText: asHearts ? '' : '\u00d7' + hp,
            streakText: momentumState.greenStreak + '/' + GAMEPLAY.momentumHp.greenStreakForHp
        }
    },
    // Centred in the HUD band between the score and the record
    drawMomentumHud: function(viewWidth, topY, fontSize)
    {
        const state = this.getMomentumHudState()
        const size = fontSize * 0.8
        const step = size * 1.2
        const gap = fontSize * 0.6
        ctx.font = fontSize + 'px ' + this.fontFamily
        const heartsWidth = state.hearts > 0 ? (state.hearts - 1) * step + size : 0
        const hpWidth = state.hpText ? gap / 2 + measureGlowText(state.hpText).width : 0
        const streakWidth = measureGlowText(state.streakText).width
        let x = viewWidth / 2 - (heartsWidth + hpWidth + gap + streakWidth) / 2

        LAYOUT_PROBE.rect('momentum-hearts', 'hp:' + state.hp, x, topY - size / 2, heartsWidth, size)
        for (let i = 0; i < state.hearts; ++i)
            this.drawHeart(x + i * step, topY - size / 2, size)
        x += heartsWidth

        ctx.fillStyle = this.fill
        if (state.hpText)
        {
            x += gap / 2
            this.drawHudText(state.hpText, x, topY, 'start')
            x += hpWidth - gap / 2
        }

        ctx.fillStyle = STYLE.momentum.streakText
        this.drawHudText(state.streakText, x + gap, topY, 'start')
    },
    drawHeart: function(x, y, size)
    {
        const lineWidth = Math.max(1, size * 0.1)
        drawGlowSprite('momentum-heart|' + size, x, y, size, size, lineWidth,
            STYLE.ui.textShadowBlur, () =>
        {
            ctx.translate(x, y)
            ctx.scale(size, size)
            ctx.beginPath()
            ctx.moveTo(0.5, 0.3)
            ctx.bezierCurveTo(0.5, 0.05, 0.05, 0, 0.05, 0.35)
            ctx.bezierCurveTo(0.05, 0.6, 0.35, 0.75, 0.5, 0.95)
            ctx.bezierCurveTo(0.65, 0.75, 0.95, 0.6, 0.95, 0.35)
            ctx.bezierCurveTo(0.95, 0, 0.5, 0.05, 0.5, 0.3)
            ctx.closePath()
            ctx.fillStyle = STYLE.momentum.heartFill
            ctx.strokeStyle = STYLE.momentum.heartStroke
            ctx.shadowColor = STYLE.momentum.heartStroke
            ctx.shadowBlur = STYLE.ui.textShadowBlur
            ctx.lineWidth = lineWidth / size
            ctx.fill()
            ctx.stroke()
        })
    },
    getRecordX: function(viewWidth)
    {
        const x = viewWidth * (isBadLikeVersion(version) ? STYLE.ui.hudBadRecordXRatio : STYLE.ui.hudRecordXRatio)
        // Left of a HUD menu button grown to the touch floor
        if (!menu.button)
            return x
        return Math.min(x, menu.button.background.x - viewWidth * STYLE.ui.hudBadTextGapRatio)
    },
    getRecordFontSize: function(recordText, scoreTextValue, scoreX, recordX, fontSize, viewWidth)
    {
        if (!isBadLikeVersion(version))
            return fontSize

        const scoreWidth = measureGlowText(scoreTextValue).width
        const recordWidth = measureGlowText(recordText).width
        const availableWidth = recordX - (scoreX + scoreWidth) - viewWidth * STYLE.ui.hudBadTextGapRatio

        if (availableWidth <= 0 || recordWidth <= availableWidth)
            return fontSize

        return fontSize * availableWidth / recordWidth
    },
    getRecordCenterY: function(text, topY)
    {
        if (!isBadLikeVersion(version))
            return topY

        const metrics = measureGlowText(text)

        if (!metrics.actualBoundingBoxAscent && !metrics.actualBoundingBoxDescent)
            return topY

        return topY + (metrics.actualBoundingBoxAscent - metrics.actualBoundingBoxDescent) / 2
    },
    drawHudText: function(text, x, y, align)
    {
        ctx.textAlign = align
        drawGlowText(text, x, y, STYLE.colors.ui.hudGlow, STYLE.ui.textShadowBlur + STYLE.ui.hudExtraShadowBlur, true)
        LAYOUT_PROBE.text(text, x, y)
    },
    drawStageIndicator: function(viewWidth, topY, fontSize)
    {
        const centerX = viewWidth / 2
        const gap = height * STYLE.ui.hudStageGapRatio / scale[version]
        const dotRadius = height * STYLE.ui.hudStageDotRatio / scale[version]
        const diamondRadius = height * STYLE.ui.hudStageDiamondRatio / scale[version]
        const labelY = topY
        const dotsY = topY + fontSize * 0.78
        const activeStage = 2

        this.drawStageDiamond(centerX - gap * 1.9, labelY, diamondRadius)

        ctx.font = height * STYLE.ui.hudStageFontRatio / scale[version] + 'px ' + this.fontFamily
        ctx.textAlign = 'center'

        for (let i = 1; i <= 3; ++i)
        {
            const x = centerX + (i - 2) * gap

            const glow = i == activeStage ? STYLE.colors.ui.hudGlow : STYLE.colors.ui.hudMuted
            ctx.strokeStyle = glow
            ctx.fillStyle = i == activeStage ? STYLE.colors.ui.hudText : STYLE.colors.ui.hudMuted
            drawGlowText(String(i), x, labelY, glow, STYLE.ui.textShadowBlur + STYLE.ui.hudExtraShadowBlur, true)

            ctx.beginPath()
            ctx.arc(x, dotsY, dotRadius, 0, Math.PI * 2)
            ctx.fill()
            ctx.closePath()
        }
    },
    drawStageDiamond: function(x, y, radius)
    {
        const lineWidth = Math.max(1, radius * 0.18)
        drawGlowSprite('stage-diamond|' + radius, x - radius, y - radius, radius * 2, radius * 2, lineWidth,
            STYLE.ui.textShadowBlur + STYLE.ui.stageExtraShadowBlur, () =>
        {
            ctx.translate(x, y)
            ctx.rotate(Math.PI / 4)
            ctx.strokeStyle = STYLE.colors.ui.hudGlow
            ctx.shadowColor = STYLE.colors.ui.hudGlow
            ctx.shadowBlur = STYLE.ui.textShadowBlur + STYLE.ui.stageExtraShadowBlur
            ctx.lineWidth = lineWidth
            ctx.strokeRect(-radius / 2, -radius / 2, radius, radius)
        })
    }
}
function scoreTextX()  { return 0.1 * width }
function scoreTextRx() { return 0.8 * width }
const scoreTextY        = STYLE.ui.hudTopRatio * height
const scoreTextFontSize = STYLE.ui.hudFontRatio * height
