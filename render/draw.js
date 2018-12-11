let draw = 
{
    ninja: new Konva.Animation(function(frame) 
    {
        ninja.speedY += GRAVITY
        ninja.move()
        ninja.object.setX(Math.floor(ninja.x))
        ninja.object.setY(Math.floor(ninja.y))
    }, layer.ninja)/*,
    grapnel: new Konva.Animation(function(frame)
    {
        grapnel.object.points(
            floorPoints([ninja.x, ninja.y, grapnel.x, grapnel.y]))
    }, layer.grapnel),
    obstacles: new Konva.Animation(function(frame)
    {
        if (!screen.speed)
            return false
        
        obstacles.setX(deltaX)
    }, layer.obstacles),
    enemies: new Konva.Animation(function(frame)
    {
        for (let i = sides.length; i < sprites.length; ++i)
        {
            sprites[i].moveObject()
        }
        enemies.setX(deltaX)
    }, layer.enemies),
    trampolines: new Konva.Animation(function(frame)
    {
        trampolines.setX(deltaX)
    }, layer.trampolines)*/
}
function drawStaticLayers()
{
    layer.static.draw()
    layer.mechanics.draw()
}
function drawObstaclesFirstTime()
{
    layer.obstacles.draw()
}
function drawEnemiesFirstTime()
{
    layer.enemies.draw()
}
function drawElementsFirstTime()
{
    drawObstaclesFirstTime()
    drawEnemiesFirstTime()
}
function drawMechanicsLines()
{
    let mechanicsOptions = 
    {
        color: 'green',
        lineJoin: 'round'
    }
    let mechanics = 
    [
        /*{
            points: [screen.whereMove, 0.2 * height, screen.whereMove, 0.8 * height],
            strokeWidth: 3,
            opacity: 1
        },*/
        {
            points: floorPoints([screen.whenceMove, 0.2 * height, screen.whenceMove, 0.8 * height]),
            strokeWidth: 3,
            opacity: 0.5
        }/*,
        {
            points: [screen.lastBarrierMove, 0.2 * height, screen.lastBarrierMove, 0.8 * height],
            strokeWidth: 5,
            opacity: 1
        }*/
    ]
    for (let i = 0; i < mechanics.length; ++i)
    {
        layer.mechanics.add(new Konva.Line(
        {
            points: mechanics[i].points, 
            stroke: mechanicsOptions.color,
            strokeWidth: mechanics[i].strokeWidth,
            lineJoin: mechanicsOptions.lineJoin,
            opacity: mechanics[i].opacity
        }))
    }
}

function startDrawAnimations()
{
    drawElementsFirstTime()
    layer.scoreText.draw()
    
    for (i in draw)
    {
        draw[i].start()
    }
}
