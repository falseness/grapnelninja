let scoreText = 
{
    text: 'score: '                     ,
    count: 
    {
        bad     : 0                     ,
        classic : 0
    }                                   ,                
    rtext: 'record: '                   ,
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
    fill: STYLE.colors.ui.score         ,
    recordFill: STYLE.colors.ui.record  ,
    draw: function()
    {
        ctx.save()
        ctx.textBaseline = 'middle'
        ctx.textAlign = 'start'
        ctx.font = this.fontSize + 'px ' + this.fontFamily
        ctx.shadowBlur = STYLE.ui.textShadowBlur
        ctx.shadowColor = this.fill
        ctx.fillStyle = this.fill
        ctx.fillText(this.text + this.count[version], this.x, this.y)
        ctx.shadowColor = this.recordFill
        ctx.fillStyle = this.recordFill
        ctx.fillText(this.rtext + this.record[version], this.rx, this.y)
        ctx.restore()
    }
}
const scoreTextX        = 0.1 * width
const scoreTextRx       = 0.8 * width
const scoreTextY        = 0.1 * height / 2
const scoreTextFontSize = 0.05 * height
