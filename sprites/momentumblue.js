// Momentum blue object: never bounces. The first ninja contact
// (Ninja.hitLine -> onNinjaPass) lets the ninja through, scales its velocity
// by GAMEPLAY.momentumBlueSlow (same direction) and costs one hp
// (momentumState.onBlueTouch). It vanishes at once (no fade, unlike a green;
// sprites/momentumonetime.js); its outline pops on the spot and the death
// ring plays round the ninja without the shake (ScreenEffects.triggerBlueTouch,
// visual only). Not lethal by itself.
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
        momentumState.onBlueTouch()
        // Pop and ring (render clock only)
        if (visualEffects && visualEffects.screenEffects)
            visualEffects.screenEffects.triggerBlueTouch(this, who)
    }
}
