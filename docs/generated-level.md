# Generated level

Authoring SVG, JSON, JavaScript copy and measurements live locally in
`/root/grapnelninja/artifacts/levels/` (ignored by Git).
The shipped runtime bundle is `/root/grapnelninja/leveldata.js`. Both HTTP
and direct file:// startup load this classic script before building the world.
No runtime request depends on the local artifacts directory.

Regenerate from the preserved original concept, from the repository root:

```sh
python3 tools/retune_extended_level.py --source artifacts/level/extended-mountain-measurements.json --output-dir artifacts/levels --guidelines artifacts/levels/level-guidelines.md
python3 tools/import_level_svg.py --input artifacts/levels/extended-mountain.svg --output artifacts/levels/extended-mountain.level.json
python3 tools/import_level_svg.py --input artifacts/levels/extended-mountain.svg --output artifacts/levels/extended-mountain.level.js --format javascript
cp artifacts/levels/extended-mountain.level.js leveldata.js
```

For manual authoring edits, run only the two importer commands and copy step.
Never edit the runtime bundle by hand. Commit the updated runtime bundle with
code changes; keep artifacts local. A fresh checkout can play the bundled level
without authoring files; authoring and comparison tests need the local sources.

Layout `extended-mountain-v4` uses 80% grapple-range opening gaps and 150%
straight-up gaps. All 25 panels, including ceilings, are green bounce surfaces; the ten separate
rectangular top bumps are removed. Incompatible older saves restart
at the spawn. Physics playability is not established by geometry checks.

Verify locally:

```sh
python3 tools/check_level_geometry.py --svg artifacts/levels/extended-mountain.svg --level artifacts/levels/extended-mountain.level.json --report artifacts/levels/distances.json
python3 -m unittest discover -s tools -p test_retuned_level.py -v
python3 -m unittest discover -s tools -p test_imported_level_runtime.py -v
```

The current design requirements are in
`/root/grapnelninja/artifacts/levels/level-guidelines.md` (local authoring input).
The generator requires this file and records its SHA-256 in the measurements.
The v4 layout enforces at least 200% grapple length (1,080 world units)
from every yellow rectangle to every green panel. The independent checker
cannot lower that threshold through reference metadata. Six fall brakes move
clear of panels; twelve additional upper fall-lane zones fit the rule.
The near-start brake and other close guards are relocated or removed. P5's shelf is
narrowed to keep the tested P3-to-P5 bypass arc away from its attachment edge;
P3 shifts left while retaining its 150% gap; P6 and later folded-section
repositioning is retained. The early-route regression probes pass, but the
broader sweep still finds bypasses in other folds. See the local
`/root/grapnelninja/artifacts/levels/v4-review/shortcut-sweep.json`; this output
is not certified free of shortcuts or fully playable.

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
