// Momentum lighting effects switch (pause screen 'Lighting' checkbox).
// Every momentum lighting effect draws only while enabled; with it off a
// momentum frame is the plain one. Stored by PROGRESS (grapnelninja.lighting).
const MOMENTUM_FX = {enabled: true}
// Test hook: set the switch without the checkbox or storage
function setMomentumFx(on)
{
    MOMENTUM_FX.enabled = !!on
}
