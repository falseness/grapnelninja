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
    sprites.push(new Sprite(new Konva.Rect(
    {
        x: sides[i].x,
        y: sides[i].y,
        width: sides[i].width,
        height: sides[i].height,
        fill: objectsColor,
    })))
}
delete sides