/* TASK-669: continuous production-input replay of the opening combination.
   The fixture places the player once (zero speed above a panel: gravity makes
   the entry state). After that only real document mouse events drive the game
   and production physics() runs every tick; nothing writes position, velocity
   or grapple state. Records the input events, bounce contacts (with the
   contact normal and the velocity before and after) and grapnel
   attach/release transitions. A level passed in goes through the production
   importedMountainLevel() wrapper, so its SVG grapple range is the
   acquisition radius exactly as in the shipped game. */
(() => {
  window.requestAnimationFrame=()=>0; cancelAnimationFrame(game);
  const shipped=structuredClone(floors[0].level);
  let log=null, tick=0;
  const original=Ninja.prototype.applyBounce;
  Ninja.prototype.applyBounce=function(c){
    const vx=this.speedX, vy=this.speedY;
    original.call(this,c);
    if(c.approaching&&log)log.contacts.push({tick,id:c.element.id,nx:+c.nx.toFixed(4),ny:+c.ny.toFixed(4),
      x:+this.x.toFixed(2),y:+this.y.toFixed(2),vxIn:+vx.toFixed(3),vyIn:+vy.toFixed(3),vxOut:+this.speedX.toFixed(3),vyOut:+this.speedY.toFixed(3)});
  };
  // Rendering-only work is unnecessary in fixed-tick replays.
  ROLE_DETAIL.markContact=()=>{}; visualEffects=null; PROGRESS.climbTick=()=>{};
  function pointer(type,p){
    const q=canvasCoordsToViewportCoords({x:(p[0]+screen.x)*scale[version],y:(p[1]+screen.y)*scale[version]});
    document.dispatchEvent(new MouseEvent(type,{clientX:q.x,clientY:q.y,bubbles:true,button:0}));
  }
  function topAt(e,fraction){
    const pts=e.getPoints();const lo=Math.min(...pts.map(p=>p.x)),hi=Math.max(...pts.map(p=>p.x));
    const x=lo+(hi-lo)*fraction;const ys=[];
    for(const l of e.getLines())if(x>=Math.min(l.x1,l.x2)&&x<=Math.max(l.x1,l.x2)&&l.x1!==l.x2)
      ys.push(l.y1+(x-l.x1)*(l.y2-l.y1)/(l.x2-l.x1));
    return {x,y:Math.min(...ys)};
  }
  const r=v=>+v.toFixed(3);
  function state(){return {tick,x:r(ninja.x),y:r(ninja.y),vx:r(ninja.speedX),vy:r(ninja.speedY)};}
  /* start(options) -> controller with press(aim), release(), step(); options:
     level (null = the shipped level), fixture {panel, fraction, drop}. */
  function start({level=null,fixture}){
    floors=[loadFixedLevel(level?importedMountainLevel(structuredClone(level)):structuredClone(shipped))];
    grapnel=new Grapnel({stroke:STYLE.colors.player.cyan});
    const p=topAt(floors[0].byId.get(fixture.panel+'-body0'),fixture.fraction);
    ninja=new Ninja({x:p.x,y:p.y-fixture.drop,radius:10.8,fill:STYLE.colors.player.cyan});
    ninja.speedX=ninja.speedY=0;
    pressHeld=stalePress=gameplayPressOwned=false;menu.gamePaused=false;hostPaused=false;unTouch=false;
    screen.trackGrappleOver(true);tick=0;
    log={layoutId:floors[0].level.layoutId,acquisitionRadius:grappleOverAcquisitionRadius(),
      fixture:{...fixture,x:r(p.x),y:r(p.y-fixture.drop),vx:0,vy:0},inputs:[],contacts:[],grapple:[],snapshots:[]};
    let held=null,attached=null,last={x:ninja.x,y:ninja.y},maxStep=0;
    const c={log,origin:p,
      press(aim){pointer('mousedown',aim);held=aim;log.inputs.push({tick,type:'down',aim,state:state()});},
      release(){pointer('mouseup',held||[ninja.x,ninja.y]);held=null;log.inputs.push({tick,type:'up',state:state()});},
      get held(){return held;},
      step(){
        if(held)pointer('mousemove',held);
        const before=log.contacts.length;physics();
        // Continuity: the largest per-tick move (no teleport after the fixture).
        maxStep=Math.max(maxStep,Math.hypot(ninja.x-last.x,ninja.y-last.y));last={x:ninja.x,y:ninja.y};
        const id=grapnel.grappled?grapnel.pos.at(-1)?.[2]?.id:null;
        if(id!==attached){
          log.grapple.push(id?{tick,event:'attach',id,point:grapnel.pos.at(-1).slice(0,2).map(r),...state()}:{tick,event:'detach',id:attached,...state()});
          attached=id;
        }
        log.maxStep=r(maxStep);tick++;
        return log.contacts.slice(before);
      },
      get tick(){return tick;},state};
    return c;
  }
  /* run(options): open-loop replay of inputs [{tick, type:'down'|'up', aim:[x,y]}]
     (aims in world units; while pressed the pointer follows the aim with
     mousemove every tick); stopOn {id, ny:'down'|'up'} ends at that contact. */
  function run(options){
    const {inputs=[],budget=1500,stopOn=null,snapshotEvery=0}=options;
    const c=start(options);const queue=[...inputs].sort((a,b)=>a.tick-b.tick);let stop=null;
    while(c.tick<budget){
      while(queue.length&&queue[0].tick===c.tick){const ev=queue.shift();ev.type==='down'?c.press(ev.aim):c.release();}
      const t=c.tick;const fresh=c.step();
      if(snapshotEvery&&t%snapshotEvery===0)c.log.snapshots.push({...state(),tick:t});
      if(stopOn)for(const k of fresh)
        if(k.id===stopOn.id+'-body0'&&(!stopOn.ny||(stopOn.ny==='down'?k.ny>0:k.ny<0))){stop=k;break;}
      if(stop||Math.abs(ninja.y-c.origin.y)>6000)break;
    }
    if(c.held)c.release();
    c.log.ticks=c.tick;c.log.final=state();c.log.stopped=stop;
    return c.log;
  }
  window.OPENING_REPLAY={run,start,shipped,topAt};
})();
