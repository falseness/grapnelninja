function createEvents()
{
    function correctCoords(event)
    {
        let coord
        if (typeof event.changedTouches != 'undefined')
        {
            coord =
            {
                x: event.changedTouches[0].clientX,
                y: event.changedTouches[0].clientY
            }
        }
        else
        {
            coord =
            {
                x: event.clientX,
                y: event.clientY
            }
        }
        return coord
    }
    function mouseCoords(event)
    {
        let rect = canvas.getBoundingClientRect()
        
        let coord = correctCoords(event)
        
        return {x: coord.x / scale[version] - rect.left - screen.x, y: coord.y / scale[version] - rect.top - screen.y}
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
    function pickUpGrapnel()
    {   
        grapnel.setGrappled(false)
        grapnel.throwed = false
    }
    function startEvent()
    {
        let coords = (menu.visible || menu.gamePaused)?correctCoords(event):mouseCoords(event)
        
        if (!(menu.visible || menu.gamePaused))
            coords.x += screen.x
        
        let res = false
        if (!menu.visible)
            res = menu.button.isClickOnButton(coords)
        menu.click(coords)
        
        return res
    }
    function click(event)
    {
        let eventStarted = startEvent()
        if (eventStarted)
            return
        if (!(menu.gamePaused || menu.visible))
            throwGrapnel(event)
    }
    function touch(event)
    {   
        let eventStarted = startEvent()
        if (eventStarted)
            return
            
        if (!grapnel.throwed)
        {
            click(event)
        }
    }
    function offclick()
    {
        if (!menu.visible)
            pickUpGrapnel()
    }
    function justclick(event)
    {
        
    }
    document.addEventListener('mousedown', click)
    document.addEventListener('mouseup', offclick)
    
    document.addEventListener('touchstart', touch)
    document.addEventListener('touchend', offclick)
    
    
    document.addEventListener('keydown', function(event)
    {
        if (!!screen && event.keyCode == 27)//screen != undefined
            screen.drawEnable = !screen.drawEnable
    })
}


