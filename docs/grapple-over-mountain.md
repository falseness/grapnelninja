# Mountain manifest

`mountain.js` defines `GRAPPLE_OVER_MOUNTAIN` and `loadMountainLevel(manifest)`.
The normal runtime loads the partial mountain. The earlier
`GRAPPLE_OVER_LEVEL` remains available as an explicit calibration fixture.
The mountain loader already supports a partial manifest: it instantiates only
`geometry.elements`, while planned encounters have empty element lists and cannot
claim a built route. No summit finish trigger is enabled by this planning task.

Coordinates use negative Y upward. The base is (2160, 0), summit (3780, -12960),
and horizontal envelope [0, 6480]. Eight ordered sections reserve 1620-unit bands;
connectors and physical recovery paths may overlap adjacent bands. Geometry is
versioned separately from the manifest schema; stable S01-01 through S08-04 IDs
are independent of coordinates. Section mechanics and landmarks follow the
approved section descriptions in the task queue.

S01-01 and S01-02 are built; the remaining 30 encounters and both optional
shortcuts are planned. The three built
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

## Foundations opening (TASK-465)

The base connects directly to a 600-unit entrance dock. A broken mast and torn
crane beam identify the loading yard; the beam is within the calibrated R=540
acquisition range. Pull toward it and release onto the raised loading bay. The
bay has visible supporting legs and a raised end stop, providing a safe temporary
exit while S01-03/04 remain planned. All silhouettes use the actual solid collision
polygons and existing gray solid semantics; there are no hazards or finish trigger.
Short releases return physically to the dock, with the broad mountain catch floor
below. The next overhead beam is visible from both the entrance and exit.

`tools/test_grapple_over_sections.py` records trusted browser inputs and every
physics tick for the connected S01-01/02 route. It measures the nominal release,
+/-3 tick releases, +/-0.02R aim offsets, and two miss/recovery cases against the
unchanged authored world. Evidence, including screenshots and source hashes, is
written beneath `GRAPPLE_OVER_EVIDENCE_DIR` (default `artifacts/TASK-465`).
