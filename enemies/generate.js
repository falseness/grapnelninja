const length = height * 0.15
const enemyRestriction = 
{
    top: sides[0].y + sides[0].height + length * Math.cos(Math.PI / 6) + 0.01 * height,
    bottom: sides[1].y - 0.01 * height
}
function generateTrianglePoints(x, y)
{
    const pointsRectangleTemplate = [0, 0, -length * Math.sin(Math.PI / 6), -length * Math.cos(Math.PI / 6),
                                     length * Math.sin(Math.PI / 6), -length * Math.cos(Math.PI / 6)]
    
    res = []
    for (let i = 0; i < pointsRectangleTemplate.length; i += 2)
    {
        res.push(pointsRectangleTemplate[i] + x)
        res.push(pointsRectangleTemplate[i + 1] + y)
    }
    return res
}
function generateEnemy(x, group)
{    
    const enemyModel =
    {
        color: '#ff0000',
        strokeColor: 'black',
        strokeWidth: 1
    }
    
    enemyModel.points = generateTrianglePoints(x, random(enemyRestriction.top, enemyRestriction.bottom))
    
    sprites.push(new Enemy(getObject(enemyModel)))
    if (random() < 50)
    {
        sprites[sprites.length - 1].speedY *= -1
    }
    group.add(sprites[sprites.length - 1].object)
    
    let generatedElementsNumber = 1
    return generatedElementsNumber
}