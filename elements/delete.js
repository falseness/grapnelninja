function elementNotOnMap(points)
{
    for (let i = 0; i < points.length; i += 2)
    {
        if (points[i] >= 0)
            return false
    }
    return true
}

function changeScoreText()
{
    scoreText.setText('score: ' + ++scoreText.count)
    layer.scoreText.draw()
}


function deleteObstacles(group)
{
    newElements = 0
    for (let i = sides.length; i < sprites.length - newElements; ++i)
    {
        if (elementNotOnMap(sprites[i].points))
        {
            sprites[i].delete(i, sprites)
    
            newElements += generate(sprites[sprites.length - 1].object.attrs.points[0] + (obstacleIndent + obstacleWidth))
            
            changeScoreText()
        }
    }
}
