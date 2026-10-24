# Generated level

Layout `extended-mountain-v16` (shipped, TASK-687) is the default generator
output (`tools/retune_extended_level.py` with no layout flag =
`--min-side-scope all --middle-purple --upper-purple`). Two rules are new:

- Minimum side length: every actual polygon edge of a gameplay body or zone
  (green bodies, extra bodies, posts and bevels, yellow drag and purple
  no-grapple zones) is at least 270 units (0.5 R). Decorative strokes are
  exempt. `tools/check_level_geometry.py` enforces this by default
  (`--no-min-side-length` only inventories legacy layouts). It is a different
  limit from the 270 maximum internal no-grapple gap. The resizes are recorded
  under `minimumSides` in the measurements (TASK-679/681).
- Three purple no-grapple encounters on the later route: NG1 (leftward, after
  the first right-up-left sequence), NGM (rightward, NG1 mirrored at the S08-01
  arrival, later panels +7500, TASK-682/683) and NGU (leftward, NG1 copied at
  the EXT-13 arrival, later panels -7500, TASK-684/685). Each encounter is
  `purpleExtensions[]` in the measurements and a `data-role="no-grapple"`
  zone. Production-input traversals exist for all three
  (`PURPLE_ROUTE_ENCOUNTER=NG1|NGM|NGU tools/test_purple_route.py`). The
  shortcut shields under NGM (a second P4 body, L2 narrowed from the left and
  the NGM zone extended over L2, TASK-686) keep the whole-route matrix free of
  skips.

v16 has 62 panels and 61 transfers. The geometry equals the TASK-686 candidate;
only the layout id and the guidelines hash differ. Saves from v15 and earlier
restart at the spawn. The explicit flags still reproduce the earlier
candidates (`--min-side-scope none` = v15).

Layout `extended-mountain-v15` (previous) adds more height variation within the opening's
existing rightward and leftward runs. The rightward extension has higher
diagonal rebounds between the existing ceiling catches and descents; L1/L2 form two
up-left jumps followed by a down-left return. The easy first two jumps,
R1–R4 combination, upward-turn endpoints, purple chute and later mountain
panels stay in place. Yellow brakes are regenerated to retain their required
clearances. Older layout saves restart at the base.

Guidelines, authoring SVG, JSON, JavaScript copy and measurements live locally in
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

The generated SVG carries a display-only `guide` and a direction arrow
(shaft arc length `min(0.5 * gap, guide length)`) on every transfer (docs/level-svg-format.md §4.6), so the game draws the same
arrows from `leveldata.js` (`render/routearrows.js`).

For manual authoring edits, run only the two importer commands and copy step.
Never edit the runtime bundle by hand. Commit the updated runtime bundle with
code changes; keep artifacts local. A fresh checkout can play the bundled level
without authoring files; authoring and comparison tests need the local sources.

Layout `extended-mountain-v6` uses 80% grapple-range opening gaps and 150%
straight-up gaps. Its opening runs rightward, turns upward, then runs leftward;
both horizontal spans are 3x the v5 layout. Four rightward panels and two
leftward panels were added, so the route has 31 panels and 30 transfers. The
measurements' `routeMap` maps v5 panel ids and encounter numbers to v6 ids and
numbers; tests refer to old encounters through it. All panels, including
ceilings, are green bounce surfaces; the ten separate rectangular top bumps are
removed. Incompatible older saves (including v5) restart at the spawn. Physics playability is not established by geometry checks.

Layout `extended-mountain-v9` (shipped) keeps that structure. After the two
80% transfers, the four rightward transfers form one mixed combination: a
ceiling catch under R1 (1,250 above P2, 2,700 wide, its left end over P2's
right end; the player crosses its underside hand over hand), a release onto
R2's sloped face (650 below the catch; the face falls 80 of 900 units, 5.1°),
a right/up rebound onto R3 (550 higher, 1,400 wide), and a mostly horizontal
transfer to R4 (500 higher over a 1,000 release gap), the upward-turn
departure. The later terrain hangs a fixed height above R4, so the combination
ends high and right of v7's endpoint, and R1's underside shields P2: no panel
beyond a source's successor lies within the pumped apex plus the 540-unit
acquisition radius of P2, R1, R2 or R3. v8 (shipped before) let pumped bounces
from P2, R1 and R2 reach L2, L1, R4 and P7. These values were tuned against
production physics with the game's 540-unit acquisition radius.
`tools/test_opening_jump_variety.py` replays the combination continuously with
real mouse events from one zero-speed drop onto P2, probes the easy transfers
and the upward turn, and runs a bounded local shortcut search (0-5 pumps) that
must find no skip family beyond the pre-change v7 layout's. A yellow band must
lie wholly above the fall-recovery line (1,500 below the spawn,
`CLIMB_FALL_RECOVERY_DEPTH`) so a falling player passes through it before
recovery; the generator records any other under `unreachableYellowBands` and
does not emit it. v9 has five yellow zones; the jumps EXT-12 and EXT-15 have
no reachable brake. Saves from v8 and earlier (including the v6 that was
shipped before v8) restart at the spawn. The shortcut search is bounded: the
opening is not certified free of shortcuts globally, and the full climb is not
proven playable.

Layout `extended-mountain-v14` introduced the
varied lower rightward run X1-X10 (TASK-676), the purple no-grapple chute NG1
after the first right-up-left sequence (TASK-675; the zone is a
`data-role="no-grapple"` element in `world.noGrappleZones`, never a solid or
drag zone), dense panel circuits and distance-based route arrows. It has 48
panels and 47 transfers; only the four chute-internal transfers use the scoped
0 < gap <= 270 rule. v14 adds the TASK-677 shortcut shields (`shortcutShields` in
the measurements): a second R1 body hanging below its underside (a slot
keeps the ceiling-catch glide open), X1's sloped face trimmed
2100 units on the left (out from under R4) and a post on NG1's high end inside
the chute. The intended route never uses the space they occupy. Saves from v13
and earlier restart at the spawn.
`tools/test_route_shortcuts.py` runs a bounded whole-route policy matrix with
production input and physics (pumps, panel-end releases, high drops, ceiling
underside traversal and carried momentum) and fails on any first later-panel
contact or attachment that is not the successor. It is finite: it does not
certify the route free of shortcuts.

Verify locally:

```sh
python3 tools/check_level_geometry.py --svg artifacts/levels/extended-mountain.svg --level artifacts/levels/extended-mountain.level.json --report artifacts/levels/distances.json
python3 -m unittest discover -s tools -p test_retuned_level.py -v
python3 -m unittest discover -s tools -p test_imported_level_runtime.py -v
```

The current design requirements are in
`/root/grapnelninja/artifacts/levels/level-guidelines.md` (local design requirements; the commit hook forbids artifacts in Git).
The generator requires this file and records its SHA-256 in the measurements.
The v6 layout enforces at least 300% grapple length (1,620 world units)
from every yellow rectangle to every green panel (v5 and `--opening original`
used 200%, 1,080 units); six yellow zones remain, nearest clearance about 1,672. The independent checker
cannot lower that threshold through reference metadata. Every yellow pair also
has at least 100% grapple length (540 units) of edge-to-edge clearance. Nearby
yellow rectangles merge into one longer rectangle when its entire area remains
clear of green panels; otherwise the longer zone is retained and its conflicting
neighbor removed. This reduces 18 zones to nine; all 36 yellow pairs pass, with
minimum measured separation about 1,060 units. Green geometry is unchanged from
v4, including the narrowed P5 shelf that avoids the tested P3-to-P5 bypass arc.
P3 shifts left while retaining its 150% gap; P6 and later folded-section
repositioning is retained. The v4 sweep found bypasses in other folds; these remain an outstanding
limitation, not a claim resolved by yellow consolidation. See the local
`/root/grapnelninja/artifacts/levels/v4-review/shortcut-sweep.json`; this output
is not certified free of shortcuts or fully playable.

Every collision polygon corner must have an interior angle of at least 20°
(concave corners count as their reflex angle). Before platform placement the
generator truncates any sharper tip with a symmetric cut about 40 units wide
(each cut stays within 40% of its adjacent edges), so placement and all distances
are measured on the blunted collision shapes. The measurements record each
changed tip under `bluntedCorners`. `check_level_geometry.py` then rejects any
final polygon with a sub-20° corner, a self-intersection, a zero-length edge or
zero area, using level coordinates only. The current v5 geometry has no corner
below 20° (sharpest: P1 at 33.02°), so blunting changes nothing. The layout id
and the saves it accepts are unchanged.

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
