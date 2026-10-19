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
a green exit ledge. S04 is layout v3 too (TASK-556): from that ledge, S04-01/02
travel left through a blue hoist pulled along the ledge, a flat green reflector
plate, a blue lift caught in flight and an angled green deflector; TASK-515
built S04-03/04 in the open upper-left of the map: at the top of the climb a
green crest hook and a green baffle send the player back to the left map edge,
and a green exit hook swings it into the exit drag zone onto a green exit
ledge. TASK-516 lowered both S04 hooks out from under the HUD text (they are
pulled at about 33 degrees from the left map edge). S05 is layout v3 too
(TASK-517) at the 1620 range: from the S04 exit ledge, S05-01/02 travel right
through a blue hoist, a green canopy that turns the rise into a drop, an angled
green deflector that throws the player under the legacy S08 spill deck, a blue
lift caught in flight and a green baffle. TASK-518 completed S05: S05-03 catches a
green pull hook below the baffle foot while flying west and swings west and back
east under the catch deck; S05-04 swings from a green exit hook up-right past the
legacy Liftworks exit and releases into an exit drag zone, where a green exit
canopy turns the rise into a drop onto the green exit ledge against the right map
edge. S06 is layout v3 too (TASK-520) at the 1620 range: from the S05 exit ledge,
S06-01/02 travel left through a blue carriage pulled out of the S05 exit drag zone,
a green skid that turns the dive into a rising flight under the S05 catch deck, a
blue lift caught in flight west of the S05 swing loop and a green canopy that
turns the swing release into a drop. TASK-521 completed S06: S06-03 catches a
green climb hook while sliding down the left map edge, skips over a bounce-only
green swing skid and is released into a straight rise; S06-04 pulls from a green
exit hook far east into an exit drag zone under the S04 exit ledge, where the
player settles on the green exit ledge. A missed exit hook falls back down the
rise onto a green drop ledge, from which the climb hook rejoins the route. S07 is
layout v3 too (TASK-523/524) at the 1620 range, travelling right: from the S06 exit ledge,
S07-01 pulls a blue trolley up-left, crawls out of the exit pocket's open west
side, swings west under the trolley and ricochets off a green west wall into a
long flight east between the S05 canopy and the S05 hoist; S07-02 catches a blue
carriage in that flight, swings up-right over the hoist and rebounds off a green
crown wall into a flight west along the top. A short trolley hold slides down the
left map edge onto the S04 catch basin; a missed carriage catch drops through a
crown drag zone onto a green crown ledge. S07-03 rides that flight onto the left
map edge and the green west wall, which bounces the player in place; from the top
of a bounce a green gable hook at the top of the band pulls it east into a flight
along the top. S07-04 catches the green exit ledge itself in that flight and dives
into an exit drag zone under the S05 hoist, where the player settles on the exit
ledge (the section exit). An early gable release sinks into a small drag zone that
kills the drift and drops straight down onto the green S06 drop ledge, from which
the S06 climb and exit hooks lead back to the S07 entrance; a missed exit-ledge
catch lands on the crown ledge. The v1 red rotor is removed (no S07 hazard), and
the S07 shortcut stays planned. The Summit Array (S08) opening is layout v3
(TASK-526; the v1 Summit Array geometry is deleted): travelling left from the S07
exit ledge, S08-01 pulls a blue mast trolley high up-left, timed so the rise out of
the exit drag zone passes the S05 hoist at its east turn; released early, the
player rebounds off a green roof onto the moving trolley's top and slides off west
into a glide. S08-02 catches a blue beacon trolley in that glide, swings west
under it, rebounds off a green west wall and rides the pull up-right into a flight
east under the roof. An early trolley release drops back through the S07 exit drag
zone onto the S07 exit ledge; a missed beacon catch glides into a drag zone onto a
green glide cap above the Crown gable hook. S08-03/04 and the summit finish stay
planned (the finish is inactive until they are rebuilt). Other sections keep their own build status; both optional shortcuts are
planned. The three built
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
