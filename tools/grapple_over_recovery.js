/* TASK-626: isolated inventory and released-route fall probes, production only. */
(() => {
 let contacts=[];
 for(const name of ['applySolidContact','applyBounce']) {
  const original=Ninja.prototype[name];
  Ninja.prototype[name]=function(c){contacts.push({id:c.element?.id,nx:c.nx,ny:c.ny});return original.call(this,c)};
 }
 const pose=()=>({x:ninja.x,y:ninja.y,vx:ninja.speedX,vy:ninja.speedY});
 const nodes=[...BYPASS.exits,'yard-entry'];
 const bounds=e=>{const p=e.getPoints();return {id:e.id,role:e.surfaceRole,points:p,left:Math.min(...p.map(v=>v.x)),right:Math.max(...p.map(v=>v.x)),top:Math.min(...p.map(v=>v.y)),bottom:Math.max(...p.map(v=>v.y))}};
 function geometry(){return {surfaces:floors[0].elements.filter(e=>/^(yard|quarry|freight|viaduct)-/.test(e.id)).map(bounds),yellow:floors[0].dragZones.map(bounds),bounds:floors[0].level.bounds,sideWall:screen.leftWall?true:false};}
 function event(type,p=ninja){const q=YARD.client(p);document.dispatchEvent(new MouseEvent(type,{clientX:q.x,clientY:q.y,bubbles:true,button:0}));}
 function run(start,range,options={}){
  BYPASS.setup(start,range,null);
  const budget=options.budget||5000,hold=options.hold||60,period=hold+30;
  const trace=[],inputs=[];let firstContact=null,returned=null,rest=0,maxRest=0,yellowRest=0,waiting=180;
  const initial=pose();
  let special=/viaduct-(exit-catch|exit-recovery|catch|recovery-wall)$/.test(start.id);
  let east=start.id.includes('exit');let climbed=false;
  for(let tick=1;tick<=budget;tick++){
   if(tick>waiting&&(tick-waiting-1)%period===0){
    event('mouseup');
    const gs=floors[0].elements.filter(e=>nodes.includes(e.id)).map(bounds);
    const goals=gs.map(g=>({...g,x:Math.max(g.left+20,Math.min(g.right-20,ninja.x)),y:g.top-12}));
    goals.sort((a,b)=>Math.hypot(a.x-ninja.x,a.y-ninja.y)-Math.hypot(b.x-ninja.x,b.y-ninja.y));
    const goal=goals[0],rangeNow=grappleOverAcquisitionRadius();let aims=[];
    // Route around the nearest deck edge, never keep pulling into its underside.
    if(ninja.y>goal.top && ninja.x>goal.left-25 && ninja.x<goal.right+25){
     goal.x=(options.right===undefined?Math.abs(ninja.x-goal.left)<Math.abs(ninja.x-goal.right):!options.right)?goal.left-80:goal.right+80;
     goal.y=ninja.y+100;
    }
    const wall=ninja.x>9800&&ninja.y>-1100?10108:ninja.x>6740&&ninja.x<9400&&ninja.y>-1100?6820:null;
    if(wall){goal.x=wall-1;goal.y=ninja.y-250;}


    for(const e of floors[0].elements){if(!e.grapplable)continue;const ps=e.getPoints();
     for(let j=0;j<ps.length;j++)for(let k=0;k<=20;k++){
      const a=ps[j],b=ps[(j+1)%ps.length],q={x:a.x+(b.x-a.x)*k/20,y:a.y+(b.y-a.y)*k/20,id:e.id};
      const d=Math.hypot(q.x-ninja.x,q.y-ninja.y),c=YARD.client(q);
      if(d<20||d>rangeNow-8||c.x<0||c.x>1280||c.y<0||c.y>720)continue;
      q.score=Math.hypot(q.x-goal.x,q.y-goal.y)+.1*d;aims.push(q);
     }
    }
    aims.sort((a,b)=>a.score-b.score);let target=aims[0];
    if(special&&!climbed){
     const wall=east?10108:6820,edge=east?10648:7360,bottom=east?-1228.2:-1188.2;
     if(ninja.y>-1050){
      if(ninja.x>wall+300)target={id:'lateral-floor',x:ninja.x-280,y:45};
      else {const dx=Math.abs(wall-1-ninja.x),up=Math.min(250,Math.sqrt(Math.max(0,350**2-dx**2)));
       target={id:'wall-ascent',x:wall-1,y:Math.max(-1140,ninja.y-up)};}
     }else target={id:'upper-edge',x:Math.min(edge-2,ninja.x+220),y:ninja.x<edge-70?bottom-5:bottom-55};
    }
    if(target&&!goal.coast){event('mousedown',target);inputs.push({tick,target:{id:target.id,x:target.x,y:target.y},range:rangeNow});}
   }
   // Release regularly; an attachment alone never counts as a recovery.
   if(tick>waiting&&(tick-waiting-1)%period===hold-1)event('mouseup');
   contacts=[];physics();
   const s={tick,...pose(),contacts:[...new Map(contacts.map(c=>[c.id+':'+c.nx+':'+c.ny,c])).values()],range:grappleOverAcquisitionRadius()};
   s.yellow=floors[0].dragZones.some(e=>pointInPolygon(e.getPoints(),ninja.x,ninja.y));
   rest=Math.hypot(s.vx,s.vy)<.05?rest+1:0;maxRest=Math.max(maxRest,rest);if(s.yellow)yellowRest=Math.max(yellowRest,rest);
   if(s.contacts.some(c=>c.ny<-.9&&c.id===(east?'viaduct-third-catch':'freight-exit-catch')))climbed=true;
   if(!firstContact&&s.contacts.some(c=>c.ny<-.9)){
    firstContact=s;
    const lower=s.contacts.find(c=>c.ny<-.9&&['viaduct-catch','viaduct-exit-catch'].includes(c.id));
    if(lower){special=true;east=lower.id==='viaduct-exit-catch';}
   }
   if(tick<=waiting||tick%30===0||s.contacts.length)trace.push(s);
   const node=s.contacts.find(c=>c.ny<-.9&&nodes.includes(c.id));
   if(node&&tick>waiting){returned={tick,id:node.id,...pose()};break;}
   if(ninja.y>2000)break;
  }
  event('mouseup');return {id:start.id,range,options,initial,provenance:start.provenance,firstContact,returned,trace,inputs,maxRest,yellowRest,postSetupInjections:0,resets:0};
 }
 function recover(start,range){
  const attempts=[];
  for(const options of [{},{hold:30},{hold:90},{hold:30,right:true},{hold:60,right:true},{hold:30,right:false}]){
   const r=run(start,range,options);attempts.push({options,returned:r.returned,last:r.trace.at(-1)});
   if(r.returned)return {...r,attempts};
  }
  return {...run(start,range,{hold:60,budget:9000}),attempts};
 }
 window.RECOVERY={geometry,run,recover};
})();
