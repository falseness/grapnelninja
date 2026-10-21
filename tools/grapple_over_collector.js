/* Test-only bounded collector over production physics/input via METRICS.
 * Retain transitions/contact events and sparse route samples, never geometry per tick.
 * One encounter per call; no screenshots and no per-tick browser round trips.
 */
window.REDESIGN_COLLECTOR = {
 compact(result, setup, label) {
  let previous;
  const events = result.rows.filter((r, i, rows) => {
   const transition = !previous || r.attached !== previous.attached || r.throwed !== previous.throwed;
   previous = r;
   return transition || r.contacts.length || i % 15 === 0 || i === rows.length - 1;
  });
  return {label, setup, ticks:result.ticks, inputs:result.inputs, events,
   acquired:result.acquired, landed:result.landed, landingAir:result.landingAir,
   anchorTopContact:result.anchorTopContact,
   success:result.acquired && result.landed && result.landingAir >= 6 && !result.anchorTopContact,
   clearance:{kind:'initial vertical anchor underside clearance, not swept clearance',
    measured:setup.clearance, minimum:setup.diameter, passes:setup.clearance >= setup.diameter}};
 },
 collect(pattern, variants) {
  if (!Array.isArray(variants) || !variants.length || variants.length > 16)
   throw Error('Expected 1..16 variants for one encounter');
  if (!Number.isInteger(GRAPPLE_OVER_MOVEMENT.observationTicks) || GRAPPLE_OVER_MOVEMENT.observationTicks > 300)
   throw Error('Observation budget exceeds 300 ticks');
  for (const v of variants) {
   const release = pattern.release + (v.offset || 0);
   if (!Number.isInteger(release) || release < 0 || release > GRAPPLE_OVER_MOVEMENT.observationTicks || !Number.isFinite(v.aim || 0))
    throw Error('Invalid bounded release/aim');
  }
  return variants.map(v => {
   const setup = METRICS.setup(pattern);
   const result = METRICS.run(pattern, v.offset || 0, v.aim || 0, !!v.held);
   return {...this.compact(result, setup, v.label), variant:v};
  });
 }
};
