function createEvents()
{
    function mouseCoords(event)
    {
        let rect = canvas.getBoundingClientRect()
        return {x: event.clientX - rect.left - screen.x, y: event.clientY - rect.top - screen.y}
    }
    
    function throwGrapnel(event)
    {
        grapnel.pos = [[ninja.x, ninja.y, new Empty()]]
        let ratio = grapnel.calcSpeed(mouseCoords(event))
        grapnel.speedY = ratio.sin * grapnelSpeed// + ninja.speedY
        grapnel.speedX = ratio.cos * grapnelSpeed// + ninja.speedX    
        
        grapnel.throwed = true
        grapnel.setGrappled(false)   
    }
    function PCThrowEvent(event)
    {
        throwGrapnel(event)
    }
    function mobileThrowEvent(event)
    {
        if (!grapnel.throwed)
        {
            throwGrapnel(event.changedTouches[0])
        }
    }
    function pickUpGrapnel()
    {   
        grapnel.setGrappled(false)
        grapnel.throwed = false
    }
    function click(event)
    {
        if (!(menu.gamePaused || menu.visible))
            PCThrowEvent(event)
    }
    function mobileclick(event)
    {   
        if (!(menu.gamePaused || menu.visible))
                mobileThrowEvent(event)
    }
    function offclick()
    {
        if (!menu.visible)
            pickUpGrapnel()
    }
    function justclick(event)
    {
        let coords = 
        {
            x: event.clientX,
            y: event.clientY
        }
        if (typeof event.changedTouches != 'undefined')
        {
            coords = 
            {
                x: event.changedTouches[0].clientX,
                y: event.changedTouches[0].clientY
            }
        }
        menu.button.isClickOnButton(coords)
        menu.click(coords)
    }
    document.addEventListener('mousedown', click)
    document.addEventListener('mouseup', offclick)
    
    document.addEventListener('touchstart', mobileclick)
    document.addEventListener('touchend', offclick)
    
    document.addEventListener('click', justclick)
    
    document.addEventListener('keydown', function(event)
    {
        if (!!screen && event.keyCode == 27)//screen != undefined
            screen.drawEnable = !screen.drawEnable
    })
}


