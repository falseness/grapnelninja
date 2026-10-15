# Mountain manifest

`mountain.js` defines `GRAPPLE_OVER_MOUNTAIN` and `loadMountainLevel(manifest)`.
The normal runtime still loads the earlier `GRAPPLE_OVER_LEVEL` calibration
fixture. Section authoring can switch that default once the opening is playable.
The mountain loader already supports a partial manifest: it instantiates only
`geometry.elements`, while planned encounters have empty element lists and cannot
claim a built route. No summit finish trigger is enabled by this planning task.

Coordinates use negative Y upward. The base is (2160, 0), summit (3780, -12960),
and horizontal envelope [0, 6480]. Eight ordered sections reserve 1620-unit bands;
connectors and physical recovery paths may overlap adjacent bands. Geometry is
versioned separately from the manifest schema; stable S01-01 through S08-04 IDs
are independent of coordinates. Section mechanics and landmarks follow the
approved section descriptions in the task queue.

All 32 encounters and both optional shortcuts are planned. The three built
boundary polygons provide a nonlethal, grappleable catch floor and outer walls.
They are infrastructure, not completed encounters. Planned coordinates and
landmark symbols are schematic reservations, not verified landing locations or
finished industrial silhouettes. Later geometry must be calibrated and tested
with real input. The structural boundary checks reject displaced walls, sealed
full-width barriers, an ungrappleable catch floor, and geometry enclosing the
spawn; they do not prove that every possible authored pocket is escapable.

The browser suite exports `manifest.json`, the annotated `map-plan.svg`, and
mutation/partial-load proof to `GRAPPLE_OVER_EVIDENCE_DIR` (default
`artifacts/TASK-464`). SVG routes distinguish normal ascent, physical falls to
named recovery destinations, and optional shortcuts in S03 and S07. The normal
route remains present alongside each shortcut.

Falls remain physical and hazards nonlethal. The manifest rejects checkpoint
and respawn fields; the existing save system continues to capture current
simulation state. No walking, jump action, rope constraint, or engine is added.
The target 30–60 minute first success is **unvalidated without human feedback**;
automated structure checks cannot establish human difficulty or completion time.
