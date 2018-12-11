class Trampoline extends Element
{
    constructor(object)
    {
        super(object)
        /*
    Добавь функцию getXForNextElement
    Сделай анимацию прогибанию батута
    Пофиксь баги с углами
    
    Сделай наконец у grapnel нормальную механику
    двигай stage, а не elements
    */
    }
    collision(who, line)
    {
        if (line.type == 'vertical')
        {
            who.speedX *= -1
        }
        else if (line.type == 'line')
        {
            let lineAngle = line.k

            let xn = -who.speedX
            let yn = -who.speedY

            let x = xn * Math.cos(lineAngle) + yn * Math.sin(lineAngle)
            let y = yn * Math.cos(lineAngle) - xn * Math.sin(lineAngle)

            x = -x

            xn = x * Math.cos(lineAngle) - y * Math.sin(lineAngle)
            yn = y * Math.cos(lineAngle) + x * Math.sin(lineAngle)

            who.speedX = xn
            who.speedY = yn
            who.speedX += GRAVITY * Math.cos(lineAngle) * Math.sin(lineAngle)
            who.speedY -= GRAVITY * Math.pow(Math.cos(lineAngle), 2)
        }
        else
            console.log('collision with trampoline error')
    }
}