/* TASK-563: isolated late-game calibration, never loaded by index.html. */
(() => {
 let tick=0,rows=[],inputs=[],contacts=[],world;
 const original=Ninja.prototype.applyHazardContact;
 Ninja.prototype.applyHazardContact=function(c){
  const before={vx:this.speedX,vy:this.speedY,cooldown:this.hazardCooldownMs};
  original.call(this,c);
  contacts.push({tick,id:c.element?.id,nx:c.nx,ny:c.ny,before,
   after:{vx:this.speedX,vy:this.speedY,cooldown:this.hazardCooldownMs,attached:grapnel.isGrappled()}});
 };
 for(const type of ['mousedown','mouseup'])document.addEventListener(type,e=>inputs.push({type,trusted:e.isTrusted,tick}));
 const rect=(id,a,role='solid')=>({id,x:a[0],y:a[1],role,grapplable:role==='solid',points:[{x:0,y:0},{x:a[2],y:0},{x:a[2],y:a[3]},{x:0,y:a[3]}]});
 window.HAZARD={
 setup(phase=0){
  tick=0;rows=[];inputs=[];contacts=[];
  const m=structuredClone(GRAPPLE_OVER_REPLACEMENT);
  m.sections=[{id:'S07',status:'built',encounters:['red-introduction']}];m.finish=null;
  m.bounds={left:-1000,right:2400,top:-1800,bottom:1500};
  m.elements=[rect('observation',[0,100,500,60]),rect('catch',[-800,600,3000,60]),
   rect('recovery-hook',[820,440,120,60]),rect('exit',[900,0,160,80]),rect('return-wall',[1100,0,60,540]),
   rect('red',[650,-500,80,80],'hazard'),rect('remote-yellow',[-700,-1200,600,100],'drag')];
  m.encounters=[{id:'red-introduction',elements:m.elements.map(e=>e.id)}];
  m.movers=[{id:'red-cycle',element:'red',axis:'y',min:-500,max:200,periodMs:6000,phase}];
  floors=[loadMountainLevel(m)];world=floors[0];world.rangeUpgraded=true;
  Object.assign(ninja,{x:480,y:100-ninja.radius-GAMEPLAY.cubeContactEpsilon,speedX:0,speedY:0,hazardCooldownMs:0});
  grapnel.endShot();pressHeld=false;stalePress=false;gameplayPressOwned=false;screen.leftWall=null;screen.trackGrappleOver(true);
  this.manifest=m;this.sample();return m;
 },
 sample(){const e=world.byId.get('red');rows.push({tick,x:ninja.x,y:ninja.y,vx:ninja.speedX,vy:ninja.speedY,redY:e.y,cooldown:ninja.hazardCooldownMs,attached:grapnel.isGrappled(),sameWorld:floors[0]===world,continueOffer:continueOffer.visible,run:runInProgress})},
 step(n){for(let i=0;i<n;i++){physics();tick++;this.sample()}},
 result(){return {rows,inputs,contacts,tick,radius:ninja.radius,stats:world.climbStats}},
 client(p){return canvasCoordsToViewportCoords({x:(p.x+screen.x)*scale[version],y:(p.y+screen.y)*scale[version]})},
 shot(p){const q=this.client(p);document.dispatchEvent(new MouseEvent('mousedown',{clientX:q.x,clientY:q.y,bubbles:true}))},
 release(){document.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}))}
 };
})();
