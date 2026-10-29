# Grapple Over level SVG format, version 1

An authoring format for fixed Grapple Over levels. A level file is a normal
SVG that a browser can display. It also carries every piece of gameplay data
the runtime loader needs, so a converter can turn it into a level object that
`validateFixedLevel()` in `fixedlevel.js` accepts, with no guessed values.

This document is the contract only. The importer comes later
(`tools/import_level_svg.py`, TASK-648). Fixtures live in
`tools/fixtures/level_svg/` (see [Fixtures](#fixtures)).

Scope: import fidelity. Nothing in this format claims that a drawn jump,
ceiling catch or fall is achievable with production physics. Physics
constants are not part of the format and are never tuned by it.

## 1. Coordinate system

- One SVG user unit is one world unit. Coordinates are read in the root user
  space. `width`/`height` on the root `<svg>` and its `viewBox` only scale the
  *display* and are never read for gameplay.
- +X points right and **+Y points down**, the same as SVG and the runtime.
  "Higher on the mountain" therefore means a smaller Y.
- Gameplay shapes, and every ancestor of a gameplay shape including the root
  `<svg>`, must not carry a `transform` attribute or a CSS `transform`
  (`style="transform:…"`). If they do, the file is rejected with
  `TransformedGameplay`. Nested `<svg>`, `<use>`, `<symbol>` and `<switch>`
  are not allowed in the gameplay layers (`UnsupportedShape`) because each
  one introduces a new coordinate system.
- Annotations (§4.4) may use transforms, nested `<svg>`, `<use>` and any
  other SVG feature. They are never read for gameplay.

## 2. Numbers

A numeric attribute holds one plain decimal number, matching
`[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?`, with optional surrounding
whitespace. Units (`px`, `%`, `em`) are rejected with `MalformedNumber`.
Tokens such as `NaN`, `inf` and `Infinity`, and values that overflow to a
non-finite float, are rejected with `NonFiniteGeometry`. List attributes
(`points`, `data-bounds`) are separated by whitespace and/or commas.

## 3. Identifiers

- Every `id` in the document, annotations included, is unique
  (`DuplicateId`). IDs match `^[A-Za-z][A-Za-z0-9_.:-]*$` (`InvalidId`).
- Every gameplay shape, fragment, section, encounter and transfer, plus the
  spawn and finish markers, must have an `id`. An empty or missing `id` is
  `InvalidId`.
- IDs are persistence keys. Saves store element IDs (`captureClimbState`), so
  an ID must not change when the geometry is edited. Renaming an element is a
  layout change and needs a new `data-layout-id`.
- The importer never generates, renumbers or sorts IDs.

## 4. Document structure

```xml
<svg xmlns="http://www.w3.org/2000/svg"
     xmlns:gn="urn:grapnelninja:level-svg:1"
     data-level-format="grapnelninja-level"
     data-level-version="1"
     data-layout-id="example-v1"
     data-grapple-range="540"
     data-bounds="-200 -1400 1600 400"
     viewBox="-200 -1400 1800 1800">
  <g id="annotations" data-layer="annotations">…ignored…</g>
  <g id="geometry" data-layer="geometry">…fragments and elements…</g>
  <g id="markers" data-layer="markers">…spawn and finish…</g>
  <metadata id="level-route">…sections, encounters, transfers…</metadata>
</svg>
```

### 4.1 Root attributes (all required)

| Attribute | Value | Error if missing or bad |
|---|---|---|
| `data-level-format` | exactly `grapnelninja-level` | `UnsupportedFormat` |
| `data-level-version` | exactly `1` | `UnsupportedVersion` (missing: `MissingMetadata`) |
| `data-layout-id` | ID syntax (§3) | `MissingMetadata` / `InvalidId` |
| `data-grapple-range` | number equal to `540` | `UnsupportedGrappleRange` |
| `data-bounds` | `left top right bottom`, 4 finite numbers, `left < right`, `top < bottom` | `MissingMetadata` / `MalformedNumber` / `NonFiniteGeometry` / `InvalidBounds` |

The root element must be `{http://www.w3.org/2000/svg}svg` (`UnsupportedFormat`).
World bounds come only from `data-bounds`. They are not taken from `viewBox`,
from the shapes' extent, or from any default.

### 4.2 Allowed top-level children

Exactly one each of `g[data-layer="geometry"]`, `g[data-layer="markers"]` and
`metadata#level-route` (`MissingLayer` / `DuplicateLayer`). Zero or more of
`g[data-layer="annotations"]`, `<defs>`, `<title>`, `<desc>` and `<style>`.
Any other top-level child is `UnexpectedTopLevel`: backgrounds, headings and
route arrows belong in an annotations layer. The order of the layers in the
file does not matter.

`<style>` sheets and `class`/`fill`/`stroke`/`style` attributes are display
only. The runtime styles surfaces by role (`PersistentWorld`). `<defs>`
contents are never read for gameplay.

### 4.3 Geometry layer

The geometry layer contains, in any mix:

- **Fragments**: `<g id="P0" data-fragment="true">`. A fragment groups the
  shapes of one named route piece. Transfers (§4.5) refer to fragment IDs.
  A fragment holds at least one element (`EmptyFragment`), no drag
  element (`InvalidDragZone`) and no no-grapple zone (`InvalidNoGrappleZone`). Fragments do not nest (`UnsupportedShape`).
- **Elements**: `<rect>` or `<polygon>`, either directly in the layer or
  inside a fragment.
- `<title>`/`<desc>` children, which are ignored.

Any other element in the geometry layer (`path`, `circle`, `ellipse`, `line`,
`polyline`, `text`, `image`, `use`, a plain `<g>` without
`data-fragment="true"`, …) is `UnsupportedShape`.

Element attributes:

| Attribute | Required | Meaning |
|---|---|---|
| `id` | yes | Runtime element ID |
| `data-role` | yes | `solid`, `bounce`, `hazard`, `drag` or `no-grapple`. Missing: `MissingMetadata`. Any other value: `InvalidSurfaceRole` |
| `data-grapplable` | yes | exactly `true` or `false`. Missing: `MissingMetadata`. Other value, or `true` on a `hazard`: `InvalidGrapplable`. `true` on a `drag`: `InvalidDragZone`. `true` on a `no-grapple`: `InvalidNoGrappleZone` |
| `x y width height` | `<rect>` | finite, `width > 0`, `height > 0`. `rx`/`ry` must be absent or `0` (`UnsupportedShape`) |
| `points` | `<polygon>` | ≥ 3 vertices, an even count of numbers. A `no-grapple` polygon must also be convex (`InvalidNoGrappleZone`) |
| `data-name` | no | Display label only, ignored |
| `class fill stroke stroke-width style opacity` | no | Display only, ignored (but a CSS `transform` is still rejected) |

Any other attribute on an element or fragment, including any other `data-*`
(for example `data-bounce-sign`, `data-restitution`, `data-mover`), is
`UnknownAttribute`. This keeps hidden per-element physics out of v1.

### 4.4 Annotations layer

The importer skips the whole layer, and everything in it, without reading
it: labels, gap percentages, route curves, background, legends, drop arrows.
A `data-role` or `<rect>` inside an annotation never becomes gameplay. The
layer may be transformed freely.

### 4.5 Markers layer

- Exactly one `<circle id="spawn" data-marker="spawn" cx="…" cy="…" r="…"/>`.
  The spawn is the circle centre; `r` is display only. No spawn:
  `MissingSpawn`. More than one: `DuplicateSpawn`.
- Exactly one `<rect id="finish" data-marker="finish" x y width height/>`,
  the finish trigger box. No finish: `MissingFinish`. More than one:
  `DuplicateFinish`. Requires `width > 0` and `height > 0` (`InvalidBounds`).
- No other children (`UnsupportedShape`). Marker attributes follow the same
  transform, number and unknown-attribute rules as elements.

### 4.6 Route metadata (`<metadata id="level-route">`)

Children use the namespace `urn:grapnelninja:level-svg:1` (prefix `gn` in
examples). Their document order is significant and is preserved.

```xml
<gn:section id="S01" encounters="E01 E02" label-key="climb.section.S01"/>
<gn:encounter id="E01" elements="P0-shelf P1-ramp"/>
<gn:transfer id="T01" from="P0" to="P1" encounter="E01" gap-percent="120"/>
```

- `gn:section`: `encounters` is a required, non-empty, space-separated list
  of encounter IDs. `label-key` is optional; it is an i18n key for the HUD
  only. When omitted, the runtime label is `climb.section.<id>` (existing
  `menu.js` behaviour, display only).
- `gn:encounter`: `elements` is a required, non-empty list of element IDs.
  These must be geometry-layer elements, not fragments or markers. An
  element may belong to several encounters. An element in no encounter is
  allowed (boundaries, drag zones).
- `gn:transfer`: `from` and `to` are required fragment IDs, `from ≠ to`.
  `encounter` is a required encounter ID. `gap-percent` is required, finite
  and `≥ 0`: the authored minimum-gap claim (§7).
- `gn:transfer` may carry an optional `guide` (additive, still format v1):
  a display-only cubic Bezier from the departure contact on `from` to the
  contact on the next panel `to`. The value is exactly 8 whitespace-separated
  finite numbers `x0 y0 x1 y1 x2 y2 x3 y3` in **world units**, in the same
  coordinate space as the geometry layer (no transform or viewBox scaling is
  applied). `(x0,y0)` is the start point, `(x1,y1)` and `(x2,y2)` are the
  control points and `(x3,y3)` is the end point. Number syntax follows §2,
  with no commas and no units. A wrong count, or any non-numeric, `nan`,
  `inf` or overflowing value, is `InvalidTransfer`. A missing `guide` is
  valid and means "no arrow". `guide` is allowed only on `gn:transfer`.
  Annotation `<path>`s, including drawn route curves, are never read as
  guides or as any other gameplay data. The guide gives no physics,
  collision or reachability guarantee.

  ```xml
  <gn:transfer id="T01" from="P0" to="P1" encounter="E01" gap-percent="60"
               guide="300 -10 500 -400 700 -400 924.5 -50"/>
  ```

  `tools/convert_extended_mountain_svg.py` writes guides only when `build(meas,
  guides=True)` is called. The points come from its route `curve()`, which
  starts and ends at the encounter's `flight` contacts. The default output
  has no guides. Guides are per transfer: in one file, some transfers may
  have a guide and others may not, and the unguided ones import in the
  legacy shape. Since TASK-660 `tools/retune_extended_level.py` (default
  extended opening) builds with guides and arrows, so the shipped
  `extended-mountain-v6` SVG and `leveldata.js` carry a guide on all 30
  transfers (`--opening original` still reproduces the unguided v5 file).
  `GuideTests.test_shipped_v6_roundtrip` strips the shipped guides, adds
  `guide()` values back and gets the shipped SVG byte-for-byte; stripping
  `guide` from the import changes nothing else.

  Direction arrows: `build(meas, guides=True, arrows=True)` (CLI
  `--arrows`) also draws one `<g class="transfer-arrow" data-transfer=…
  data-from=… data-to=…>` per transfer in `annotations-front`. Each one is
  the same `curve()` cubic from `t=0` to the parameter `t*` where its arc
  length reaches `min(0.5 * G, L)` world units, split with de Casteljau
  (`arrow_geometry`). `G` is the minimum edge-to-edge distance between the
  transfer's complete from/to fragment polygons (0 when they touch or
  overlap) and `L` is the guide's arc length, so short transfers get short
  shafts and a guide shorter than `0.5 * G` is drawn whole. `t*` comes from
  a 1024-chord arc-length table; a zero-length guide gives `t*=0`. The 6px
  arrowhead lies along the forward derivative at `t*` (the chord, then +x,
  when the derivative vanishes). It uses cyan
  `#8bdde8` at opacity 0.4 with a 1.5px stroke. Sizes are in canvas pixels:
  the annotation transform (scale `1/s`) times the root viewBox scale (`s`)
  is 1, so they are displayed pixels. The dashed full route curves stay
  unchanged. The importer ignores the arrows, so collision data is identical
  with or without them (`tools/test_level_route_arrows.py`).

  In the game, `render/routearrows.js` draws the same arrow from each loaded
  `svgFormat.transfers[].guide`: the same arc-length sub-cubic (computed once
  per level from the loaded fragment polygons and cached) and tangent head,
  with the same colour and opacity. The 1.5px stroke and 6px head are
  screen (CSS) pixels at every camera zoom. Arrows are drawn in the world
  layer under the range circle, grapnel, terrain and player. Each one is
  culled by the box of its own curve, not by its source panel. Transfers
  without a guide draw nothing. The arrows add no physics, input or save
  data (`tools/test_runtime_route_arrows.py`).
- At least one section, one encounter and one transfer. An empty kind is
  `MissingMetadata`.
- Any unresolved reference is `MissingReference`. An encounter that no
  section lists is `MissingReference` (orphan encounter). A repeated ID
  inside one list, or `from = to`, is `InvalidTransfer` for transfers and
  `MissingReference` for lists.
- Unknown element names or attributes inside `level-route` are
  `UnknownAttribute`.

## 5. Mapping to the runtime level (`validateFixedLevel`)

Output object, with keys in this order:

| Output field | Source | `validateFixedLevel` check |
|---|---|---|
| `version` | `1` (from `data-level-version`) | `data.version !== 1` gives `UnsupportedVersion` |
| `layoutId` | `data-layout-id` | not checked there. Used by `captureClimbState`/`restoreClimbState` to reject saves from another layout |
| `bounds` | `data-bounds` → `{left, top, right, bottom}` | finite, `left<right`, `top<bottom` (`InvalidBounds`) |
| `spawn` | spawn `cx, cy` → `{x, y}` | finite point |
| `finish` | finish rect → `{left:x, top:y, right:x+width, bottom:y+height}` | `bounds()` check. Never `null` in v1 |
| `sections` | `gn:section` → `{id, encounters[, labelKey]}` | unique ID, `MissingReference` on encounters |
| `encounters` | `gn:encounter` → `{id, elements}` | unique ID, `MissingReference` on elements |
| `elements` | geometry shapes in document (pre-order) order → `{id, x, y, role, grapplable, points}` | unique ID, role in set, ≥ 3 finite points, no repeated consecutive vertex, no self-intersection, non-zero area; a `no-grapple` element is `grapplable: false`, convex and not moved (`InvalidNoGrappleZone`) |
| `movers` | always `[]` (v1 has no movers) | collection must be an array |
| `svgFormat` | `{version:1, grappleRange:540, fragments:[{id, elements}], transfers:[{id, from, to, encounter, gapPercent[, guide]}]}` | ignored by the loader. Kept so geometry checks (TASK-649) can test transfers. `guide`, present only when the SVG has one, is `[[x0,y0],[x1,y1],[x2,y2],[x3,y3]]` in world units. Integral values are written as integers (`plain()`) |

Element conversion:

- `<rect x y width height>`: `x`, `y` are the rect origin; `points` are
  `[{0,0},{w,0},{w,h},{0,h}]`. This is the same convention as
  `GRAPPLE_OVER_LEVEL`.
- `<polygon points="x0,y0 x1,y1 …">`: `x=x0`, `y=y0`; `points[i] = {xi-x0, yi-y0}`
  in document order, so the first relative point is `{0,0}`. Winding is kept
  as written: the loader accepts either direction.
- The importer runs the same structural checks as `validateFixedLevel` and
  uses the same diagnostic names, so a file that imports always loads.

Role semantics. These are the existing runtime behaviours; the format adds
none, except the `no-grapple` contract below.

- `solid`: collides, and the grapple can attach anywhere on its outline,
  undersides included, when `grapplable="true"`. A **ceiling hold** is not a
  separate role. It is a grapplable `solid` whose underside the player can
  reach. Mark a non-grappleable solid (for example a world wall) with
  `grapplable="false"`.
- `bounce`: keeps the existing `Trampoline` bounce response. v1 has no
  per-element direction or strength attribute.
- `hazard`: collides and damages through the existing hazard path. The
  runtime never hooks a hazard (`Grapnel.blocksShot` in `sprites/grapnel.js`
  stops the line on it whatever its flag says). A hazard must therefore say
  `data-grapplable="false"` (`InvalidGrapplable` otherwise), so that the file
  cannot claim a grapple target the game refuses.
- `drag`: never collides and can never be grappled. `PersistentWorld` keeps
  drag zones out of `elements`, which is the list every collision, rope and
  save consumer walks. While the player circle overlaps one, each tick
  multiplies horizontal speed by `DRAG_ZONE_HORIZONTAL_DAMPING` (0.8) and
  vertical speed by `DRAG_ZONE_VERTICAL_DAMPING` (0.985). A drag element must
  say `data-grapplable="false"` (`InvalidDragZone` otherwise), even though
  the runtime would force it to false anyway. That makes the file
  self-describing.
- `no-grapple` (purple, TASK-672): a static convex region (rect or
  convex polygon, any orientation) in world units, for example the default 5400 x 2700 (10R x 5R) rect. It is
  not a surface. It never collides, never slows the player (it is not a drag
  zone or yellow brake: momentum, gravity and bounce responses are
  unchanged) and is never a grapple target, so it must say
  `data-grapplable="false"` and sit directly in the geometry layer, outside
  every fragment (`InvalidNoGrappleZone` otherwise). v1 has no movers, so a
  zone is always static; a level JSON mover on one is rejected by the loader
  (`InvalidNoGrappleZone`). `PersistentWorld` keeps zones in
  `noGrappleZones`, out of `elements` (collision, rope, saves) and out of
  `dragZones`. The zone acts on the **player's location**: the player is
  inside while the player circle overlaps the zone, boundary and corner
  tangency included. While inside, any attached or in-flight rope is
  released immediately and no new rope can be acquired (held or repeated
  input included) until the circle is completely outside every zone. Panels
  inside the zone stay `grapplable="true"`: only acquisition is inhibited,
  by player location. A player outside may fire a rope that crosses a zone
  or attaches to a panel inside one. Runtime (TASK-673):
  `PersistentWorld.playerInNoGrappleZone` tests the circle (tangency within
  `NO_GRAPPLE_TANGENCY_TOLERANCE`, 1e-6 world units), and `calcPhysics`
  drops the rope right after the player moves, before that step's rope
  pull or acquisition. Input ownership is unchanged: as after a fall
  recovery, a press whose rope was dropped, or one made inside a zone, stays
  stale until released. Held input therefore never attaches after exit
  either; a fresh press is needed (`tools/test_no_grapple_physics.py`).
  Drawing is TASK-674.
  Spacing inside a zone is relaxed only for route transfers, see §7.1.
  The player must not be able to come to rest inside a zone (it could not
  grapple out); see the no-rest rule in §7.3 (checker default since v17).
- `grapplable` is always written explicitly in the output. The loader's
  `grapplable !== false` default is never relied on.

No unspecified defaults affect gameplay. Bounds, spawn, finish, every role,
every grapplable flag, every ID and every reference must appear explicitly in
the SVG. The only implied values are display-only: section `labelKey`
(omitted from the output when absent) and `movers: []` (fixed by the version).

## 6. CLI contract (for TASK-648)

```
python3 tools/import_level_svg.py --input LEVEL.svg --output LEVEL.level.json
```

- **Deterministic**: the same input bytes always give the same output bytes.
  The output is
  `json.dumps(obj, separators=(',', ':'), ensure_ascii=True)` with the
  §5 key order, followed by one `\n`. Numbers are parsed with `float()`, and
  integral values are written as JSON integers. The output contains no
  timestamps, absolute paths or hashes.
- **Success**: exit `0`, output written, nothing on stdout except an optional
  one-line summary.
- **Failure**: exit `1`, one or more lines on stderr in the form
  `ERROR <Category>: <id-or-xpath>: <message>`.
  The output file is not created, truncated or replaced. The importer writes a temporary file in
  the output's directory and calls `os.replace()` only after every check
  passes; on failure the temporary file is removed. Usage errors exit `2`
  (argparse). `--input` and `--output` must name different files (exit `2`).
- **Annotations are excluded** from the output entirely (§4.4).

## 7. Gap-percent semantics

Gap percentage = **minimum edge-to-edge distance / 540 * 100**. For transfer
`T` from fragment `A` to fragment `B`:

```
distance(A, B) = min over element polygons a in A, b in B of edge-to-edge distance(a, b)
                 (0 when the polygons intersect or one contains the other)
gapPercent     = distance(A, B) / 540 * 100
```

- 540 is `data-grapple-range`, the upgraded acquisition radius (`gameoptions.js`
  `upgradedAcquisitionRadius: 540`). It is fixed in v1.
- Distances use absolute world polygons (`x + points[i]`), only gameplay
  elements of the two fragments, never annotations, labels or route curves.
- `gap-percent` in the file is the author's claim. The importer copies it into
  `svgFormat.transfers[].gapPercent` and checks only that it is a finite
  number `≥ 0`. The geometry checker (TASK-649) recomputes the distance from
  the imported polygons and reports a mismatch when
  `|computed − declared| > 0.01` percentage points. A drawn or printed label
  is never the computed result.
- A gap percentage describes clearance only. It does not mean the jump is
  feasible.

### 7.1 Internal no-grapple transfers

The independent checker (`tools/check_level_geometry.py`) normally requires
every fragment pair to keep `clearance - 21.6 > 540` (no grapple shortcut).
One narrow exception exists, and nothing else is relaxed:

- A pair `(A, B)` is **internal** when `A -> B` (or `B -> A`) is a
  `gn:transfer`, and one single `no-grapple` zone `Z` contains every vertex
  of every polygon of `A` and of `B` and both ends of the minimum-distance
  witness segment between them. Containment is inclusive (a vertex on `Z`'s
  boundary is inside). Because `Z` is convex, this means both complete
  panels and the intervening transfer segment are inside `Z`.
- An internal pair must have `0 < distance <= 270` (0.5R). An internal
  transfer with a larger gap fails, even if it would pass the 540 rule.
- Every other pair keeps its existing rule: pairs that are not transfers
  (even when both panels are inside the same zone), pairs that straddle the
  zone boundary, pairs whose panels sit in two different zones, and pairs
  outside any zone. `allowedGrapplePairs` keep their opening rule.
- Yellow (drag) clearances are unchanged: at least 1620 (3R) to the nearest
  green panel and at least 540 between yellow zones. A `no-grapple` zone is
  neither a solid nor a brake for these checks.
- Each pair in the report carries `rule` (`grappleClearance`, `opening` or
  `noGrappleInternal`) and `noGrappleZone`; the summary counts
  `noGrappleZones` and `noGrappleInternalPairs`
  (`tools/test_no_grapple_format.py`).

### 7.2 Minimum side length

Every generated layout (shipped since v16) must give every actual polygon edge a length of at least
**270 units (0.5R)**. The checker measures each edge `i -> i+1` (and the
closing edge) with `hypot` from the imported world vertices, never from SVG
widths, labels or recorded metadata.

- Measured: every polygon of every gameplay role — `solid`, `bounce`,
  `hazard` bodies including a fragment's extra bodies, posts and bevel facets,
  yellow `drag` zones and purple `no-grapple` zones. Elements without a
  gameplay role (decorative strokes, annotations, route curves) are exempt.
- An edge fails when `length < 270 - 0.01` (the coordinate tolerance), so
  270 and 269.991 pass while 269.989 and 269 fail.
- The CLI enforces the rule by default (270; `--min-side-length UNITS` sets
  another minimum). With `--no-min-side-length` (legacy layouts before v16)
  or `check(..., min_side=None)` in Python the report still lists every edge
  (`sides[]`: element, role, fragment, body index, semantic id, edge, length)
  and `summary.sideViolations`, but the result is unaffected, so old levels
  stay checkable. `--sides-only --level LEVEL.json` runs only the side,
  corner and self-intersection checks, without an SVG or reference file.
- This is a **minimum side length**, unrelated to the **maximum internal
  no-grapple transfer gap** of 270 in §7.1: one bounds a polygon's own edges
  from below, the other bounds the distance between two fragments from above.
- The 20 degree corner and self-intersection checks remain active in both modes
  (`tools/test_level_minimum_sides.py`).

### 7.3 No rest inside purple (default since v17)

Inside a `no-grapple` zone the player cannot fire a rope, so a spot where it
comes to rest there is a softlock. The rule (TASK-694):

- Every **upward-facing face** that overlaps a `no-grapple` zone slopes at
  least **15 degrees from horizontal**. A face is a polygon edge of a `solid`
  or `bounce` element whose outward normal points up (negative y, either
  winding). It overlaps a zone when more than 0.01 unit of the edge lies inside
  the convex zone (clipped, boundary inclusive), so a face that only partly
  enters the zone is checked too. Vertical edges and downward faces are not
  rest faces. `hazard` faces are exempt (contact kills, so it is no softlock),
  and so are drag and no-grapple zones (they do not collide).
- **No pockets**: no two such faces meet at a vertex (within 0.01 unit, same
  or different polygon) where both slope down toward it from opposite sides,
  even when both are steeper than 15 degrees: the player would settle in the V.
- The slope is measured with `atan2(|dy|, |dx|)` from the imported world
  vertices. 15 degrees passes, 14.9 fails (tolerance 1e-9 degrees).
- **Default** (TASK-698): `tools/check_level_geometry.py` runs it on every
  full check (`--no-grapple-rest` is accepted and redundant). `--allow-grapple-rest`
  skips it for legacy layouts up to v16, and `--sides-only` never runs it. The Python
  `check(..., no_grapple_rest=True)` API stays opt-in. Without the rule the report
  is unchanged. With it the report gains `noGrappleRest`
  (`minSlope`, `roles`, `faces[]`: element, fragment, semantic id, edge,
  angle, zone, zones, a, b, pass; `pockets[]`: vertex, left/right element,
  edge and angle, zones), the summary gains `noGrappleRestFaces`,
  `noGrappleRestFaceViolations`, `noGrappleRestPockets` and
  `minNoGrappleRestAngle`, and each violation is a failure ending in `(rest)`.
- The shipped v21 level passes it (293 rest faces including the Z1..Z8 and
  Sky Spire Y1..Y8 slabs, minimum 15 degrees, no pockets). v20 passed it (127 rest
  faces including the Z1..Z8 slabs, minimum 15 degrees, no pockets). v19 passed it (53 rest faces including the BZ1..BZ3 slabs,
  minimum 15 degrees, no pockets), as did v18 and v17 (23 rest faces, minimum 15.5
  degrees). The earlier v16 fails it on the rest rule only: NG1's near-flat
  tops P23 (4.8 degrees), P24 (0 degrees) and P25 (0.6 degrees), and their
  copies in NGM (P33-P35) and NGU (P46-P48) (`tools/test_no_grapple_rest.py`).

### 7.4 Map width (TASK-722, default since TASK-725 / v19)

- Every element point, the spawn and the finish region lie within
  `x -1100..62534`, the bottom run's span, so a failed jump falls onto lower
  geometry instead of beside the map.
- `tools/check_level_geometry.py` applies it on every full check
  (`DEFAULT_X_RANGE`; `--max-x-range MIN:MAX` sets another span,
  `--no-max-x-range` skips it for legacy layouts up to v18). With
  `--sides-only` it is opt-in. The report gains `maxXRange` (`min`, `max`,
  `checked`, `minX`, `maxX`, `violations[]` with each element's x extent) and
  the summary `maxXRangeViolations`.
- v21, v20 and v19 pass it. v18 fails it (the SEC-ext-summit panels from about x -80,450).

## 8. Rejection summary

| Category | Cause |
|---|---|
| `MalformedXml` | not well-formed XML |
| `UnsupportedFormat` | root is not SVG, or `data-level-format` is wrong |
| `UnsupportedVersion` | `data-level-version` is not `1` |
| `UnsupportedGrappleRange` | `data-grapple-range` is not 540 |
| `MissingMetadata` | a required root, element or route attribute/kind is missing |
| `MissingLayer` / `DuplicateLayer` / `UnexpectedTopLevel` | §4.2 layer rules |
| `TransformedGameplay` | a transform on a gameplay shape, marker, fragment, layer or root |
| `UnsupportedShape` | anything but rect/polygon in geometry, rounded rect, nested fragment, `use`/`svg`/`symbol`/`switch` |
| `UnknownAttribute` | an unrecognised attribute on gameplay or route nodes |
| `InvalidId` / `DuplicateId` | §3 |
| `InvalidSurfaceRole` | role not in `solid bounce hazard drag no-grapple` |
| `InvalidGrapplable` | not exactly `true`/`false`, or a hazard marked `true` |
| `InvalidDragZone` | drag that is grapplable or inside a fragment |
| `InvalidNoGrappleZone` | no-grapple zone that is grapplable, inside a fragment, not convex, or (level JSON) moved by a mover |
| `EmptyFragment` | a fragment without elements |
| `MalformedNumber` / `NonFiniteGeometry` | §2 |
| `MalformedPolygon` | < 3 vertices, odd number count, repeated consecutive vertex, self-intersection, zero area |
| `InvalidBounds` | bad world bounds or finish box |
| `MissingSpawn` / `DuplicateSpawn` / `MissingFinish` / `DuplicateFinish` | §4.5 |
| `MissingReference` | unresolved section/encounter/transfer reference, or an orphan encounter |
| `InvalidTransfer` | `from = to`, a bad `gap-percent`, or a malformed `guide` |

## Fixtures

`tools/fixtures/level_svg/`:

- `valid.svg`: a small level with two fragments, every role, a transformed
  annotation, one transfer.
- `valid.expected.json`: the exact §5 output for `valid.svg`, accepted by
  `validateFixedLevel`.
- `valid-guide.svg` / `valid-guide.expected.json`: `valid.svg` with a
  `guide` on T01. The output is `valid.expected.json` plus the transfer's
  `guide`.
- `valid-no-grapple.svg` / `valid-no-grapple.expected.json`: `valid.svg`
  plus a 1200 x 600 `no-grapple` rect; the output is `valid.expected.json`
  plus that element (and its own layout id).
- `invalid-no-grapple-{grapplable,concave,fragment}.svg`: a grapplable,
  concave, or in-fragment no-grapple zone.
- `invalid-guide-{count,nonnumeric,nonfinite,unknown-fragment}.svg`: bad
  guides, and a guided transfer whose `from` is not a fragment.
- `invalid-*.svg`: each file breaks exactly one rule.
  `manifest.json` lists every fixture with its expected outcome or
  diagnostic category.
