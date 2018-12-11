const width = window.innerWidth
const height = window.innerHeight

const cyclesPerTick = 1

const minimumDeltaRealNumber = 0.0001

function random(min, max)
{
    min = min || 0
    max = max || 100
    return Math.floor(Math.random() * (max - min)) + min
}