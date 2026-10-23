/* Local deterministic probes. Only setup may place the player; thereafter use
   real pointer handlers and production physics. A seeded drop is not proof of
   a complete climb from spawn. */
(() => {
  window.requestAnimationFrame=()=>0; cancelAnimationFrame(game);
  const base=structuredClone(floors[0].level);
  let events=[], tick=0, recording=false, inputs=[];
  const original=Ninja.prototype.applyBounce;
  Ninja.prototype.applyBounce=function(c){
    original.call(this,c);
    if(c.approaching) events.push({tick,id:c.element.id,x:this.x,y:this.y,vx:this.speedX,vy:this.speedY});
  };
  // Rendering-only work is unnecessary in fixed-tick probes.
  ROLE_DETAIL.markContact=()=>{}; visualEffects=null;
  PROGRESS.climbTick=()=>{};
  function pointer(type,p){
    if(recording)inputs.push({tick,type:{mousedown:'down',mouseup:'up',mousemove:'move'}[type],aim:[p.x,p.y]});
    const q=canvasCoordsToViewportCoords({x:(p.x+screen.x)*scale[version],y:(p.y+screen.y)*scale[version]});
    document.dispatchEvent(new MouseEvent(type,{clientX:q.x,clientY:q.y,bubbles:true,button:0}));
  }
  function nearest(e){
    let best=null;
    for(const l of e.getLines()){
      const dx=l.x2-l.x1,dy=l.y2-l.y1;
      const t=Math.max(0,Math.min(1,((ninja.x-l.x1)*dx+(ninja.y-l.y1)*dy)/(dx*dx+dy*dy)));
      const q={x:l.x1+t*dx,y:l.y1+t*dy};q.d=Math.hypot(q.x-ninja.x,q.y-ninja.y);
      if(!best||q.d<best.d)best=q;
    }
    return best;
  }
  function top(e,fraction){
    const pts=e.getPoints();const lo=Math.min(...pts.map(p=>p.x)),hi=Math.max(...pts.map(p=>p.x));
    const x=lo+(hi-lo)*fraction;
    const ys=[];for(const l of e.getLines())if(x>=Math.min(l.x1,l.x2)&&x<=Math.max(l.x1,l.x2)&&l.x1!==l.x2)
      ys.push(l.y1+(x-l.x1)*(l.y2-l.y1)/(l.x2-l.x1));
    return {x,y:Math.min(...ys)};
  }
  function run(options){
    recording=!!options.recordInputs;inputs=[];
    const {source,target,fraction=.5,aimOffset=0,lastAimOffset=null,drop=30,holdTicks=0,pumps=2,budget=1800,level=base,guard=true,initialState=null}=options;
    const model=level.svgFormat?importedMountainLevel(structuredClone(level)):structuredClone(level);if(!guard)model.elements=model.elements.filter(e=>!e.id.startsWith('G'));
    floors=[loadFixedLevel(model)];grapnel=new Grapnel({stroke:STYLE.colors.player.cyan});
    const start=floors[0].byId.get(source+'-body0'), dest=floors[0].byId.get(target+'-body0');
    const launch=top(start,fraction);
    const pumpAim=top(start,Math.max(.02,Math.min(.98,fraction+aimOffset)));
    const lastPumpAim=lastAimOffset===null?pumpAim:top(start,Math.max(.02,Math.min(.98,fraction+lastAimOffset)));
    ninja=new Ninja({x:launch.x,y:launch.y-drop,radius:10.8,fill:STYLE.colors.player.cyan});
    ninja.speedX=ninja.speedY=0;
    pressHeld=stalePress=gameplayPressOwned=false;menu.gamePaused=false;hostPaused=false;unTouch=false;
    if(initialState){
      restoreClimbState(initialState.save);
      gameplayPressOwned=initialState.owned;
      grapnel.aim=initialState.aim;
      menu.gamePaused=false;
    }
    screen.trackGrappleOver(true);events=[];tick=0;
    let arrival=null,count=0,lastBounce=-1,lastAim='',minY=ninja.y,hit=null,dragTicks=0;
    const snapshots=[];
    for(tick=0;tick<budget;tick++){
      let q=nearest(dest);
      if(options.targetSurface==='underside'){const ps=dest.getPoints();q={x:Math.max(Math.min(...ps.map(p=>p.x))+2,Math.min(Math.max(...ps.map(p=>p.x))-2,ninja.x)),y:Math.max(...ps.map(p=>p.y))-2};}
      let aim=null,key='';
      if(tick<holdTicks || (count<pumps && ninja.speedY>0)){const last=count===pumps-1;aim=last?lastPumpAim:pumpAim;key=last&&lastAimOffset!==null?'last-pump':'pump';}
      else {aim=q;key='target';}
      if(key!==lastAim){pointer('mouseup',ninja);pointer('mousedown',aim);lastAim=key;}
      else pointer('mousemove',aim);
      const before=events.length;physics();minY=Math.min(minY,ninja.y);
      for(const ev of events.slice(before)){
        if(ev.id===start.id){count++;lastBounce=tick;if(!arrival)arrival={...ev};}
        const idx=Number(ev.id.match(/^P(\d+)/)?.[1]);
        if(idx>Number(source.slice(1))){hit={kind:'contact',...ev};break;}
      }
      if(grapnel.grappled){const id=grapnel.pos.at(-1)?.[2]?.id;
        if(id&&Number(id.match(/^P(\d+)/)?.[1])>Number(source.slice(1)))hit={kind:'attach',tick,id,x:ninja.x,y:ninja.y,vx:ninja.speedX,vy:ninja.speedY};}
      if(floors[0].climbStats.completed&&!hit)hit={kind:'finish',tick,id:model.svgFormat.fragments.at(-1).id+'-body0',x:ninja.x,y:ninja.y,vx:ninja.speedX,vy:ninja.speedY};
      if(floors[0].dragZones.some(z=>pointInPolygon(z.getPoints(),ninja.x,ninja.y)))dragTicks++;
      if(tick%60===0)snapshots.push({tick,x:ninja.x,y:ninja.y,vx:ninja.speedX,vy:ninja.speedY});
      if(hit||ninja.y>launch.y+4000||Math.abs(ninja.x-launch.x)>12000)break;
    }
    const finalState=hit?{save:captureClimbState(),owned:gameplayPressOwned,aim:grapnel.aim}:null;
    pointer('mouseup',ninja);
    return {inputs:recording?inputs:undefined,finalState,source,target,fraction,aimOffset,lastAimOffset,drop,holdTicks,pumps,budget,guard,setup:{x:launch.x,y:launch.y-drop,vx:0,vy:0},arrival,
      hit,bounces:count,ticks:tick,minY,dragTicks,events:events.slice(0,30),snapshots};
  }
  window.ROUTE_PROBE={run,base};
})();
