/* TASK-624 isolated fixtures, production input/physics; observation only. */
(() => {
 let contacts=[], events=[], tick=0;
 for(const method of ['applySolidContact','applyBounce']){
  const original=Ninja.prototype[method];
  Ninja.prototype[method]=function(c){contacts.push({id:c.element?.id||'boundary',nx:c.nx,ny:c.ny});return original.call(this,c)};
 }
 const lifecycle=PLATFORM.sendLifecycle;
 PLATFORM.sendLifecycle=function(name,...args){if(name==='level_completed')events.push({tick,x:ninja.x,y:ninja.y,contacts:structuredClone(contacts)});return lifecycle.call(this,name,...args)};
 const pose=()=>({x:ninja.x,y:ninja.y,vx:ninja.speedX,vy:ninja.speedY});
 function run(start,range,target,hold=120,budget=600){
  BYPASS.setup(start,range,null);events=[];contacts=[];tick=0;
  const inputs=[],hits=[],trace=[],attached=new Set();
  const crossing=grapnel.nearestCrossing(ninja,[target.x,target.y]);
  const initialHit=crossing?{id:crossing.element.id||'boundary',blocked:grapnel.blocksShot(crossing.element),...crossing.hit}:null;
  function input(type){const p=YARD.client(target);document.dispatchEvent(new MouseEvent(type,{clientX:p.x,clientY:p.y,button:0,bubbles:true}));inputs.push({tick,type,target});}
  input('mousedown');
  for(tick=1;tick<=budget;tick++){
   if(tick===hold+1)input('mouseup');contacts=[];physics();
   if(grapnel.isGrappled())attached.add(grapnel.pos.at(-1)[2]?.id||'boundary');
   if(contacts.length)hits.push({tick,...pose(),contacts:structuredClone(contacts)});
   if(tick%120===0||tick===1)trace.push({tick,...pose(),attached:grapnel.isGrappled()});
  }
  input('mouseup');
  return {start,range,target,hold,budget,initialHit,inputs,attached:[...attached],contacts:hits,trace,events,final:pose(),postSetupInjections:0};
 }
 window.BOUNDARY={run};
})();
