const whereMoveScreen = 0.3 * width
const whenceMoveScreen = 0.5 * width

const prelastBarrierMoveScreen = 0.8 * width
const lastBarrierMoveScreen = 0.9 * width
const screenTimeCoefficient = 50

let screen = 
{
    speed: 0,
    acceleration: 0,
    primaryDistance: 0,
    currentDistance: 0,
    move: 0,
}
function moveScreen()
{
    screen.speed += screen.acceleration
    screen.currentDistance += screen.speed
    
    if (screen.move == 'ninja' && screen.currentDistance < screen.primaryDistance / 2)
        screen.acceleration = calcFiniteAcceleration(screen.speed, 0, screen.currentDistance)
    if (screen.speed < -5 && screen.move == 'ninja')
    {
        screen.speed = screen.speed
    }
    if (Math.abs(screen.speed) < minimumDeltaRealNumber)
    {
        screen.acceleration = 0
        screen.speed = 0
        screen.move = 0
    }
    for (let i = sides.length; i < sprites.length; ++i)
    {
        sprites[i].speedX = screen.speed
    }
    ninja.x += screen.speed
    
    grapnel.x += screen.speed
}
function calcFiniteAcceleration(v, v0, s)
{
    /* s = (v^2 - v0^2) / (2 * a)
    a = (v^2 - v0^2) / (2 * s)*/
    return ((Math.pow(v, 2) - Math.pow(v0, 2)) / (2 * s))
}
function calcPrimaryAcceleration(t, v0, s)
{
    /* s = v0 * t + (a * t ^ 2) / 2
    a = 2 * (s - v0 * t) / t ^ 2*/
    return (2 * (s - v0 * t) / Math.pow(t, 2))
}
function moveScreenToGrapnel()
{
    if (ninja.x > whenceMoveScreen)// && ninja.x > grapnel.x)
    {
        screen.primaryDistance = ninja.x - whereMoveScreen
        screen.currentDistance = screen.primaryDistance
        screen.acceleration = calcPrimaryAcceleration(screenTimeCoefficient, 0, -screen.primaryDistance)
        screen.move = 'ninja'
    }
}
function prelastBarrierBehindNinja()
{
    /*if (ninja.x > prelastBarrierMoveScreen)
    {
        screen.primaryDistance = ninja.x - whereMoveScreen
        screen.currentDistance = screen.primaryDistance
        screen.move = 'prelastBarrier'
        screen.acceleration = calcPrimaryAcceleration(screenTimeCoefficient, 0, -screen.primaryDistance)
    }*/
}