const wayHeight = 0.3 * height
const obstacleWidth = 0.05 * width

const obstacleIndent = 0.3 * width

function generateRectPoints(point, size)
{
    return [point.x, point.y, point.x + size.width, point.y, 
            point.x + size.width, point.y + size.height, point.x, point.y + size.height]
}
function generateObstacle(x)
{
    let obstacleHeight = Math.floor(Math.random() * ((height - sides[1].height - sides[0].height - wayHeight) - 0)) + 0
    sprites.push(new Sprite(new Konva.Line({
      points: generateRectPoints({x: x, y: sides[0].height}, {width: obstacleWidth, height: obstacleHeight}),
      fill: objectsColor,
      stroke: 'black',
      strokeWidth: 1,
      closed: true
    })))
    sprites.push(new Sprite(new Konva.Line({
      points: generateRectPoints({x: x, y: sides[0].height + obstacleHeight + wayHeight}, 
                                 {width: obstacleWidth, height: (height - sides[0].height - sides[1].height - wayHeight - obstacleHeight)}),
      fill: objectsColor,
      stroke: 'black',
      strokeWidth: 1,
      closed: true
    })))
}