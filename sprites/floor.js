class Floor
{
    constructor(topBorder, bottomBorder, elementsIntervalX, creations)
    {
        this.bottom             = bottomBorder
        this.top                = topBorder
        
        this.creations          = creations
        this.elementsIntervalX  = elementsIntervalX
        
        this.elements           = []
    }
    generatePrimaryElements()
    {
        const firstPrimaryElementX      = 0.2 * width
        const primaryElementsQuantity   = 4
        
        let nextElementX                = firstPrimaryElementX
        
        for (let i = 0; i < primaryElementsQuantity; ++i)
        {
            this.generateElements(nextElementX)
            nextElementX = this.elements[this.elements.length - 1].getRightPointX()
        }
    }
    generateElements(x)
    {
        let num = random()
        
        let sumChances = 0
        for (let i = 0; i < this.creations.length; ++i)
        {
            if (num < this.creations[i].chance + sumChances)
            {
                this.elements.push(elementsFactory.create(
                    {min: x + this.elementsIntervalX.min, max: x + this.elementsIntervalX.max}, 
                    {min: this.top, max: this.bottom}   , this.creations[i].type))
                
                break
            }
            sumChances += this.creations[i].chance
        }
    }
    deleteElements()
    {
        let newElements = 0
        for (let i = 0; i < this.elements.length - newElements; ++i)
        {
            if (this.elements[i].getRightPointX() + screen.x < 0)
            {
                this.elements.splice(i, 1)
                
                this.generateElements(this.elements[this.elements.length - 1].getRightPointX())
                
                ++newElements
                --i
                
                changeScoreText()
            }
        }
    }
    moveElements()
    {
        for (let i = 0; i < this.elements.length; ++i)
        {
            this.elements[i].move()
        }
    }
    draw()
    {
        for (let i = 0; i < this.elements.length; ++i)
        {
            this.elements[i].draw()
        }
    }
    drawTracks()
    {
        if (trackEnabled)
        {
            for (let i = 0; i < this.elements.length; ++i)
            {
                this.elements[i].track.draw()
            }
        }
    }
}
class SideFloor extends Floor
{
    constructor(bottomBorder, topBorder, creations)
    {
        super(bottomBorder, topBorder, {min: 0, max: 0}, creations)
        
        this.leftPointX = -2 * width
    }
    generatePrimaryElements()
    {
        const firstPrimaryElementX      = this.leftPointX
        const primaryElementsQuantity   = 4
        
        let nextElementX                = firstPrimaryElementX
        
        for (let i = 0; i < primaryElementsQuantity; ++i)
        {
            this.generateElements(nextElementX)
            let t = this.elements[this.elements.length - 1]
            nextElementX = t.getRightPointX()
        }
    }
    deleteElements()
    {
        if (this.elements[0].getRightPointX() + screen.x < this.leftPointX)
        {
            this.elements.splice(0, 1)
            this.generateElements(this.elements[this.elements.length - 1].getRightPointX())
        }
    }
    moveElements()
    {
        
    }
}