let ninja = new Ninja(
{
    x: 0.2 * width,
    y: ninjaY,
    radius: 0.01 * height,
    fill: '#0000ff',
    stroke: '#000000'
})

let grapnel = new Grapnel(
{
    points: [0, 0, 0, 0],
    stroke: 'red'
})

let scoreText = 
{
    text: 'score: '                     ,
    count: 0                            ,
    rtext: 'record: '                   ,
    record: 0                           ,
    x: Math.floor(0.1 * width)          ,
    rx: 0.8 * width                     ,
    y: Math.floor(0.1 * height / 2)     ,
    fontSize: Math.floor(0.05 * height) ,
    fontFamily: 'Calibri'               ,
    fill: 'blue'                        ,
    draw: function()
    {
        ctx.fillStyle = this.fill
        ctx.textBaseline = 'middle'
        ctx.font = this.fontSize + 'px ' + this.fontFamily
        ctx.fillText(this.text + this.count, this.x, this.y)
        ctx.fillText(this.rtext + this.record, this.rx, this.y)
    }
}