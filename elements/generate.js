function generate(x)
{
    const generateChancePercent = 
    {
        obstacles: 40,
        enemies: 35,
        trampolines: 25
    }
    let num = random()
    
    if (num < generateChancePercent.obstacles)
    {
        let generatedElementsNumber = generateObstacle(x, obstacles)
        return generatedElementsNumber
    }
    
    if (generateChancePercent.obstacles <= num && 
             num < generateChancePercent.obstacles + generateChancePercent.enemies)
    {
        let generatedElementsNumber = generateEnemy(x, enemies)
        return generatedElementsNumber
    }
    if (generateChancePercent.obstacles + generateChancePercent.enemies <= num &&
        generateChancePercent.obstacles + generateChancePercent.enemies + generateChancePercent.trampolines)
    {
        let generatedElementsNumber = generateTrampoline(x, trampolines)
        return generatedElementsNumber
    }
    console.log("Error generate")
}

function generatePrimaryElements()
{
    const firstElementX = 0.4 * width
    const elementsPairNumber = 5
    
    for (let i = 0; i < elementsPairNumber; ++i)
    {
        generate(firstElementX + (obstacleIndent + obstacleWidth) * i)
    }
}