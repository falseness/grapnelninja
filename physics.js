let gravity = 0.1

function physics()
{
    ninja.speedY += gravity
    ninja.move()
    ninja.collision()
}