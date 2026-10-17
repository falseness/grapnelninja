// Momentum blue object: never bounces. The first ninja contact
// (Ninja.hitLine -> onNinjaPass) lets the ninja through, scales its velocity
// by GAMEPLAY.momentumBlueSlow (same direction) and costs one hp
// (momentumState.onBlueTouch), then it fades out like a green
// (sprites/momentumonetime.js). Not lethal by itself.
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
    onNinjaPass(who)
    {
        if (!this.use())
            return
        who.speedX *= GAMEPLAY.momentumBlueSlow
        who.speedY *= GAMEPLAY.momentumBlueSlow
        momentumState.onBlueTouch()
    }
}
