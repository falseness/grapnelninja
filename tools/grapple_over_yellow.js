/* Isolated production-physics fixtures; never loaded by the live game. */
(() => {
 let tick,rows,inputs,bounces;
 const original=Ninja.prototype.applyBounce;
 Ninja.prototype.applyBounce=function(c){
  const before={x:this.x,y:this.y,vy:this.speedY};const result=original.call(this,c);
  if(c.approaching)bounces.push({tick,id:c.element?.id,before,after:{x:this.x,y:this.y,vy:this.speedY}});
  return result;
 };
 for(const type of ['mousedown','mouseup'])document.addEventListener(type,e=>inputs.push({type,trusted:e.isTrusted,tick}));
 const rect=(id,a,role='solid')=>({id,x:a[0],y:a[1],role,grapplable:role!=='drag',points:[{x:0,y:0},{x:a[2],y:0},{x:a[2],y:a[3]},{x:0,y:a[3]}]});
 window.YELLOW={
 setup({band=true,height=GRAPPLE_OVER_YELLOW.band.height}={}){
  tick=0;rows=[];inputs=[];bounces=[];
  const c=GRAPPLE_OVER_YELLOW,m=structuredClone(GRAPPLE_OVER_REPLACEMENT);
  m.sections=[{id:'S01',status:'built',encounters:['yellow-example']}];m.finish=null;m.movers=[{id:'remote-mover',element:'blue',axis:'x',min:-2500,max:-1780,periodMs:10000,phase:0}];
  m.bounds={left:-3000,right:4000,top:-4000,bottom:4000};
  m.elements=[rect('blue',[-2500,-1800,160,80]),rect('lower-landing',c.landing,'bounce'),rect('return-hook',c.returnHook),rect('return-wall',c.returnWall),rect('upper-route',[-1200,-3000,2400,60])];
  if(band)m.elements.push(rect('yellow',[c.band.left,c.band.top,c.band.width,height],'drag'));
  m.encounters=[{id:'yellow-example',elements:m.elements.map(e=>e.id)}];
  floors=[loadMountainLevel(m)];floors[0].rangeUpgraded=true;
  Object.assign(ninja,{...c.fall,speedX:0,speedY:0});
  grapnel.endShot();pressHeld=false;stalePress=false;gameplayPressOwned=false;screen.leftWall=null;screen.trackGrappleOver(true);
  this.manifest=m;this.height=height;this.sample();return m;
 },
 sample(){rows.push({tick,x:ninja.x,y:ninja.y,vx:ninja.speedX,vy:ninja.speedY,attached:grapnel.isGrappled(),inDrag:floors[0].dragZones.some(z=>pointInPolygon(z.getPoints(),ninja.x,ninja.y)||z.getLines().some(l=>segmentDistanceSquared(l,ninja.x,ninja.y)<ninja.radius*ninja.radius))})},
 step(n){for(let i=0;i<n;i++){physics();tick++;this.sample()}},
 result(){return {rows,inputs,bounces,radius:ninja.radius,tick,stats:floors[0].climbStats}},
 client(p){return canvasCoordsToViewportCoords({x:(p.x+screen.x)*scale[version],y:(p.y+screen.y)*scale[version]})},
 shot(p){const q=this.client(p);document.dispatchEvent(new MouseEvent('mousedown',{clientX:q.x,clientY:q.y,bubbles:true}))},
 release(){document.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}))}
 };
})();
