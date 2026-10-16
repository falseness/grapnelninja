// Momentum hp and green streak. Green touches build the streak, every
// GAMEPLAY.momentumHp.greenStreakForHp of them in a row give one hp; a blue
// touch costs one hp and breaks the streak; a border bounce changes nothing.
// Hp 0 ends the run through the usual death flow (onLethalDeath saves the
// records). Reset by startMomentumVersion; inert in the other modes.
class MomentumState
{
    constructor()
    {
        this.reset()
    }
    reset()
    {
        this.hp = GAMEPLAY.momentumHp.startHp
        this.greenStreak = 0
        this.borderTouches = 0
    }
    onGreenTouch()
    {
        if (version != 'momentum')
            return
        if (++this.greenStreak >= GAMEPLAY.momentumHp.greenStreakForHp)
        {
            ++this.hp
            this.greenStreak = 0
        }
    }
    onBlueTouch()
    {
        if (version != 'momentum')
            return
        if (this.hp > 0)
            --this.hp
        this.greenStreak = 0
        // Retried on later hits if the death flow ignored it (respawn shield)
        if (this.hp == 0)
            onLethalDeath()
    }
    onBorderTouch()
    {
        if (version != 'momentum')
            return
        ++this.borderTouches
    }
}
const momentumState = new MomentumState
