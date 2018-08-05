let objectsColor = '#f0f0f0'

let sides = 
[
    {
        x: 0, 
        y: 0, 
        width: width, 
        height: 0.1 * height
    },
    {
        x: 0, 
        y: 0.9 * height, 
        width: width,
        height: 0.1 * height
    }
]
for (let i = 0; i < sides.length; ++i)
{
    sprites.push(new Sprite(new Konva.Line({
      points: [sides[i].x, sides[i].y, 
              sides[i].x + sides[i].width, sides[i].y, 
              sides[i].x + sides[i].width, sides[i].y + sides[i].height,
              sides[i].x, sides[i].y + sides[i].height],
      fill: objectsColor,
      stroke: 'black',
      strokeWidth: 1,
      closed: true
    })))
}


