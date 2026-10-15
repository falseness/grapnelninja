/* Isolated calibration fixtures; test-only, never loaded by index.html. */
window.calibrationSetup = ({family, negative}) => {
    const rect=(id,x,y,w,h,role='solid')=>({id,x,y,role,
        points:[{x:0,y:0},{x:w,y:0},{x:w,y:h},{x:0,y:h}]});
    const level=structuredClone(GRAPPLE_OVER_LEVEL);
    level.movers=[];
    level.elements=[rect('anchor',850,620,180,40),rect('landing',-3000,1100,9000,60)];
    let player={x:700,y:950,speedX:0,speedY:0};
    if(family==='braking') {
        player={x:800,y:700,speedX:2,speedY:0};
        level.elements=[rect('anchor',500,620,80,160),rect('landing',-3000,1100,9000,60)];
    }
    if(family==='angled_bounce') {
        player={x:700,y:690,speedX:0,speedY:2};
        level.elements=[{id:'slope',x:600,y:800,role:negative?'solid':'bounce',
            points:[{x:0,y:0},{x:400,y:-200},{x:400,y:100},{x:0,y:100}]},
            rect('anchor',600,400,200,40),rect('landing',-10000,2600,20000,60)];
    }
    if(family==='corner_wrap') {
        player={x:800,y:700,speedX:0,speedY:3};
        level.elements=[rect('anchor',1100,680,30,40),rect('landing',-10000,2600,20000,60)];
        if(!negative) level.elements.push(rect('corner',900,800,80,50));
    }
    if(family==='moving_transfer') {
        level.elements.push(rect('moving-target',550,470,220,40));
        level.movers=[{id:'moving',element:'moving-target',axis:'x',min:550,max:650,periodMs:2000,phase:0}];
    }
    level.encounters[0].elements=level.elements.map(e=>e.id);
    GRAPPLE_OVER_TEST.spawn({level,player,camera:{x:-300,y:-300}});
    window.calibrationBounces=[];
    return {level,player};
};
const calibrationOriginalBounce=Ninja.prototype.applyBounce;
Ninja.prototype.applyBounce=function(contact) {
    const before={x:this.x,y:this.y,speedX:this.speedX,speedY:this.speedY};
    const result=calibrationOriginalBounce.call(this,contact);
    if(contact.approaching) calibrationBounces.push({before,
        after:{x:this.x,y:this.y,speedX:this.speedX,speedY:this.speedY},
        normal:{x:contact.nx,y:contact.ny},element:contact.element.id});
    return result;
};
window.calibrationResult = () => {
    const a=GRAPPLE_OVER_TEST.attempts.at(-1);
    return {setup:a.metadata.setupOnlySpawns[0].fixture,
        rows:a.snapshots.map(r=>({tick:r.tick,...r.state.simulation.player,
            rope:r.state.rope, elements:r.state.simulation.elements})),
        inputs:a.events.filter(e=>e.type==='input').map(e=>({tick:e.tick,event:e.event,
            trusted:e.trusted,world:e.world})),
        events:a.events.filter(e=>e.type!=='input').map(e=>({type:e.type,tick:e.tick,
            player:e.after.simulation.player,rope:e.after.rope,contact:e.contact})),
        bounces:calibrationBounces};
};
