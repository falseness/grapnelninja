let scoreText = 
{
    text: 'SCORE: '                     ,
    count: 
    {
        bad     : 0                     ,
        classic : 0
    }                                   ,                
    rtext: 'RECORD: '                   ,
    record: 
    {
        bad     : 0,
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
        ctx.shadowBlur = STYLE.ui.textShadowBlur + 5
        ctx.shadowColor = STYLE.colors.ui.hudGlow
        ctx.fillStyle = this.fill
        ctx.strokeStyle = STYLE.colors.ui.hudGlow
        const scoreTextValue = this.text + this.count[version]
        const recordText = this.rtext + this.record[version]
        const scoreX = viewWidth * 0.03
        const recordX = this.getRecordX(viewWidth)
        const recordFontSize = this.getRecordFontSize(recordText, scoreTextValue, scoreX, recordX, fontSize, viewWidth)

        this.drawHudText(scoreTextValue, scoreX, topY, 'start')

        ctx.font = recordFontSize + 'px ' + this.fontFamily
        const recordY = this.getRecordCenterY(recordText, topY)

        this.drawHudText(recordText, recordX, recordY, 'end')

        ctx.restore()
    },
    getRecordX: function(viewWidth)
    {
        if (version == 'bad')
            return viewWidth * STYLE.ui.hudBadRecordXRatio

        return viewWidth * STYLE.ui.hudRecordXRatio
    },
    getRecordFontSize: function(recordText, scoreTextValue, scoreX, recordX, fontSize, viewWidth)
    {
        if (version != 'bad')
            return fontSize

        const scoreWidth = ctx.measureText(scoreTextValue).width
        const recordWidth = ctx.measureText(recordText).width
        const availableWidth = recordX - (scoreX + scoreWidth) - viewWidth * STYLE.ui.hudBadTextGapRatio

        if (availableWidth <= 0 || recordWidth <= availableWidth)
            return fontSize

        return fontSize * availableWidth / recordWidth
    },
    getRecordCenterY: function(text, topY)
    {
        if (version != 'bad')
            return topY

        const metrics = ctx.measureText(text)

        if (!metrics.actualBoundingBoxAscent && !metrics.actualBoundingBoxDescent)
            return topY

        return topY + (metrics.actualBoundingBoxAscent - metrics.actualBoundingBoxDescent) / 2
    },
    drawHudText: function(text, x, y, align)
    {
        ctx.textAlign = align
        ctx.strokeText(text, x, y)
        ctx.fillText(text, x, y)
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

            ctx.shadowColor = i == activeStage ? STYLE.colors.ui.hudGlow : STYLE.colors.ui.hudMuted
            ctx.strokeStyle = i == activeStage ? STYLE.colors.ui.hudGlow : STYLE.colors.ui.hudMuted
            ctx.fillStyle = i == activeStage ? STYLE.colors.ui.hudText : STYLE.colors.ui.hudMuted
            ctx.strokeText(i, x, labelY)
            ctx.fillText(i, x, labelY)

            ctx.beginPath()
            ctx.arc(x, dotsY, dotRadius, 0, Math.PI * 2)
            ctx.fill()
            ctx.closePath()
        }
    },
    drawStageDiamond: function(x, y, radius)
    {
        ctx.save()
        ctx.beginPath()
        ctx.translate(x, y)
        ctx.rotate(Math.PI / 4)
        ctx.strokeStyle = STYLE.colors.ui.hudGlow
        ctx.fillStyle = STYLE.colors.ui.transparent
        ctx.shadowColor = STYLE.colors.ui.hudGlow
        ctx.shadowBlur = STYLE.ui.textShadowBlur + 4
        ctx.lineWidth = Math.max(1, radius * 0.18)
        ctx.strokeRect(-radius / 2, -radius / 2, radius, radius)
        ctx.closePath()
        ctx.restore()
    }
}
const scoreTextX        = 0.1 * width
const scoreTextRx       = 0.8 * width
const scoreTextY        = STYLE.ui.hudTopRatio * height
const scoreTextFontSize = STYLE.ui.hudFontRatio * height
