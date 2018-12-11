 const obstacleWidth = 0.05 * width
 const obstacleIndent = 0.3 * width

function generateRectPoints(point, size)
{
    return [point.x, point.y, point.x + size.width, point.y, 
            point.x + size.width, point.y + size.height, point.x, point.y + size.height]
}
function generateObstacle(x, group)
{
    const wayHeight = 0.3 * height
    let obstacleHeight = random(0, height - sides[1].height - sides[0].height - wayHeight)
    
    let obstacleModel = 
    {
        color: '#f0f0f0',
        strokeColor: 'black',
        strokeWidth: 1,
    }
    obstacleModel.points = generateRectPoints({x: x, y: sides[0].height}, {width: obstacleWidth, height: obstacleHeight})
    sprites.push(new Obstacle(getObject(obstacleModel)))
    group.add(sprites[sprites.length - 1].object)
    
    obstacleModel.points = generateRectPoints({x: x, y: sides[0].height + obstacleHeight + wayHeight}, 
                                 {width: obstacleWidth, height: (height - sides[0].height - sides[1].height - wayHeight - obstacleHeight)})
    sprites.push(new Obstacle(getObject(obstacleModel)))
    group.add(sprites[sprites.length - 1].object)
    
    let generatedElementsNumber = 2
    return generatedElementsNumber
}