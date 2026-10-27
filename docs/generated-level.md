# Generated level

Layout `extended-mountain-v19` (shipped, TASK-725) is the default generator
output (`tools/retune_extended_level.py` with no layout flag =
`--min-side-scope all --middle-purple --upper-purple --purple-rest
--ext-summit --ext-summit-riser`). It is v18 with SEC-ext-summit laid out again
inside the bottom run's x span (TASK-722..724), so a failed jump falls onto
lower levels instead of beside the map:

- Map width: every element point, the spawn and the finish lie within
  x -1,100..62,534. `tools/check_level_geometry.py` enforces this by default
  for the full check (`--max-x-range`, default `-1100:62534`;
  `--no-max-x-range` skips it for legacy layouts up to v18, which fail it).
- From the old summit, five climbs run rightward along the top of the bottom
  run to its right end. The first starts on a riser: XS-C1a-1 is copied 5,000
  units straight up (C1a-1R), so the rest of C1a runs more than pump reach
  above the main level's last climb P18..P24, which runs leftward under it
  (without it the whole-route shortcut matrix found 84 skips, TASK-725). The
  sixth turns on a riser: its first panel C1f-1 is
  copied 5,000 units straight up (C1f-1R) and the rest of that climb runs
  leftward from the copy. A turn never stacks a return climb within pump reach
  of the climb below it (the TASK-723 fold did, and the shortcut matrix found
  368 skips). Then BZ1, one leftward climb, BZ2, one leftward climb, BZ3 and
  the new summit P117, whose finish is 42,426 units above the old one.
- BZ1..BZ3 are the v18 big-zone units (approach, slabs, exit, zone) moved
  rigidly by whole-unit (dx, dy), recorded in `extSummit.units`, so the BZ
  input fixtures are unchanged. Three catch shelves (flat bodies of XS-C1a-1)
  cover the columns where the bottom run has nothing under higher geometry,
  so a drop from them lands on the main level. The two over P17..P20 sit at
  y -37,500, out of pump reach of the main-level panels under them.
- Climb transfers have per-transfer production inputs
  (`tools/fixtures/ext-summit-climb-inputs.json`, `test_ext_summit_route`
  test_04).

v19 has 118 panels, 117 transfers and six no-grapple zones. The geometry is
the TASK-724 candidate plus the C1a riser and the two raised shelves
(TASK-725). Everything below the
old finish is unchanged from v18. Saves from v18 and earlier restart at the
spawn. `--no-ext-summit-riser` without layout flags reproduces v18,
`--no-ext-summit` reproduces v17 and `--no-purple-rest` reproduces v16.

### Gauntlet (v20 candidate)

`--ext-summit-gauntlet` (TASK-732, `EXT_SUMMIT_GAUNTLET`) is a candidate that
rebuilds SEC-ext-summit as a gauntlet. The shipped level stays v19, and the
candidate keeps the v19 layout id until it ships. The v19 extension is not
added. The old summit (P61) stays an ordinary landing, and everything below it
is identical to v19. Above it is a switchback tower over the old summit's
column (x 2,102..10,382, inside -1,100..62,534):

- Eight zone slots Z1..Z8, each an empty 5,760 x 4,320 purple no-grapple
  rect. Slabs come in later tickets. Odd zones are entered from the left side
  and run rightward. Even zones are entered from the right side and run
  leftward. Each zone is stacked 4,500 above the previous one, with 180
  between the zone rects.
- Every zone has an approach ledge 60 before it and an exit ledge 60 past it,
  both outside the zone. The exit ledge's top is 342 below the approach
  ledge's top.
- Green safe spaces S0..S8: S0 runs from the old summit to Z1's approach
  (6,700 up). Sk runs from Zk's exit to Z(k+1)'s approach, and S8 runs from
  Z8's exit to the new summit (4,842 up). Each one is two ceiling grapple
  panels on the tower's outer side. Consecutive safe spaces on the same side
  are 9,000 apart, so no climb is stacked within pump reach.
- `extSummit.gauntlet` records the slots: zone rects, entry side and
  direction, approach and exit ledges, the safe spaces' start/end fragments
  and grapple panels, the finish and the purple share. Purple share is 0.80
  (34,560 of 43,000 from the old summit top to the finish top).

Layout `extended-mountain-v18` (previous, TASK-711) is the generator output with
`--no-ext-summit-riser` and no layout flag. It is v17 with SEC-ext-summit, a
new section above the old summit (TASK-708..710), running leftward past the
left edge of the bottom run (x down to about -80,450):

- The old summit (P61) is an ordinary landing. Above it, three zigzag grapple
  climbs (translated copies of the final chain, all running leftward) lead into
  three big no-grapple zones BZ1, BZ2 and BZ3. The last climb ends on the new
  summit P103, whose finish is 19,882 units higher than the old one.
- Big zones are 5,760 x 4,320 units (the TASK-706/707 big-zone template v2).
  Each is entered from an approach ledge outside the zone with momentum. The
  player crosses it rope-free on a descending staircase of mixed-tilt bounce
  slabs and leaves through the side onto an exit ledge. The rope is grabbed again
  on the exit ledge and then on the first panel of the next climb (for BZ3, the
  summit). Slab 5 of every ext-summit zone is tilted to 30 degrees, so a high
  drop cannot bounce over the exit ledge (TASK-710). The first panel after a zone
  keeps the TASK-708 mirrored copy and position.
- Production-input traversals: `tools/test_ext_summit_route.py` with the
  `tools/fixtures/ext-summit-inputs-BZ1..3.json` fixtures. It runs on the shipped
  level by default (`EXT_SUMMIT_CANDIDATE=DIR` for a candidate). The whole-route
  shortcut matrix (`tools/test_route_shortcuts.py`) treats consecutive slabs
  of one no-grapple zone as one route step (`zoneSlab-*` outcomes). It has no
  skips.
- Section label: `climb.section.SEC-ext-summit` in every locale of `i18n.js`.

v18 has 104 panels, 103 transfers and six no-grapple zones (NG1, NGM, NGU,
BZ1..BZ3). The geometry equals the TASK-710 candidate; only the layout id
differs. All v17 elements below the old finish are unchanged. Saves from v17
and earlier restart at the spawn. `--no-ext-summit` without layout flags
reproduces v17, and `--no-purple-rest` reproduces v16.

Layout `extended-mountain-v17` (previous, TASK-698) is the generator output with
`--no-ext-summit` and no layout flag (= `--min-side-scope all --middle-purple
--upper-purple --purple-rest`). It is v16 with no place to rest inside a purple
zone:

- No rest inside purple: every upward face of a solid or bounce body that
  overlaps a no-grapple zone slopes at least 15 degrees, and no two of them
  form a pocket (docs/level-svg-format.md §7.3). `tools/check_level_geometry.py`
  enforces this by default (`--allow-grapple-rest` skips it for legacy layouts).
  v17 passes it (23 rest faces, minimum 15.5 degrees). v16 fails it only on the
  near-flat tops P23-P25 and their NGM/NGU copies.
- The chutes of NG1, NGM and NGU are re-routed (TASK-696/697): the chute floor
  rises leftward, the Overhang is raised, the Launch ramp is flatter (25.64
  degrees), the tops of NG2/NG4 fall toward the exit, the exit ledges are
  narrower and NGM3 is trimmed. The runtime rest-drop probe
  (`tools/probe_purple_rest.py`, 20 s) finds no stuck sample in any zone.
- Production-input traversals replay the `*-rest.json` input fixtures
  (`tools/fixtures/purple-route-inputs{,-ngm,-ngu}-rest.json`). They are the
  default of `tools/test_purple_route.py` on the shipped level. The plain fixtures
  stay for v16 (`PURPLE_ROUTE_REST=0`).

v17 has 62 panels and 61 transfers. The geometry equals the TASK-697 candidate;
only the layout id differs. The whole-route shortcut matrix has no skips.
Saves from v16 and earlier restart at the spawn. `--no-purple-rest` without
layout flags reproduces v16; the explicit layout flags still reproduce the
earlier candidates and default to no retilt.

Layout `extended-mountain-v16` (previous, TASK-687) is the generator output
with `--no-purple-rest` and no layout flag (= `--min-side-scope all
--middle-purple --upper-purple`). Two rules were new:

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
