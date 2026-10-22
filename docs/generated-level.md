# Generated level

Authoring SVG, JSON, JavaScript copy and measurements live locally in
`/root/grapnelninja/artifacts/levels/` (ignored by Git).
The shipped runtime bundle is `/root/grapnelninja/leveldata.js`. Both HTTP
and direct file:// startup load this classic script before building the world.
No runtime request depends on the local artifacts directory.

Regenerate from the preserved original concept, from the repository root:

```sh
python3 tools/retune_extended_level.py --source artifacts/level/extended-mountain-measurements.json --output-dir artifacts/levels
python3 tools/import_level_svg.py --input artifacts/levels/extended-mountain.svg --output artifacts/levels/extended-mountain.level.json
python3 tools/import_level_svg.py --input artifacts/levels/extended-mountain.svg --output artifacts/levels/extended-mountain.level.js --format javascript
cp artifacts/levels/extended-mountain.level.js leveldata.js
```

For manual authoring edits, run only the two importer commands and copy step.
Never edit the runtime bundle by hand. Commit the updated runtime bundle with
code changes; keep artifacts local. A fresh checkout can play the bundled level
without authoring files; authoring and comparison tests need the local sources.

Layout `extended-mountain-v3` uses 80% grapple-range opening gaps and 150%
straight-up gaps. All 25 panels, including ceilings, are green bounce surfaces; the ten separate
rectangular top bumps are removed. Incompatible older saves restart
at the spawn. Physics playability is not established by geometry checks.

Verify locally:

```sh
python3 tools/check_level_geometry.py --svg artifacts/levels/extended-mountain.svg --level artifacts/levels/extended-mountain.level.json --report artifacts/levels/distances.json
python3 -m unittest discover -s tools -p test_retuned_level.py -v
python3 -m unittest discover -s tools -p test_imported_level_runtime.py -v
```

The v3 generator repositions P6 and the later folded sections to reduce upward
skips. Six fall brakes remain, with additional horizontal yellow zones above
launch areas and over the high P3-to-P5 bypass arc. These are existing pass-through
drag zones; gravity, grapple range, reflection and damping constants are unchanged.

Run the focused physics regressions:

```sh
python3 -m unittest discover -s tools -p test_level_shortcuts.py -v
```

`tools/probe_level_routes.py` uses real pointer handlers and fixed-tick production
physics. Its local fixtures begin with zero-velocity drops and record actual
bounce arrival velocities; they do not inject a launch velocity after setup.
The finite sweep tests sampled hold/release policies, not every possible input
or a complete from-spawn climb. Failed intended-route searches are retained in
`artifacts/levels/shortcut-review/`; lack of a found route is not a proof that
a passage is impossible, and the level is not certified fully playable.
