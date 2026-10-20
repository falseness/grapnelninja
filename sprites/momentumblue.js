// Momentum blue object: never bounces. The first ninja contact
// (Ninja.hitLine -> onNinjaPass) lets the ninja through, scales its velocity
// by GAMEPLAY.momentumBlueSlow (same direction) and costs one hp
// (momentumState.onBlueTouch). It vanishes at once (no fade, unlike a green;
// sprites/momentumonetime.js); its outline pops on the spot
// (ScreenEffects.triggerBlueTouch) and the death ring plays where the ninja
// touched it, without the shake (ScreenEffects.triggerRing, world-anchored;
// visual only). A touch that takes the last hp runs the death flow, whose
// own ring (with the shake) is the only one. Not lethal by itself.
class MomentumBlue extends MomentumOneTime
{
    constructor(object)
    {
        super(object, STYLE.momentum.blueStroke, STYLE.momentum.blueFill,
            STYLE.momentum.blueBadVersionFill)
    }
    static box(x, y, w, h)
    {
        return new MomentumBlue(MomentumOneTime.boxObject(x, y, w, h))
    }
    // MomentumOneTime.shapeObject spec (rect, triangle, polygon; motion)
    static shape(spec)
    {
        return new MomentumBlue(MomentumOneTime.shapeObject(spec))
    }
    hasInnerShell()
    {
        return true
    }
    // Faceted sapphire (render/crystalpieces.js) instead of the inset copy,
    // under the piece's own neon outline (stroked again, inside the piece),
    // its twinkling glints on top
    drawInnerShell(alpha)
    {
        if (bloomPassActive || !CRYSTAL_PIECES.enabled)
        {
            super.drawInnerShell(alpha)
            return
        }
        const sprite = CRYSTAL_PIECES.drawBlue(this, alpha)
        const points = this.getPoints()
        ctx.save()
        ctx.beginPath()
        ctx.moveTo(points[points.length - 1].x + screen.x, points[points.length - 1].y + screen.y)
        for (let i = 0; i < points.length; ++i)
            ctx.lineTo(points[i].x + screen.x, points[i].y + screen.y)
        ctx.closePath()
        ctx.clip()
        strokeNeonPath(this.stroke, alpha)
        ctx.restore()
        CRYSTAL_PIECES.drawGlints(this, sprite, alpha)
    }
    vanishesOnUse()
    {
        return true
    }
    onNinjaPass(who)
    {
        if (!this.use())
            return
        who.speedX *= GAMEPLAY.momentumBlueSlow
        who.speedY *= GAMEPLAY.momentumBlueSlow
        // Taking the last hp runs the death flow (unless the respawn shield
        // ignores it), which restarts the run: decided before the touch
        const lethal = momentumState.hp <= 1 && !who.isInvulnerable()
        const x = who.x, y = who.y
        momentumState.onBlueTouch()
        // A lethal touch that restarted the run leaves only the death ring
        if (ninja !== who)
            return
        // Pop and ring (render clock only); a lethal touch has the death ring
        if (visualEffects && visualEffects.screenEffects)
        {
            visualEffects.screenEffects.triggerBlueTouch(this)
            if (!lethal)
                visualEffects.screenEffects.triggerRing(x, y)
        }
    }
}
