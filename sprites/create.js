let ninja = new Ninja(new Konva.Circle({
    x: Math.floor(0.2 * width),
    y: Math.floor(0.2 * height),
    radius: Math.round(0.01 * height),
    fill: '#0000ff',
    stroke: '#000000',
    strokeWidth: 1
}))
let grapnel = new Grapnel(new Konva.Line({
    points: [0, 0, 0, 0],
    stroke: 'red',
    strokeWidth: Math.round(0.006 * height),
    lineJoin: 'round'
}))

let scoreText = new Konva.Text({
        x: Math.floor(0.1 * width),
        y: Math.floor(0.02 * height),
        text: 'score: 0',
        fontSize: Math.floor(0.05 * height),
        fontFamily: 'Calibri',
        fill: 'blue'
    })
scoreText.count = 0


let deltaX = 0

let obstacles = new Konva.Group(
{
    x: 0,
    y: 0,
    rotation: 0
})

let enemies = new Konva.Group(
{
    x: 0,
    y: 0,
    rotation: 0
})

let trampolines = new Konva.Group(
{
    x: 0,
    y: 0,
    rotation: 0
})

let sides = 
[
    {
        x: -width, 
        y: 0, 
        width: 3 * width, 
        height: 0.1 * height
    },
    {
        x: -width, 
        y: 0.9 * height, 
        width: 3 * width,
        height: 0.1 * height
    }
]
for (let i = 0; i < sides.length; ++i)
{
    const sidesColor = '#f0f0f0'
    sprites.push(new Sprite(new Konva.Line({
      points: floorPoints([sides[i].x, sides[i].y, 
              sides[i].x + sides[i].width, sides[i].y, 
              sides[i].x + sides[i].width, sides[i].y + sides[i].height,
              sides[i].x, sides[i].y + sides[i].height]),
      fill: sidesColor,
      stroke: 'black',
      strokeWidth: 1,
      closed: true
    })))
}

function floorPoints(points)
{
    let resPoints = []
    for (let i = 0; i < points.length; ++i)
    {
        resPoints.push(Math.floor(points[i]))
    }
    return resPoints
}