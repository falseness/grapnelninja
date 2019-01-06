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
        if (menu.visible)
        {
            menu.click({x: event.clientX, y: event.clientY})
        }
        else
        {
            if (!menu.button.isClickOnButton({x: event.clientX, y: event.clientY}))
                PCThrowEvent(event)
        }
    }
    function mobileclick(event)
    {
        if (menu.visible)
        {
            menu.click({x: event.changedTouches[0].clientX, y: event.changedTouches[0].clientY})
        }
        else
        {
            if (!menu.button.isClickOnButton({x: event.changedTouches[0].clientX, y: event.changedTouches[0].clientY}))
                mobileThrowEvent(event)
        }
    }
    function offclick()
    {
        pickUpGrapnel()
    }
    document.addEventListener('mousedown', click)
    document.addEventListener('mouseup', offclick)
    
    document.addEventListener('touchstart', mobileclick)
    document.addEventListener('touchend', offclick)
    
    document.addEventListener('keydown', function(event)
    {
        if (event.keyCode == 27)
            screen.drawEnable = !screen.drawEnable
    })
}

