function generateTrampolinePoints(x)
{
    const trampolineRestriction = 
    {
        width:
        {
            min: 0.2 * width,
            max: 0.3 * width
        }, 
        height:
        {
            min: 0.1 * height,
            max: 0.3 * height
        }
    }
    
    let x2 = x + random(trampolineRestriction.width.min, trampolineRestriction.width.max)
    let y1 = sides[1].y
    return [x, y1, x, 
            y1 - random(trampolineRestriction.height.min, trampolineRestriction.height.max),
            x2, y1 - random(trampolineRestriction.height.min, trampolineRestriction.height.max),
            x2, y1]
}
function generateTrampoline(x, group)
{
    const trampolineModel = 
    {
        color: '#3e1170',
        strokeColor: 'black',
        strokeWidth: 1
    }
    
    trampolineModel.points = generateTrampolinePoints(x)
    sprites.push(new Trampoline(getObject(trampolineModel)))
    group.add(sprites[sprites.length - 1].object)
    
    let generatedElementsNumber = 1
    return generatedElementsNumber
}
