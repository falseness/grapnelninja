// Mountain design contract. Planned positions are schematic reservations, NOT
// collision terrain or verified routes. Built encounters use the fixed-world loader.
const MOUNTAIN_BRIEF = [
    {
        "name": "Foundations",
        "landmark": "broken loading yard",
        "mechanics": [
            "Acquire a visible anchor within range from broad solid ground",
            "Release onto a broad ledge without losing control",
            "Transfer between staggered anchors",
            "Recover from a small fall using a lower anchor"
        ],
        "recoveryIntent": "safe rest pad at entrance; short misses land on broad ground; no red hazards"
    },
    {
        "name": "Switchback Shaft",
        "landmark": "alternating industrial balconies",
        "mechanics": [
            "Alternate pulls across opposing shaft walls",
            "Brake using an opposing anchor before a ledge",
            "Control an overshoot through a lateral reversal",
            "Climb out through a recessed exit"
        ],
        "recoveryIntent": "wide lower balconies catch early misses; a visible side route reconnects to Foundations"
    },
    {
        "name": "Broken Viaduct",
        "landmark": "interrupted elevated bridge",
        "mechanics": [
            "Build speed under a departure beam",
            "Release across a gap beyond direct acquisition range",
            "Acquire a new anchor during flight",
            "Brake into a narrower landing"
        ],
        "recoveryIntent": "a lower broken bridge catches recoverable misses and reconnects to Switchback Shaft; add one optional faster high-risk launch shortcut"
    },
    {
        "name": "Deflector Works",
        "landmark": "angled green machinery",
        "mechanics": [
            "Read and use a flat green reflection",
            "Redirect momentum with an angled green surface",
            "Combine a bounce with a new grapple",
            "Complete a two-bounce transfer"
        ],
        "recoveryIntent": "teach each reflection over a catch basin before the exposed combination; lower stairs reconnect to the Viaduct"
    },
    {
        "name": "Cable Galleries",
        "landmark": "projecting beams and deep overhangs",
        "mechanics": [
            "Wrap the rope around a projecting corner",
            "Pull around an obstruction using the wrapped segment",
            "Release and reacquire beyond an overhang",
            "Traverse a recessed ceiling route"
        ],
        "recoveryIntent": "rests sit between overhangs; misses drop to Deflector Works through a visible lower shaft with reachable recovery anchors"
    },
    {
        "name": "Liftworks",
        "landmark": "moving counterweights",
        "mechanics": [
            "Acquire a moving blue target",
            "Remain attached through its travel and reversal",
            "Release at a useful phase toward a fixed landing",
            "Transfer between moving and fixed targets"
        ],
        "recoveryIntent": "introduce the first mover above a broad floor; later falls return to Cable Galleries via a static recovery route"
    },
    {
        "name": "Exposed Crown",
        "landmark": "open rooftop machinery",
        "mechanics": [
            "Time passage past a red moving knockback hazard",
            "Catch a safe anchor after displacement",
            "Cross an exposed launch above earlier terrain",
            "Recover and rejoin using a lower side route"
        ],
        "recoveryIntent": "hazards are visible before commitment and never kill; exposed misses may lose multiple sections; add the second optional skill shortcut with a normal route"
    },
    {
        "name": "Summit Array",
        "landmark": "distinct final beacon silhouette",
        "mechanics": [
            "Combine opposing-anchor braking and release",
            "Combine an angled bounce and airborne transfer",
            "Negotiate a moving-target overhang",
            "Make a controlled final landing inside the summit finish region"
        ],
        "recoveryIntent": "rests separate combinations; misses have explicit routes back through the Crown/Liftworks; no new mechanic or surprise hazard at the ending"
    }
]

const GRAPPLE_OVER_MOUNTAIN = (() => {
    // U is the frozen v1/v2 layout unit (the old 540 range); R is the grapnel range.
    const U = 540, R = 1080, bandHeight = 3 * U
    const sections = [], encounters = [], connectors = [], recoveries = [], shortcuts = []
    for (let i = 0; i < 8; i++) {
        const id = 'S' + String(i + 1).padStart(2, '0'), brief = MOUNTAIN_BRIEF[i]
        const bottom = -i * bandHeight, top = bottom - bandHeight
        const ids = brief.mechanics.map((_, j) => id + '-0' + (j + 1))
        sections.push({id, order:i + 1, name:brief.name, status:'planned',
            band:{left:0, right:6480, top, bottom}, encounters:ids,
            landmark:{id:id + '-landmark', name:brief.landmark, x:3240, y:bottom - 810},
            recoveryIntent:brief.recoveryIntent})
        ids.forEach((eid, j) => encounters.push({id:eid, section:id, status:'planned',
            mechanic:brief.mechanics[j], x:2160 + (j % 2) * 1620,
            y:bottom - 180 - j * 360, elements:[]}))
        connectors.push({id:id + '-entrance', from:i ? 'S' + String(i).padStart(2, '0') + '-04' : 'base',
            to:ids[0], status:'planned', intent:'Physical ascent; connector/recovery overlap across bands allowed'})
        for (let j = 0; j < 3; j++) connectors.push({id:id + '-route-' + (j+1),
            from:ids[j], to:ids[j+1], status:'planned', intent:'Normal route'})
        const destination = i === 0 ? 'base' : i === 6 ? 'S05-01' : 'S' + String(i).padStart(2, '0') + '-01'
        recoveries.push({id:id + '-fall', from:ids[3], to:destination, status:'planned',
            intent:brief.recoveryIntent, transport:'physical-fall'})
        if (i === 2 || i === 6) shortcuts.push({id:id + '-shortcut', from:ids[0], to:ids[3],
            status:'planned', optional:true, intent:i === 2 ? 'Faster high-risk launch' : 'Exposed skill shortcut'})
    }
    connectors.push({id:'summit-approach', from:'S08-04', to:'summit', status:'planned', intent:'Controlled final landing'})
    const rectangle = (id,x,y,w,h,grapplable) => ({id,x,y,role:'solid',grapplable,
        points:[{x:0,y:0},{x:w,y:0},{x:w,y:h},{x:0,y:h}]})
    const rest = (id,x,y,w) => ({id,x,y,role:'solid',grapplable:true,
        points:[{x:0,y:0},{x:w-40,y:0},{x:w-40,y:-60},{x:w,y:-60},{x:w,y:55},{x:0,y:55}]});
    // Rest pads with low end stops (layout v2 sections).
    const lowRest = (id,x,y,w,lip=20,left=false) => ({id,x,y,role:'solid',grapplable:true,
        points:left ? [{x:0,y:-lip},{x:40,y:-lip},{x:40,y:0},{x:w,y:0},{x:w,y:55},{x:0,y:55}]
            : [{x:0,y:0},{x:w-40,y:0},{x:w-40,y:-lip},{x:w,y:-lip},{x:w,y:55},{x:0,y:55}]})
    // Green bounce hook bar; the rope catches its underside.
    const hook = (id,x,y) => ({...rectangle(id,x,y,120,30,true),role:'bounce'})
    // Foundations v3 (layout v3, TASK-547): no gray pads. Green bouncers and blue
    // movers at the doubled 1080-range distances, travelling right from the base spawn.
    // S01-01: from the green entry pad, pull the blue hoist and release onto the green
    // yard bouncer. S01-02: off the yard rebound, pull the blue lift and release into
    // the green deflector wall. S01-03 (TASK-548): catch the green gantry hook on the
    // up-left rebound and swing right. S01-04: catch the green crown hook in flight and
    // release down-right into the exit drag zone, settling on the green exit pad.
    const bouncer = (id,x,y,w,h) => ({...rectangle(id,x,y,w,h,true),role:'bounce'})
    const yard = [
        bouncer('S01-entry-pad',2060,18,200,40),
        rectangle('S01-hoist',2640,-820,120,30,true),
        bouncer('S01-yard-pad',3900,-880,300,40),
        rectangle('S01-lift',4440,-1760,120,30,true),
        bouncer('S01-deflector',4900,-2100,30,750),
        bouncer('S01-gantry-hook',5190,-3010,120,30),
        bouncer('S01-crown-hook',5890,-3150,120,30),
        bouncer('S01-exit-pad',6040,-2700,400,40),
        // Green floor bouncers on the base catch every declared S01 fall line.
        bouncer('S01-floor',2520,80,3960,40),
        // Kept (converted to green) from the v2 Switchback S02-01 start; no v3 route uses it.
        bouncer('S01-exit',4060,-1620,200,55),
        // TASK-491: the base left of the entry pad (x 0..2060, on mountain-catch) had no anchor in reach, so a
        // fall that came to rest there (e.g. down the left map edge) forced a restart. This green recovery hook
        // is within 1080 of the whole strip up to the entry pad; a pull and release lands on the green floor
        // bouncers, whose yard-pad rejoin is the declared S01 recovery. It sits left of every S01 route rope.
        bouncer('S01-west-hook',700,-560,120,30)
    ];
    // Misses fall to the green floor bouncers through this pass-through drag zone, which
    // damps horizontal and vertical speed (420 tall so the first rebound stays well under
    // half the drop); it spans only the declared S01 fall points and starts right of the
    // S01-01 hoist pull. The exit drag zone holds the S01 exit pad; the S01-04 short
    // line (off the crown hook along the right wall) falls through it. Drag zones are not
    // colliders, so they go last and the collider order still matches the manifest.
    const yardDrag = {id:'S01-yard-drag',x:2520,y:-300,role:'drag',grapplable:false,
        points:[{x:0,y:0},{x:3960,y:0},{x:3960,y:420},{x:0,y:420}]};
    const exitDrag = {id:'S01-exit-drag',x:5960,y:-3100,role:'drag',grapplable:false,
        points:[{x:0,y:0},{x:520,y:0},{x:520,y:440},{x:0,y:440}]};
    // TASK-531: an S01-03 overpull (the gantry hook caught early at its near corner and held) flings the
    // player up the S02 shaft past the canopy onto the S02-04 launch, or near enough to pull onto the S02 exit
    // ledge. This drag zone, left of the canopy, covers that whole rise up to below the gallery hook, so the
    // fling loses its horizontal speed and any pull from inside it stays slow; it is clear of every nominal
    // S01/S02 flight (>= 132) and above the S02-03-short east-wall bank (apex ~-4065).
    const overpullDrag = {id:'S01-overpull-drag',x:5380,y:-4650,role:'drag',grapplable:false,
        points:[{x:0,y:0},{x:260,y:0},{x:260,y:500},{x:0,y:500}]};
    const yardMovers = [
        {id:'S01-hoist-travel',element:'S01-hoist',axis:'x',min:2640,max:2760,periodMs:4000,phase:0,velocity:60},
        {id:'S01-lift-travel',element:'S01-lift',axis:'y',min:-1760,max:-1680,periodMs:4000,phase:0,velocity:40}];
    Object.assign(sections[0], {status:'built', designVersion:3, landmark:{id:'S01-landmark',
        name:'broken loading yard',x:3460,y:-1100},
        band:{...sections[0].band, top:-3240},
        // Rope-to-anchor reach from the launch point at the press to the acquisition point.
        gaps:[{id:'S01-01-hoist',from:{x:2160,y:3.4},to:{x:2698.6,y:-790}},
            // Caught off the yard rebound: from the player at the press to the lift.
            {id:'S01-02-lift',from:{x:4010.8,y:-893},to:{x:4490.7,y:-1717}},
            // Caught on the up-left deflector rebound, then in flight off the gantry swing.
            {id:'S01-03-gantry',from:{x:4466.4,y:-2446.4},to:{x:5231.2,y:-2980}},
            {id:'S01-04-crown',from:{x:5035.9,y:-3556},to:{x:5911.4,y:-3150}}],
        // Declared miss points: a short or mistimed release falls straight down
        // through the yard drag zone onto the green floor bouncers.
        fallPoints:[{id:'S01-01-short',encounter:'S01-01',x:3520,y:-545},
            {id:'S01-02-short',encounter:'S01-02',x:4300,y:-900},
            {id:'S01-02-overshoot',encounter:'S01-02',x:5200,y:-1600},
            {id:'S01-03-early',encounter:'S01-03',x:5000,y:-2700},
            {id:'S01-04-short',encounter:'S01-04',x:6460,y:-3300},
            {id:'S01-03-overpull',encounter:'S01-03',x:5500,y:-4250}]});
    Object.assign(encounters[0], {status:'built',x:2160,y:0,
        elements:['S01-entry-pad','S01-hoist','S01-yard-pad'],
        start:{x:2160,y:0},target:{x:2700,y:-790},
        exit:{left:3990,right:4060,top:-910,bottom:-880},
        action:'Pull the blue hoist from the green entry pad, release and bounce off the green yard pad'});
    Object.assign(encounters[1], {status:'built',x:4011,y:-893,
        elements:['S01-yard-pad','S01-lift','S01-deflector'],
        start:{from:'S01-01',x:4010.8,y:-893},target:{x:4500,y:-1730},
        exit:{left:4600,right:4800,top:-2200,bottom:-1950},
        action:'Off the yard rebound, pull the blue lift, release into the green deflector wall and rebound'});
    Object.assign(encounters[2], {status:'built',x:4466,y:-2446,
        elements:['S01-deflector','S01-gantry-hook'],
        start:{from:'S01-02',x:4466.4,y:-2446.4},target:{x:5250,y:-2990},
        exit:{left:4900,right:5000,top:-3540,bottom:-3480},
        action:'On the up-left deflector rebound, catch the green gantry hook, swing right over it and release'});
    // The node is the crown hook; the flight apex (~-3640) overlaps the band above.
    Object.assign(encounters[3], {status:'built',x:5950,y:-3150,
        elements:['S01-crown-hook','S01-exit-pad','S01-exit-drag'],
        start:{from:'S01-03',x:5035.9,y:-3556},target:{x:5950,y:-3130},
        exit:{left:6040,right:6440,top:-2730,bottom:-2700},
        action:'Catch the green crown hook in flight, swing down-right and release into the exit drag zone to settle on the green exit pad'});
    for (let i=0;i<4;i++) connectors[i].status='built';
    Object.assign(recoveries[0], {status:'built',elements:['S01-yard-drag','S01-exit-drag','S01-floor','S01-west-hook'],
        rejoin:'S01-02',sideRoute:'Every declared S01 miss falls through a drag zone onto the green floor bouncers and settles; a green yard-pad pull and a blue lift pull rejoin the route through the deflector. A rest on the base left of the entry pad pulls the green west hook onto the floor bouncers (TASK-491)'});
    // Switchback Shaft v3 (layout v3, TASK-550): no gray pads. Travelling left from the
    // green S01 exit pad at the doubled 1080-range distances, between opposing shaft walls.
    // S01's exit drag zone kills horizontal speed, so the hoist pull is near-vertical.
    // S02-01: from the S01 exit pad, pull the blue hoist up out of the exit drag zone and
    // release up-left into the green canopy, which turns the climb into a down-left drop.
    // S02-02: on that drop, catch the blue lift, swing left under it and release into the
    // green west bulkhead, which rebounds the player right. S02-03 (TASK-551): off that
    // rebound, catch the green gallery hook and ride the pull up-right into the green east
    // wall, whose rebound reverses the climb left over the canopy. S02-04: catch the green
    // crown hook above, climb out up-right, glance off the crown-hook top and the east wall and drop into
    // the exit drag zone onto the green exit ledge, where the player settles. The canopy,
    // hoist, bulkhead and east wall stay clear of the S01-03/04 flight (apex ~-3640); the
    // S02-03/04 elements stay right of the v2 Viaduct/Deflector geometry (x <= 4750), so
    // every declared S02 miss falls onto S01.
    const shaft = [
        rectangle('S02-hoist',6040,-3710,120,30,true),
        bouncer('S02-canopy',5700,-4320,420,30),
        rectangle('S02-lift',4925,-4705,120,30,true),
        bouncer('S02-bulkhead',4840,-4300,30,500),
        bouncer('S02-gallery-hook',5480,-4720,120,30),
        bouncer('S02-east-wall',6330,-5800,30,2100),
        bouncer('S02-crown-hook',6000,-5630,120,30),
        bouncer('S02-exit-ledge',5640,-4860,520,40),
        // v2 pads kept (converted to green); they were the v2 Broken Viaduct S03-01 start pad and
        // S03-02 fall-line landing. Since the v3 Viaduct (TASK-553) no route uses them.
        bouncer('S02-landing',2987,-2100,200,40),
        bouncer('S02-exit-pad',2000,-2680,200,40)
    ];
    // The exit drag zone holds the exit ledge; the S02-04 overshoot line (a crown release
    // that misses the crown-hook top and carries past the ledge) falls through it and the S01 exit drag zone onto the S01 exit pad. Every
    // other declared S02 miss drops into an S01 drag zone.
    const shaftDrags = [{id:'S02-exit-drag',x:5620,y:-5260,role:'drag',grapplable:false,
        points:[{x:0,y:0},{x:710,y:0},{x:710,y:440},{x:0,y:440}]}];
    const shaftMovers = [
        {id:'S02-hoist-travel',element:'S02-hoist',axis:'y',min:-3710,max:-3630,periodMs:4000,phase:0,velocity:40},
        {id:'S02-lift-travel',element:'S02-lift',axis:'y',min:-4705,max:-4625,periodMs:4000,phase:0,velocity:40}];
    Object.assign(sections[1], {status:'built', designVersion:3, landmark:{id:'S02-landmark',
        name:'alternating industrial balconies',x:5450,y:-4000},
        band:{...sections[1].band, top:-4860},
        // Rope-to-anchor reach from the player at the press to the acquisition point.
        gaps:[{id:'S02-01-hoist',from:{x:6373.4,y:-2711.1},to:{x:6109.6,y:-3637}},
            // Caught in flight on the drop off the canopy.
            {id:'S02-02-lift',from:{x:5863.4,y:-4163.6},to:{x:5029.3,y:-4642}},
            // Caught on the bulkhead rebound, then in flight on the east-wall reversal.
            {id:'S02-03-gallery',from:{x:5183.6,y:-3796.3},to:{x:5533,y:-4690}},
            {id:'S02-04-crown',from:{x:5549.8,y:-4810.7},to:{x:6050.2,y:-5600}}],
        // Declared miss points: a short hoist pull settles back on the S01 exit pad; a
        // missed lift catch drops off the canopy; the bulkhead rebound with no further
        // catch crosses to the right wall and drops along it; a short gallery pull banks off
        // the east wall onto the S01 exit pad; an early crown release misses the crown-hook top and
        // carries past the exit ledge. Each falls through a drag zone onto a green S01 bouncer.
        fallPoints:[{id:'S02-01-short',encounter:'S02-01',x:6355,y:-3000},
            {id:'S02-02-missed',encounter:'S02-02',x:5650,y:-3800},
            {id:'S02-02-rebound',encounter:'S02-02',x:6460,y:-3150},
            {id:'S02-03-short',encounter:'S02-03',x:6190,y:-3650},
            {id:'S02-04-overshoot',encounter:'S02-04',x:6230,y:-5100}]});
    Object.assign(encounters[4], {status:'built',x:6373,y:-2711,
        elements:['S01-exit-pad','S02-hoist','S02-canopy'],
        start:{x:6373.4,y:-2711.1,from:'S01-04'},target:{x:6100,y:-3670},
        exit:{left:5800,right:5950,top:-4250,bottom:-4100},
        action:'Pull the blue hoist up out of the Foundations exit drag zone, release up-left and bounce off the green canopy'});
    Object.assign(encounters[5], {status:'built',x:5863,y:-4164,
        elements:['S02-canopy','S02-lift','S02-bulkhead'],
        start:{from:'S02-01',x:5863.4,y:-4163.6},target:{x:4985,y:-4665},
        exit:{left:4950,right:5150,top:-3880,bottom:-3760},
        action:'On the drop off the canopy, catch the blue lift, swing left and rebound off the green west bulkhead'});
    Object.assign(encounters[6], {status:'built',x:4977,y:-3846,
        elements:['S02-bulkhead','S02-gallery-hook','S02-east-wall'],
        start:{from:'S02-02',x:4977.1,y:-3845.8},target:{x:5540,y:-4705},
        exit:{left:5500,right:5700,top:-4860,bottom:-4760},
        action:'Off the bulkhead rebound, catch the green gallery hook, ride the pull up-right into the green east wall and reverse left over the canopy'});
    // The node is the S02-04 launch; the climb-out and the exit ledge overlap the band above.
    Object.assign(encounters[7], {status:'built',x:5550,y:-4811,
        elements:['S02-crown-hook','S02-exit-ledge','S02-exit-drag'],
        start:{from:'S02-03',x:5549.8,y:-4810.7},target:{x:6060,y:-5615},
        exit:{left:5640,right:6160,top:-4890,bottom:-4860},
        action:'Catch the green crown hook on the reversal, climb out up-right, glance off the crown-hook top and the east wall and drop into the exit drag zone to settle on the green exit ledge'});
    Object.assign(connectors[4], {status:'built',intent:'Physical ascent: the S02-01 hoist pull starts on the v3 Foundations exit pad'});
    for (let i=5;i<8;i++) connectors[i].status='built';
    Object.assign(recoveries[1], {status:'built',elements:['S02-exit-drag','S01-exit-drag','S01-exit-pad','S01-yard-drag','S01-floor'],
        rejoin:'S02-02',sideRoute:'Every declared S02 miss falls through a drag zone onto a green S01 bouncer and settles; from the S01 exit pad a blue hoist pull, the east-wall and canopy-underside bounces and a swing from the green canopy rejoin the route at the bulkhead rebound'});
    // Broken Viaduct v3 (layout v3, TASK-553/554): no gray pads. From the green S02 exit ledge
    // (inside S02-exit-drag) at the doubled 1080-range distances; the right map edge is only
    // ~500 east of the ledge, so the section climbs in a west-east zigzag and ends east of
    // its entry. S03-01: pull the blue hoist up-left out of the S02 exit drag zone (the drag
    // kills horizontal speed, so the pull is steep) and release into the green west pier,
    // which rebounds the climb right. S03-02: on that rightward flight, catch the blue span
    // lift up-right, swing across the broken span and release into the green east pier,
    // which rebounds the player left. S03-03 (TASK-554): the leftward flight slams into the
    // blue shutter under the legacy gallery staircase, which kills its speed; pull the green
    // crest hook up-right past the lift, release into the right map edge (which stops the
    // sideways speed) and rise along it to an apex under the legacy Cable Galleries exit.
    // S03-04: at that apex, pull the green exit hook west under the galleries exit into the
    // exit drag zone and settle on the green exit ledge laid over the recessed ceiling top.
    // TASK-555: the crest hook sits down-right of the galleries exit, over the east pier, so at the
    // S03-03 press it is drawn below the touch pause button (top-right HUD corner); the pier top is
    // at -7000 so the up-right pull flies over it into the map edge.
    // The hoist stays above and west of the S02-04 climb-out (apex ~-5656); the piers, lift
    // and shutter are above the S02 shaft, and the shutter stays above the S03-02 lift rope.
    const viaduct = [
        rectangle('S03-hoist',5460,-5827,120,30,true),
        bouncer('S03-west-pier',5150,-6600,30,900),
        rectangle('S03-lift',6140,-6960,120,30,true),
        bouncer('S03-east-pier',6420,-7000,30,400),
        rectangle('S03-shutter',5715,-6960,30,230,true),
        bouncer('S03-crest-hook',6330,-7500,120,25),
        bouncer('S03-exit-hook',5400,-7975,120,25),
        bouncer('S03-exit-ledge',5800,-7770,390,25),
        // Lower broken bridge: green catch in the slot between the S02 east wall and the
        // right map edge, where the missed-lift flight drops after glancing off the wall top.
        bouncer('S03-lower-bridge',6360,-5400,120,40),
        // v2 Viaduct exit pad kept (converted to green); the v2 Deflector Works S04-01 started on it
        // until TASK-556. No v3 route uses it.
        bouncer('S03-exit-pad',4600,-3830,150,55)
    ];
    // The fall drag zone holds the lower bridge; the S03-02 missed line and an S03-04 miss
    // (no exit-hook catch at the apex) drop through it along the right map edge. The exit
    // drag zone holds the exit ledge; an S03-04 overshoot (holding the exit hook too long)
    // drifts inside it and settles on the ledge. A short S03-01 pull or an early S03-03
    // release falls back through S02-exit-drag onto the green S02 exit ledge.
    const viaductDrags = [{id:'S03-fall-drag',x:6360,y:-5800,role:'drag',grapplable:false,
        points:[{x:0,y:0},{x:120,y:0},{x:120,y:440},{x:0,y:440}]},
        {id:'S03-exit-drag',x:5790,y:-8095,role:'drag',grapplable:false,
        points:[{x:0,y:0},{x:410,y:0},{x:410,y:325},{x:0,y:325}]}];
    const viaductMovers = [
        {id:'S03-hoist-travel',element:'S03-hoist',axis:'y',min:-5827,max:-5747,periodMs:4000,phase:0,velocity:40},
        {id:'S03-lift-travel',element:'S03-lift',axis:'x',min:6140,max:6260,periodMs:4000,phase:0,velocity:60},
        {id:'S03-shutter-travel',element:'S03-shutter',axis:'x',min:5715,max:5745,periodMs:4000,phase:0,velocity:15}];
    Object.assign(sections[2], {status:'built', designVersion:3, landmark:{id:'S03-landmark',
        name:'interrupted elevated bridge',x:5800,y:-6300},
        band:{...sections[2].band, top:-6480},
        // Rope-to-anchor reach from the player at the press to the acquisition point.
        gaps:[{id:'S03-01-hoist',from:{x:5955.4,y:-4870.9},to:{x:5532,y:-5726.7}},
            // Caught in flight on the rightward rebound off the west pier.
            {id:'S03-02-lift',from:{x:5388.9,y:-6501.3},to:{x:6224.5,y:-6955.3}},
            // From rest against the shutter; then from rest at the apex on the map edge.
            {id:'S03-03-crest',from:{x:5767.1,y:-6771.4},to:{x:6412.8,y:-7475}},
            {id:'S03-04-exit',from:{x:6469.2,y:-7939.9},to:{x:5520,y:-7952.2}}],
        // Declared miss points: a short hoist pull drops back onto the S02 exit ledge through
        // S02-exit-drag; a missed lift catch glances off the S02 east-wall top and drops along
        // the right map edge through S03-fall-drag onto the green lower bridge; an early
        // crest-hook release drops off the shutter through S02-exit-drag onto the S02 exit
        // ledge; a missed exit-hook catch falls back down the right map edge through
        // S03-fall-drag onto the lower bridge; an exit-hook overshoot stays in the exit drag.
        fallPoints:[{id:'S03-01-short',encounter:'S03-01',x:5910,y:-5400},
            {id:'S03-02-missed',encounter:'S03-02',x:6460,y:-6000},
            {id:'S03-03-early',encounter:'S03-03',x:5780,y:-6760},
            {id:'S03-04-missed',encounter:'S03-04',x:6469,y:-7800},
            {id:'S03-04-overshoot',encounter:'S03-04',x:6000,y:-8050}]});
    Object.assign(encounters[8], {status:'built',x:5955,y:-4871,
        elements:['S02-exit-ledge','S03-hoist','S03-west-pier'],
        start:{x:5955.4,y:-4870.9,from:'S02-04'},target:{x:5520,y:-5750},
        exit:{left:5240,right:5360,top:-6520,bottom:-6420},
        action:'Pull the blue hoist up-left out of the Switchback exit drag zone, release and rebound right off the green west pier'});
    // The node is on the band top; the S03-02 launch is just above it.
    Object.assign(encounters[9], {status:'built',x:5389,y:-6480,
        elements:['S03-west-pier','S03-lift','S03-east-pier'],
        start:{from:'S03-01',x:5388.9,y:-6501.3},target:{x:6200,y:-6940},
        exit:{left:6150,right:6400,top:-6820,bottom:-6720},
        action:'On the rebound off the west pier, catch the blue span lift, swing across the broken span and rebound left off the green east pier'});
    // S03-03/04 nodes sit on the band top; the climb runs above it (the S04 band overlaps).
    Object.assign(encounters[10], {status:'built',x:5767,y:-6480,
        elements:['S03-east-pier','S03-shutter','S03-crest-hook'],
        start:{from:'S03-02',x:5767.1,y:-6771.4},target:{x:6430,y:-7488},
        exit:{left:6440,right:6480,top:-7990,bottom:-7900},
        action:'Slam into the blue shutter off the east-pier rebound, pull the green crest hook up-right past the lift, release into the right map edge and rise along it'});
    Object.assign(encounters[11], {status:'built',x:6469,y:-6480,
        elements:['S03-exit-hook','S03-exit-ledge','S03-exit-drag'],
        start:{from:'S03-03',x:6469.2,y:-7939.9},target:{x:5460,y:-7950},
        exit:{left:5960,right:6190,top:-7800,bottom:-7770},
        action:'At the apex on the map edge, pull the green exit hook west under the galleries exit into the exit drag zone and settle on the green exit ledge'});
    Object.assign(connectors[8], {status:'built',intent:'Physical ascent: the S03-01 hoist pull starts on the v3 Switchback exit ledge'});
    for (let i=9;i<12;i++) connectors[i].status='built';
    Object.assign(recoveries[2], {status:'built',elements:['S03-fall-drag','S03-lower-bridge','S02-exit-drag','S02-exit-ledge'],
        rejoin:'S03-01',sideRoute:'Every declared S03 miss falls through a drag zone onto the green S02 exit ledge or the green lower bridge and settles; from the S02 exit ledge a blue hoist pull rejoins the route at S03-01'});
    // TASK-492: the optional shortcut found by the bounded bypass audit (shortcuts.json): a long hoist launch past the lift.
    Object.assign(shortcuts[0], {status:'built', elements:['S03-hoist','S03-shutter','S03-exit-hook','S03-exit-ledge'],
        intent:'Optional faster high-risk launch from S03-01 to S03-04',
        route:'Hold the blue S03 hoist about twice as long as the normal pull: the launch carries past the lift line; pull the blue shutter on the way up, rise along the right map edge and pull the green exit hook at the apex onto the exit ledge (skips the S03-02 lift and the S03-03 crest hook)',
        risk:'A launch held a little short or long misses the shutter line and falls back to the S03 start or into the S02 band'});
    // Deflector Works v3 (layout v3, TASK-556): no gray pads. Travelling left from the green S03
    // exit ledge (inside S03-exit-drag) at the doubled 1080-range distances, across the open west
    // half of the map above the legacy Cable Galleries. The legacy S06 loading floor caps the S03
    // exit drag zone, so the first pull is near-horizontal. S04-01: pull the blue hoist west along
    // the exit ledge out of the exit drag zone, release the swing and reflect off the flat green
    // reflector plate. S04-02: on the rebound, catch the blue lift in flight, swing up-left under it
    // and release into the angled green deflector, which turns the leftward flight into a steep
    // climb along the left map edge. S04-03 (TASK-515): at the top of that climb on the left map
    // edge, pull the green crest hook up-right, release into the green baffle, which turns the flight
    // back left into the map edge (it stops the sideways speed), and rise along it to an apex.
    // S04-04: at that apex, pull the green exit hook up-right, release and fall east into the exit
    // drag zone onto the green exit ledge. The route stays in the open upper-left of the map, clear
    // of the legacy S06-S08 geometry. A missed lift, crest-hook or exit-hook catch drops down the left
    // map edge through the fall drag zone onto the green catch basin; a short hoist hold stays in the
    // S03 exit drag zone, and a hoist held too long swings back east into it, settling on the S03 exit
    // ledge; an exit hook held too long still drops into the S04 exit drag zone.
    const deflectors = [
        rectangle('S04-hoist',5154,-7900,120,30,true),
        bouncer('S04-reflector',3200,-7450,600,30),
        rectangle('S04-lift',2240,-8030,120,30,true),
        // Angled green face from (900,-8550) down-right to (1200,-8250); its normal points up-right.
        {id:'S04-deflector',x:900,y:-8550,role:'bounce',grapplable:true,points:[{x:0,y:0},{x:300,y:300},{x:0,y:300}]},
        bouncer('S04-catch-basin',0,-6000,300,40),
        // S04-03/04: crest hook up-right of the climb apex, the baffle wall east of it, the exit hook
        // up-right of the second apex and the exit ledge east of the baffle top. TASK-516: both hooks
        // sit at most ~530 above the press pose and right of world x 800, so at the press (the camera
        // keeps the climbing player at 0.4 of the view height on the left map edge) they are drawn
        // below and right of the HUD text on both viewports (on touch the 12 px HUD font covers the
        // top-left 170x79 px). The narrow crest hook sits between the release flight (under it) and
        // the baffle rebound (over it); the baffle moved east so that gap is wide.
        bouncer('S04-crest-hook',800,-10915,60,25),
        bouncer('S04-baffle',1100,-11150,30,400),
        bouncer('S04-exit-hook',800,-12015,60,25),
        bouncer('S04-exit-ledge',1350,-11650,390,25),
        // v1 Cable Galleries recovery step and entrance deck (v1 S05-01 start), converted to green;
        // no v3 S04 route uses them.
        {...rest('S04-upper-step',4700,-6050,200),role:'bounce'},
        {id:'S04-exit',x:4460,y:-6480,role:'bounce',grapplable:true,points:[{x:0,y:-180},{x:40,y:-180},{x:40,y:0},{x:160,y:0},{x:160,y:-30},{x:200,y:-30},{x:200,y:55},{x:0,y:55}]},
        // TASK-491: the catch basin had no anchor in reach but itself (a dead end at 1080 and 1620 for every
        // miss that settles there). Pulling this green recovery hook up-right off the basin and releasing is a
        // deliberate fall east of the basin to the broad base. Right of the S04-fall-drag column (x <= 300).
        bouncer('S04-basin-hook',590,-6630,120,30)
    ];
    deflectors.find(e=>e.id==='S04-upper-step').points.forEach(p=>{if(p.y===-60)p.y=-30;});
    deflectors.find(e=>e.id==='S04-upper-step').points.splice(0,1,{x:0,y:-180},{x:40,y:-180},{x:40,y:0});
    // The fall drag zone holds the catch basin against the left map edge; the S04-02, S04-03 and
    // S04-04 missed lines drop through it. The exit drag zone holds the exit ledge; an S04-04
    // overshoot (exit hook held too long) falls inside it and settles on the ledge.
    const worksDrags = [{id:'S04-fall-drag',x:0,y:-6440,role:'drag',grapplable:false,
        points:[{x:0,y:0},{x:300,y:0},{x:300,y:440},{x:0,y:440}]},
        {id:'S04-exit-drag',x:1340,y:-11975,role:'drag',grapplable:false,
        points:[{x:0,y:0},{x:410,y:0},{x:410,y:325},{x:0,y:325}]}];
    const worksMovers = [
        {id:'S04-hoist-travel',element:'S04-hoist',axis:'y',min:-7900,max:-7820,periodMs:4000,phase:0,velocity:40},
        {id:'S04-lift-travel',element:'S04-lift',axis:'x',min:2240,max:2360,periodMs:4000,phase:0,velocity:60}];
    Object.assign(sections[3], {status:'built', designVersion:3, landmark:{id:'S04-landmark',
        name:'angled green machinery',x:2400,y:-7700},
        band:{...sections[3].band, top:-8100},
        // Rope-to-anchor reach from the player at the press to the acquisition point.
        gaps:[{id:'S04-01-hoist',from:{x:6127,y:-7781.1},to:{x:5174.1,y:-7866.3}},
            // Caught in flight on the rebound off the reflector plate.
            {id:'S04-02-lift',from:{x:3194.9,y:-7569.5},to:{x:2352.5,y:-8000}},
            // From the climb apex on the left map edge; then from the second apex on it.
            {id:'S04-03-crest',from:{x:10.8,y:-10385.5},to:{x:800,y:-10893}},
            {id:'S04-04-exit',from:{x:10.8,y:-11507.2},to:{x:800,y:-11992.9}}],
        // Declared miss points: a short hoist hold leaves the player in S03-exit-drag, where it
        // settles on the green S03 exit ledge; a missed lift catch carries the reflector rebound into
        // the left map edge and drops along it through S04-fall-drag onto the green catch basin; a
        // hoist held too long swings back east and drops into S03-exit-drag onto the S03 exit ledge;
        // a missed crest-hook or exit-hook catch drops from its apex down the left map edge through
        // S04-fall-drag onto the catch basin; an exit hook held too long stays in S04-exit-drag.
        fallPoints:[{id:'S04-01-short',encounter:'S04-01',x:5900,y:-7850},
            {id:'S04-02-missed',encounter:'S04-02',x:30,y:-6900},
            {id:'S04-01-late',encounter:'S04-01',x:5830,y:-7880},
            {id:'S04-03-missed',encounter:'S04-03',x:30,y:-10350},
            {id:'S04-04-missed',encounter:'S04-04',x:30,y:-11300},
            {id:'S04-04-overshoot',encounter:'S04-04',x:1400,y:-11900}]});
    // Encounter nodes sit inside the band (y >= -8100) and below the S05-04 node (S05-fall rejoins S04-01).
    Object.assign(encounters[12], {status:'built',x:6127,y:-7700,
        elements:['S03-exit-ledge','S04-hoist','S04-reflector'],
        start:{x:6127,y:-7781.1,from:'S03-04'},target:{x:5234,y:-7860},
        exit:{left:3200,right:3400,top:-7600,bottom:-7480},
        action:'Pull the blue hoist west along the Viaduct exit ledge out of the exit drag zone, release and reflect off the flat green reflector plate'});
    Object.assign(encounters[13], {status:'built',x:3195,y:-7700,
        elements:['S04-reflector','S04-lift','S04-deflector'],
        start:{from:'S04-01',x:3194.9,y:-7569.5},target:{x:2350,y:-8000},
        exit:{left:780,right:920,top:-9100,bottom:-8950},
        action:'On the rebound off the reflector plate, catch the blue lift, swing up-left and redirect off the angled green deflector into a climb along the left map edge'});
    // S04-03/04 nodes sit on the band top; the climb runs above it (the S06-S08 bands overlap).
    Object.assign(encounters[14], {status:'built',x:11,y:-8100,
        elements:['S04-deflector','S04-crest-hook','S04-baffle'],
        start:{from:'S04-02',x:10.8,y:-10385.5},target:{x:820,y:-10902},
        exit:{left:0,right:30,top:-11600,bottom:-11380},
        action:'At the top of the climb on the left map edge, pull the green crest hook up-right, release into the green baffle and rebound back left into the map edge, rising along it'});
    Object.assign(encounters[15], {status:'built',x:11,y:-8100,
        elements:['S04-exit-hook','S04-exit-ledge','S04-exit-drag'],
        start:{from:'S04-03',x:10.8,y:-11507.2},target:{x:820,y:-12002},
        exit:{left:1350,right:1740,top:-11680,bottom:-11650},
        action:'At the apex on the left map edge, pull the green exit hook up-right, release over the baffle into the exit drag zone and settle on the green exit ledge'});
    Object.assign(connectors[12], {status:'built',intent:'Physical ascent: the S04-01 hoist pull starts on the v3 Viaduct exit ledge'});
    for (let i=13;i<16;i++) connectors[i].status='built';
    Object.assign(recoveries[3], {status:'built',elements:['S04-fall-drag','S04-catch-basin','S04-basin-hook','S04-exit-drag','S04-exit-ledge','S03-exit-drag','S03-exit-ledge'],
        rejoin:'S04-01',sideRoute:'Every declared S04 miss falls through a drag zone onto a green bouncer and settles: short or late hoist holds on the green S03 exit ledge, from which the S04-01 hoist pull rejoins the route; missed lift, crest-hook and exit-hook catches down the left map edge onto the green catch basin, from which a green basin-hook pull is a deliberate fall to the broad base (TASK-491); an exit-hook overshoot on the green S04 exit ledge'});
    // Cable Galleries v3 (layout v3, TASK-517/518): no gray pads. Travelling right from the green S04
    // exit ledge (inside S04-exit-drag) at the 1620-range distances (the range upgrade is already held:
    // the S03 route climbs through the S05 band), under the legacy S08 spill deck and left of the legacy
    // S07 rooftop. S05-01: pull the blue hoist up-right out of the exit drag zone, release under the
    // green gallery canopy (it turns the rise into a drop) and fall onto the angled green deflector,
    // which throws the flight right under the spill deck. S05-02: catch the blue lift in flight, swing
    // under it and release into the green gallery baffle, which rebounds the flight back west.
    // S05-03: catch the green pull hook east of the baffle foot while flying west; the long swing runs
    // west under the catch deck and back east, released on the upswing. S05-04: catch the green exit
    // hook from that flight, swing up-right past the legacy S06 exit and release into the exit drag
    // zone, where the green exit canopy turns the rise into a drop onto the green exit ledge.
    // A short hoist hold drops back into the S04 exit drag zone onto the S04 exit ledge; a missed lift
    // catch falls through the fall drag zone onto the green catch deck; a missed pull-hook catch flies
    // into the left map edge and drops through S04-fall-drag onto the green S04 catch basin; an early
    // exit-hook release still settles in the exit drag zone.
    const galleries = [
        rectangle('S05-hoist',2490,-12470,120,30,true),
        // The canopy sits right of the hoist rope (the rope passes under its right end at the release).
        bouncer('S05-canopy',1590,-12150,90,30),
        // Angled green face from (2190,-11190) down-right to (2790,-10590); its normal points up-right.
        {id:'S05-deflector',x:2190,y:-11190,role:'bounce',grapplable:true,points:[{x:0,y:0},{x:600,y:600},{x:0,y:600}]},
        rectangle('S05-lift',3800,-10870,120,30,true),
        bouncer('S05-baffle',4500,-10980,30,930),
        bouncer('S05-catch-deck',3800,-9500,600,40),
        // Under the baffle foot, left of the legacy S07 rest ledge: the rope passes below the baffle.
        bouncer('S05-pull-hook',5220,-9320,90,30),
        bouncer('S05-exit-hook',4950,-9100,60,25),
        // Exit pocket against the right map edge, above the legacy S06 transfer head; the exit-hook
        // swing stays left of it (x <= 6080).
        bouncer('S05-exit-canopy',6100,-10030,370,30),
        bouncer('S05-exit-ledge',6100,-9420,370,30),
        // Legacy v1 Cable Galleries pieces still named by the v1 Liftworks/Crown (the S06-01 start deck and
        // their recovery colliders), converted to green in place; no v3 S05 route uses them.
        {id:'S05-projecting-girder',x:4650,y:-6800,role:'bounce',grapplable:true,
            points:[{x:0,y:0},{x:200,y:0},{x:200,y:-20},{x:240,y:-20},{x:240,y:35},{x:80,y:35},{x:80,y:110},{x:0,y:110}]},
        {id:'S05-recessed-ceiling',x:5800,y:-7720,role:'bounce',grapplable:true,
            points:[{x:0,y:0},{x:230,y:0},{x:230,y:-25},{x:270,y:-25},{x:270,y:190},{x:210,y:190},{x:210,y:55},{x:65,y:55},{x:65,y:120},{x:0,y:120}]},
        {...rest('S05-exit',6200,-8070,240), role:'bounce', points:[{x:0,y:0},{x:200,y:0},{x:200,y:-20},{x:240,y:-20},{x:240,y:55},{x:0,y:55}]}
    ];
    // The fall drag zone holds the catch deck; only the S05-02 missed line drops through it. The exit
    // drag zone fills the exit pocket between the exit canopy and the exit ledge.
    const galleriesDrags = [{id:'S05-fall-drag',x:3800,y:-9900,role:'drag',grapplable:false,
        points:[{x:0,y:0},{x:600,y:0},{x:600,y:400},{x:0,y:400}]},
        {id:'S05-exit-drag',x:6100,y:-9990,role:'drag',grapplable:false,
        points:[{x:0,y:0},{x:380,y:0},{x:380,y:570},{x:0,y:570}]}];
    const galleriesMovers = [
        {id:'S05-hoist-travel',element:'S05-hoist',axis:'x',min:2490,max:2610,periodMs:4000,phase:0,velocity:60},
        {id:'S05-lift-travel',element:'S05-lift',axis:'x',min:3800,max:3920,periodMs:4000,phase:0,velocity:60}];
    Object.assign(sections[4], {status:'built', designVersion:3, landmark:{id:'S05-landmark',
        name:'projecting beams and deep overhangs',x:3000,y:-10900},
        band:{...sections[4].band, top:-9720},
        // TASK-529: the range upgrade is earned on entering S05, i.e. on landing on the S04 exit ledge (the
        // S05-01 start): the top of the S04-04 exit box, above the settled pose (y -11660.9). The v3 S03/S04
        // routes climb through the S05 band, so the band itself would grant 1620 inside S03.
        rangeUpgradeZone:{left:1350, right:1740, top:-11680, bottom:-11662},
        // Rope-to-anchor reach from the player at the press to the acquisition point (range 1620).
        gaps:[{id:'S05-01-hoist',from:{x:1387.9,y:-11660.9},to:{x:2566.6,y:-12469.7}},
            // Caught in flight just after the deflector bounce.
            {id:'S05-02-lift',from:{x:2511.7,y:-10905.2},to:{x:3904.5,y:-10853.5}},
            // Caught in flight after the baffle rebound; then from the swing release.
            {id:'S05-03-pull',from:{x:4078.6,y:-10145.9},to:{x:5248,y:-9320}},
            {id:'S05-04-exit',from:{x:3965.2,y:-8039.9},to:{x:4965.2,y:-9075}}],
        // Declared miss points: a short hoist hold drops from its apex back into S04-exit-drag onto the
        // green S04 exit ledge; a missed lift catch carries the deflector throw down through S05-fall-drag
        // onto the green catch deck; a missed pull-hook catch carries the baffle rebound into the left map
        // edge and drops along it through S04-fall-drag onto the green S04 catch basin; an early exit-hook
        // release drops from the exit canopy through S05-exit-drag onto the green exit ledge.
        fallPoints:[{id:'S05-01-short',encounter:'S05-01',x:1560,y:-12070},
            {id:'S05-02-missed',encounter:'S05-02',x:3850,y:-10000},
            {id:'S05-03-missed',encounter:'S05-03',x:30,y:-8000},
            {id:'S05-04-early',encounter:'S05-04',x:6200,y:-9960}]});
    // Encounter nodes sit inside the band (y >= -9720): S05-01 below the S06-04 node (S06-fall rejoins
    // S05-01) and S05-04 above the S04-01 node (S05-fall rejoins S04-01); the route runs above.
    // TASK-519: the S05-01 exit box also takes a 3-tick-early hoist release (deflector bounce at 295,
    // x 2437.5 y -11019 at tick 304); the nominal state (2511.7,-10905.2) is unchanged.
    Object.assign(encounters[16], {status:'built',x:1388,y:-8000,
        elements:['S04-exit-ledge','S05-hoist','S05-canopy','S05-deflector'],
        start:{x:1387.9,y:-11660.9,from:'S04-04'},target:{x:2548,y:-12456.9},
        exit:{left:2420,right:2580,top:-11040,bottom:-10860},
        action:'Pull the blue hoist up-right out of the Works exit drag zone, release under the green canopy and drop onto the angled green deflector'});
    Object.assign(encounters[17], {status:'built',x:2512,y:-8000,
        elements:['S05-deflector','S05-lift','S05-baffle'],
        start:{from:'S05-01',x:2511.7,y:-10905.2},target:{x:3860,y:-10855.2},
        exit:{left:4050,right:4300,top:-10250,bottom:-10120},
        action:'On the deflector throw, catch the blue lift, swing under the spill deck and rebound off the green gallery baffle'});
    Object.assign(encounters[18], {status:'built',x:4400,y:-9720,
        elements:['S05-baffle','S05-pull-hook'],
        start:{from:'S05-02',x:4078.6,y:-10145.9},target:{x:5265,y:-9305},
        exit:{left:3900,right:4030,top:-8100,bottom:-7980},
        action:'Flying west off the baffle, catch the green pull hook below its foot, swing west under the catch deck and back east, release on the upswing'});
    Object.assign(encounters[19], {status:'built',x:5800,y:-9720,
        elements:['S05-exit-hook','S05-exit-canopy','S05-exit-ledge'],
        start:{from:'S05-03',x:3965.2,y:-8039.9},target:{x:4980,y:-9087.5},
        exit:{left:6100,right:6470,top:-9460,bottom:-9420},
        action:'Catch the green exit hook from the swing release, swing up-right past the Liftworks exit and release into the exit drag zone under the green exit canopy; settle on the green exit ledge'});
    Object.assign(connectors[16], {status:'built',intent:'Physical ascent: the S05-01 hoist pull starts on the v3 Works exit ledge'});
    for (let i=17;i<20;i++) connectors[i].status='built';
    Object.assign(recoveries[4], {status:'built',elements:['S04-exit-drag','S04-exit-ledge','S05-fall-drag','S05-catch-deck','S04-fall-drag','S04-catch-basin','S05-exit-drag','S05-exit-ledge'],
        rejoin:'S05-01',sideRoute:'Every declared S05 miss falls through a drag zone onto a green bouncer and settles: a short hoist hold on the green S04 exit ledge, from which the S05-01 hoist pull rejoins the route; a missed lift catch on the green catch deck; a missed pull-hook catch down the left map edge onto the green S04 catch basin; an early exit-hook release on the green exit ledge'});
    // Liftworks v3 (layout v3, TASK-520): no gray pads. Travelling left from the green S05 exit ledge
    // (inside S05-exit-drag, against the right map edge) at the 1620-range distances. S06-01: pull the
    // blue carriage left out of the exit drag zone (the rope runs under the S05 pull hook and over the
    // S05 exit hook) and release; the dive lands on the green skid, which turns it into a long rising
    // flight west under the S05 catch deck. S06-02: catch the blue lift in flight, west of the S05-03
    // swing loop, swing up-left past it and release into the green Liftworks canopy, which turns the
    // rise into a drop toward the S04 climb. The carriage sits under every S05 throw line; the skid
    // is bounce-only (not grappleable, so S05 ropes pass over it) and west of the S05-04 exit-hook throws.
    // A short carriage hold drops from the exit-pocket mouth through S06-fall-drag onto the green catch
    // ledge; a missed lift catch carries the rising flight under the canopy into the left map edge and
    // drops along it through S04-fall-drag onto the green S04 catch basin.
    // S06-03 (TASK-521): sliding down the left map edge below the canopy, catch the green climb hook;
    // the swing skips over the bounce-only green swing skid at its bottom and, released at the top of
    // the upswing, rises straight up between the S04 baffle and the exit pocket. S06-04: near the top
    // of that rise, catch the green exit hook far to the east (the rope runs above the S05 deflector)
    // and release once the pull has carried the player into the exit drag zone under the S04 exit
    // ledge; it settles on the green exit ledge. A missed climb-hook catch slides on down the map edge
    // through S04-fall-drag onto the green S04 catch basin; a missed exit-hook catch drops straight back
    // down the rise through S06-drop-drag onto the green drop ledge (the climb hook is in reach again);
    // an early exit-hook release still settles in the exit drag zone.
    const liftworks = [
        rectangle('S06-carriage',4600,-9120,120,30,true),
        // Bounce only (not grappleable): S05 ropes pass over it; the S05 exit-hook throws pass east of it.
        {...bouncer('S06-skid',4140,-8650,230,30), grapplable:false},
        rectangle('S06-lift',1880,-9665,120,30,true),
        // Up-left of the lift, right of the S04 climb along the left map edge; the missed-lift flight passes under it.
        bouncer('S06-canopy',700,-9905,450,30),
        bouncer('S06-catch-ledge',5700,-8350,390,30),
        // Up-right of the map-edge slide, above the canopy (the throw passes left of its end).
        bouncer('S06-climb-hook',1090,-10460,60,25),
        // Bounce only (not grappleable): the climb swing grazes it at its lowest point.
        {...bouncer('S06-swing-skid',300,-8896,220,30), grapplable:false},
        // Far east of the rise, above the S05 deflector apex and right of the S05-01 flight.
        bouncer('S06-exit-hook',2620,-11515,60,25),
        // Exit pocket floor under the S04 exit ledge, left of the S05-01 flight; the drag zone above it
        // is the pocket (no canopy: the pull reaches it near the top of the rise).
        bouncer('S06-exit-ledge',1450,-11250,400,30),
        // Under the rise, between the S06-02 missed flight and the S05-03 missed fall.
        bouncer('S06-drop-ledge',1150,-9080,160,30),
        // Legacy v1 Liftworks pieces still named by the v1 Crown (the S07-01 start ledge and a recovery
        // opening collider), converted to green in place; no v3 S06 route uses them.
        {id:'S06-phase-rest',x:5780,y:-8270,role:'bounce',grapplable:true,
            points:[{x:0,y:-20},{x:40,y:-20},{x:40,y:0},{x:220,y:0},{x:220,y:50},{x:70,y:50},{x:70,y:110},{x:0,y:110}]},
        {id:'S06-exit',x:5520,y:-9680,role:'bounce',grapplable:true,
            points:[{x:0,y:-20},{x:40,y:-20},{x:40,y:0},{x:220,y:0},{x:220,y:-20},{x:260,y:-20},{x:260,y:55},{x:0,y:55}]}
    ];
    // The fall drag zone holds the catch ledge below the exit-pocket mouth; only S06-01-short drops through it.
    const liftworksDrags = [{id:'S06-fall-drag',x:5700,y:-8800,role:'drag',grapplable:false,
        points:[{x:0,y:0},{x:390,y:0},{x:390,y:450},{x:0,y:450}]},
        // The exit pocket above the exit ledge (S06-04-early) and the drop column above the drop ledge (S06-04-missed).
        {id:'S06-exit-drag',x:1450,y:-11570,role:'drag',grapplable:false,
        points:[{x:0,y:0},{x:400,y:0},{x:400,y:320},{x:0,y:320}]},
        {id:'S06-drop-drag',x:1150,y:-9400,role:'drag',grapplable:false,
        points:[{x:0,y:0},{x:160,y:0},{x:160,y:320},{x:0,y:320}]}];
    const liftMovers = [...yardMovers, ...shaftMovers, ...viaductMovers, ...worksMovers, ...galleriesMovers,
        {id:'S06-carriage-travel',element:'S06-carriage',axis:'x',min:4600,max:4720,periodMs:4000,phase:0,velocity:60},
        {id:'S06-lift-travel',element:'S06-lift',axis:'x',min:1880,max:2000,periodMs:4000,phase:0,velocity:60}];
    Object.assign(sections[5], {status:'built', designVersion:3, landmark:{id:'S06-landmark',
        name:'moving counterweights',x:3400,y:-9600},
        band:{...sections[5].band, top:-11340},
        // Rope-to-anchor reach from the player at the press to the acquisition point (range 1620).
        gaps:[{id:'S06-01-carriage',from:{x:6120.4,y:-9432.4},to:{x:4756.5,y:-9119.5}},
            // Caught in flight from the skid rebound.
            {id:'S06-02-lift',from:{x:3269.4,y:-9059},to:{x:2004.5,y:-9649.1}},
            // Pressed sliding down the map edge; then near the top of the rise off the climb swing.
            {id:'S06-03-climb',from:{x:10.8,y:-9519.5},to:{x:1100.5,y:-10435}},
            {id:'S06-04-exit',from:{x:1239.8,y:-11279.8},to:{x:2620,y:-11502.6}}],
        // Declared miss points: a short carriage hold drops from the exit-pocket mouth through
        // S06-fall-drag onto the green catch ledge; a missed lift catch carries the rising flight into the
        // left map edge and drops along it through S04-fall-drag onto the green S04 catch basin; a
        // missed climb-hook catch slides on down the map edge the same way; a missed exit-hook catch
        // drops from the top of the rise through S06-drop-drag onto the green drop ledge; an early
        // exit-hook release drops through S06-exit-drag onto the green exit ledge.
        fallPoints:[{id:'S06-01-short',encounter:'S06-01',x:6020,y:-8900},
            {id:'S06-02-missed',encounter:'S06-02',x:30,y:-9450},
            {id:'S06-03-missed',encounter:'S06-03',x:30,y:-9540},
            {id:'S06-04-missed',encounter:'S06-04',x:1230,y:-11500},
            {id:'S06-04-early',encounter:'S06-04',x:1500,y:-11520}]});
    Object.assign(encounters[20], {status:'built',x:6120,y:-9432,
        elements:['S05-exit-ledge','S06-carriage','S06-skid'],
        start:{x:6120.4,y:-9432.4,from:'S05-04'},target:{x:4708,y:-9108.4},
        exit:{left:3200,right:3340,top:-9120,bottom:-9000},
        action:'Pull the blue carriage left out of the Galleries exit drag zone, release into a dive and skip off the green skid into a rising flight west'});
    Object.assign(encounters[21], {status:'built',x:3269,y:-9059,
        elements:['S06-lift','S06-canopy'],
        start:{from:'S06-01',x:3269.4,y:-9059},target:{x:1986.1,y:-9657.6},
        exit:{left:540,right:660,top:-9800,bottom:-9720},
        action:'On the rising flight, catch the blue lift, swing up-left past it and release into the green Liftworks canopy, which turns the rise into a drop'});
    Object.assign(connectors[20], {status:'built',intent:'Physical ascent: the S06-01 carriage pull starts on the v3 Galleries exit ledge'});
    Object.assign(encounters[22], {status:'built',x:597,y:-9758,
        elements:['S06-climb-hook','S06-swing-skid'],
        start:{from:'S06-02',x:597.5,y:-9758.5},target:{x:1120,y:-10451.4},
        exit:{left:1130,right:1360,top:-11330,bottom:-11230},
        action:'Sliding down the map edge under the canopy, catch the green climb hook, skip over the green swing skid and release at the top of the upswing into a straight rise'});
    Object.assign(encounters[23], {status:'built',x:1240,y:-11280,
        elements:['S06-exit-hook','S06-exit-ledge','S06-exit-drag'],
        start:{from:'S06-03',x:1239.8,y:-11279.8},target:{x:2648,y:-11507.1},
        exit:{left:1450,right:1850,top:-11300,bottom:-11250},
        action:'Near the top of the rise, catch the green exit hook far to the east, release in the exit drag zone under the Works exit ledge and settle on the green exit ledge'});
    for (let i=21;i<24;i++) connectors[i].status='built';
    // The S07 entrance stays planned: the v1 Crown still starts on the legacy S06-exit ledge.
    Object.assign(recoveries[5], {status:'built',elements:['S06-fall-drag','S06-catch-ledge','S04-fall-drag','S04-catch-basin','S06-drop-drag','S06-drop-ledge','S06-exit-drag','S06-exit-ledge'],
        rejoin:'S06-03',intent:'Liftworks misses fall through drag zones onto green catches',
        sideRoute:'Every declared S06 miss falls through a drag zone onto a green bouncer and settles: a short carriage hold on the green catch ledge; missed lift and climb-hook catches down the left map edge onto the green S04 catch basin; a missed exit-hook catch on the green drop ledge, from which the S06-03 climb hook rejoins the route; an early exit-hook release on the green exit ledge'});
    // Exposed Crown v3 (layout v3, TASK-523): no gray pads. Travelling right from the green S06 exit ledge
    // (inside S06-exit-drag, under the S04 exit ledge) at the 1620-range distances. S07-01: pull the blue
    // trolley up-left, far over the S04 route; the drag zone only lets the player crawl out of the pocket's
    // open west side, then the pull swings it west under the trolley; released just before the green west
    // wall, it ricochets east into a long flight between the S05 canopy and the S05 hoist. S07-02: catch the
    // blue carriage in that flight; the swing climbs up-right over the hoist, and released early it rebounds
    // off the green crown wall (west of the legacy beacon mast) into a flight west along the top.
    // A short trolley hold drops onto the left map edge and slides down it through S04-fall-drag onto the
    // green S04 catch basin; a missed carriage catch carries the flight under the hoist into S07-crown-drag,
    // where it drops onto the green crown ledge. S07-03 (TASK-524): the westward flight meets the left map
    // edge and drops onto the green west wall, which keeps bouncing it; from the top of a bounce pull the
    // green gable hook (top of the band) east and release into a flight east along the top. S07-04: in that
    // flight, catch the green exit ledge itself; the pull dives east into S07-exit-drag, where the player is
    // released and settles on the exit ledge (the section exit, under the S05 hoist). A gable hook released
    // early drops into S07-short-drag, which kills the drift, straight down the clear column onto the green
    // S06 drop ledge inside S06-drop-drag; a missed exit-ledge catch lands in S07-crown-drag on the green
    // crown ledge; an exit-ledge pull held too long dives into S07-exit-drag onto the exit ledge.
    const crown = [
        rectangle('S07-trolley',250,-11960,120,30,true),
        // Against the left map edge, above the S04 route's map-edge contact; the S07-01 swing ricochets off it.
        bouncer('S07-west-wall',0,-12260,30,400),
        // High over the S05 hoist throw lines and ropes.
        rectangle('S07-carriage',1930,-12910,120,30,true),
        // East of the S05 hoist travel and west of the legacy beacon mast; the drag zone under its upper part
        // holds the crown ledge (only S07-02-missed drops through it).
        bouncer('S07-crown-wall',2930,-12950,30,960),
        bouncer('S07-crown-ledge',2740,-12020,190,30),
        // At the top of the band, high over the S07-02 return flight.
        bouncer('S07-gable-hook',1405,-12955,60,30),
        // Under the S05 hoist, west of the crown drag; clear of the S05 hoist rope.
        bouncer('S07-exit-ledge',2340,-11960,360,30),
        // Legacy v1 Crown pieces still named by the v1 Summit Array (the S08-01 start ledge and recovery
        // opening colliders), converted to green in place; no v3 S07 route uses them.
        {id:'S07-roof-boom',x:5150,y:-10410,role:'bounce',grapplable:true,
            points:[{x:0,y:0},{x:170,y:0},{x:170,y:30},{x:60,y:30},{x:40,y:65},{x:0,y:65}]},
        {...rest('S07-recovery-balcony',5480,-10180,340),role:'bounce'},
        {id:'S07-exit',x:5240,y:-11340,role:'bounce',grapplable:true,
            points:[{x:0,y:-30},{x:20,y:-30},{x:20,y:0},{x:110,y:0},{x:110,y:-60},{x:150,y:-60},{x:150,y:55},{x:0,y:55}]}
    ];
    const crownDrags = [{id:'S07-crown-drag',x:2740,y:-12530,role:'drag',grapplable:false,
        points:[{x:0,y:0},{x:190,y:0},{x:190,y:510},{x:0,y:510}]},
        {id:'S07-exit-drag',x:2340,y:-12260,role:'drag',grapplable:false,
            points:[{x:0,y:0},{x:360,y:0},{x:360,y:300},{x:0,y:300}]},
        // Over the clear column above the S06 drop ledge, under the S07-02 flights.
        {id:'S07-short-drag',x:1145,y:-12520,role:'drag',grapplable:false,
            points:[{x:0,y:0},{x:120,y:0},{x:120,y:160},{x:0,y:160}]}];
    liftMovers.push({id:'S07-trolley-travel',element:'S07-trolley',axis:'x',min:250,max:370,periodMs:4000,phase:0,velocity:60},
        {id:'S07-carriage-travel',element:'S07-carriage',axis:'x',min:1930,max:2050,periodMs:4000,phase:0,velocity:60});
    Object.assign(sections[6], {status:'built', designVersion:3, landmark:{id:'S07-landmark',
        name:'open rooftop machinery',x:1500,y:-12600},
        band:{...sections[6].band, top:-12960},
        // Rope-to-anchor reach from the player at the press to the acquisition point (range 1620).
        gaps:[{id:'S07-01-trolley',from:{x:1543.2,y:-11261.3},to:{x:313.1,y:-11930}},
            // Caught in flight after the west-wall ricochet.
            {id:'S07-02-carriage',from:{x:770.1,y:-12154.3},to:{x:1988.4,y:-12882.7}},
            // From the top of a west-wall bounce, and in the flight east along the top.
            {id:'S07-03-gable',from:{x:10.8,y:-12696.3},to:{x:1405,y:-12935.4}},
            {id:'S07-04-exit',from:{x:1164,y:-12742.7},to:{x:2344,y:-11960}}],
        // Declared miss points: a short trolley hold flies west onto the left map edge and slides down it
        // through S04-fall-drag onto the green S04 catch basin; a missed carriage catch carries the flight
        // into S07-crown-drag, which drops it onto the green crown ledge; an early gable-hook release drifts
        // into S07-short-drag and drops straight down through S06-drop-drag onto the green S06 drop ledge;
        // a missed exit-ledge catch lands in S07-crown-drag; an exit-ledge pull held too long dives through
        // S07-exit-drag onto the exit ledge.
        fallPoints:[{id:'S07-01-short',encounter:'S07-01',x:30,y:-11560},
            {id:'S07-02-missed',encounter:'S07-02',x:2800,y:-12330},
            {id:'S07-03-short',encounter:'S07-03',x:1180,y:-12400},
            {id:'S07-04-missed',encounter:'S07-04',x:2794,y:-12150},
            {id:'S07-04-late',encounter:'S07-04',x:2560,y:-12150}]});
    Object.assign(encounters[24], {status:'built',x:1543,y:-11261,
        elements:['S06-exit-ledge','S07-trolley','S07-west-wall'],
        start:{x:1543.2,y:-11261.3,from:'S06-04'},target:{x:308,y:-11933.3},
        exit:{left:700,right:840,top:-12200,bottom:-12110},
        action:'Pull the blue trolley up-left, crawl out of the Liftworks exit pocket, swing west under the trolley and ricochet off the green west wall into a long flight east'});
    Object.assign(encounters[25], {status:'built',x:770,y:-12154,
        elements:['S07-carriage','S07-crown-wall'],
        start:{from:'S07-01',x:770.1,y:-12154.3},target:{x:1988,y:-12882.5},
        exit:{left:1600,right:1800,top:-12780,bottom:-12680},
        action:'In the flight, catch the blue carriage, swing up-right over the Galleries hoist and rebound off the green crown wall into a flight west along the top'});
    Object.assign(encounters[26], {status:'built',x:1687,y:-12736,
        elements:['S07-west-wall','S07-gable-hook'],
        start:{from:'S07-02',x:1687.3,y:-12735.5},target:{x:1435,y:-12940},
        exit:{left:1050,right:1250,top:-12800,bottom:-12700},
        action:'Ride the flight west onto the green west wall, then from the top of a bounce pull the green gable hook and release into a flight east along the top'});
    Object.assign(encounters[27], {status:'built',x:1164,y:-12743,
        elements:['S07-exit-ledge','S07-exit-drag'],
        start:{from:'S07-03',x:1164,y:-12742.7},target:{x:2345,y:-11958},
        exit:{left:2340,right:2700,top:-12010,bottom:-11960},
        action:'In the flight, catch the green exit ledge, dive into the exit drag zone under the Galleries hoist, release and settle on the exit ledge'});
    Object.assign(connectors[24], {status:'built',intent:'Physical ascent: the S07-01 trolley pull starts on the v3 Liftworks exit ledge'});
    Object.assign(connectors[25], {status:'built'});
    Object.assign(connectors[26], {status:'built'});
    Object.assign(connectors[27], {status:'built'});
    // TASK-492: the optional shortcut found by the bounded bypass audit (shortcuts.json): a short trolley launch.
    Object.assign(shortcuts[1], {status:'built', elements:['S07-trolley','S07-exit-ledge'],
        intent:'Optional exposed skill shortcut from S07-01 to S07-04',
        route:'Release the blue S07 trolley earlier than the normal pull: the flight crosses the open strip under the carriage line straight to the Crown exit pocket; catch the green exit ledge on the way and settle on it (skips the S07-02 carriage and the S07-03 gable hook)',
        risk:'Exposed: a release a few ticks off misses the pocket and falls to the Galleries entrance shelf or much lower'});
    Object.assign(recoveries[6], {status:'built',elements:['S04-fall-drag','S04-catch-basin','S07-crown-drag','S07-crown-ledge','S07-short-drag','S06-drop-drag','S06-drop-ledge','S07-exit-drag','S07-exit-ledge'],
        rejoin:'S07-01',intent:'Crown misses fall through drag zones onto green catches',
        sideRoute:'Every declared S07 miss falls through a drag zone onto a green bouncer and settles: a short trolley hold down the left map edge onto the green S04 catch basin; a missed carriage or exit-ledge catch on the green crown ledge; an early gable-hook release straight down onto the green S06 drop ledge, from which the S06 climb and exit hooks return to the S06 exit ledge and the S07-01 trolley; an exit-ledge pull held too long on the green exit ledge'});
    // Summit Array v3 (layout v3, TASK-526): no gray pads. Travelling left from the green S07 exit ledge (inside
    // S07-exit-drag, under the S05 hoist) at the 1620-range distances, up into the open strip above the Crown.
    // S08-01: pull the blue mast trolley (high up-left, right of the S07 carriage's travel); the drag zone lets the
    // player rise only straight up out of the pocket, so the pull is timed to pass the S05 hoist at its east turn; the
    // pull then hurls it up-left, and released early it rebounds off the green roof onto the top of the moving mast
    // trolley and slides off west into a long glide. S08-02: from that glide, catch the blue beacon trolley (far west);
    // the swing runs west under it, rebounds off the green west wall still attached, and the pull lifts it up-right
    // into a flight east under the roof. A trolley released too early drops back through S07-exit-drag onto the green
    // S07 exit ledge; a missed beacon catch carries the glide down into S08-glide-drag onto the green glide cap (above
    // the Crown gable hook).
    // S08-03 (TASK-527): in the flight east under the roof, pull the green east wall (far east, out of reach of the Crown
    // ledges); released before the wall, the player rebounds off its slightly leaning face back west, nearly level, and
    // the rebound crosses the crown wall top into S08-crest-drag, which stops it in the crest pocket over the Crown.
    // S08-04: from the crest pocket, pull the far west end of the roof: the drag only lets the player crawl west out of
    // the pocket, straight into the summit finish region over the green summit pad (the pad keeps straight pulls from the
    // Crown exit pocket and the crown ledge out of it). Without the S08-04 pull, or with the east wall released early,
    // the player sinks through S08-crest-drag and S07-crown-drag onto the green S07 crown ledge.
    const summit = [
        // Up-left of the S07 exit pocket, between the S05 hoist's and the S07 carriage's travel lines.
        rectangle('S08-mast-trolley',2000,-13330,120,30,true),
        // At the top of the map, over the mast trolley; its far west end is the S08-04 anchor. TASK-492: it ends over the
        // summit rail (it reached x 2600, over the finish, and a pull on that part dropped the player straight into the finish).
        bouncer('S08-roof',1350,-13495,1020,25),
        // TASK-492: bounce only (not grappleable), the roof's former east part over the finish: it still caps the S08-03 flight
        // east under the roof (the touch S08-03 route rebounds off it) but offers no anchor to drop into the finish from.
        {...bouncer('S08-roof-skid',2370,-13495,230,25), grapplable:false},
        rectangle('S08-beacon-trolley',370,-13360,120,30,true),
        // Against the left map edge, high above the S07-03 map-edge climb. It reaches down to the S08 band bottom
        // (TASK-528), so an early beacon release flying west at the band bottom still rebounds off it, not the map edge.
        bouncer('S08-west-wall',0,-13420,30,460),
        // Over the S07 gable hook, under the missed-beacon glide; the drag zone above it holds it.
        bouncer('S08-glide-cap',1400,-13030,160,30),
        // Far east of the Crown; its face leans back 42 px over its height, so the rebound leaves nearly level.
        {id:'S08-east-wall',x:4150,y:-13470,role:'bounce',grapplable:true,
            points:[{x:42,y:0},{x:72,y:0},{x:30,y:320},{x:0,y:320}]},
        // Under the summit finish region, west of the crest pocket.
        bouncer('S08-summit-floor',2370,-13110,380,30),
        // TASK-492: west rail of the finish region, from its top down to the summit floor. Without it, a long S05-hoist hold
        // from the S05 start reaches the mast trolley, and drifting east off it enters the finish from the west (S05-02..S08-04
        // bypassed). The S08-01 rise passes under its foot, which ends at the summit floor's top (a foot at the floor's
        // bottom clipped the aim-right/early S08-01 rises). Its top slopes down to the west, so nothing settles on it next to
        // the finish; the S08-04 roof rope bends over its top corner while the player crawls into the finish.
        {id:'S08-summit-rail',x:2340,y:-13300,role:'bounce',grapplable:true,
            points:[{x:0,y:25},{x:30,y:0},{x:30,y:190},{x:0,y:190}]},
        // TASK-492: west jamb of the crest pocket's drag column, under the summit floor's east end. A long rope caught in a
        // fast flight east (the mast trolley at full range from an S07-trolley launch) swung up into the column from the
        // west and rose into the crest pocket, one roof pull from the finish (S07-02..S08-03 bypassed). The S08-03 rebound
        // enters the pocket from the east above the crown wall and the S08-04 crawl leaves above the jamb; the S07-02 swing
        // turns about 70 below it.
        bouncer('S08-crest-jamb',2720,-13080,30,360)
    ];
    const summitDrags = [{id:'S08-glide-drag',x:1400,y:-13140,role:'drag',grapplable:false,
        points:[{x:0,y:0},{x:160,y:0},{x:160,y:110},{x:0,y:110}]},
        // The crest pocket: over S07-crown-drag and the crown ledge, under the S08-03 pull's outbound flight.
        {id:'S08-crest-drag',x:2750,y:-13350,role:'drag',grapplable:false,
            points:[{x:0,y:0},{x:180,y:0},{x:180,y:550},{x:0,y:550}]},
        // TASK-492: a curtain over the summit rail, east of the S08-01 rise and under the S08-03 flight along the roof: a
        // flight up the corridor west of the finish (off the S05 hoist, the S07 gable hook or the S08 glide cap) loses its speed
        // here and sinks down the rail's west face instead of rebounding over the rail into the finish.
        {id:'S08-summit-brake',x:2280,y:-13435,role:'drag',grapplable:false,
            points:[{x:0,y:0},{x:90,y:0},{x:90,y:210},{x:0,y:210}]}];
    liftMovers.push({id:'S08-mast-trolley-travel',element:'S08-mast-trolley',axis:'x',min:2000,max:2120,periodMs:4000,phase:0,velocity:60},
        {id:'S08-beacon-trolley-travel',element:'S08-beacon-trolley',axis:'x',min:370,max:490,periodMs:4000,phase:0,velocity:60});
    Object.assign(sections[7], {status:'built', designVersion:3, landmark:{id:'S08-landmark',
        name:'distinct final beacon silhouette',x:1300,y:-12960},
        band:{...sections[7].band, top:-14580},
        // Rope-to-anchor reach from the player at the press to the acquisition point (range 1620); S08-02..04
        // re-measured on the TASK-528 camera (topLead), which moves the client pixel of each aimed press.
        gaps:[{id:'S08-01-trolley',from:{x:2608.9,y:-11971.2},to:{x:2058.4,y:-13300}},
            // Caught in the glide off the mast trolley.
            {id:'S08-02-beacon',from:{x:1917.7,y:-13330.5},to:{x:491.6,y:-13333.3}},
            // Pressed in the flight east under the roof.
            {id:'S08-03-wall',from:{x:2770.6,y:-13412.1},to:{x:4188.1,y:-13440.2}},
            // Pressed in the crest pocket.
            {id:'S08-04-roof',from:{x:2806.0,y:-13253.6},to:{x:1414.7,y:-13470}}],
        // Declared miss points: a mast trolley released too early rises short of the S05 hoist and drops back through
        // S07-exit-drag onto the green S07 exit ledge; a missed beacon catch glides down into S08-glide-drag, which
        // drops it onto the green glide cap. An east wall released early rebounds lower and slower into the crest pocket,
        // and without the S08-04 pull the pocket sinks: both drop through S08-crest-drag and S07-crown-drag onto the
        // green S07 crown ledge.
        fallPoints:[{id:'S08-01-short',encounter:'S08-01',x:2587,y:-12300},
            {id:'S08-02-missed',encounter:'S08-02',x:1560,y:-13150},
            {id:'S08-03-short',encounter:'S08-03',x:2830,y:-13050},
            {id:'S08-04-missed',encounter:'S08-04',x:2803,y:-13150},
            // TASK-492: an S08-01 overflight (a flight up the corridor west of the summit rail, off the roof) sinks
            // through S08-summit-brake down the rail's west face back to the S07 exit pocket.
            {id:'S08-01-overflight',encounter:'S08-01',x:2325,y:-13450}]});
    Object.assign(encounters[28], {status:'built',x:2609,y:-11971,
        elements:['S07-exit-ledge','S08-mast-trolley','S08-roof'],
        start:{x:2608.9,y:-11971.5,from:'S07-04'},target:{x:2060,y:-13300},
        exit:{left:1850,right:2000,top:-13345,bottom:-13310},
        action:'Pull the blue mast trolley up out of the Crown exit pocket past the Galleries hoist, rebound off the green roof onto the trolley top and slide off west into a glide'});
    // Encounter nodes may not sit above the summit height (-12960); the start carries the real pose.
    Object.assign(encounters[29], {status:'built',x:1918,y:-12960,
        elements:['S08-beacon-trolley','S08-west-wall'],
        start:{from:'S08-01',x:1917.7,y:-13330.5},target:{x:430,y:-13330},
        exit:{left:1450,right:1700,top:-13400,bottom:-13300},
        action:'In the glide, catch the blue beacon trolley, swing west under it, rebound off the green west wall and ride the pull up-right into a flight east under the roof'});
    // The summit finish: over the green summit pad, entered from the crest pocket (west of the S08 entry).
    const finish = {left:2380,right:2735,top:-13300,bottom:-13121}
    Object.assign(encounters[30], {status:'built',x:2806,y:-12960,
        elements:['S08-east-wall','S08-crest-drag'],
        start:{from:'S08-02',x:1563,y:-13346.8},target:{x:4180,y:-13440},
        exit:{left:2780,right:2840,top:-13290,bottom:-13230},
        action:'In the flight east under the roof, pull the green east wall, release before it, rebound off its leaning face back west over the crown wall top and stop in the crest pocket'});
    Object.assign(encounters[31], {status:'built',x:2560,y:-12960,
        elements:['S08-crest-drag','S08-roof','S08-summit-floor'],
        start:{from:'S08-03',x:2805.9,y:-13257.1},target:{x:1400,y:-13471},
        exit:finish, finishRegion:finish,
        action:'From the crest pocket, pull the far west end of the green roof and crawl west out of the pocket into the summit finish region over the green summit pad'});
    Object.assign(connectors[28], {status:'built',intent:'Physical ascent: the S08-01 mast trolley pull starts on the v3 Crown exit ledge'});
    Object.assign(connectors[29], {status:'built'});
    Object.assign(connectors[30], {status:'built',intent:'The S08-02 flight east under the roof carries the player into reach of the east wall'});
    Object.assign(connectors[31], {status:'built',intent:'The crest pocket holds the S08-03 rebound within reach of the far west end of the roof'});
    Object.assign(connectors[32], {status:'built',finishRegion:finish,
        intent:'Controlled final approach: the crawl out of the crest pocket enters the summit finish region over the green summit pad'});
    Object.assign(recoveries[7], {status:'built',elements:['S08-crest-drag','S07-crown-drag','S07-crown-ledge','S05-hoist','S07-exit-drag','S07-exit-ledge'],
        rejoin:'S08-01',intent:'Summit misses fall through drag zones onto green catches',
        sideRoute:'An early east-wall release or a missing roof pull sinks through S08-crest-drag and S07-crown-drag onto the green S07 crown ledge; from there the S05 hoist swings the player west into S07-exit-drag onto the S07 exit ledge, the S08 entrance, and the S08-01 mast trolley pull starts again. No hazards at the ending.'});
    return {schemaVersion:1, geometryVersion:1,
        // Grapnel range: base until the player enters upgradeBand (its rangeUpgradeZone when set), upgraded after.
        range:{base:R, upgraded:1620, upgradeBand:'S05'}, ascent:24*U, horizontalEnvelope:12*U,
        coordinateConvention:'negative Y upward', base:{id:'base',x:2160,y:0},
        summit:{id:'summit',x:3780,y:-24*U},
        // topLead (TASK-528): while the player is above y -24*U (the S08 band bottom; every S01-S07 pose is below
        // it), the camera top bound rises `rate` times as fast as the player, up to the S08 band top, so the S08 anchors
        // in the band's upper west corner (beacon trolley, roof end) are drawn below the HUD rows, not under them.
        // Below y -24*U the bound is exactly bounds.top, so the S01-S07 cameras are unchanged; it never jumps.
        bounds:{left:0,right:6480,top:-24*U-540,bottom:120,topLead:{from:-24*U,rate:3,limit:-27*U}},
        spawn:{x:2160,y:0}, startSection:'S01', sections, encounters, connectors, recoveries, shortcuts,
        geometry:{version:1, elements:[rectangle('mountain-catch',0,120,6480,60,true),
            rectangle('mountain-left',-60,-13500,60,13680,false),
            rectangle('mountain-right',6480,-13500,60,13680,false),...yard,...shaft,...viaduct,...deflectors,...galleries,...liftworks,...crown,...summit,yardDrag,exitDrag,overpullDrag,...shaftDrags,...viaductDrags,...worksDrags,...galleriesDrags,...liftworksDrags,...crownDrags,...summitDrags], movers:liftMovers},
        difficulty:{targetFirstSuccessMinutes:[30,60], validated:false,
            note:'30-60 minute first success is unvalidated without human feedback.'},
        finish, completion:'Summit finish region on the S08-04 beacon pad; reaching it completes the climb',
        recoveryPolicy:'Physical falls, nonlethal hazards, current-state saves; no automatic relocation'}
})()

// Layout-v2 design rules. A section opts in with designVersion:2; legacy (v1)
// sections are reported but never fail. Gap targets are the TASK-503 frozen
// 85-90% band of measured reach for the section's active grapnel range.
// v2 sections were laid out for the 540/810 range, so their gaps keep that
// design range after the TASK-543 range doubling.
const LAYOUT_V2_GAP_TARGETS = {540:[459,486], 810:[689,729]}
const LAYOUT_V2_RANGE = {base:540, upgraded:810}
const LAYOUT_V2_SOLID_EXCEPTIONS = ['rest-pad','lip','side-wall']
const LAYOUT_V2_REST_PAD_MAX_WIDTH = 200
const LAYOUT_V2_DENSITY_CAP_TICKS = 180

// Layout-v3 targets, frozen by TASK-544 from the 1080/1620 recalibration.
// Gaps: twice the v2 band, inside 85-90% of the measured reach at each range.
// Extent: twice v2. Density cap: longest nominal-trace stretch without an
// acquisition, bounce or mover contact, i.e. the v2 cap scaled by the measured
// free-fall flight-time ratio across a v3 vs a v2 band height.
const LAYOUT_V3_GAP_TARGETS = {1080:[918,972], 1620:[1378,1458]}
const LAYOUT_V3_RANGE = {base:1080, upgraded:1620}
const LAYOUT_V3_EXTENT = {ascent:25920, horizontalEnvelope:12960, bandHeight:3240, encountersPerSection:4}
const LAYOUT_V3_DENSITY_CAP_TICKS = 254
// Layout-v3 design rules (TASK-546). A section opts in with designVersion:3;
// v1/v2 sections are reported but not judged by them. Fall columns are as wide
// as the player circle (the radius the spawn guard below uses).
const LAYOUT_V3_FALL_COLUMN_RADIUS = 18
const LAYOUT_V3_RULES = {graySolid:'LayoutV3GraySolid', moverCoverage:'LayoutV2MoverCoverage',
    direction:'LayoutV2Direction', gapBand:'LayoutV3GapBand', dragUnderFall:'LayoutV3DragUnderFall',
    strayDrag:'LayoutV3StrayDrag', extent:'LayoutV3Extent'}

function layoutV2Report(m)
{
    const box = e => ({left:e.x+Math.min(...e.points.map(p=>p.x)),right:e.x+Math.max(...e.points.map(p=>p.x)),
        top:e.y+Math.min(...e.points.map(p=>p.y)),bottom:e.y+Math.max(...e.points.map(p=>p.y))})
    const elements = new Map(m.geometry.elements.map(e=>[e.id,e]))
    const encounters = new Map(m.encounters.map(e=>[e.id,e]))
    const upgradeOrder = m.sections.find(s=>s.id===m.range.upgradeBand).order
    // v3 fall columns: from a declared fall point straight down to the first
    // bouncer (any collider) under it; a drag zone counts if it crosses that stretch.
    const inColumn = (b, x) => b.left < x+LAYOUT_V3_FALL_COLUMN_RADIUS && b.right > x-LAYOUT_V3_FALL_COLUMN_RADIUS
    const fallColumn = f => {
        const hit = m.geometry.elements.filter(e=>['bounce','solid'].includes(e.role))
            .map(e=>({id:e.id, b:box(e)})).filter(h=>inColumn(h.b, f.x) && h.b.top > f.y)
            .map(h=>({id:h.id, top:h.b.top})).sort((a,b)=>a.top-b.top)[0]
        const floor = hit ? hit.top : m.bounds.bottom
        const zones = m.geometry.elements.filter(e=>e.role === 'drag').filter(d=>{const b = box(d)
            return inColumn(b, f.x) && b.bottom > f.y && b.top < floor}).map(d=>d.id)
        return {id:f.id, encounter:f.encounter, x:f.x, y:f.y, firstBouncer:hit ? hit.id : null,
            firstBouncerTop:floor, dragZones:zones}
    }
    const v3Falls = m.sections.filter(s=>s.designVersion === 3 && Array.isArray(s.fallPoints))
        .flatMap(s=>s.fallPoints.map(fallColumn))
    const sections = m.sections.map(s=>{
        const version = s.designVersion ?? 1
        if (version === 1) return {id:s.id, designVersion:1, legacy:true, failed:false}
        const errors = [], rules = {}
        const rule = (name, code, measured, problems) => {
            problems.forEach(path=>errors.push({rule:name, code, path:s.id+'.'+path}))
            rules[name] = {passed:!problems.length, measured}
        }
        if (version !== 2 && version !== 3) {
            errors.push({rule:'designVersion', code:'InvalidDesignVersion', path:s.id+'.designVersion'})
            return {id:s.id, designVersion:version, legacy:false, failed:true, passed:false, errors, rules}
        }
        const own = m.geometry.elements.filter(e=>e.id.startsWith(s.id+'-'))
        const movers = m.geometry.movers.filter(v=>v.element.startsWith(s.id+'-'))
        const moving = new Set(movers.map(v=>v.element))
        const exceptions = new Map((s.solidExceptions||[]).map(x=>[x.element,x]))
        // Blue movers are exempt from the bounce default but must carry >=2 encounters.
        const moverCoverage = () => {
            const carrying = s.encounters.filter(id=>encounters.get(id).elements.some(e=>moving.has(e)))
            rule('moverCoverage', LAYOUT_V3_RULES.moverCoverage, {movers:movers.map(v=>v.id), encounters:carrying,
                count:carrying.length, required:2}, carrying.length >= 2 ? [] : ['movers'])
        }
        // Travel alternates: odd sections exit right of entry, even sections left.
        const direction = () => {
            const first = encounters.get(s.encounters[0]), last = encounters.get(s.encounters[3])
            const entryX = first.start?.x ?? first.x, exitX = last.exit ? (last.exit.left+last.exit.right)/2 : last.x
            const required = s.order % 2 ? 'right' : 'left'
            const actual = exitX > entryX ? 'right' : exitX < entryX ? 'left' : 'none'
            rule('direction', LAYOUT_V3_RULES.direction, {entryX, exitX, required, actual},
                actual === required ? [] : ['direction'])
        }
        // Mandatory gaps sit in the frozen band for the active range.
        const gapBand = (code, ranges, targets) => {
            const range = s.order >= upgradeOrder ? ranges.upgraded : ranges.base, target = targets[range]
            const gaps = (s.gaps||[]).filter(g=>g.mandatory !== false).map(g=>{
                const distance = Math.hypot(g.to.x-g.from.x, g.to.y-g.from.y)
                return {id:g.id, distance, fraction:distance/range,
                    inBand:distance >= target[0] && distance <= target[1]}
            })
            rule('gapBand', code, {range, target, gaps},
                [...(Array.isArray(s.gaps) ? [] : ['gaps']), ...gaps.filter(g=>!g.inBand).map(g=>'gaps.'+g.id)])
            return range
        }
        if (version === 3) {
            // No gray pads: every static solid is a stray, and no exception is accepted.
            const statics = own.filter(e=>e.role === 'solid' && !moving.has(e.id)).map(e=>e.id)
            rule('graySolid', LAYOUT_V3_RULES.graySolid, {staticSolids:statics, movers:[...moving],
                solidExceptions:s.solidExceptions ?? null},
                [...(s.solidExceptions !== undefined ? ['solidExceptions'] : []), ...statics])
            moverCoverage()
            direction()
            const range = gapBand(LAYOUT_V3_RULES.gapBand, LAYOUT_V3_RANGE, LAYOUT_V3_GAP_TARGETS)
            // Each declared fall/miss point has a drag zone in its column above the first bouncer.
            const falls = (s.fallPoints||[]).map(f=>({...fallColumn(f), ownEncounter:s.encounters.includes(f.encounter)}))
            rule('dragUnderFall', LAYOUT_V3_RULES.dragUnderFall, {columnRadius:LAYOUT_V3_FALL_COLUMN_RADIUS, fallPoints:falls},
                [...(Array.isArray(s.fallPoints) ? [] : ['fallPoints']),
                    ...falls.filter(f=>!f.ownEncounter || !f.dragZones.length).map(f=>'fallPoints.'+f.id)])
            // Drag zones exist only under declared fall points.
            const drags = own.filter(e=>e.role === 'drag').map(d=>({id:d.id,
                fallPoints:v3Falls.filter(f=>f.dragZones.includes(d.id)).map(f=>f.id)}))
            rule('strayDrag', LAYOUT_V3_RULES.strayDrag, {dragZones:drags},
                drags.filter(d=>!d.fallPoints.length).map(d=>d.id))
            const height = s.band.bottom-s.band.top, width = s.band.right-s.band.left
            rule('extent', LAYOUT_V3_RULES.extent, {bandHeight:height, bandWidth:width, encounters:s.encounters.length,
                frozen:LAYOUT_V3_EXTENT}, height === LAYOUT_V3_EXTENT.bandHeight && width <= LAYOUT_V3_EXTENT.horizontalEnvelope &&
                s.encounters.length === LAYOUT_V3_EXTENT.encountersPerSection ? [] : ['band'])
            return {id:s.id, designVersion:3, legacy:false, failed:!!errors.length, passed:!errors.length, range, errors, rules}
        }
        // Grappleable platforms bounce; solid only through a reasoned exception.
        let problems = [], platforms = [], excepted = []
        for (const x of exceptions.values()) {
            const e = elements.get(x.element), width = e ? box(e).right-box(e).left : null
            excepted.push({element:x.element, kind:x.kind, reason:x.reason, width})
            if (!e || !x.element.startsWith(s.id+'-') || !LAYOUT_V2_SOLID_EXCEPTIONS.includes(x.kind) ||
                typeof x.reason !== 'string' || !x.reason.trim() ||
                (x.kind === 'rest-pad' && width > LAYOUT_V2_REST_PAD_MAX_WIDTH))
                problems.push('solidExceptions.'+x.element)
        }
        for (const e of own) {
            if (e.grapplable !== true || !['solid','bounce'].includes(e.role)) continue
            const mover = moving.has(e.id)
            platforms.push({id:e.id, role:e.role, mover, exception:exceptions.has(e.id)})
            if (e.role === 'solid' && !mover && !exceptions.has(e.id)) problems.push(e.id)
        }
        rule('bounceDefault', 'LayoutV2StraySolid', {platforms, exceptions:excepted,
            restPadMaxWidth:LAYOUT_V2_REST_PAD_MAX_WIDTH}, problems)
        moverCoverage()
        direction()
        const range = gapBand('LayoutV2GapBand', LAYOUT_V2_RANGE, LAYOUT_V2_GAP_TARGETS)
        // Each fall line lands in the section below under a drag zone.
        const below = m.sections.find(b=>b.order === s.order-1)
        const drags = m.geometry.elements.filter(e=>e.role === 'drag')
        const fallLines = (s.fallLines||[]).map(f=>{
            const landing = elements.get(f.landing), lb = landing && box(landing)
            const onBelow = !!landing && (below ? f.landing.startsWith(below.id+'-') : f.landing === 'mountain-catch')
            const zone = lb && drags.find(d=>{const b = box(d)
                return b.left <= f.x && b.right >= f.x && b.bottom <= lb.top})
            return {id:f.id, x:f.x, landing:f.landing, landingSection:below ? below.id : 'base',
                landingTop:lb ? lb.top : null, onBelow, underLanding:!!lb && lb.left <= f.x && lb.right >= f.x,
                dragZone:zone ? zone.id : null, dragZoneBottom:zone ? box(zone).bottom : null}
        })
        rule('fallDrag', 'LayoutV2FallDrag', {fallLines},
            fallLines.filter(f=>!f.onBelow || !f.underLanding || !f.dragZone).map(f=>'fallLines.'+f.id))
        return {id:s.id, designVersion:2, legacy:false, failed:!!errors.length, passed:!errors.length, range, errors, rules}
    })
    return {sections, v2:sections.filter(s=>s.designVersion === 2).map(s=>s.id),
        v3:sections.filter(s=>s.designVersion === 3).map(s=>s.id),
        legacy:sections.filter(s=>s.legacy).map(s=>s.id), failed:sections.some(s=>s.failed)}
}

function validateMountainManifest(m)
{
    const fail = (code, path) => {throw new Error(code + ': ' + path)}
    const walk = (v, path='manifest') => {
        if (!v || typeof v !== 'object') return
        for (const [k,value] of Object.entries(v)) {
            if (/checkpoint|respawn|highestProgress/i.test(k)) fail('ForbiddenCheckpoint', path + '.' + k)
            if (typeof value === 'number' && !Number.isFinite(value)) fail('NonFiniteGeometry', path + '.' + k)
            walk(value, path + '.' + k)
        }
    }
    walk(m)
    if (m.schemaVersion !== 1 || m.geometryVersion !== m.geometry.version) fail('UnsupportedVersion','mountain')
    const range = m.range
    if (!range || typeof range !== 'object' || Object.keys(range).sort().join() !== 'base,upgradeBand,upgraded' ||
        range.base !== 1080 || range.upgraded !== 1620 || range.upgradeBand !== 'S05')
        fail('InvalidRange','mountain.range')
    if (m.ascent !== 12960 || m.horizontalEnvelope !== 6480 ||
        m.bounds.right-m.bounds.left !== 6480 || m.base.y-m.summit.y !== 12960 ||
        m.startSection !== 'S01' || m.spawn.x !== m.base.x || m.spawn.y !== m.base.y)
        fail('InvalidMountainExtent','mountain')
    if (m.sections.length !== 8 || m.encounters.length !== 32) fail('InvalidSectionOrder','count')
    const ids = new Set()
    const rows = [...m.sections,...m.encounters,...m.connectors,...m.recoveries,...m.shortcuts,
        ...m.sections.map(s=>s.landmark),m.base,m.summit,...m.geometry.elements,...m.geometry.movers]
    for (const r of rows) {
        if (typeof r.id !== 'string' || !r.id.trim()) fail('InvalidId','mountain')
        if (ids.has(r.id)) fail('DuplicateId',r.id)
        ids.add(r.id)
    }
    const nodes = new Map([m.base,m.summit,...m.encounters].map(e=>[e.id,e]))
    for (const n of [...nodes.values(),...m.sections.map(s=>s.landmark)]) {
        if (![n.x,n.y].every(Number.isFinite)) fail('NonFiniteGeometry',n.id)
        if (n.x < m.bounds.left || n.x > m.bounds.right || n.y < m.summit.y || n.y > m.base.y)
            fail('InvalidMountainExtent',n.id)
    }
    m.sections.forEach((s,i)=>{
        const id='S'+String(i+1).padStart(2,'0')
        if (s.id !== id || s.order !== i+1 || s.band.bottom !== m.base.y-i*1620 ||
            (s.designVersion !== 3 && s.band.top !== s.band.bottom-1620) || s.band.left !== m.bounds.left || s.band.right !== m.bounds.right ||
            s.encounters.length !== 4) fail('InvalidSectionOrder',s.id)
        if (!['planned','partial','built'].includes(s.status)) fail('InvalidBuildStatus',s.id)
        s.encounters.forEach((eid,j)=>{
            const e=nodes.get(eid)
            if (!e || eid !== id+'-0'+(j+1) || e.section !== id) fail('MissingReference',eid)
            if (e.y < s.band.top || e.y > s.band.bottom) fail('InvalidSectionOrder',eid)
            if (!['planned','built'].includes(e.status) || (e.status==='planned' && e.elements.length) ||
                (e.status==='built' && !e.elements.length)) fail('InvalidBuildStatus',eid)
        })
        const built=s.encounters.filter(id=>nodes.get(id).status==='built').length
        if (s.status !== (built===4 ? 'built' : built ? 'partial' : 'planned')) fail('InvalidBuildStatus',s.id)
    })
    for (const r of [...m.connectors,...m.recoveries,...m.shortcuts]) {
        if (!nodes.has(r.from) || !nodes.has(r.to)) fail('MissingReference',r.id)
        if (!['planned','built'].includes(r.status)) fail('InvalidBuildStatus',r.id)
        if (r.status==='built' && [r.from,r.to].some(id=>nodes.get(id).status==='planned')) fail('InvalidBuildStatus',r.id)
    }
    const route = ['base', ...m.sections.flatMap(s=>s.encounters), 'summit']
    if (m.connectors.length !== route.length-1 || route.slice(1).some((to,i)=>
        !m.connectors.some(r=>r.from===route[i] && r.to===to))) fail('MissingReference','normal route')
    if (m.recoveries.length !== 8 || m.sections.some(s=>
        !m.recoveries.some(r=>r.from===s.encounters[3]))) fail('MissingReference','recovery routes')
    if (m.shortcuts.length !== 2 || m.shortcuts.some((s,i)=>
        s.from !== ['S03-01','S07-01'][i] || s.to !== ['S03-04','S07-04'][i] || s.optional !== true))
        fail('InvalidShortcut','shortcuts')
    for (const r of m.recoveries) {
        if (r.transport !== 'physical-fall' || nodes.get(r.to).y <= nodes.get(r.from).y)
            fail('InvalidRecovery',r.id)
    }
    // The finish trigger exists only once the summit approach is authored.
    const summitBuilt = m.sections[7].status === 'built' && m.connectors.at(-1).status === 'built'
    const level = {version:m.geometry.version,bounds:m.bounds,spawn:m.spawn,finish:summitBuilt ? m.finish : null,
        sections:m.sections,encounters:m.encounters,elements:m.geometry.elements,movers:m.geometry.movers}
    validateFixedLevel(level)
    // Structural boundary guard, not a reachability proof: continuous catch floor
    // must itself accept a grapple, walls must sit outside the playable envelope,
    // and no polygon may seal the full width above it or enclose the spawn.
    const box = e => ({left:e.x+Math.min(...e.points.map(p=>p.x)),right:e.x+Math.max(...e.points.map(p=>p.x)),
        top:e.y+Math.min(...e.points.map(p=>p.y)),bottom:e.y+Math.max(...e.points.map(p=>p.y))})
    const catchFloor=m.geometry.elements.find(e=>e.id==='mountain-catch')
    if (!catchFloor || catchFloor.role !== 'solid' || catchFloor.grapplable !== true ||
        box(catchFloor).left !== m.bounds.left || box(catchFloor).right !== m.bounds.right ||
        box(catchFloor).top !== m.bounds.bottom) fail('BoundaryTrap','catch-floor')
    for (const e of m.geometry.elements) {
        const b=box(e)
        if (e.grapplable !== undefined && typeof e.grapplable !== 'boolean') fail('InvalidSurfaceRole',e.id)
        if (e.id==='mountain-catch') continue
        if (e.id==='mountain-left' || e.id==='mountain-right') {
            if (e.role !== 'solid' || e.grapplable !== false || b.top > m.bounds.top || b.bottom < m.bounds.bottom ||
                (e.id==='mountain-left' ? b.right !== m.bounds.left : b.left !== m.bounds.right)) fail('BoundaryTrap',e.id)
        } else if (b.left < m.bounds.left || b.right > m.bounds.right || b.top < m.bounds.top || b.bottom > m.bounds.bottom ||
            (b.left <= m.bounds.left && b.right >= m.bounds.right) ||
            (m.spawn.x+18 > b.left && m.spawn.x-18 < b.right && m.spawn.y+18 > b.top && m.spawn.y-18 < b.bottom))
            fail('BoundaryTrap',e.id)
    }
    for (const id of ['mountain-left','mountain-right']) if (!ids.has(id)) fail('BoundaryTrap',id)
    const failed = layoutV2Report(m).sections.find(s=>s.failed)
    if (failed) fail(failed.errors[0].code, failed.errors[0].path)
    return level
}

// Replacement built prefix: four Loading Yard encounters only. Planned terrain stays noncollidable.
const GRAPPLE_OVER_REPLACEMENT = {
    layoutId: 'grapple-over-replacement-v1', version: 1,
    bounds: {left: 0, right: 6480, top: -3000, bottom: 280},
    spawn: {x: 2160, y: 0}, finish: null,
    sections: [
        {id: 'S01', labelKey: 'climb.section.loadingYard', status: 'built', encounters: ['S01-01', 'S01-02', 'S01-03', 'S01-04']},
        {id: 'S05', status: 'planned', encounters: ['preview-future'],
            band: {left: 0, right: 6480, top: -3000, bottom: -2000}}
    ],
    encounters: [
        {id: 'S01-01', name: 'Loading Yard', elements: ['yard-entry', 'yard-landing', 'yard-anchor', 'yard-catch']},
        {id: 'S01-02', name: 'Loading Yard raised bay', elements: ['yard-landing', 'yard-second-anchor', 'yard-second-landing', 'yard-catch']},
        {id: 'S01-03', name: 'Loading Yard return terrace', elements: ['yard-second-landing', 'yard-third-anchor', 'yard-third-landing', 'yard-catch']},
        {id: 'S01-04', name: 'Loading Yard section exit', elements: ['yard-third-landing', 'yard-fourth-anchor', 'yard-fourth-landing']},
        {id: 'preview-future', elements: ['preview-unbuilt']}
    ],
    // TASK-564 opening envelope, translated to the actual preview spawn.
    // Green shelves bounce; planning surfaces do not promise static standing.
    elements: [
        ['yard-entry', 1700, 11.8, 540, 60, 'Broad base entry and takeoff planning shelf'],
        ['yard-landing', 2492, 11.8, 540, 60, 'Broad safe exit for the first release jump'],
        ['yard-anchor', 2340, -179, 160, 80, 'Reachable launch face; not a designated landing'],
        ['yard-second-anchor', 3072, -239, 160, 80, 'Second bay launch face; reachable from the shared planning shelf, not a landing'],
        ['yard-second-landing', 3284, -48.2, 540, 60, 'Raised second bay landing, planning area and local catch for the return jump; 60 units above entry'],
        ['yard-third-anchor', 3080, -419, 160, 80, 'Upper return launch face; leftward pull from the raised bay, not a landing'],
        ['yard-third-landing', 2492, -288.2, 540, 60, 'Broad upper return terrace; reverses travel above the first bay'],
        ['yard-fourth-anchor', 2700, -659, 160, 80, 'Final bay launch face; combines the leftward release with the upper terrace approach'],
        ['yard-fourth-landing', 1700, -528.2, 540, 60, 'Broad Loading Yard section exit; ordinary green terrain with local recovery via the third terrace'],
        ['yard-catch', 0, 220, 6480, 60, 'Lower recovery floor; return via the entry or landing shelf'],
        ['preview-unbuilt', 2160, -2200, 200, 40, 'Planned only; never emitted']
    ].map(([id, x, y, w, h, purpose]) => ({id, x, y, purpose, role: 'bounce', grapplable: true,
        points: [{x:0,y:0},{x:w,y:0},{x:w,y:h},{x:0,y:h}]})),
    movers: []
}

function replacementMountainLevel(manifest)
{
    validateFixedLevel(manifest)
    let planned = false
    for (const section of manifest.sections) {
        if (!['built', 'planned'].includes(section.status) || (planned && section.status === 'built'))
            throw new Error('InvalidBuiltPrefix: ' + section.id)
        planned ||= section.status === 'planned'
    }
    const sections = manifest.sections.filter(s => s.status === 'built')
    const encounterIds = new Set(sections.flatMap(s => s.encounters))
    const encounters = manifest.encounters.filter(e => encounterIds.has(e.id))
    const elementIds = new Set(encounters.flatMap(e => e.elements))
    return {...manifest, sections, encounters,
        elements: manifest.elements.filter(e => elementIds.has(e.id)),
        movers: manifest.movers.filter(m => elementIds.has(m.element)),
        finish: !planned && sections.some(s => s.id === 'S08') ? manifest.finish : null, profile: REPLACEMENT_PROFILE}
}

function loadMountainLevel(manifest = GRAPPLE_OVER_PREVIEW ? GRAPPLE_OVER_REPLACEMENT : GRAPPLE_OVER_MOUNTAIN)
{
    if (manifest.layoutId === GRAPPLE_OVER_REPLACEMENT.layoutId)
        return loadFixedLevel(replacementMountainLevel(manifest))
    return loadFixedLevel({...validateMountainManifest(manifest),
        layoutId: 'grapple-over-legacy-v3', profile: MODE_DEFINITIONS.grapple_over})
}

// Measured replacement authoring envelopes (TASK-560). Test-only playground
// consumes these; activation and full-mountain placement are separate work.
const GRAPPLE_OVER_MOVEMENT = Object.freeze({
    panelThickness: 60,
    minimumLandingLength: 360,
    openingRecoveryLength: 540,
    anchorFace: Object.freeze({width: 160, height: 80, landingSurface: false}),
    observationTicks: 150,
    patterns: Object.freeze([
        Object.freeze({name:'opening',radius:360,width:540,gap:252,dx:180,dy:180,release:30}),
        Object.freeze({name:'base',radius:360,width:360,gap:216,dx:120,dy:180,release:24}),
        Object.freeze({name:'upgraded',radius:540,width:360,gap:324,dx:180,dy:180,release:30})
    ])
});

// Isolated replacement teaching examples; not placed in the live mountain.
// Slowest tested cycle in the 6..10 s calibration range. Blue faces are anchors,
// not landing pads. The broad solid fixtures permit waiting without bouncing.
const GRAPPLE_OVER_MOVERS = Object.freeze({
    width:160, height:80, displacement:720, periodMs:10000,
    examples:Object.freeze([
        Object.freeze({axis:'x',min:600,max:1320,startPhase:0,spawnX:500,
            takeoff:[0,1040,540,60],blue:[600,800,160,80],landing:[1200,1100,540,60]}),
        Object.freeze({axis:'y',min:80,max:800,startPhase:.5,spawnX:850,
            takeoff:[800,1040,540,60],blue:[600,80,160,80],landing:[785,400,540,60]})
    ])
});

// TASK-562 isolated fall-braking envelope, consumed by the replacement playground.
// No legacy pad geometry or damping coefficients change. Recovery goes around
// the east edge; nominal ascent uses that clear lateral corridor.
const GRAPPLE_OVER_YELLOW = Object.freeze({
    band: Object.freeze({left:-1200,top:0,width:2400,height:600}),
    thicknessCandidates: Object.freeze([150,300,450,600]),
    clearance:600, range:540, fall: Object.freeze({x:1100,y:-2400}),
    landing: Object.freeze([-1400,1200,3800,60]),
    returnHook: Object.freeze([1400,1140,160,60]),
    returnWall: Object.freeze([1800,-1000,80,1900])
});
