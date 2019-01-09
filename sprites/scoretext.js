let scoreText = 
{
    text: 'score: '                     ,
    count: 
    {
        bad     : 0,
        classic : 0
    }                                   ,                
    rtext: 'record: '                   ,
    record: 
    {
        bad     : 0,
        classic : 0
    }                                   ,
    x: Math.floor(0.1 * width)          ,
    rx: 0.8 * width                     ,
    y: Math.floor(0.1 * height / 2)     ,
    fontSize: 0.05 * height ,
    fontFamily: 'Calibri'               ,
    fill: 'blue'                        ,
    draw: function()
    {
        ctx.fillStyle = this.fill
        ctx.textBaseline = 'middle'
        ctx.font = this.fontSize + 'px ' + this.fontFamily
        ctx.fillText(this.text + this.count[version], this.x, this.y)
        ctx.fillText(this.rtext + this.record[version], this.rx, this.y)
    }
}
const scoreTextX        = 0.1 * width
const scoreTextRx       = 0.8 * width
const scoreTextY        = 0.1 * height / 2
const scoreTextFontSize = 0.05 * height