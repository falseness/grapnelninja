/* TASK-623 bounded isolated launch probes; no production behavior changes. */
(() => {
 const pose=()=>({x:ninja.x,y:ninja.y,vx:ninja.speedX,vy:ninja.speedY});
 let contacts=[];
 for(const name of ['applySolidContact','applyBounce']) {
  const original=Ninja.prototype[name];
  Ninja.prototype[name]=function(c){contacts.push({id:c.element?.id,nx:c.nx,ny:c.ny});return original.call(this,c)};
 }
 function geometry(){
  const level=replacementMountainLevel(GRAPPLE_OVER_REPLACEMENT);
  return level.encounters.map(e=>{
   const ps=floors[0].elements.filter(x=>e.elements.includes(x.id)).flatMap(x=>x.getPoints());
   return {id:e.id,elements:e.elements,minX:Math.min(...ps.map(p=>p.x)),maxX:Math.max(...ps.map(p=>p.x)),minY:Math.min(...ps.map(p=>p.y)),maxY:Math.max(...ps.map(p=>p.y))};
  });
 }
 function run(start,policy,budget=1200){
  BYPASS.setup(start,540,null);
  const regions=geometry(),inputs=[],visits=new Set(),completions=[],skips=[],trace=[];
  let high=start.completed,attachedTicks=0;
  function input(type,target,tick){
   const p=YARD.client(target||ninja);
   document.dispatchEvent(new MouseEvent(type,{clientX:p.x,clientY:p.y,bubbles:true,button:0}));
   inputs.push({tick,type,target:target||null,client:p});
  }
  for(let tick=1;tick<=budget;tick++){
   const shot=policy.presses.find(s=>s.tick===tick);
   if(shot){
    const candidates=BYPASS.candidates(false);
    let target;
    if(shot.target)target=shot.target;
    else if(policy.target){
     const e=floors[0].elements.find(e=>e.id===policy.target),ps=e.getPoints();
     target={id:e.id,x:ps.reduce((s,p)=>s+p.x,0)/ps.length,y:Math.min(...ps.map(p=>p.y))};
    }else target=candidates[policy.rank % Math.max(1,candidates.length)];
    if(target)input('mousedown',target,tick);
   }
   if(policy.presses.some(s=>s.tick+s.hold===tick))input('mouseup',null,tick);
   contacts=[];physics();if(grapnel.isGrappled())attachedTicks++;
   for(const r of regions)if(ninja.x>=r.minX&&ninja.x<=r.maxX&&ninja.y>=r.minY&&ninja.y<=r.maxY)visits.add(r.id);
   for(const c of contacts){
    const index=BYPASS.exits.indexOf(c.id);if(index<=high||c.ny>=-.9)continue;
    const skipped=BYPASS.exits.slice(high+1,index),crossSection=skipped.length>0&&Math.floor(index/4)!==Math.floor(Math.max(0,high)/4);
    const row={tick,id:c.id,index,previous:high,skipped,crossSection,contact:c,pose:pose()};
    completions.push(row);if(skipped.length)skips.push({...row,unapproved:skipped.length>1||crossSection});high=index;
   }
   if(tick%120===0||shot||inputs.at(-1)?.tick===tick||completions.at(-1)?.tick===tick)trace.push({tick,...pose(),attached:grapnel.isGrappled(),contacts});
  }
  input('mouseup',null,budget);
  return {start:start.id,policy,range:540,ticks:budget,inputs,visitedRegions:[...visits],completions,skips,trace,attachedTicks,final:pose(),postSetupInjections:0};
 }
 window.UPPER_BYPASS={geometry,run};
})();
