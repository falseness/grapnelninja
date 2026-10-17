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
        bouncer('S01-exit',4060,-1620,200,55)
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
            {id:'S01-04-short',encounter:'S01-04',x:6460,y:-3300}]});
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
    Object.assign(recoveries[0], {status:'built',elements:['S01-yard-drag','S01-exit-drag','S01-floor'],
        rejoin:'S01-02',sideRoute:'Every declared S01 miss falls through a drag zone onto the green floor bouncers and settles; a green yard-pad pull and a blue lift pull rejoin the route through the deflector'});
    // Switchback Shaft v3 (layout v3, TASK-550): no gray pads. Travelling left from the
    // green S01 exit pad at the doubled 1080-range distances, between opposing shaft walls.
    // S01's exit drag zone kills horizontal speed, so the hoist pull is near-vertical.
    // S02-01: from the S01 exit pad, pull the blue hoist up out of the exit drag zone and
    // release up-left into the green canopy, which turns the climb into a down-left drop.
    // S02-02: on that drop, catch the blue lift, swing left under it and release into the
    // green west bulkhead, which rebounds the player right. S02-03/04 are planned. The
    // canopy, hoist and bulkhead stay clear of the S01-03/04 flight (apex ~-3640).
    const shaft = [
        rectangle('S02-hoist',6040,-3710,120,30,true),
        bouncer('S02-canopy',5700,-4320,360,30),
        rectangle('S02-lift',4925,-4705,120,30,true),
        bouncer('S02-bulkhead',4840,-4300,30,500),
        // v2 pads kept (converted to green) only as references of the v2 Broken Viaduct:
        // the S03-01 start pad and the S03-02 fall-line landing.
        bouncer('S02-landing',2987,-2100,200,40),
        bouncer('S02-exit-pad',2000,-2680,200,40)
    ];
    // Every declared S02 miss drops into an S01 drag zone, so S02 adds none of its own.
    const shaftDrags = [];
    const shaftMovers = [
        {id:'S02-hoist-travel',element:'S02-hoist',axis:'y',min:-3710,max:-3630,periodMs:4000,phase:0,velocity:40},
        {id:'S02-lift-travel',element:'S02-lift',axis:'y',min:-4705,max:-4625,periodMs:4000,phase:0,velocity:40}];
    Object.assign(sections[1], {status:'partial', designVersion:3, landmark:{id:'S02-landmark',
        name:'alternating industrial balconies',x:5450,y:-4000},
        band:{...sections[1].band, top:-4860},
        // Rope-to-anchor reach from the player at the press to the acquisition point.
        gaps:[{id:'S02-01-hoist',from:{x:6373.4,y:-2711.1},to:{x:6109.6,y:-3637}},
            // Caught in flight on the drop off the canopy.
            {id:'S02-02-lift',from:{x:5863.4,y:-4163.6},to:{x:5029.3,y:-4642}}],
        // Declared miss points: a short hoist pull settles back on the S01 exit pad; a
        // missed lift catch drops off the canopy; the bulkhead rebound with no further
        // catch crosses to the right wall and drops along it. Each falls through an S01
        // drag zone onto a green bouncer.
        fallPoints:[{id:'S02-01-short',encounter:'S02-01',x:6355,y:-3000},
            {id:'S02-02-missed',encounter:'S02-02',x:5650,y:-3800},
            {id:'S02-02-rebound',encounter:'S02-02',x:6460,y:-3150}]});
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
    for (const i of [6,7]) Object.assign(encounters[i], {status:'planned', elements:[]});
    Object.assign(connectors[4], {status:'built',intent:'Physical ascent: the S02-01 hoist pull starts on the v3 Foundations exit pad'});
    connectors[5].status='built';
    Object.assign(recoveries[1], {status:'planned',elements:[],
        intent:'Replanned with S02-03/04 (layout v3); S02-01/02 misses already fall into the S01 drag zones'});
    // Broken Viaduct v2 (layout v2): travelling right from the Switchback exit pad.
    // S03-01: blue departure carriage pulled up-right; the swing skims its underside and
    // carries rightward speed onto the pier pad. S03-02: blue span lift pulled from the
    // pier; release across the broken span (landing far beyond the 540 range) into the
    // green buffer, whose rebound settles on the far deck against its tall left lip.
    // S03-03: steep green crest-hook pull that clears the buffer top, then the ledge is
    // acquired in flight past the apex and pulls the arc down into the ledge brake.
    // S03-04: blue trolley pulled up-right; the arc brakes into the narrower exit pad.
    // TASK-513 tolerance: the buffer top is lowered to -3490 (short S03-02 arcs still
    // strike its face below -3420; S03-03 arcs cross it above -3531) and the crest hook
    // is 90 wide, so steep S03-03 arcs clear the buffer top and the hook's right end; the exit pad's right lip rises 140 so long trolley
    // arcs drop onto the pad instead of resting on the lip or flying past it.
    const viaduct = [
        rectangle('S03-carriage',2190,-3150,120,30,true),
        lowRest('S03-pier',2420,-3000,200),
        rectangle('S03-lift',2858,-3436,120,30,true),
        lowRest('S03-far-deck',3330,-3250,200,60,true),
        {id:'S03-span-buffer',x:3500,y:-3490,role:'bounce',grapplable:true,
            points:[{x:0,y:0},{x:30,y:0},{x:30,y:240},{x:0,y:240}]},
        {...rectangle('S03-crest-hook',3443,-3745,90,30,true),role:'bounce'},
        lowRest('S03-ledge',4007,-3630,200),
        rectangle('S03-trolley',4303,-4085,120,30,true),
        lowRest('S03-exit-pad',4600,-3830,150,140)
    ];
    // Pass-through brakes: the in-flight ledge catch settles on the ledge deck, and the
    // trolley arc sheds horizontal speed over the narrower exit pad before its tall lip.
    const viaductBrake = {id:'S03-ledge-brake',x:4007,y:-3710,role:'drag',grapplable:false,
        points:[{x:0,y:0},{x:200,y:0},{x:200,y:80},{x:0,y:80}]};
    const exitBrake = {id:'S03-exit-brake',x:4600,y:-3920,role:'drag',grapplable:false,
        points:[{x:0,y:0},{x:150,y:0},{x:150,y:90},{x:0,y:90}]};
    // S03 fall line: short S03-02 releases rebound off the span buffer back over the
    // broken span; this column sheds their leftward speed so they drop onto the S02
    // landing deck. It sits below the S03-02 flight (y ~-3380) and above the S02-03 pull.
    const viaductDrag = {id:'S03-fall-drag',x:3030,y:-3310,role:'drag',grapplable:false,
        points:[{x:0,y:0},{x:110,y:0},{x:110,y:910},{x:0,y:910}]};
    const viaductMovers = [
        {id:'S03-carriage-travel',element:'S03-carriage',axis:'x',min:2190,max:2310,periodMs:4000,phase:0,velocity:60},
        {id:'S03-lift-travel',element:'S03-lift',axis:'y',min:-3436,max:-3356,periodMs:4000,phase:0,velocity:40},
        {id:'S03-trolley-travel',element:'S03-trolley',axis:'x',min:4303,max:4423,periodMs:4000,phase:0,velocity:60}];
    Object.assign(sections[2], {status:'built', designVersion:2, landmark:{id:'S03-landmark',
        name:'interrupted elevated bridge',x:2900,y:-3300},
        solidExceptions:[
            {element:'S03-pier',kind:'rest-pad',reason:'S03-01 landing / S03-02 launch rest; low right end stop catches the carriage swing'},
            {element:'S03-far-deck',kind:'rest-pad',reason:'S03-02 landing / S03-03 launch rest across the broken span; tall left lip stops the buffer rebound'},
            {element:'S03-ledge',kind:'rest-pad',reason:'S03-03 landing / S03-04 launch rest under the ledge brake, low right end stop'},
            {element:'S03-exit-pad',kind:'rest-pad',reason:'S03 exit rest, 150 wide under the exit brake; tall right lip stops the trolley landing'}],
        // Rope-to-anchor reach from the resting launch point to the nominal acquisition point.
        gaps:[{id:'S03-01-carriage',from:{x:2050.8,y:-2690.8},to:{x:2239.1,y:-3120}},
            {id:'S03-02-lift',from:{x:2569.2,y:-3010.8},to:{x:2886.6,y:-3354.7}},
            {id:'S03-03-crest',from:{x:3380.8,y:-3260.8},to:{x:3508,y:-3715}},
            {id:'S03-04-trolley',from:{x:4104.7,y:-3640.8},to:{x:4349.9,y:-4055}}],
        // Short S03-02 releases rebound off the buffer and drop onto the S02 landing deck.
        fallLines:[{id:'S03-02-short',x:3085,landing:'S02-landing'}]});
    // Encounter nodes sit on the band edge (y -3240) as the v1 S03 nodes did; the
    // starts below the band are the real rest poses.
    Object.assign(encounters[8], {status:'built',x:2051,y:-3240,
        elements:['S02-exit-pad','S03-carriage','S03-pier'],
        start:{x:2050.8,y:-2690.8,from:'S02-04'},target:{x:2240,y:-3125},
        exit:{left:2420,right:2580,top:-3020,bottom:-3000},
        action:'Pull the blue departure carriage up-right from the Switchback exit pad, skim its underside and carry the speed onto the pier pad'});
    Object.assign(encounters[9], {status:'built',x:2569,y:-3240,
        elements:['S03-pier','S03-lift','S03-span-buffer','S03-far-deck'],
        start:{from:'S03-01',x:2569.2,y:-3010.8},target:{x:2903,y:-3370},
        exit:{left:3370,right:3500,top:-3270,bottom:-3250},
        action:'Pull the blue span lift, release across the broken span beyond grapnel range into the green buffer and rebound onto the far deck'});
    Object.assign(encounters[10], {status:'built',x:3381,y:-3261,
        elements:['S03-far-deck','S03-span-buffer','S03-crest-hook','S03-ledge','S03-ledge-brake'],
        start:{from:'S03-02',x:3380.8,y:-3260.8},target:{x:3508,y:-3715},
        exit:{left:4007,right:4167,top:-3650,bottom:-3630},
        action:'Pull the green crest hook steeply over the span buffer, release, acquire the ledge in flight past the apex and brake onto it'});
    Object.assign(encounters[11], {status:'built',x:4105,y:-3641,
        elements:['S03-ledge','S03-trolley','S03-exit-pad','S03-exit-brake'],
        start:{from:'S03-03',x:4104.7,y:-3640.8},target:{x:4353,y:-4055},
        exit:{left:4600,right:4710,top:-3850,bottom:-3830},
        action:'Catch the blue trolley from the ledge, pull up-right, re-catch the trolley top in flight and brake into the narrower exit pad against its tall right lip'});
    Object.assign(connectors[8], {status:'planned',intent:'Physical ascent from the Switchback exit pad to the blue departure carriage; replanned until the S02 v3 exit is built'});
    for (let i=9;i<12;i++) connectors[i].status='built';
    Object.assign(recoveries[2], {status:'planned',elements:['S03-fall-drag','S02-landing'],
        rejoin:'S02-03',sideRoute:'Short S03-02 releases rebound off the span buffer, drop through the fall column onto the S02 landing deck and stop; the S02-03 crest-hook pull rejoins the Switchback route'});
    Object.assign(shortcuts[0], {intent:'Optional faster high-risk launch from S03-01 to S03-04; kept planned (not yet authored) for layout v2'});
    // Deflector Works v2 (layout v2): travelling left from the Viaduct exit pad, the
    // mirror image of the S03 opening (x' = 6726 - x, 1150 higher). S04-01: blue
    // carriage pulled up-left; the swing skims its underside and carries leftward speed
    // onto the pier pad. S04-02: blue lift pulled from the pier; release across the open
    // works floor (landing far beyond the 540 range) into the flat green press face,
    // whose reflection settles on the press deck against its tall right lip. The pier's
    // right end stays left of x 4250, clear of the S03-04 trolley arcs (x >= 4282).
    // Mover phases mirror the S03 movers at the S03 exit rest time (tick 3270 of the
    // base-start route). S04-03/04 are planned; until they are rebuilt the v1 upper
    // step and exit deck stay as the legacy Cable Galleries entrance.
    const deflectors = [
        rectangle('S04-carriage',4366,-4285,120,30,true),
        lowRest('S04-pier',4106,-4150,140,20,true),
        rectangle('S04-lift',3748,-4586+80*10/24,120,30,true),
        lowRest('S04-press-deck',3196,-4400,200,60),
        {id:'S04-flat-press',x:3196,y:-4640,role:'bounce',grapplable:true,
            points:[{x:0,y:0},{x:30,y:0},{x:30,y:240},{x:0,y:240}]},
        rest('S04-upper-step',4700,-6050,200),
        {id:'S04-exit',x:4460,y:-6480,role:'solid',grapplable:true,points:[{x:0,y:-180},{x:40,y:-180},{x:40,y:0},{x:160,y:0},{x:160,y:-30},{x:200,y:-30},{x:200,y:55},{x:0,y:55}]}
    ];
    deflectors.find(e=>e.id==='S04-upper-step').points.forEach(p=>{if(p.y===-60)p.y=-30;});
    deflectors.find(e=>e.id==='S04-upper-step').points.splice(0,1,{x:0,y:-180},{x:40,y:-180},{x:40,y:0});
    const worksMovers = [
        {id:'S04-carriage-travel',element:'S04-carriage',axis:'x',min:4296,max:4416,periodMs:4000,phase:17/24,velocity:-60},
        {id:'S04-lift-travel',element:'S04-lift',axis:'y',min:-4586,max:-4506,periodMs:4000,phase:5/24,velocity:40}];
    Object.assign(sections[3], {status:'partial', designVersion:2, landmark:{id:'S04-landmark',
        name:'angled green machinery',x:3800,y:-4900},
        solidExceptions:[
            {element:'S04-pier',kind:'rest-pad',reason:'S04-01 landing / S04-02 launch rest, 140 wide; low left end stop catches the carriage swing'},
            {element:'S04-press-deck',kind:'rest-pad',reason:'S04-02 landing rest under the flat press; tall right lip stops the reflection'},
            {element:'S04-upper-step',kind:'rest-pad',reason:'Legacy v1 Cable Galleries recovery step until S04-03/04 are rebuilt for layout v2'},
            {element:'S04-exit',kind:'rest-pad',reason:'Legacy v1 Cable Galleries entrance deck (S05-01 start) until S04-03/04 are rebuilt for layout v2'}],
        // Rope-to-anchor reach from the resting launch point to the nominal acquisition point.
        gaps:[{id:'S04-01-carriage',from:{x:4675.2,y:-3840.8},to:{x:4450.6,y:-4255}},
            {id:'S04-02-lift',from:{x:4156.8,y:-4160.8},to:{x:3839.4,y:-4504.7}}],
        fallLines:[]});
    // Encounter nodes sit on the band edge (y -4860); the starts below the band are the real rest poses.
    Object.assign(encounters[12], {status:'built',x:4675,y:-4860,
        elements:['S03-exit-pad','S04-carriage','S04-pier'],
        start:{x:4675.2,y:-3840.8,from:'S03-04'},target:{x:4466,y:-4225},
        exit:{left:4146,right:4246,top:-4170,bottom:-4150},
        action:'Pull the blue carriage up-left from the Viaduct exit pad, skim its underside and carry the speed onto the pier pad'});
    Object.assign(encounters[13], {status:'built',x:4157,y:-4860,
        elements:['S04-pier','S04-lift','S04-flat-press','S04-press-deck'],
        start:{from:'S04-01',x:4156.8,y:-4160.8},target:{x:3823,y:-4520},
        exit:{left:3226,right:3356,top:-4420,bottom:-4400},
        action:'Pull the blue lift, release across the works floor beyond grapnel range into the flat green press and reflect onto the press deck'});
    Object.assign(connectors[12], {status:'built',intent:'Physical ascent from the Viaduct exit pad to the blue carriage'});
    connectors[13].status='built';
    // Cable Galleries: cantilever girders and a deep service overhang. The
    // open shaft below the projecting tips returns misses to Deflector Works.
    const galleries = [
        {id:'S05-projecting-girder',x:4650,y:-6800,role:'solid',grapplable:true,
            points:[{x:0,y:0},{x:200,y:0},{x:200,y:-20},{x:240,y:-20},{x:240,y:35},{x:80,y:35},{x:80,y:110},{x:0,y:110}]},
        rest('S05-rest',4740,-6620,260),
        {id:'S05-deep-overhang',x:5000,y:-7100,role:'solid',grapplable:true,
            points:[{x:0,y:0},{x:250,y:0},{x:250,y:-20},{x:300,y:-20},{x:300,y:150},{x:230,y:150},{x:230,y:45},{x:0,y:45}]},
        rest('S05-lower-gallery',5100,-6810,260),
        {id:'S05-transfer-canopy',x:5420,y:-7400,role:'solid',grapplable:true,
            points:[{x:0,y:0},{x:230,y:0},{x:230,y:-25},{x:270,y:-25},{x:270,y:160},{x:180,y:160},{x:180,y:45},{x:0,y:45}]},
        rest('S05-upper-rest',5500,-7190,230),
        {id:'S05-recessed-ceiling',x:5800,y:-7720,role:'solid',grapplable:true,
            points:[{x:0,y:0},{x:230,y:0},{x:230,y:-25},{x:270,y:-25},{x:270,y:190},{x:210,y:190},{x:210,y:55},{x:65,y:55},{x:65,y:120},{x:0,y:120}]},
        {...rest('S05-exit',6200,-8070,240), points:[{x:0,y:0},{x:200,y:0},{x:200,y:-20},{x:240,y:-20},{x:240,y:55},{x:0,y:55}]}
    ];
    Object.assign(sections[4], {status:'built',landmark:{id:'S05-landmark',
        name:'projecting beams and deep overhangs',x:4990,y:-6900}});
    Object.assign(encounters[16], {status:'built',x:4530,y:-6480,
        elements:['S04-exit','S05-projecting-girder','S05-rest'],
        start:{from:'S04-04',x:4530,y:-6490.8},target:{x:4655,y:-6780},
        action:'Wrap the rope around the projecting girder corner; release onto the service rest',
        exit:{x:4839.2,y:-6810.8,width:200}});
    Object.assign(encounters[17], {status:'built',x:4839.2,y:-6800,
        elements:['S05-rest','S05-deep-overhang','S05-lower-gallery'],
        start:{from:'S05-01',x:4839.2,y:-6810.8},target:{x:5005,y:-7080},
        action:'Pull around the deep overhang using the wrapped segment; release onto its departure shelf',
        exit:{x:5239.2,y:-7110.8,width:250}});
    Object.assign(encounters[18], {status:'built',x:5420,y:-7400,
        elements:['S05-deep-overhang','S05-transfer-canopy','S05-upper-rest'],
        start:{from:'S05-02',x:5239.2,y:-7110.8},target:{x:5425,y:-7380},
        action:'Release beyond the overhang and reacquire the projecting canopy while airborne',
        exit:{x:5639.2,y:-7410.8,width:230}});
    Object.assign(encounters[19], {status:'built',x:5800,y:-7720,
        elements:['S05-upper-rest','S05-recessed-ceiling','S05-exit'],
        start:{from:'S05-03',x:5639.2,y:-7410.8},target:{x:5805,y:-7700},
        action:'Traverse the recessed ceiling around its lip; release and climb to the next band',
        exit:{left:6210.8,right:6389.2,top:-8082,bottom:-8070}});
    connectors[18].status='built';
    Object.assign(connectors[19], {status:'built',intent:'Exposed departure ledge to the next band; S06 counterweight entrance'});
    // Planned until S04-04 is rebuilt for layout v2; v1 S05-01 still starts on the legacy S04-exit deck.
    Object.assign(connectors[16], {intent:'Pull from the Works exit around the projecting girder; planned until S04-04 is rebuilt'});
    connectors[17].status='built';
    Object.assign(recoveries[4], {openingElements:['S05-rest','S04-exit','S04-upper-step'],
        openingRejoin:'S04-04',sideRoute:'Visible open shaft west of the girders; reachable Works mast and upper step'});
    // Liftworks opening: a travelling counterweight over a wide loading floor.
    // The open western edge drops onto the existing Galleries ceiling/recovery rests.
    const liftworks = [
        {...rest('S06-loading-floor',5780,-8130,400), points:[{x:0,y:0},{x:400,y:0},{x:400,y:15},{x:300,y:15},{x:300,y:30},{x:70,y:30},{x:70,y:15},{x:0,y:15}]},
        {id:'S06-counterweight',x:6060,y:-8480,role:'solid',grapplable:true,
            points:[{x:0,y:0},{x:100,y:0},{x:100,y:35},{x:125,y:35},{x:125,y:110},{x:-25,y:110},{x:-25,y:35},{x:0,y:35}]},
        {...rest('S06-phase-rest',5780,-8270,220), points:[{x:0,y:-20},{x:40,y:-20},{x:40,y:0},{x:220,y:0},{x:220,y:50},{x:70,y:50},{x:70,y:110},{x:0,y:110}]}
    ];
    // Alternating fixed heads and a second travelling weight form the upper lift.
    liftworks.push(
        {id:'S06-fixed-head',x:5480,y:-8610,role:'solid',grapplable:true,
            points:[{x:0,y:-20},{x:40,y:-20},{x:40,y:0},{x:240,y:0},{x:240,y:110},{x:170,y:110},{x:170,y:35},{x:0,y:35}]},
        {id:'S06-upper-weight',x:5780,y:-9010,role:'solid',grapplable:true,
            points:[{x:0,y:0},{x:100,y:0},{x:100,y:35},{x:125,y:35},{x:125,y:100},{x:-25,y:100},{x:-25,y:35},{x:0,y:35}]},
        {id:'S06-transfer-head',x:6100,y:-9300,role:'solid',grapplable:true,
            points:[{x:0,y:0},{x:220,y:0},{x:220,y:-25},{x:260,y:-25},{x:260,y:130},{x:190,y:130},{x:190,y:40},{x:0,y:40}]},
        {...rest('S06-exit',5520,-9680,260),points:[{x:0,y:-20},{x:40,y:-20},{x:40,y:0},{x:220,y:0},{x:220,y:-20},{x:260,y:-20},{x:260,y:55},{x:0,y:55}]}
    );
    const liftMovers = [...yardMovers, ...shaftMovers, ...viaductMovers, ...worksMovers, {id:'S06-counterweight-travel',element:'S06-counterweight',
        axis:'y',min:-8480,max:-8320,periodMs:4000,phase:0,velocity:80},
        {id:'S06-upper-weight-travel',element:'S06-upper-weight',axis:'y',
            min:-9010,max:-8890,periodMs:4000,phase:0,velocity:60}];
    Object.assign(sections[5], {status:'built',landmark:{id:'S06-landmark',
        name:'moving counterweights',x:6110,y:-8400}});
    Object.assign(encounters[20], {status:'built',x:6300,y:-8130,
        elements:['S05-exit','S06-loading-floor','S06-counterweight'],
        start:{from:'S05-04',x:6300,y:-8080.8},target:{x:6110,y:-8370},
        action:'Acquire the moving blue counterweight above the broad loading floor',
        exit:{left:6030,right:6200,top:-8500,bottom:-8300}});
    Object.assign(encounters[21], {status:'built',x:6110,y:-8400,
        elements:['S06-counterweight','S06-loading-floor','S06-phase-rest'],
        start:{from:'S06-01',attachedTo:'S06-counterweight'},target:{x:5900,y:-8270},
        action:'Remain attached through counterweight travel and reversal',
        exit:{left:5830.8,right:5989.2,top:-8282,bottom:-8270}});
    Object.assign(connectors[20], {status:'built',intent:'Acquire counterweight from the Galleries departure ledge'});
    Object.assign(connectors[21], {status:'built',intent:'Keep attachment through reversal before the rising-phase release'});
    Object.assign(encounters[22], {status:'built',x:5900,y:-8270,
        elements:['S06-counterweight','S06-phase-rest'],
        start:{from:'S06-02',attachedTo:'S06-counterweight'},target:{x:5900,y:-8270},
        action:'Release on the rising phase to settle behind the fixed rest end stop',
        exit:{left:5830.8,right:5989.2,top:-8282,bottom:-8270}});
    Object.assign(encounters[23], {status:'built',x:5830,y:-8970,
        elements:['S06-phase-rest','S06-fixed-head','S06-upper-weight','S06-transfer-head','S06-exit'],
        start:{from:'S06-03',x:5830.8,y:-8280.8},target:{x:5715,y:-8590},
        action:'Transfer from fixed head to travelling weight, then fixed upper head and exposed departure',
        exit:{left:5570.8,right:5729.2,top:-9692,bottom:-9680}});
    Object.assign(connectors[22], {status:'built',intent:'Rising-phase release onto ordinary fixed rest'});
    Object.assign(connectors[23], {status:'built',intent:'Alternating moving/fixed targets reach S06-exit at the Crown band; connects to the exposed rooftop entrance'});
    Object.assign(recoveries[5], {status:'built',
        elements:['S06-phase-rest','S06-loading-floor','S05-transfer-canopy','S05-recessed-ceiling'],
        openingElements:['S06-loading-floor','S05-exit','S05-recessed-ceiling'],
        openingRejoin:'S05-04',sideRoute:'Open western loading-floor edge returns to the static Galleries ceiling and rests'});
    // Open rooftop: a swept red rotor, torn service gantry and vent plinth.
    // All silhouettes are the actual collision polygons; no invisible helper floors.
    const crown = [
        {id:'S07-service-gantry',x:5310,y:-10030,role:'solid',grapplable:true,
            points:[{x:0,y:0},{x:240,y:0},{x:240,y:25},{x:200,y:45},{x:30,y:45},{x:0,y:25}]},
        {id:'S07-sweeper',x:5420,y:-9860,role:'hazard',grapplable:false,
            points:[{x:0,y:0},{x:90,y:0},{x:110,y:20},{x:90,y:40},{x:0,y:40},{x:-20,y:20}]},
        {id:'S07-rest-ledge',x:5060,y:-9740,role:'solid',grapplable:true,
            points:[{x:0,y:-30},{x:30,y:-30},{x:30,y:0},{x:320,y:0},{x:320,y:8},{x:280,y:8},{x:280,y:20},{x:40,y:20},{x:40,y:8},{x:0,y:8}]},
        {id:'S07-shortcut-jib',x:5130,y:-10040,role:'solid',grapplable:true,
            points:[{x:0,y:0},{x:140,y:0},{x:140,y:35},{x:90,y:35},{x:90,y:90},{x:55,y:90},{x:55,y:35},{x:0,y:35}]}
    ];
    liftMovers.push({id:'S07-rotor-sweep',element:'S07-sweeper',axis:'x',
        min:5420,max:5700,periodMs:3000,phase:0,velocity:186.66666666666666});
    Object.assign(sections[6],{status:'built',landmark:{id:'S07-landmark',
        name:'open rooftop machinery',x:5420,y:-9930}});
    Object.assign(encounters[24],{status:'built',x:5650,y:-9720,
        elements:['S06-exit','S07-service-gantry','S07-sweeper'],
        start:{x:5650,y:-9690.8,from:'S06-04'},target:{x:5430,y:-10000},
        exit:{left:5100.8,right:5369.2,top:-9762,bottom:-9740},
        action:'Watch the red rotor sweep from the Liftworks ledge; time a pull to the gray service gantry'});
    Object.assign(encounters[25],{status:'built',x:5270,y:-9740,
        elements:['S07-service-gantry','S07-rest-ledge','S07-shortcut-jib'],
        start:{from:'S07-01'},target:{x:5200,y:-9970},
        exit:{left:5100,right:5500,top:-10000,bottom:-9400,attachedTo:'S07-shortcut-jib'},
        rest:'S07-rest-ledge',
        action:'After rotor displacement, release and press again to catch the safe jib and brake the fall; the normal rooftop route has a broad rest ledge'});
    Object.assign(connectors[24],{status:'built',intent:'S06-exit exposes the rotor and safe gantry before commitment'});
    Object.assign(connectors[25],{status:'built',intent:'Normal gantry route reaches the vent-plinth rest; displaced players can catch the safe jib'});
    Object.assign(shortcuts[1],{openingStatus:'built',openingExit:'S07-02',
        elements:['S07-shortcut-jib','S07-rest-ledge']});
    Object.assign(recoveries[6],{openingElements:['S06-exit','S06-phase-rest','S05-projecting-girder'],
        openingRejoin:'S05-04',sideRoute:'Unwalled rooftop edges permit physical falls through Liftworks into Cable Galleries'});
    // The upper roof is open underneath: a missed launch can lose several bands.
    // A narrow eastern maintenance balcony offers a lower physical route back.
    crown.push(
        {id:'S07-launch-head',x:4850,y:-10090,role:'solid',grapplable:true,
            points:[{x:0,y:0},{x:150,y:0},{x:150,y:25},{x:105,y:45},{x:0,y:45}]},
        {id:'S07-roof-boom',x:5150,y:-10410,role:'solid',grapplable:true,
            points:[{x:0,y:0},{x:170,y:0},{x:170,y:30},{x:60,y:30},{x:40,y:65},{x:0,y:65}]},
        {id:'S07-upper-motor',x:5430,y:-10810,role:'solid',grapplable:true,
            points:[{x:0,y:15},{x:35,y:0},{x:150,y:0},{x:175,y:25},{x:175,y:55},{x:0,y:55}]},
        rest('S07-recovery-balcony',5480,-10180,340),
        {id:'S07-side-hoist',x:5690,y:-10510,role:'solid',grapplable:true,
            points:[{x:0,y:0},{x:100,y:0},{x:100,y:55},{x:65,y:55},{x:65,y:100},{x:35,y:100},{x:35,y:55},{x:0,y:55}]},
        {...rest('S07-exit',5240,-11340,150),points:[{x:0,y:-30},{x:20,y:-30},{x:20,y:0},{x:110,y:0},{x:110,y:-60},{x:150,y:-60},{x:150,y:55},{x:0,y:55}]}
    );
    Object.assign(encounters[26],{status:'built',x:5101,y:-9750,
        elements:['S07-rest-ledge','S07-launch-head','S07-roof-boom','S07-upper-motor'],
        start:{from:'S07-02',x:5101,y:-9750.8},target:{x:4995,y:-10060},
        action:'Launch across the open roof above earlier terrain; transfer from torn head to boom and motor',
        exit:{left:5400,right:5670,top:-10900,bottom:-10600}});
    Object.assign(encounters[27],{status:'built',x:5600,y:-10180,
        elements:['S07-recovery-balcony','S07-side-hoist','S07-upper-motor','S07-exit'],
        start:{from:'S07-03'},target:{x:5695,y:-10480},
        action:'Catch the lower eastern maintenance balcony after a miss; climb the side hoist and rejoin the motor before the departure ledge',
        exit:{left:5270.8,right:5339.2,top:-11352,bottom:-11340}});
    Object.assign(connectors[26],{status:'built',intent:'Rest at vent plinth before exposed head-to-boom launch'});
    Object.assign(connectors[27],{status:'built',intent:'Normal motor route and lower side hoist converge on S07-exit at the next band; S08 is not required'});
    Object.assign(shortcuts[1],{status:'built',elements:['S07-shortcut-jib','S07-rest-ledge','S07-launch-head','S07-roof-boom','S07-upper-motor','S07-exit'],
        intent:'Optional jib cut reaches the rest sooner, then shares the exposed head/boom crossing to S07-04; normal gantry route remains'});
    Object.assign(recoveries[6],{status:'built',elements:['S07-recovery-balcony','S07-side-hoist','S07-upper-motor'],
        rejoin:'S07-04',sideRoute:'Lower eastern balcony and hoist rejoin the upper motor; misses outside it fall physically into earlier sections'});
    // Summit Array opening: beacon arms, a davit brake, a green ramp and the
    // lamp mast. Every silhouette is its own collider; the mast is the landmark.
    const summit = [
        {id:'S08-launch-arm',x:4900,y:-11760,role:'solid',grapplable:true,
            points:[{x:0,y:0},{x:180,y:0},{x:180,y:30},{x:40,y:30},{x:0,y:12}]},
        {id:'S08-brake-davit',x:4880,y:-11880,role:'solid',grapplable:true,
            points:[{x:0,y:0},{x:100,y:0},{x:100,y:30},{x:65,y:30},{x:65,y:42},{x:35,y:42},{x:35,y:30},{x:0,y:30}]},
        {id:'S08-footing-rest',x:4260,y:-11600,role:'solid',grapplable:true,
            points:[{x:0,y:-20},{x:20,y:-20},{x:20,y:0},{x:200,y:0},{x:200,y:-60},{x:240,y:-60},{x:240,y:55},{x:0,y:55}]},
        {id:'S08-lamp-hook',x:4020,y:-11960,role:'solid',grapplable:true,
            points:[{x:0,y:0},{x:100,y:0},{x:100,y:30},{x:60,y:30},{x:50,y:45},{x:40,y:30},{x:0,y:30}]},
        {id:'S08-deflector-ramp',x:3520,y:-11800,role:'bounce',grapplable:true,
            points:[{x:0,y:0},{x:360,y:180},{x:345,y:210},{x:-15,y:30}]},
        {id:'S08-mast-yard',x:3400,y:-12200,role:'solid',grapplable:true,
            points:[{x:0,y:0},{x:100,y:0},{x:100,y:18},{x:80,y:30},{x:20,y:30},{x:0,y:18}]},
        {id:'S08-rest-ledge',x:3020,y:-12080,role:'solid',grapplable:true,
            points:[{x:0,y:-60},{x:40,y:-60},{x:40,y:0},{x:400,y:0},{x:400,y:-20},{x:420,y:-20},{x:420,y:55},{x:0,y:55}]},
        {id:'S08-beacon-mast',x:3020,y:-12140,role:'solid',grapplable:true,
            points:[{x:8,y:0},{x:32,y:0},{x:32,y:-460},{x:64,y:-460},{x:64,y:-540},{x:-24,y:-540},{x:-24,y:-460},{x:8,y:-460}]},
        // Misses west of the footing roll down a tilted spill deck to its east stop;
        // the pulley block above returns them onto the Crown boom and balcony.
        {id:'S08-spill-deck',x:3340,y:-11160,role:'solid',grapplable:true,
            points:[{x:0,y:-40},{x:30,y:-40},{x:30,y:2.5},{x:1440,y:120},{x:1440,y:105},{x:1480,y:105},{x:1480,y:160},{x:0,y:40}]},
        {id:'S08-recovery-hook',x:4950,y:-11450,role:'solid',grapplable:true,
            points:[{x:0,y:10},{x:20,y:0},{x:80,y:0},{x:100,y:10},{x:100,y:30},{x:0,y:30}]}
    ];
    Object.assign(sections[7],{status:'partial',landmark:{id:'S08-landmark',
        name:'distinct final beacon silhouette',x:3040,y:-12640}});
    Object.assign(encounters[28],{status:'built',x:5339,y:-11351,
        elements:['S07-exit','S08-launch-arm','S08-brake-davit','S08-footing-rest'],
        start:{from:'S07-04',x:5339.2,y:-11350.8},target:{x:5000,y:-11740},brakeTarget:{x:4930,y:-11865},
        exit:{left:4290.8,right:4449.2,top:-11612,bottom:-11600},
        action:'Pull up the launch arm and release west; brake on the opposing davit, then release onto the footing rest'});
    Object.assign(encounters[29],{status:'built',x:4291,y:-11611,
        elements:['S08-footing-rest','S08-lamp-hook','S08-deflector-ramp','S08-mast-yard','S08-rest-ledge'],
        start:{from:'S08-01',x:4290.8,y:-11610.8},target:{x:4070,y:-11945},transferTarget:{x:3450,y:-12185},
        exit:{left:3070.8,right:3409.2,top:-12092,bottom:-12080},
        rest:'S08-rest-ledge',
        action:'Pull the lamp hook, fall onto the angled green ramp, grab the mast yard in flight and release onto the beacon rest ledge'});
    Object.assign(connectors[28],{status:'built',intent:'S07-exit launches directly to the beacon arm; the davit and footing rest are visible before commitment'});
    Object.assign(connectors[29],{status:'built',intent:'Footing rest separates the brake from the bounce transfer; S08-02 ends on the beacon rest ledge'});
    Object.assign(recoveries[7],{openingElements:['S08-spill-deck','S08-recovery-hook','S07-roof-boom','S07-recovery-balcony'],
        openingRejoin:'S07-03',sideRoute:'Western misses collect on the spill deck; the recovery hook throws players back onto the Crown boom or balcony. Eastern misses fall through the Crown into Liftworks. No hazards.'});
    // Summit Array finish: the rest ledge sits under the beacon-deck overhang. A blue
    // carriage rises beyond its lip and swings players up onto the array deck; the
    // summit gantry then sets them down on the final beacon pad. No new hazards.
    summit.push(
        {id:'S08-beacon-deck',x:3052,y:-12390,role:'solid',grapplable:true,
            points:[{x:0,y:0},{x:368,y:0},{x:368,y:-50},{x:348,y:-50},{x:348,y:-30},{x:0,y:-30}]},
        {id:'S08-overhang-carriage',x:3440,y:-12620,role:'solid',grapplable:true,
            points:[{x:0,y:0},{x:100,y:0},{x:100,y:28},{x:70,y:40},{x:30,y:40},{x:0,y:28}]},
        {id:'S08-array-deck',x:3900,y:-12700,role:'solid',grapplable:true,
            points:[{x:0,y:-20},{x:20,y:-20},{x:20,y:0},{x:300,y:0},{x:300,y:-120},{x:340,y:-120},{x:340,y:55},{x:0,y:55}]},
        {id:'S08-summit-gantry',x:3700,y:-12930,role:'solid',grapplable:true,
            points:[{x:0,y:0},{x:120,y:0},{x:120,y:30},{x:80,y:45},{x:40,y:45},{x:0,y:30}]},
        {id:'S08-summit-pad',x:3380,y:-12760,role:'solid',grapplable:true,
            points:[{x:0,y:55},{x:0,y:-160},{x:-40,y:-180},{x:20,y:-200},{x:80,y:-180},{x:40,y:-160},
                {x:40,y:0},{x:320,y:0},{x:320,y:-20},{x:340,y:-20},{x:340,y:55}]}
    )
    liftMovers.push({id:'S08-carriage-lift',element:'S08-overhang-carriage',axis:'y',
        min:-12620,max:-12340,periodMs:4000,phase:0,velocity:140});
    const finish = {left:3420,right:3700,top:-12772,bottom:-12760}
    // The diamond lamp on the summit pad is the final beacon; the lower mast is a waypoint.
    Object.assign(sections[7],{status:'built',landmark:{id:'S08-landmark',
        name:'distinct final beacon silhouette',x:3400,y:-12940}});
    Object.assign(encounters[30],{status:'built',x:3071,y:-12091,
        elements:['S08-rest-ledge','S08-beacon-deck','S08-overhang-carriage','S08-array-deck'],
        start:{from:'S08-02',x:3070.8,y:-12090.8},target:{x:3490,y:-12338},
        exit:{left:3930.8,right:4189.2,top:-12712,bottom:-12700},
        action:'Catch the blue carriage beyond the overhang lip on its low turn, ride it up and release onto the array deck'});
    Object.assign(encounters[31],{status:'built',x:4189,y:-12711,
        elements:['S08-array-deck','S08-summit-gantry','S08-summit-pad'],
        start:{from:'S08-03',x:4189.2,y:-12710.8},target:{x:3760,y:-12890},
        exit:finish,finishRegion:finish,
        action:'Pull the summit gantry and release to settle on the final beacon pad inside the finish region'});
    Object.assign(connectors[30],{status:'built',intent:'Rest ledge under the overhang shows the carriage and array deck before commitment'});
    Object.assign(connectors[31],{status:'built',intent:'Array deck rest separates the overhang from the final landing; gantry and pad are visible'});
    Object.assign(connectors[32],{status:'built',finishRegion:finish,
        intent:'Controlled final landing: the finish region is the beacon pad surface between its lips'});
    Object.assign(recoveries[7],{status:'built',elements:['S08-array-deck','S08-rest-ledge','S08-deflector-ramp','S08-spill-deck','S08-recovery-hook'],
        rejoin:'S08-03',sideRoute:'Short gantry pulls drop back onto the array deck west lip; longer overhang/gantry misses fall via the green ramp onto the spill deck, whose hook returns to the Crown. No hazards at the ending.'});
    return {schemaVersion:1, geometryVersion:1,
        // Grapnel range: base until the player enters upgradeBand, upgraded after.
        range:{base:R, upgraded:1620, upgradeBand:'S05'}, ascent:24*U, horizontalEnvelope:12*U,
        coordinateConvention:'negative Y upward', base:{id:'base',x:2160,y:0},
        summit:{id:'summit',x:3780,y:-24*U},
        bounds:{left:0,right:6480,top:-24*U-540,bottom:120},
        spawn:{x:2160,y:0}, startSection:'S01', sections, encounters, connectors, recoveries, shortcuts,
        geometry:{version:1, elements:[rectangle('mountain-catch',0,120,6480,60,true),
            rectangle('mountain-left',-60,-13500,60,13680,false),
            rectangle('mountain-right',6480,-13500,60,13680,false),...yard,...shaft,...viaduct,...deflectors,...galleries,...liftworks,...crown,...summit,yardDrag,exitDrag,...shaftDrags,viaductBrake,exitBrake,viaductDrag], movers:liftMovers},
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

function loadMountainLevel(manifest = GRAPPLE_OVER_MOUNTAIN)
{
    return loadFixedLevel(validateMountainManifest(manifest))
}
