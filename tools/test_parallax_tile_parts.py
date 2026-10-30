"""Grapple Over parallax tiles kept as parts (TASK-788, render/parallax.js).

Each tile is stored as the rows its paint reaches plus, for the ridges, a fill
strip repeated across the tile. For every layer and band, at the user's
recording size (1706x932 DPR 1.5) and a touch size (844x390 DPR 2):
  - the whole tile painted as before (one buildGlowSprite of the full size)
    has no visible px above the first part, and every part's px equal the
    whole tile's px at its rows (a fill strip's px at every column),
  - the canvases a fill part draws across the tile (its strip repeated,
    then the rest) cover the tile's width exactly,
  - a rebuild (new pixel scale, as a resize does) creates one canvas per
    tile, as whole tiles did: the fill strips' canvases are reused,
  - the parts hold at most 60% of the whole tiles' bytes at the recording
    size, 75% at the touch size (the glow margin is in device px, so it
    is a larger share of a smaller tile).

    python3 tools/test_parallax_tile_parts.py
"""
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
from browser_test_support import start_browser_test, wait_for_boot_run  # noqa: E402

COMPARE = r'''() => {
    const rows = []
    for (const [key, tile] of GRAPPLE_OVER_PARALLAX_TILES.cache) {
        const [, name, band, scale] = key.split('|')
        const layer = GRAPPLE_OVER_PARALLAX.layers.find(l => l.name == name)
        const whole = buildGlowSprite(tile.width, tile.height, 0, +scale, +scale, 0, 0, 1,
            paintGrappleOverParallaxTile, [layer, +band], true)
        const W = tile.width, data = whole.getContext('2d').getImageData(0, 0, W, tile.height).data
        let above = 0, differing = 0, bytes = 0
        for (let i = 0; i < tile.parts[0].y * W; ++i)
            if (data[i * 4 + 3])
                ++above
        for (const part of tile.parts) {
            // The canvases drawn across the tile, as a fill part draws them
            const across = []
            if (part.rest === undefined)
                across.push([part.canvas, 0])
            else
                for (let from = 0; from < W;) {
                    const image = from + part.canvas.width <= W ? part.canvas : part.rest
                    across.push([image, from])
                    from += image.width
                }
            for (const image of new Set(across.map(([image]) => image)))
                bytes += image.width * image.height * 4
            for (const [image, from] of across) {
                const cw = image.width, own = image.getContext('2d').getImageData(0, 0, cw, part.rows).data
                for (let y = 0; y < part.rows; ++y)
                    for (let x = 0; x < cw; ++x) {
                        const i = (y * cw + x) * 4, j = ((part.y + y) * W + from + x) * 4
                        if (own[i] != data[j] || own[i + 1] != data[j + 1] || own[i + 2] != data[j + 2] || own[i + 3] != data[j + 3])
                            ++differing
                    }
            }
        }
        rows.push({key, size: [W, tile.height],
                   parts: tile.parts.map(p => [p.y, p.rows, p.canvas.width, p.rest === undefined ? null : p.rest && p.rest.width]),
                   above, differing, bytes, wholeBytes: W * tile.height * 4})
    }
    return rows
}'''

REBUILD = r'''() => {
    const store = GRAPPLE_OVER_PARALLAX_TILES, create = document.createElement
    const fills = store.fills.slice()
    let created = 0
    document.createElement = function(tag) {
        if (String(tag).toLowerCase() == 'canvas')
            ++created
        return create.apply(this, arguments)
    }
    try { buildGrappleOverParallaxTiles(store.scale + 0.0001) } finally { document.createElement = create }
    return {created, tiles: store.cache.size, fillsReused: store.fills.length == fills.length &&
            store.fills.every((c, i) => c === fills[i])}
}'''


class ParallaxTilePartsTests(unittest.TestCase):
    def check(self, viewport, dpr, share):
        with ExitStack() as stack:
            url, browser = start_browser_test(ROOT, stack.callback)
            context = browser.new_context(viewport=viewport, device_scale_factor=dpr)
            stack.callback(context.close)
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(url + 'index.html', wait_until='load')
            wait_for_boot_run(page)
            self.assertTrue(page.evaluate('GRADIENT_DITHER.enabled'))
            rows = page.evaluate(COMPARE)
            rebuild = page.evaluate(REBUILD)
            self.assertEqual(errors, [])
        self.assertEqual(len(rows), 16)
        for row in rows:
            self.assertEqual((row['above'], row['differing']), (0, 0), row)
            self.assertEqual(len(row['parts']), 2 if '|ridges|' in row['key'] else 1, row)
        parts, whole = sum(r['bytes'] for r in rows), sum(r['wholeBytes'] for r in rows)
        self.assertLessEqual(parts, share * whole)
        self.assertEqual(rebuild, {'created': 16, 'tiles': 16, 'fillsReused': True})
        print('PASS %dx%d DPR %s: 16 tiles, parts equal the whole tiles (0 px differ, 0 visible above), '
              '%.1f of %.1f MB (%.0f%%); a rebuild creates %d canvases, fill strips reused' % (
                  viewport['width'], viewport['height'], dpr, parts / 1048576, whole / 1048576,
                  100 * parts / whole, rebuild['created']))

    def test_recording_size(self):
        self.check({'width': 1706, 'height': 932}, 1.5, 0.6)

    def test_touch_size(self):
        self.check({'width': 844, 'height': 390}, 2, 0.75)


if __name__ == '__main__':
    unittest.main()
