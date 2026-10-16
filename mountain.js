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
    const R = 540, bandHeight = 3 * R
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
    // Broken loading yard: a low dock, torn crane beam, and raised loading bay.
    // These polygons are both the rendered silhouettes and the collision shapes.
    const yard = [
        rectangle('S01-rest-dock',1860,18,600,64,true),
        {id:'S01-crane-beam',x:2310,y:-330,role:'solid',grapplable:true,
            points:[{x:0,y:0},{x:180,y:0},{x:180,y:20},{x:150,y:40},{x:0,y:40}]},
        {id:'S01-loading-bay',x:2460,y:-120,role:'solid',grapplable:true,
            points:[{x:0,y:0},{x:560,y:0},{x:560,y:-60},{x:600,y:-60},{x:600,y:210},{x:520,y:210},
                {x:520,y:55},{x:80,y:55},{x:80,y:210},{x:0,y:210}]},
        {id:'S01-broken-mast',x:1980,y:-480,role:'solid',grapplable:true,
            points:[{x:0,y:0},{x:35,y:15},{x:35,y:430},{x:0,y:430}]},
        rectangle('S01-next-beam',2740,-440,240,35,true),
        rectangle('S01-transfer-beam',3100,-750,180,35,true),
        rectangle('S01-upper-beam',2800,-1060,180,35,true),
        rest('S01-recovery-balcony',3230,-780,420),
        rectangle('S01-lower-anchor',3210,-1090,160,35,true),
        rectangle('S01-exit-crane',3470,-1300,180,35,true),
        rest('S01-rest-ledge',3610,-1150,420),
        rectangle('S01-connector-anchor',3750,-1700,180,35,true),
        rest('S01-exit',3940,-1620,320)
    ];
    Object.assign(sections[0], {status:'built', landmark:{id:'S01-landmark',
        name:'broken loading yard',x:2460,y:-240}});
    Object.assign(encounters[0], {status:'built',x:2160,y:0,
        elements:['S01-rest-dock','S01-crane-beam','S01-broken-mast'],
        start:{x:2160,y:0},target:{x:2390,y:-310},
        exit:{left:2200,right:2460,top:-330,bottom:-80},
        action:'Press the visible torn crane beam from the entrance dock'});
    Object.assign(encounters[1], {status:'built',x:2540,y:-120,
        elements:['S01-crane-beam','S01-loading-bay','S01-next-beam'],
        start:{from:'S01-01'},target:{x:2860,y:-425},
        exit:{left:2480,right:3040,top:-140,bottom:-120},
        action:'Release the crane pull onto the wide loading bay'});
    Object.assign(encounters[2], {status:'built',x:2860,y:-425,
        elements:['S01-next-beam','S01-transfer-beam','S01-upper-beam'],
        start:{from:'S01-02'}, target:{x:2890,y:-1040},
        exit:{left:2800,right:3030,top:-1080,bottom:-900},
        action:'Release and reacquire the staggered beams during ascent'});
    Object.assign(encounters[3], {status:'built',x:3220,y:-780,
        elements:['S01-recovery-balcony','S01-lower-anchor','S01-exit-crane',
            'S01-rest-ledge','S01-connector-anchor','S01-exit'],
        start:{from:'S01-03'}, target:{x:3290,y:-1070},
        exit:{left:3940,right:4260,top:-1650,bottom:-1620},
        action:'Catch a small fall on the balcony; pull the lower anchor, rest, then climb the exit connector'});
    for (let i=0;i<4;i++) connectors[i].status='built';
    Object.assign(connectors[4], {authoredFrom:'S01',
        departure:{left:3940,right:4260,top:-1650,bottom:-1620},
        intent:'Built S01 departure ledge at the next band; S02 destination remains planned'});
    Object.assign(recoveries[0], {status:'built',
        elements:['S01-recovery-balcony','S01-lower-anchor','S01-rest-dock'],
        localRejoin:'S01-04'});
    // Switchback Shaft: cantilevered decks with integral wall returns
    // and tapered undersides. The silhouette is the solid collider, not decoration.
    const shaft = [
        {id:'S02-left-balcony',x:3700,y:-1960,role:'solid',grapplable:true,
            points:[{x:0,y:-140},{x:35,y:-140},{x:35,y:0},{x:260,y:0},
                {x:260,y:30},{x:100,y:70},{x:0,y:70}]},
        {id:'S02-right-balcony',x:4140,y:-2260,role:'solid',grapplable:true,
            points:[{x:0,y:0},{x:230,y:0},{x:230,y:-150},{x:265,y:-150},
                {x:265,y:80},{x:170,y:80},{x:0,y:30}]},
        {id:'S02-brake-girder',x:3800,y:-2500,role:'solid',grapplable:true,
            points:[{x:0,y:0},{x:170,y:0},{x:170,y:25},{x:120,y:45},{x:0,y:45}]},
        rest('S02-rest-ledge',3700,-2050,350),
        rest('S02-catch-balcony',4260,-1840,600),
        {id:'S02-reversal-balcony',x:4140,y:-2780,role:'solid',grapplable:true,
            points:[{x:0,y:0},{x:240,y:0},{x:240,y:-120},{x:275,y:-120},
                {x:275,y:75},{x:180,y:75},{x:0,y:30}]},
        {id:'S02-upper-return',x:3760,y:-3060,role:'solid',grapplable:true,
            points:[{x:0,y:-120},{x:35,y:-120},{x:35,y:0},{x:200,y:0},
                {x:200,y:30},{x:90,y:65},{x:0,y:65}]},
        rectangle('S02-exit-anchor',4080,-3240,180,35,true),
        rest('S02-exit',4280,-3180,360)
    ];
    // A low mid-deck lip stops the landing slide at the authored S03 start,
    // below the departure beam; it is low enough to keep that sightline clear.
    shaft.at(-1).points=[{x:0,y:0},{x:160,y:0},{x:160,y:-20},{x:200,y:-20},{x:200,y:0},
        {x:360,y:0},{x:360,y:55},{x:0,y:55}];
    Object.assign(sections[1], {status:'built',landmark:{id:'S02-landmark',
        name:'alternating industrial balconies',x:4030,y:-2100}});
    Object.assign(encounters[4], {status:'built',x:4100,y:-1631,
        elements:['S01-exit','S02-left-balcony','S02-right-balcony','S02-catch-balcony'],
        start:{x:4209.2,y:-1630.8,from:'S01-04'},target:{x:4220,y:-2240},
        exit:{left:4080,right:4170,top:-2030,bottom:-1970},
        action:'Pull left from Foundations, release and pull the opposing right balcony'});
    Object.assign(encounters[5], {status:'built',x:4160,y:-2250,
        elements:['S02-right-balcony','S02-brake-girder','S02-rest-ledge'],
        start:{from:'S02-01'},target:{x:3890,y:-2480},
        exit:{left:3720,right:4030,top:-2062,bottom:-2050},
        action:'Brake rightward momentum with the opposing left girder; release onto the ordinary rest ledge'});
    Object.assign(connectors[4], {status:'built',intent:'Physical ascent from Foundations exit to left balcony'});
    connectors[5].status='built';
    Object.assign(recoveries[1], {openingElements:['S02-catch-balcony','S01-exit','S01-rest-ledge'],
        openingRejoin:'S02-01',sideRoute:'Open left side drops visibly to Foundations exit and rest ledge'});
    Object.assign(encounters[6], {status:'built',x:4130,y:-2580,
        elements:['S02-brake-girder','S02-reversal-balcony','S02-upper-return'],
        start:{from:'S02-02'},target:{x:3850,y:-3040},
        exit:{left:3800,right:4180,top:-3000,bottom:-2700},
        action:'Control an overshoot through a lateral reversal from the right balcony to the upper left return'});
    Object.assign(encounters[7], {status:'built',x:4170,y:-3160,
        elements:['S02-upper-return','S02-exit-anchor','S02-exit'],
        start:{from:'S02-03'},target:{x:4170,y:-3220},
        exit:{left:4280,right:4600,top:-3200,bottom:-3180},
        action:'Climb out through the recessed exit, release into its sheltered landing'});
    connectors[6].status='built';connectors[7].status='built';
    Object.assign(connectors[8], {authoredFrom:'S02',
        departure:{left:4280,right:4600,top:-3200,bottom:-3180},
        intent:'Built shaft exit at the next band; destination S03 remains planned'});
    Object.assign(recoveries[1], {status:'built',
        elements:['S02-rest-ledge','S02-left-balcony','S02-catch-balcony','S01-exit'],
        localRejoin:'S02-01'});
    // Interrupted viaduct: tapered departure girder, torn deck and lower bridge.
    const viaduct = [
        {id:'S03-departure-beam',x:4620,y:-3510,role:'solid',grapplable:true,
            points:[{x:0,y:0},{x:240,y:0},{x:240,y:25},{x:190,y:55},{x:0,y:35}]},
        {id:'S03-rest-ledge',x:5180,y:-3280,role:'solid',grapplable:true,
            points:[{x:0,y:0},{x:360,y:0},{x:360,y:-60},{x:400,y:-60},{x:400,y:65},{x:310,y:65},
                {x:310,y:170},{x:275,y:170},{x:275,y:65},{x:45,y:40}]},
        {id:'S03-lower-bridge',x:4630,y:-3245,role:'solid',grapplable:true,
            points:[{x:0,y:0},{x:310,y:0},{x:280,y:35},{x:80,y:60},{x:0,y:60}]}
    ];
    viaduct.push(
        rectangle('S03-flight-beam',5160,-3690,180,30,true),
        rectangle('S03-return-beam',4820,-4010,180,30,true),
        rectangle('S03-upper-beam',5180,-4330,180,30,true),
        rectangle('S03-brake-beam',5100,-4650,180,30,true),
        rectangle('S03-exit-anchor',5180,-4900,180,30,true),
        // Low west lip stops the landing slide but keeps the shot to the S04 press clear.
        {id:'S03-exit',x:5000,y:-4820,role:'solid',grapplable:true,
            points:[{x:0,y:-20},{x:40,y:-20},{x:40,y:0},{x:240,y:0},{x:240,y:55},{x:0,y:55}]});
    Object.assign(sections[2], {status:'built',landmark:{id:'S03-landmark',
        name:'interrupted elevated bridge',x:4800,y:-3420}});
    Object.assign(encounters[8], {status:'built',x:4430,y:-3240,
        elements:['S02-exit','S03-departure-beam'],start:{x:4429.2,y:-3190.8,from:'S02-04'},
        target:{x:4740,y:-3480},exit:{left:4600,right:4900,top:-3500,bottom:-3280},
        action:'Build rightward speed under the departure beam before release'});
    Object.assign(encounters[9], {status:'built',x:4870,y:-3400,
        elements:['S03-departure-beam','S03-rest-ledge','S03-lower-bridge'],
        start:{from:'S03-01'},target:{x:5230,y:-3260},
        exit:{left:5191,right:5529,top:-3292,bottom:-3280},
        action:'Release across the broken span beyond direct acquisition range, then catch the far deck'});
    Object.assign(connectors[8], {status:'built',intent:'Pull from Switchback exit into departure beam'});
    connectors[9].status='built';
    Object.assign(recoveries[2], {openingElements:['S03-lower-bridge','S02-exit'],
        openingRejoin:'S02-04',sideRoute:'Release left from the lower broken bridge to the shaft exit'});
    Object.assign(encounters[10], {status:'built',x:5200,y:-3650,
        elements:['S03-flight-beam','S03-return-beam','S03-upper-beam'],
        start:{from:'S03-02'},target:{x:5250,y:-3670},
        exit:{left:4800,right:5400,top:-4340,bottom:-3950},
        action:'Acquire the far beam during flight, then transfer up the interrupted bridge piers'});
    Object.assign(encounters[11], {status:'built',x:5200,y:-4600,
        elements:['S03-upper-beam','S03-brake-beam','S03-exit-anchor','S03-exit'],
        start:{from:'S03-03'},target:{x:5190,y:-4630},
        exit:{left:5051,right:5229,top:-4832,bottom:-4820},
        action:'Brake against the opposing pier, then release into the narrow sheltered exit'});
    connectors[10].status='built';connectors[11].status='built';
    Object.assign(connectors[12], {authoredFrom:'S03',
        departure:encounters[11].exit,
        intent:'Built viaduct exit at the next band; Deflector Works destination remains planned'});
    Object.assign(recoveries[2], {status:'built',elements:['S03-rest-ledge','S03-lower-bridge','S02-exit'],
        localRejoin:'S02-04'});
    Object.assign(shortcuts[0], {status:'built',elements:['S03-departure-beam','S03-rest-ledge'],
        openingExit:'S03-02',intent:'Optional earlier high-speed launch skips the conservative swing; exposed faster approach rejoins the normal route to the same narrow exit'});
    // Deflector Works: a flat press face and tilted chute, above open catch basins.
    // Green polygons are the machinery itself, with matching reflection colliders.
    const deflectors = [
        {id:'S04-flat-press',x:5500,y:-5270,role:'bounce',grapplable:true,
            points:[{x:0,y:0},{x:60,y:0},{x:90,y:60},{x:90,y:350},{x:0,y:350}]},
        rest('S04-rest',4900,-5000,360),
        {id:'S04-angled-chute',x:5000,y:-5380,role:'bounce',grapplable:true,
            points:[{x:0,y:0},{x:280,y:-140},{x:310,y:-100},{x:30,y:40}]},
        rest('S04-transfer-ledge',5220,-5250,160),
        {id:'S04-catch-basin',x:5240,y:-4800,role:'solid',grapplable:true,
            points:[{x:0,y:0},{x:700,y:0},{x:700,y:-100},{x:740,y:-100},
                {x:740,y:65},{x:0,y:65}]},
        rectangle('S04-lower-stair',5200,-4770,100,35,true)
    ];
    for (const e of deflectors) {e.x=10300-e.x; e.points=e.points.map(p=>({x:-p.x,y:p.y})).reverse();}
    // Low departure lip catches the angled return while allowing the next shot.
    deflectors.find(e=>e.id==='S04-transfer-ledge').points.forEach(p=>{if(p.y===-60)p.y=-20;});
    deflectors.push(
        {id:'S04-combination-press',x:4620,y:-5700,role:'bounce',grapplable:true,
            points:[{x:0,y:0},{x:0,y:350},{x:-75,y:350},{x:-60,y:40}]},
        {id:'S04-combination-rest',x:4990,y:-5530,role:'solid',grapplable:true,points:[{x:0,y:0},{x:-150,y:0},{x:-150,y:-8},{x:-190,y:-8},{x:-190,y:55},{x:0,y:55}]},
        {id:'S04-double-left',x:4820,y:-6000,role:'bounce',grapplable:true,
            points:[{x:0,y:0},{x:0,y:170},{x:-65,y:170},{x:-65,y:30}]},
        {id:'S04-double-right',x:5160,y:-5980,role:'bounce',grapplable:true,
            points:[{x:0,y:0},{x:65,y:30},{x:65,y:350},{x:0,y:350}]},
        rectangle('S04-brake-anchor',4800,-5730,40,35,true),
        // The landing is frictionless after the double reflection; a low mid
        // lip stops the westward slide where the exit stairs climb begins.
        {id:'S04-double-landing',x:4880,y:-5780,role:'solid',grapplable:true,
            points:[{x:0,y:-30},{x:15,y:-30},{x:15,y:0},{x:85.47,y:0},{x:85.47,y:-20},
                {x:100.47,y:-20},{x:100.47,y:0},{x:155,y:0},
                {x:155,y:-30},{x:170,y:-30},{x:170,y:35},{x:0,y:35}]},
        rest('S04-upper-step',4700,-6050,200),
        {id:'S04-exit',x:4460,y:-6480,role:'solid',grapplable:true,points:[{x:0,y:-180},{x:40,y:-180},{x:40,y:0},{x:160,y:0},{x:160,y:-30},{x:200,y:-30},{x:200,y:55},{x:0,y:55}]}
    );
    deflectors.find(e=>e.id==='S04-upper-step').points.forEach(p=>{if(p.y===-60)p.y=-30;});
    deflectors.find(e=>e.id==='S04-upper-step').points.splice(0,1,{x:0,y:-180},{x:40,y:-180},{x:40,y:0});
    Object.assign(encounters[14], {status:'built',x:4620,y:-5630,
        elements:['S04-transfer-ledge','S04-combination-press','S04-combination-rest'],
        start:{from:'S04-02'},target:{x:4610,y:-5630},
        exit:{left:4811,right:4979,top:-5550,bottom:-5530},
        action:'Reflect off the upper press then acquire the new rest shelf while airborne'});
    Object.assign(encounters[15], {status:'built',x:5000,y:-5850,
        elements:['S04-combination-rest','S04-double-left','S04-double-right','S04-brake-anchor','S04-double-landing','S04-upper-step','S04-exit'],
        start:{from:'S04-03'},target:{x:5170,y:-5910},
        exit:{left:4510.8,right:4609.2,top:-6492,bottom:-6480},
        action:'Release into opposing green faces for two reflections; land and climb the exposed departure stairs'});
    connectors[14].status='built';
    Object.assign(connectors[15], {status:'built',intent:'Authored S04 departure to the Cable Galleries band; destination remains planned'});
    Object.assign(sections[3], {status:'built',landmark:{id:'S04-landmark',
        name:'angled green machinery',x:5050,y:-5370}});
    Object.assign(encounters[12], {status:'built',x:4900,y:-5030,
        elements:['S03-exit','S04-flat-press','S04-rest','S04-catch-basin'],
        start:{x:5050.8,y:-4830.8,from:'S03-04'},target:{x:4790,y:-5200},
        exit:{left:5090.8,right:5389.2,top:-5012,bottom:-5000},
        action:'Pull toward the flat green press; release, reflect right, and brake onto the rest shelf'});
    Object.assign(encounters[13], {status:'built',x:5150,y:-5400,
        elements:['S04-rest','S04-angled-chute','S04-transfer-ledge','S04-catch-basin'],
        start:{from:'S04-01'},target:{x:5150,y:-5430},
        exit:{left:4970.8,right:5069.2,top:-5262,bottom:-5250},
        action:'Pull toward the tilted green chute; release and redirect momentum toward the transfer ledge'});
    Object.assign(connectors[12], {status:'built',intent:'Physical pull from Viaduct exit to flat press'});
    connectors[13].status='built';
    Object.assign(recoveries[3], {openingElements:['S04-catch-basin','S04-lower-stair','S03-exit'],
        openingRejoin:'S03-04',sideRoute:'Catch basin and lower stairs reconnect physically to the Viaduct'});
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
    Object.assign(connectors[16], {status:'built',intent:'Pull from the Works exit around the projecting girder'});
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
    const liftMovers = [{id:'S06-counterweight-travel',element:'S06-counterweight',
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
        range:{base:R, upgraded:810, upgradeBand:'S05'}, ascent:24*R, horizontalEnvelope:12*R,
        coordinateConvention:'negative Y upward', base:{id:'base',x:2160,y:0},
        summit:{id:'summit',x:3780,y:-24*R},
        bounds:{left:0,right:6480,top:-24*R-540,bottom:120},
        spawn:{x:2160,y:0}, startSection:'S01', sections, encounters, connectors, recoveries, shortcuts,
        geometry:{version:1, elements:[rectangle('mountain-catch',0,120,6480,60,true),
            rectangle('mountain-left',-60,-13500,60,13680,false),
            rectangle('mountain-right',6480,-13500,60,13680,false),...yard,...shaft,...viaduct,...deflectors,...galleries,...liftworks,...crown,...summit], movers:liftMovers},
        difficulty:{targetFirstSuccessMinutes:[30,60], validated:false,
            note:'30-60 minute first success is unvalidated without human feedback.'},
        finish, completion:'Summit finish region on the S08-04 beacon pad; reaching it completes the climb',
        recoveryPolicy:'Physical falls, nonlethal hazards, current-state saves; no automatic relocation'}
})()

// Layout-v2 design rules. A section opts in with designVersion:2; legacy (v1)
// sections are reported but never fail. Gap targets are the TASK-503 frozen
// 85-90% band of measured reach for the section's active grapnel range.
const LAYOUT_V2_GAP_TARGETS = {540:[459,486], 810:[689,729]}
const LAYOUT_V2_SOLID_EXCEPTIONS = ['rest-pad','lip','side-wall']
const LAYOUT_V2_REST_PAD_MAX_WIDTH = 200

function layoutV2Report(m)
{
    const box = e => ({left:e.x+Math.min(...e.points.map(p=>p.x)),right:e.x+Math.max(...e.points.map(p=>p.x)),
        top:e.y+Math.min(...e.points.map(p=>p.y)),bottom:e.y+Math.max(...e.points.map(p=>p.y))})
    const elements = new Map(m.geometry.elements.map(e=>[e.id,e]))
    const encounters = new Map(m.encounters.map(e=>[e.id,e]))
    const upgradeOrder = m.sections.find(s=>s.id===m.range.upgradeBand).order
    const sections = m.sections.map(s=>{
        const version = s.designVersion ?? 1
        if (version === 1) return {id:s.id, designVersion:1, legacy:true, failed:false}
        const errors = [], rules = {}
        const rule = (name, code, measured, problems) => {
            problems.forEach(path=>errors.push({rule:name, code, path:s.id+'.'+path}))
            rules[name] = {passed:!problems.length, measured}
        }
        if (version !== 2) {
            errors.push({rule:'designVersion', code:'InvalidDesignVersion', path:s.id+'.designVersion'})
            return {id:s.id, designVersion:version, legacy:false, failed:true, passed:false, errors, rules}
        }
        const own = m.geometry.elements.filter(e=>e.id.startsWith(s.id+'-'))
        const movers = m.geometry.movers.filter(v=>v.element.startsWith(s.id+'-'))
        const moving = new Set(movers.map(v=>v.element))
        const exceptions = new Map((s.solidExceptions||[]).map(x=>[x.element,x]))
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
        // Blue movers are exempt from the bounce default but must carry >=2 encounters.
        const carrying = s.encounters.filter(id=>encounters.get(id).elements.some(e=>moving.has(e)))
        rule('moverCoverage', 'LayoutV2MoverCoverage', {movers:movers.map(v=>v.id), encounters:carrying,
            count:carrying.length, required:2}, carrying.length >= 2 ? [] : ['movers'])
        // Travel alternates: odd sections exit right of entry, even sections left.
        const first = encounters.get(s.encounters[0]), last = encounters.get(s.encounters[3])
        const entryX = first.start?.x ?? first.x, exitX = last.exit ? (last.exit.left+last.exit.right)/2 : last.x
        const required = s.order % 2 ? 'right' : 'left'
        const actual = exitX > entryX ? 'right' : exitX < entryX ? 'left' : 'none'
        rule('direction', 'LayoutV2Direction', {entryX, exitX, required, actual},
            actual === required ? [] : ['direction'])
        // Mandatory gaps sit in the frozen band for the active range.
        const range = s.order >= upgradeOrder ? m.range.upgraded : m.range.base
        const target = LAYOUT_V2_GAP_TARGETS[range]
        const gaps = (s.gaps||[]).filter(g=>g.mandatory !== false).map(g=>{
            const distance = Math.hypot(g.to.x-g.from.x, g.to.y-g.from.y)
            return {id:g.id, distance, fraction:distance/range,
                inBand:distance >= target[0] && distance <= target[1]}
        })
        rule('gapBand', 'LayoutV2GapBand', {range, target, gaps},
            [...(Array.isArray(s.gaps) ? [] : ['gaps']), ...gaps.filter(g=>!g.inBand).map(g=>'gaps.'+g.id)])
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
    return {sections, v2:sections.filter(s=>!s.legacy).map(s=>s.id),
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
        range.base !== 540 || range.upgraded !== 810 || range.upgradeBand !== 'S05')
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
            s.band.top !== s.band.bottom-1620 || s.band.left !== m.bounds.left || s.band.right !== m.bounds.right ||
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
