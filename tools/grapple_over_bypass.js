/* Bounded TASK-622 isolated probes; production input handlers and physics. */
(() => {
 const exits=['yard-landing','yard-second-landing','yard-third-landing','yard-fourth-landing',
 'quarry-landing','quarry-second-landing','quarry-third-landing','quarry-fourth-landing',
 'freight-landing','freight-second-landing','freight-lift-landing','freight-exit',
 'viaduct-landing','viaduct-second-landing','viaduct-third-landing','viaduct-exit',
 'gallery-landing','gallery-upper-landing','gallery-third-landing','gallery-exit',
 'tower-observation','tower-shaft-landing','tower-rebound-landing','tower-exit',
 'crown-landing','crown-practice-landing','crown-upper-landing','crown-exit',
 'summit-landing','summit-upper-landing','summit-timing-landing','summit-final-landing'];
 let contacts=[];
 for(const method of ['applySolidContact','applyBounce']) {
  const original=Ninja.prototype[method];
  Ninja.prototype[method]=function(c){contacts.push({id:c.element?.id,nx:c.nx,ny:c.ny});return original.call(this,c)};
 }
 const pose=()=>({x:ninja.x,y:ninja.y,vx:ninja.speedX,vy:ninja.speedY});
 const client=p=>canvasCoordsToViewportCoords({x:(p.x+screen.x)*scale[version],y:(p.y+screen.y)*scale[version]});
 function event(type,p){const q=client(p||ninja);document.dispatchEvent(new MouseEvent(type,{clientX:q.x,clientY:q.y,bubbles:true,button:0}));}
 function candidates(anchorsOnly){
  const candidates=[];
  for(const e of floors[0].elements){
   if(anchorsOnly&&!/anchor|carrier|lift|projection|overhang|counterweight|shuttle/.test(e.id))continue;
   const points=e.getPoints();
   for(let i=0;i<points.length;i++){
    const a=points[i],b=points[(i+1)%points.length],dx=b.x-a.x,dy=b.y-a.y;
    const t=Math.max(0,Math.min(1,((ninja.x-a.x)*dx+(ninja.y-a.y)*dy)/(dx*dx+dy*dy)));
    const q={id:e.id,x:a.x+t*dx,y:a.y+t*dy};q.distance=Math.hypot(q.x-ninja.x,q.y-ninja.y);
    const v=client(q);if(q.distance<1||q.distance>grappleOverAcquisitionRadius()||v.x<0||v.x>1280||v.y<0||v.y>720)continue;
    // A visible surface has no other polygon edge before it along the aim ray.
    const rx=q.x-ninja.x,ry=q.y-ninja.y;let blocked=false;
    for(const other of floors[0].elements){const ps=other.getPoints();
     for(let j=0;j<ps.length;j++){const c=ps[j],d=ps[(j+1)%ps.length],sx=d.x-c.x,sy=d.y-c.y,den=rx*sy-ry*sx;
      if(Math.abs(den)<1e-9)continue;
      const cx=c.x-ninja.x,cy=c.y-ninja.y,u=(cx*ry-cy*rx)/den,t=(cx*sy-cy*sx)/den;
      if(t>1e-6&&t<.99999&&u>=0&&u<=1){blocked=true;break;}
     }if(blocked)break;
    }
    if(!blocked)candidates.push(q);
   }
  }
  return candidates.sort((a,b)=>a.distance-b.distance||a.id.localeCompare(b.id));
 }
 function setup(start,range,control){
  let level=structuredClone(replacementMountainLevel(GRAPPLE_OVER_REPLACEMENT));
  if(control){
   const landing=level.elements.find(e=>e.id===control);landing.x=2050;landing.y=50;
   level.elements=[landing];level.movers=[];
   level.encounters=[{id:'control-encounter',elements:[control]}];
   level.sections=[{id:'control-section',encounters:['control-encounter']}];
  }
  floors=[loadFixedLevel(level)];floors[0].rangeUpgraded=range===540;
  floors[0].elapsedSteps=start.phaseTick*cyclesPerTick;
  floors[0].applyMovers(start.phaseTick*physicsStepMs);
  Object.assign(ninja,{x:start.pose.x,y:start.pose.y,speedX:start.pose.vx,speedY:start.pose.vy});
  grapnel=new Grapnel({stroke:STYLE.colors.player.cyan});
  pressHeld=stalePress=gameplayPressOwned=false;TUTORIAL_HINT.visible=false;
  menu.unPause();screen.trackGrappleOver(true);
 }
 function run(start,range,policy,budget=1200,control=null){
  setup(start,range,control);
  let high=start.completed,attachedTicks=0,shots=0;const completions=[],skips=[],aims=[],events=[];
  for(let tick=1;tick<=budget;tick++){
   if(tick===1||(policy.interval&&(tick-1)%policy.interval===0)){
    if(tick>1)event('mouseup');
    const target=candidates(policy.anchorsOnly)[0];
    if(target){event('mousedown',target);shots++;aims.push({tick,...target});}
   }
   contacts=[];physics();if(grapnel.isGrappled())attachedTicks++;
   for(const c of contacts){const index=exits.indexOf(c.id);if(index<0||c.ny>=-.9)continue;
    if(index>high){const skipped=exits.slice(high+1,index),crossSection=skipped.length>0&&Math.floor(index/4)!==Math.floor(Math.max(0,high)/4);
     const record={tick,id:c.id,index,previous:high,skipped,crossSection,pose:pose(),contact:c};
     completions.push(record);if(skipped.length)skips.push({...record,unapproved:skipped.length>1||crossSection});high=index;
    }
   }
   if(tick%120===0||completions.at(-1)?.tick===tick)events.push({tick,...pose(),attached:grapnel.isGrappled(),contacts});
  }
  event('mouseup');
  return {start:start.id,range,policy:policy.name,ticks:budget,shots,attachedTicks,aims,events,completions,skips,final:pose(),postSetupInjections:0};
 }
 window.BYPASS={run,setup,candidates,exits};
})();
