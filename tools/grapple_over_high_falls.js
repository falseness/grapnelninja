/* TASK-627: observation and ordinary mouse input only after isolated setup. */
(()=>{
 let contacts=[];
 for(const name of ['applySolidContact','applyBounce']){
  const original=Ninja.prototype[name];
  Ninja.prototype[name]=function(c){contacts.push({id:c.element?.id,nx:c.nx,ny:c.ny});return original.call(this,c)};
 }
 const pose=()=>({x:ninja.x,y:ninja.y,vx:ninja.speedX,vy:ninja.speedY});
 function input(type,target){const q=YARD.client(target||ninja);document.dispatchEvent(new MouseEvent(type,{clientX:q.x,clientY:q.y,button:0,bubbles:true}));}
 function begin(spec){
  BYPASS.setup(spec.start,540,null);
  const target=spec.target||BYPASS.candidates(false)[spec.rank];
  if(!target)throw Error('No launch target');
  const state={spec,target,trace:[],inputs:[],zones:[],landing:null,rebound:null,initial:pose(),released:null,attachedTicks:0};
  window.highFall=state;return state;
 }
 function step(){const s=window.highFall,tick=s.trace.length+1;
  if(tick===1){input('mousedown',s.target);s.inputs.push({tick,type:'mousedown',target:s.target})}
  if(tick===s.spec.hold+1){input('mouseup');s.inputs.push({tick,type:'mouseup'});s.released={tick,...pose()}}
  contacts=[];physics();if(grapnel.isGrappled())s.attachedTicks++;
  const yellow=floors[0].dragZones.filter(e=>pointInPolygon(e.getPoints(),ninja.x,ninja.y)).map(e=>e.id);
  const row={tick,...pose(),yellow,contacts:[...new Map(contacts.map(c=>[c.id+':'+c.nx+':'+c.ny,c])).values()]};
  const previous=s.trace.at(-1);if(JSON.stringify(previous?.yellow||[])!==JSON.stringify(yellow))s.zones.push({kind:yellow.length?'entry':'exit',...row});
  s.trace.push(row);
  if(s.released&&!s.landing&&row.contacts.some(c=>c.ny<-.9))s.landing=row;
  if(s.landing&&!s.rebound&&tick>s.landing.tick&&previous.vy<0&&row.vy>=0)s.rebound=row;
  return !!s.rebound;
 }
 function finish(onStep){const s=window.highFall;input('mouseup');
  s.recovery=RECOVERY.run({id:s.landing.contacts.find(c=>c.ny<-.9).id},540,{continue:true,budget:9000,hold:s.spec.recoveryHold||60,onStep});
  return s;
 }
 window.HIGH_FALL={begin,step,finish};
})();
