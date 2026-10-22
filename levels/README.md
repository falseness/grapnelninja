# Levels

`extended-mountain.svg` is the authoring source (SVG level format v1,
`docs/level-svg-format.md`). `extended-mountain.level.json` is generated from it
and is what normal Grapple Over starts load (`loadGrappleOverLevelAsset` in
`mountain.js`, fetched during boot before the world is built). Layout id:
`extended-mountain-v1`. Saves made with another layout id are rejected and the
climb restarts at the spawn.

Regenerate the runtime JSON after editing the SVG (run from the repo root):

    python3 tools/import_level_svg.py --input levels/extended-mountain.svg --output levels/extended-mountain.level.json

Also regenerate the classic-script copy used when opening `index.html` directly
with a `file://` URL (browsers prohibit fetching local JSON):

    python3 tools/import_level_svg.py --input levels/extended-mountain.svg --output levels/extended-mountain.level.js --format javascript

Both outputs contain the same level data and pass the same runtime validator.
HTTP startup continues to use JSON.

Then check it:

    python3 tools/check_level_geometry.py --svg levels/extended-mountain.svg --level levels/extended-mountain.level.json --report /tmp/geometry.json
    python3 -m unittest discover -s tools -p test_imported_level_runtime.py -v

Do not edit the JSON by hand. A changed layout needs a new `data-layout-id`
(and `GRAPPLE_OVER_IMPORTED_LAYOUT_ID` in `mountain.js`).

Local test selectors: `?grappleFixture=replacement-v1` keeps the hand-authored
replacement layout, `?grappleFixture=legacy-v3` the legacy mountain.
