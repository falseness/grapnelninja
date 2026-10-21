/* TASK-567 observation only: no fixtures, physics overrides, or state injection. */
(() => {
 let tick=0, contacts=[], rows=[], inputs=[];
 for (const method of ['applySolidContact','applyBounce']) {
  const original=Ninja.prototype[method];
  Ninja.prototype[method]=function(c) {
   contacts.push({id:c.element?.id || 'solid',nx:c.nx,ny:c.ny});
   return original.call(this,c);
  };
 }
 for (const type of ['mousedown','mouseup']) document.addEventListener(type,e=>{
  inputs.push({tick,type,trusted:e.isTrusted,x:e.clientX,y:e.clientY});
 });
 window.YARD={
  client(p){return canvasCoordsToViewportCoords({x:(p.x+screen.x)*scale[version],y:(p.y+screen.y)*scale[version]})},
  step(n){for(let i=0;i<n;i++){
   contacts=[];physics();tick++;
   rows.push({tick,x:ninja.x,y:ninja.y,vx:ninja.speedX,vy:ninja.speedY,
    attached:grapnel.isGrappled(),shot:grapnel.throwed,contacts});
  }},
  result(){return {tick,rows,inputs,range:grappleOverAcquisitionRadius()}},
  nearest(){
   const candidates=[];
   for(const e of floors[0].elements){
    const pts=e.getPoints(), center={x:pts.reduce((v,p)=>v+p.x,0)/pts.length,y:pts.reduce((v,p)=>v+p.y,0)/pts.length};
    for(let i=0;i<pts.length;i++){
     const a=pts[i],b=pts[(i+1)%pts.length],dx=b.x-a.x,dy=b.y-a.y;
     const t=Math.max(0,Math.min(1,((ninja.x-a.x)*dx+(ninja.y-a.y)*dy)/(dx*dx+dy*dy)));
     const x=a.x+t*dx,y=a.y+t*dy;
     candidates.push({id:e.id,x:x*.99+center.x*.01,y:y*.99+center.y*.01,distance:Math.hypot(x-ninja.x,y-ninja.y)});
    }
   }
   return candidates.sort((a,b)=>a.distance-b.distance)[0];
  }
 };
})();
