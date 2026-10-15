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
    Object.assign(sections[1], {status:'built',landmark:{id:'S02-landmark',
        name:'alternating industrial balconies',x:4030,y:-2100}});
    Object.assign(encounters[4], {status:'built',x:4100,y:-1631,
        elements:['S01-exit','S02-left-balcony','S02-right-balcony','S02-catch-balcony'],
        start:{x:4100,y:-1630.8,from:'S01-04'},target:{x:4220,y:-2240},
        exit:{left:4100,right:4170,top:-2020,bottom:-1970},
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
        {id:'S03-test-exit',x:5180,y:-3280,role:'solid',grapplable:true,
            points:[{x:0,y:0},{x:360,y:0},{x:360,y:-60},{x:400,y:-60},{x:400,y:65},{x:310,y:65},
                {x:310,y:170},{x:275,y:170},{x:275,y:65},{x:45,y:40}]},
        {id:'S03-lower-bridge',x:4630,y:-3245,role:'solid',grapplable:true,
            points:[{x:0,y:0},{x:310,y:0},{x:280,y:35},{x:80,y:60},{x:0,y:60}]}
    ];
    Object.assign(sections[2], {status:'partial',landmark:{id:'S03-landmark',
        name:'interrupted elevated bridge',x:4800,y:-3420}});
    Object.assign(encounters[8], {status:'built',x:4430,y:-3240,
        elements:['S02-exit','S03-departure-beam'],start:{x:4430,y:-3190.8,from:'S02-04'},
        target:{x:4740,y:-3480},exit:{left:4600,right:4900,top:-3500,bottom:-3280},
        action:'Build rightward speed under the departure beam before release'});
    Object.assign(encounters[9], {status:'built',x:4870,y:-3400,
        elements:['S03-departure-beam','S03-test-exit','S03-lower-bridge'],
        start:{from:'S03-01'},target:{x:5230,y:-3260},
        exit:{left:5191,right:5529,top:-3292,bottom:-3280},
        action:'Release across the broken span beyond direct acquisition range, then catch the far deck'});
    Object.assign(connectors[8], {status:'built',intent:'Pull from Switchback exit into departure beam'});
    connectors[9].status='built';
    Object.assign(recoveries[2], {openingElements:['S03-lower-bridge','S02-exit'],
        openingRejoin:'S02-04',sideRoute:'Release left from the lower broken bridge to the shaft exit'});
    Object.assign(shortcuts[0], {openingElements:['S03-departure-beam','S03-test-exit'],
        openingExit:'S03-02',intent:'Optional early high-speed release; faster exposed flight to the temporary exit; upper continuation planned'});
    return {schemaVersion:1, geometryVersion:1, range:R, ascent:24*R, horizontalEnvelope:12*R,
        coordinateConvention:'negative Y upward', base:{id:'base',x:2160,y:0},
        summit:{id:'summit',x:3780,y:-24*R},
        bounds:{left:0,right:6480,top:-24*R-540,bottom:120},
        spawn:{x:2160,y:0}, startSection:'S01', sections, encounters, connectors, recoveries, shortcuts,
        geometry:{version:1, elements:[rectangle('mountain-catch',0,120,6480,60,true),
            rectangle('mountain-left',-60,-13500,60,13680,false),
            rectangle('mountain-right',6480,-13500,60,13680,false),...yard,...shaft,...viaduct], movers:[]},
        difficulty:{targetFirstSuccessMinutes:[30,60], validated:false,
            note:'30-60 minute first success is unvalidated without human feedback.'},
        completion:'planned; no summit trigger until authored',
        recoveryPolicy:'Physical falls, nonlethal hazards, current-state saves; no automatic relocation'}
})()

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
    if (m.range !== 540 || m.ascent !== 12960 || m.horizontalEnvelope !== 6480 ||
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
    const level = {version:m.geometry.version,bounds:m.bounds,spawn:m.spawn,finish:null,
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
    return level
}

function loadMountainLevel(manifest = GRAPPLE_OVER_MOUNTAIN)
{
    return loadFixedLevel(validateMountainManifest(manifest))
}
