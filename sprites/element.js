class Element extends Sprite
{
    constructor(object)
    {
        super(object)
        this.points = []
        /*
        Код из дерьма и палок
        Переделай полностью sprite и obstacle
        сделай препятствия rect'ами
        добавь функцию, дающую по информации о rect'е массив points и обрабатывай нормально коллизии
        или сделай у rect'a свой личный массив points для удобства и оптимизации
        */
        for (let i = 0; i < object.attrs.points.length; i += 2)
        {
            this.points.push(object.attrs.points[i] + deltaX)
            this.points.push(object.attrs.points[i + 1])
        }
    }
    delete(indexInArray, array)
    {
        array[indexInArray].object.destroy()
        array.splice(indexInArray, 1)
    }
}