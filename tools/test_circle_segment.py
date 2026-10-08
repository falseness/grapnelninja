"""Unit cases for the circle-vs-segment test (collision/circlewithline.js) and
the centre-inside hit in Ninja.collision (sprites/ninja.js)."""
from contextlib import ExitStack
from pathlib import Path
import unittest

from browser_test_support import start_browser_test, wait_for_boot

ROOT = Path(__file__).resolve().parent.parent


class CircleSegmentTest(unittest.TestCase):
    CASES = '''() => {
        const hit = (x1, y1, x2, y2, x, y, r) => collisionCircleWithLine(lineFormula(x1, y1, x2, y2), x, y, r)
        const square = [{x: 0, y: 0}, {x: 100, y: 0}, {x: 100, y: 100}, {x: 0, y: 100}]
        // Ninja.collision against one fake element; records the lines it reports.
        const centreInside = (x, y, r) => {
            const hits = []
            const element = {
                getPoints: () => square,
                getLines: Element.prototype.getLines,
                writeBounds: Element.prototype.writeBounds,
                getCircumscribedCircle: () => ({x: 50, y: 50, radius: Math.hypot(50, 50)}),
                collision: (who, line) => hits.push([line.x1, line.y1, line.x2, line.y2])
            }
            const saved = floors
            floors = [{elements: [element]}]
            const ninja = new Ninja({x, y, radius: r, fill: '#fff', stroke: '#fff'})
            const result = ninja.collision()
            floors = saved
            return {hits, result: !!result}
        }
        const eps = 1e-6
        return {
            crossing: hit(0, 0, 100, 0, 50, 3, 5),
            crossingSloped: hit(0, 0, 100, 50, 50, 25, 5),
            insideShort: hit(48, 0, 52, 1, 50, 0, 10),
            insideShortVertical: hit(50, -2, 50, 2, 50, 0, 10),
            touchEndpoint: hit(0, 0, 100, 0, 105, 0, 5),
            touchEndpointDiagonal: hit(0, 0, 100, 0, 103, 4, 5),
            touchEndpointVertical: hit(0, 0, 0, 100, 0, -5, 5),
            vertex: hit(0, 0, 100, 0, -3, -4, 5),
            vertexSloped: hit(0, 0, 100, 50, 103, 54, 5),
            tangentHorizontal: hit(0, 0, 100, 0, 50, 5, 5),
            tangentVertical: hit(0, 0, 0, 100, -5, 50, 5),
            nearMissHorizontal: hit(0, 0, 100, 0, 50, 5 + eps, 5),
            nearMissVertical: hit(0, 100, 0, 0, -(5 + eps), 50, 5),
            nearMissSloped: hit(0, 0, 100, 50, 50 + (5 + eps) / Math.sqrt(5), 25 - 2 * (5 + eps) / Math.sqrt(5), 5),
            nearMissEndpoint: hit(0, 0, 100, 0, 105 + eps, 0, 5),
            nearMissVertex: hit(0, 0, 100, 0, -3 - eps, -4 - eps, 5),
            beyondEnd: hit(0, 0, 100, 0, 110, 1, 5),
            crossingVertical: hit(20, 0, 20, 100, 22, 50, 5),
            reversedHorizontal: hit(100, 0, 0, 0, 50, -4, 5),
            inPoly: pointInPolygon(square, 50, 50),
            outPoly: pointInPolygon(square, 150, 50),
            nearest: (l => [l.x1, l.y1, l.x2, l.y2])(nearestLine(Element.prototype.getLines.call({getPoints: () => square}), 50, 90)),
            centreDeep: centreInside(50, 80, 5),
            centreNearEdge: centreInside(50, 97, 5),
            centreOutside: centreInside(50, 150, 5)
        }
    }'''

    @classmethod
    def setUpClass(cls):
        with ExitStack() as stack:
            url, browser = start_browser_test(ROOT, stack.callback)
            page = browser.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(url + 'index.html', wait_until='load')
            wait_for_boot(page)
            cls.r = page.evaluate(cls.CASES)
            cls.errors = errors

    def test_no_page_errors(self):
        self.assertEqual(self.errors, [])

    def test_crossing_edge(self):
        for key in ('crossing', 'crossingSloped', 'crossingVertical', 'reversedHorizontal'):
            self.assertTrue(self.r[key], key)

    def test_segment_inside_circle(self):
        self.assertTrue(self.r['insideShort'])
        self.assertTrue(self.r['insideShortVertical'])

    def test_touching_endpoint(self):
        for key in ('touchEndpoint', 'touchEndpointDiagonal', 'touchEndpointVertical'):
            self.assertTrue(self.r[key], key)

    def test_vertex_hit(self):
        self.assertTrue(self.r['vertex'])
        self.assertTrue(self.r['vertexSloped'])

    def test_tangent_horizontal_and_vertical(self):
        self.assertTrue(self.r['tangentHorizontal'])
        self.assertTrue(self.r['tangentVertical'])

    def test_near_miss(self):
        for key in ('nearMissHorizontal', 'nearMissVertical', 'nearMissSloped',
                    'nearMissEndpoint', 'nearMissVertex', 'beyondEnd'):
            self.assertFalse(self.r[key], key)

    def test_point_in_polygon_and_nearest_edge(self):
        self.assertTrue(self.r['inPoly'])
        self.assertFalse(self.r['outPoly'])
        self.assertEqual(self.r['nearest'], [100, 100, 0, 100])

    def test_centre_inside_hits_nearest_edge(self):
        deep = self.r['centreDeep']
        self.assertTrue(deep['result'])
        self.assertEqual(deep['hits'], [[100, 100, 0, 100]])

    def test_centre_inside_near_edge_hits_once_by_line(self):
        near = self.r['centreNearEdge']
        self.assertTrue(near['result'])
        self.assertEqual(near['hits'], [[100, 100, 0, 100]])

    def test_centre_outside_misses(self):
        self.assertEqual(self.r['centreOutside'], {'hits': [], 'result': False})


if __name__ == '__main__':
    unittest.main()
