class Obstacle extends Element
{
    constructor(object)
    {
        super(object)
    }
    delete(indexInArray, array)
    {
        array[indexInArray].object.destroy()
        array[indexInArray + 1].object.destroy() //obstacles идут парами
        array.splice(indexInArray, 2)
    }
}