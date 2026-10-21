/* Isolated replacement mover calibration. Not loaded by the live mountain. */
(() => {
 let tick=0,rows=[],inputs=[],contacts=[],minClearance;
 const original=Ninja.prototype.applySolidContact;
 Ninja.prototype.applySolidContact=function(c){contacts.push({id:c.element?.id,x:c.x,y:c.y,nx:c.nx,ny:c.ny});return original.call(this,c)};
 for(const type of ['mousedown','mouseup'])document.addEventListener(type,e=>inputs.push({type,trusted:e.isTrusted,tick}));
 const rect=(id,x,y,w,h,role='bounce')=>({id,x,y,role,grapplable:true,points:[{x:0,y:0},{x:w,y:0},{x:w,y:h},{x:0,y:h}]});
 window.MOVERS={
 setup({axis='x',periodMs=10000,phase=0}={}){
  tick=0;rows=[];inputs=[];contacts=[];minClearance=Infinity;
  const m=structuredClone(GRAPPLE_OVER_REPLACEMENT);
  m.sections=[{id:'S01',status:'built',encounters:['mover-example']}];m.finish=null;
  m.bounds={left:-2000,right:4000,top:-2000,bottom:4000};
  const horizontal=axis==='x';
  const spec=GRAPPLE_OVER_MOVERS.examples.find(e=>e.axis===axis);
  m.elements=['takeoff','blue','landing'].map(id=>rect(id,...spec[id],'solid'));
  m.elements.push(rect('yellow',1600,200,160,300,'drag'));
  m.encounters=[{id:'mover-example',elements:m.elements.map(e=>e.id)}];
  m.movers=[{id:'long-'+axis,element:'blue',axis,min:horizontal?600:80,max:horizontal?1320:800,periodMs,phase}];
  floors=[loadMountainLevel(m)];Object.assign(ninja,{x:horizontal?500:850,y:1040-ninja.radius-GAMEPLAY.cubeContactEpsilon,speedX:0,speedY:0});
  grapnel.endShot();pressHeld=false;stalePress=false;gameplayPressOwned=false;screen.leftWall=null;screen.trackGrappleOver(true);
  this.axis=axis;this.periodMs=periodMs;return m;
 },
 target(){const e=floors[0].byId.get('blue');return {x:this.axis==='x'?e.x:e.x+160,y:e.y+80}},
 client(p){return canvasCoordsToViewportCoords({x:(p.x+screen.x)*scale[version],y:(p.y+screen.y)*scale[version]})},
 step(n){for(let i=0;i<n;i++){contacts=[];
   for(let j=0;j<cyclesPerTick;j++){calcPhysics();
    for(const e of floors[0].elements){const pts=e.getPoints(),xs=pts.map(p=>p.x),ys=pts.map(p=>p.y);
     const l=Math.min(...xs),r=Math.max(...xs),t=Math.min(...ys),b=Math.max(...ys);
     const dx=Math.max(l-ninja.x,0,ninja.x-r),dy=Math.max(t-ninja.y,0,ninja.y-b);
     minClearance=Math.min(minClearance,Math.hypot(dx,dy)-ninja.radius);
    }
   }screen.trackGrappleOver();tick++;const e=floors[0].byId.get('blue');rows.push({tick,x:ninja.x,y:ninja.y,vx:ninja.speedX,vy:ninja.speedY,mx:e.x,my:e.y,attached:grapnel.isGrappled(),contacts:contacts.filter((c,i,a)=>i===a.findIndex(v=>v.nx===c.nx&&v.ny===c.ny&&v.y===c.y))});}},
 result(){return {rows,inputs,tick,minClearance,radius:ninja.radius}},
 shot(){const p=this.client(this.target());document.dispatchEvent(new MouseEvent('mousedown',{clientX:p.x,clientY:p.y,bubbles:true}))},
 release(){document.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}))}
 };
})();
