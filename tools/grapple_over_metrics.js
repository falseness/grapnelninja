/* Test-only isolated movement playground. Never loaded by the game. */
(() => {
 let tick=0, contacts=[], rows=[], inputs=[], acquired=false, streak=0, maxAir=0, landed=false, landingAir=0, anchorTopContact=false;
 for(const method of ['applySolidContact','applyBounce']) {
  const original=Ninja.prototype[method];
  Ninja.prototype[method]=function(c){contacts.push({id:c.element?.id || 'solid',nx:c.nx,ny:c.ny});return original.call(this,c)};
 }
 for(const type of ['mousedown','mouseup','touchstart','touchend']) document.addEventListener(type,e=>{
  const p=e.changedTouches?e.changedTouches[0]:e;
  inputs.push({type,trusted:e.isTrusted,tick,x:p.clientX,y:p.clientY});
 });
 window.METRICS={
 setup(c){
  const rect=(id,x,y,w,h)=>({id,x,y,role:'bounce',grapplable:true,points:[{x:0,y:0},{x:w,y:0},{x:w,y:h},{x:0,y:h}]});
  const m=structuredClone(GRAPPLE_OVER_REPLACEMENT);
  m.sections=[{id:'S01',status:'built',encounters:['metrics']}];m.finish=null;
  m.elements=[rect('takeoff',0,1000,c.width,GRAPPLE_OVER_MOVEMENT.panelThickness),rect('landing',c.width+c.gap,1000,c.width,GRAPPLE_OVER_MOVEMENT.panelThickness),rect('anchor',c.width-80+c.dx,1000-ninja.radius-c.dy,GRAPPLE_OVER_MOVEMENT.anchorFace.width,GRAPPLE_OVER_MOVEMENT.anchorFace.height)];
  m.encounters=[{id:'metrics',elements:m.elements.map(e=>e.id)}];m.bounds={left:-2000,right:6000,top:-4000,bottom:8000};
  floors=[loadMountainLevel(m)];floors[0].rangeUpgraded=c.radius===540;
  Object.assign(ninja,{x:c.width-80,y:1000-ninja.radius-1,speedX:0,speedY:0});
  grapnel.endShot();pressHeld=false;stalePress=false;gameplayPressOwned=false;
  screen.leftWall=null;screen.trackGrappleOver(true);
  tick=0;contacts=[];rows=[];inputs=[];acquired=false;streak=0;maxAir=0;landed=false;landingAir=0;anchorTopContact=false;
  this.c=c;
  return {x:m.elements[2].x+80,y:m.elements[2].y+40,diameter:ninja.radius*2,stepMs:physicsStepMs,reach:Math.hypot(c.dx+80,c.dy-40),clearance:c.dy-80+ninja.radius};
 },
 client(p){return canvasCoordsToViewportCoords({x:(p.x+screen.x)*scale[version],y:(p.y+screen.y)*scale[version]})},
 step(n){for(let i=0;i<n;i++){
  contacts=[];physics();tick++;
  acquired ||= grapnel.isGrappled();
  if(contacts.some(c=>c.id==='landing'&&c.ny<-.9)){landed=true;landingAir=Math.max(landingAir,streak)}
  anchorTopContact ||= contacts.some(c=>c.id==='anchor'&&c.ny<-.9);
  streak=contacts.length===0&&!grapnel.isGrappled()&&!grapnel.throwed?streak+1:0;maxAir=Math.max(maxAir,streak);

  rows.push({tick,x:ninja.x,y:ninja.y,attached:grapnel.isGrappled(),throwed:grapnel.throwed,contacts});
 }},
 result(){return {acquired,landed,maxAir,landingAir,anchorTopContact,ticks:tick,inputs,rows,range:grappleOverAcquisitionRadius()}},
 // Search uses production input handlers with synthetic events; final proof uses trusted input.
 shot(p,aim=0){const q=this.client(p);q.x+=aim;document.dispatchEvent(new MouseEvent('mousedown',{clientX:q.x,clientY:q.y,bubbles:true}))},
 release(){document.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}))},
 run(c,offset=0,aim=0,held=false){const p=this.setup(c);this.shot(p,aim);this.step(c.release+offset);if(!held)this.release();this.step(GRAPPLE_OVER_MOVEMENT.observationTicks-c.release-offset);return this.result()}
 };
})();
