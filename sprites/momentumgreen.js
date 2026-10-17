// Momentum green object: a one-time trampoline. The first ninja contact
// bounces like any trampoline (Ninja.applyBounce -> bounceSpeed) and adds to
// the green streak, then it fades out (sprites/momentumonetime.js).
class MomentumGreen extends MomentumOneTime
{
    constructor(object)
    {
        super(object, STYLE.colors.cube.greenStroke, STYLE.colors.cube.greenFill,
            STYLE.badVersionEffects.obstacles.greenFill)
    }
    static box(x, y, w, h)
    {
        return new MomentumGreen(MomentumOneTime.boxObject(x, y, w, h))
    }
    // MomentumOneTime.shapeObject spec (rect, triangle, polygon; motion)
    static shape(spec)
    {
        return new MomentumGreen(MomentumOneTime.shapeObject(spec))
    }
    onNinjaBounce()
    {
        if (this.use())
            momentumState.onGreenTouch()
    }
}
