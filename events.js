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
        let coord = viewportCoordsToCanvasCoords(getCoords(event))

        return {x: coord.x / scale[version] - screen.x, y: coord.y / scale[version] - screen.y}
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
    function startEvent(event)
    {
        let coords = viewportCoordsToCanvasCoords(getCoords(event))
        if (continueOffer.visible && !menu.gamePaused)
        {
            if (continueOffer.click(coords))
                return true
            if (continueOffer.adPending)
                return false
            // The HUD menu button still opens the pause menu: Menu after a death
            return menu.clickToPause({x: coords.x / scale[version], y: coords.y / scale[version]})
        }
        if (LANGUAGE_BUTTON.click(coords))
            return true
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
        if (adOpen || interstitialPending)
            return
        if (!unTouch && startEvent(event))
        {
            //Элегантный костыль:
            unTouch = true
            setTimeout(function()
            {
                unTouch = false
            }, STYLE.timing.inputUntouchMs)
            return
        }
        if (!menu.opened() && !continueOffer.visible)
            throwGrapnel(event)
    }
    // preventDefault stops the emulated mousedown/mouseup after a tap
    function touch(event)
    {
        event.preventDefault()
        // No grapnel before the first run: a menu tap must still reach click()
        if (!grapnel || !grapnel.throwed)
        {
            click(event)
        }
    }
    function offclick()
    {
        if (adOpen || interstitialPending)
            return
        if (!menu.visible)
            pickUpGrapnel()
    }
    function offtouch(event)
    {
        event.preventDefault()
        offclick()
    }
    document.addEventListener('mousedown', click)
    document.addEventListener('mouseup', offclick)
    
    document.addEventListener('touchstart', touch, {passive: false})
    document.addEventListener('touchend', offtouch, {passive: false})
    
    
    document.addEventListener('contextmenu', function(event)
    {
        event.preventDefault()
    })
    document.addEventListener('wheel', function(event)
    {
        event.preventDefault()
    }, {passive: false})
    
    // Keys that would scroll the host page around an embedding iframe
    const scrollKeys = ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', ' ',
        'PageUp', 'PageDown', 'Home', 'End']
    const pauseKeys = ['Escape', 'p', 'P']
    document.addEventListener('keydown', function(event)
    {
        if (scrollKeys.includes(event.key))
            event.preventDefault()
        if (pauseKeys.includes(event.key) && !menu.visible && !continueOffer.visible && !adOpen && !interstitialPending)
        {
            event.preventDefault()

            if (menu.gamePaused)
                menu.unPause()
            else
                menu.startPause()
        }
    })
}


