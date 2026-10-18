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

S01 is layout v3 (TASK-547): S01-01/02 are built from green bouncers and blue
movers at the 1080 range, with no gray pads; S01-03/04 are planned again until
TASK-548. S02 is layout v3 too (TASK-550): from the S01 exit pad, S02-01/02
travel left through a blue hoist, a green canopy, a blue lift and a green west
bulkhead; TASK-551 built S02-03/04 up to a green exit ledge. S03 is layout v3
too (TASK-553): from that ledge, S03-01/02 climb through a blue hoist, a green
west pier, a blue span lift and a green east pier; TASK-554 built S03-03/04: a
blue shutter stops the leftward flight, a green crest hook lifts the player to
the right map edge, and a green exit hook pulls it into the exit drag zone onto
a green exit ledge. Other sections keep their own build status; both optional
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
bay has visible supporting legs and a raised end stop, providing an ordinary rest before the staggered transfer. All silhouettes use the actual solid collision
polygons and existing gray solid semantics; there are no hazards or finish trigger.
Short releases return physically to the dock, with the broad mountain catch floor
below. The next overhead beam is visible from both the entrance and exit.

`tools/test_grapple_over_sections.py` records trusted browser inputs and every
physics tick for the connected S01-01/02 route. It measures the nominal release,
+/-3 tick releases, +/-0.02R aim offsets, and two miss/recovery cases against the
unchanged authored world. Evidence, including screenshots and source hashes, is
written beneath `GRAPPLE_OVER_EVIDENCE_DIR` (default `artifacts/TASK-465`).


## Foundations completion (TASK-466)

The staggered beams lead up and back across the broken yard. A side balcony
catches a short fall; its lower anchor reconnects to the exit crane and a broad
rest ledge. The final anchor leads to an ordinary solid departure ledge at
Y=-1620. This is the authored connector to the next band; S02 remains planned,
and reaching this ledge does not complete the mountain or trigger a checkpoint.
The loading bay end stop remains a useful brake, but its temporary-exit metadata
has been removed. No placeholder geometry or shortcut is added in Foundations.
All new terrain uses the existing solid gray surface and deterministic polygons.

`Task466Tests` records a continuous entrance-to-exit mouse route, including
staggered acquisition and a deliberate local miss followed by lower-anchor
recovery, plus trusted touch acquisition and lift from the recovery balcony. The overview is an annotated map of the actual runtime collision
vertices. All evidence honors `GRAPPLE_OVER_EVIDENCE_DIR`.
