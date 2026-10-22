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
  A fragment holds at least one element (`EmptyFragment`) and no drag
  element (`InvalidDragZone`). Fragments do not nest (`UnsupportedShape`).
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
| `data-role` | yes | `solid`, `bounce`, `hazard` or `drag`. Missing: `MissingMetadata`. Any other value: `InvalidSurfaceRole` |
| `data-grapplable` | yes | exactly `true` or `false`. Missing: `MissingMetadata`. Other value, or `true` on a `hazard`: `InvalidGrapplable`. `true` on a `drag`: `InvalidDragZone` |
| `x y width height` | `<rect>` | finite, `width > 0`, `height > 0`. `rx`/`ry` must be absent or `0` (`UnsupportedShape`) |
| `points` | `<polygon>` | ≥ 3 vertices, an even count of numbers |
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
  has no guides.
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
| `elements` | geometry shapes in document (pre-order) order → `{id, x, y, role, grapplable, points}` | unique ID, role in set, ≥ 3 finite points, no repeated consecutive vertex, no self-intersection, non-zero area |
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
none.

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
| `InvalidSurfaceRole` | role not in `solid bounce hazard drag` |
| `InvalidGrapplable` | not exactly `true`/`false`, or a hazard marked `true` |
| `InvalidDragZone` | drag that is grapplable or inside a fragment |
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
- `invalid-guide-{count,nonnumeric,nonfinite,unknown-fragment}.svg`: bad
  guides, and a guided transfer whose `from` is not a fragment.
- `invalid-*.svg`: each file breaks exactly one rule.
  `manifest.json` lists every fixture with its expected outcome or
  diagnostic category.
