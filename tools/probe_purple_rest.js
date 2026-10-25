/* Rest-drop probe for no-grapple zones. Setup places the player at rest just
   above a face sample; thereafter only production physics runs (no input). */
(() => {
  window.requestAnimationFrame=()=>0; cancelAnimationFrame(game);
  ROLE_DETAIL.markContact=()=>{}; visualEffects=null; PROGRESS.climbTick=()=>{};
  let model=null;
  function load(level){model=level.svgFormat?importedMountainLevel(structuredClone(level)):structuredClone(level);}
  // One sample: {x,y} on the face, outward normal {nx,ny}. Returns the outcome only.
  function drop(s,o){
    const {seconds=5,stillSpeed=10,stillSeconds=1,gap=0.5}=o||{};
    floors=[loadFixedLevel(model)];grapnel=new Grapnel({stroke:STYLE.colors.player.cyan});
    const radius=10.8, d=radius+gap;
    ninja=new Ninja({x:s.x+s.nx*d,y:s.y+s.ny*d,radius,fill:STYLE.colors.player.cyan});
    ninja.speedX=ninja.speedY=0;
    pressHeld=stalePress=gameplayPressOwned=false;menu.gamePaused=false;hostPaused=false;unTouch=false;
    screen.trackGrappleOver(true);
    const world=floors[0], ticks=Math.round(seconds*physicsTicksPerSecond), need=Math.round(stillSeconds*physicsTicksPerSecond);
    const startInZone=world.playerInNoGrappleZone(ninja);
    // Still: over a stillSeconds window every position fits in a box of side
    // stillSpeed*stillSeconds (window speed below stillSpeed; ignores sub-unit bounce
    // jitter). Stuck = still in the final window of the run, so a slow roll-off from a
    // balanced start (still early, gone later) is not counted.
    const win=[],span=stillSpeed*stillSeconds;
    let px=ninja.x,py=ninja.y,firstStill=null,leftAt=null,maxSpeed=0,extent=null;
    for(let t=1;t<=ticks;t++){
      physics();
      maxSpeed=Math.max(maxSpeed,Math.hypot(ninja.x-px,ninja.y-py)*physicsTicksPerSecond);px=ninja.x;py=ninja.y;
      if(!world.playerInNoGrappleZone(ninja)){leftAt=t;break;}
      win.push([ninja.x,ninja.y]);if(win.length>need)win.shift();
      if(win.length===need){
        const xs=win.map(q=>q[0]),ys=win.map(q=>q[1]);
        extent=Math.max(Math.max(...xs)-Math.min(...xs),Math.max(...ys)-Math.min(...ys));
        if(extent<span&&firstStill===null)firstStill=t;
      }
    }
    const outcome=leftAt?'left':extent!==null&&extent<span?'stuck':'moving';
    const stuckAt=outcome==='stuck'?firstStill:null;
    const r=v=>Math.round(v*100)/100;
    return {outcome,startInZone,tick:stuckAt||leftAt||ticks,x:r(ninja.x),y:r(ninja.y),maxSpeed:r(maxSpeed),...(outcome==='left'||extent===null?{}:{extent:r(extent)})};
  }
  window.PURPLE_REST={load,drop};
})();
