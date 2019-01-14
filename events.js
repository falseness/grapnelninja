function createEvents()
{
    function getCoords(event)
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
    function getRealCoords(event)
    {
        let rect = canvas.getBoundingClientRect()
        
        let coord = getCoords(event)
        
        return {x: coord.x / scale[version] - rect.left - screen.x, y: coord.y / scale[version] - rect.top - screen.y}
    }
    function throwGrapnel(event)
    {
        grapnel.pos = [[ninja.x, ninja.y, new Empty()]]
        let ratio = grapnel.calcSpeed(getRealCoords(event))
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
        let coords = getCoords(event)
        if (menu.opened())
        {
            let isButtonClicked     = false
            isButtonClicked         |= menu.click(coords)
            return isButtonClicked
        }
        coords.x /= scale[version]
        coords.y /= scale[version]
        return menu.clickToPause(coords)
    }
    function click(event)
    {
        if (startEvent())
        {
            //Элегантный костыль:
            unTouch = true
            return
        }
        if (!(menu.opened()))
            throwGrapnel(event)
    }
    function touch(event)
    {       
        if (!grapnel.throwed && !unTouch)
        {
            click(event)
        }
    }
    function offclick()
    {
        if (!menu.visible)
            pickUpGrapnel()
    }
    function offtouch()
    {
        if (TouchList.length == 0)
            unTouch = false
        offclick()
    }
    document.addEventListener('mousedown', click)
    document.addEventListener('mouseup', offclick)
    
    document.addEventListener('touchstart', touch)
    document.addEventListener('touchend', offtouch)
    
    
    document.addEventListener('keydown', function(event)
    {
        if (!!screen && event.keyCode == 27)//screen != undefined
            screen.drawEnable = !screen.drawEnable
    })
}


