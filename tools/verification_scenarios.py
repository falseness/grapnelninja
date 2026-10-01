"""Shared, import-safe fixtures for percentage verification tools."""

scenario = '''mode => {
 startGame(mode); cancelAnimationFrame(game); menu.visible=false;
 // Reset randomness after startup so factory warm-up is identical.
 window.seed=1234;
 Math.random=()=>{seed=(1664525*seed+1013904223)>>>0;return seed/4294967296};
 floors[1].elements=[];
 floors[1].creations=[{type:'frame13Elements',chance:100}];
 floors[1].generatePrimaryElements();
 const cube=floors[1].elements.find(e=>e instanceof JumpingCube);
 const triangle=floors[1].elements.find(e=>e instanceof Triangle);
 ninja.x=width*.2; ninja.y=height*.3; ninja.speedX=0; ninja.speedY=0;
 const values={gravity:GRAVITY,throwSpeed:grapnelSpeed,pullSpeed:grappleSpeed,
   triangleSpeed:Math.abs(triangle.speedY),cameraX:screen.borderX,
   cameraTop:screen.topBorderY,cameraBottom:screen.bottomBorderY,cameraCenter:screen.centerBorderY};
 // Exercise the actual player cap without obstacle interference.
 const savedFloors=floors; floors=[];
 ninja.speedY=height; ninja.move(); values.ninjaCap=ninja.speedY;
 ninja.speedY=0; floors=savedFloors;
 grapnel.pos=[[ninja.x,ninja.y,new Empty()]];grapnel.throwed=true;
 const direction=grapnel.calcSpeed({x:ninja.x+100,y:ninja.y-100});
 grapnel.speedX=direction.cos*grapnelSpeed;grapnel.speedY=direction.sin*grapnelSpeed;
 const trace=[];
 for(let i=0;i<240;i++) {
   ninja.speedY+=GRAVITY;ninja.move();triangle.move();cube.move();grapnel.move();
   trace.push([ninja.x,ninja.y,ninja.speedY,triangle.y,triangle.speedY,cube.x,cube.y,cube.speedY,grapnel.pos[0][0],grapnel.pos[0][1]]);
 }
 // Exercise attached grapnel pull in the real physics function.
 floors=[];grapnel.pos=[[ninja.x+100,ninja.y-100,new Empty()]];
 grapnel.grappled=true; ninja.speedX=0;ninja.speedY=0;
 calcPhysics();values.pulledSpeedX=ninja.speedX;values.pulledSpeedY=ninja.speedY;
 floors=savedFloors;
 const eps=typeof GAMEPLAY==='undefined'?1:screenHeightPercent(GAMEPLAY.coordinateToleranceHeightPercent);
 values.lineInside=pointIsOnStraight({x:0,y:eps*.9},{type:'line',k:0,b:0});
 values.lineOutside=pointIsOnStraight({x:0,y:eps*1.1},{type:'line',k:0,b:0});
 values.cornerTolerance=typeof GAMEPLAY==='undefined'?6:screenHeightPercent(GAMEPLAY.cornerToleranceHeightPercent);
 values.firstPointTolerance=typeof GAMEPLAY==='undefined'?50:screenHeightPercent(GAMEPLAY.firstPointToleranceHeightPercent);
 values.coordinateTolerance=eps;
 return {values,trace};
}'''

frames = ['frame1Elements', 'frame3Triangle', 'frame4Elements', 'frame5Rects',
          'frame6Rects', 'frame7Elements', 'frame8Elements',
          'frame10Elements', 'frame11Elements', 'frame12Elements', 'frame13Elements']

expected = [['Trampoline', 'Trampoline', 'JumpingCube'], ['Triangle'], ['Trampoline', 'JumpingCube', 'Triangle'],
            ['Trampoline']*3, ['Rect']*2, ['Trampoline', 'JumpingCube'],
            ['Rect']+['Trampoline']*3,
            ['Trampoline', 'Rect', 'Rect'], ['Trampoline', 'Rect', 'Rect'],
            ['Trampoline']*3+['JumpingCube']*2, ['Trampoline']*3+['Triangle', 'JumpingCube']]

setup = '''frame => {
 startGame('bad'); cancelAnimationFrame(game); menu.visible=false;
 window.seed=1234;
 Math.random=()=>{seed=(1664525*seed+1013904223)>>>0;return seed/4294967296};
 const f=floors[1]; f.elements=[];
 window.snapshot=e=>({type:e.constructor.name,x:e.x,y:e.y,width:e.width,height:e.height,
   radius:e.radius,side:e.side,speedX:e.speedX,speedY:e.speedY,restrictionY:e.restrictionY,
   points:e.getPoints(),circle:e.getCircumscribedCircle(),fill:e.fill,stroke:e.stroke});
 // Check direct factory output as well as the floor's real group placement.
 window.raw=elementsFactory.create({min:width*.2,max:width*.2},{min:f.top,max:f.bottom},frame).map(snapshot);
 seed=1234; f.creations=[{type:frame,chance:100}]; f.generatePrimaryElements();
 // Startup may prefill several groups. Keep one real, fully placed template
 // for initial geometry, dynamic targets and all subsequent motion samples.
 const groupId=f.elements[0].generationGroupId;
 f.elements=f.elements.filter(e=>e.generationGroupId===groupId);
 window.initial=f.elements.map(snapshot);
 window.box=e=>{const p=e.getPoints();return {left:Math.min(...p.map(p=>p.x)),right:Math.max(...p.map(p=>p.x)),top:Math.min(...p.map(p=>p.y)),bottom:Math.max(...p.map(p=>p.y))}};
 window.dynamic=f.elements.filter(e=>e instanceof Triangle||e instanceof JumpingCube);
 draw();return {raw,initial};
}'''

motion = '''() => {
 const samples=[], stats=dynamic.map(e=>({type:e.constructor.name,minY:e.y,maxY:e.y,turns:0,minGap:Infinity,overlaps:0,boundViolations:0}));
 for(let step=0;step<14400;step++) {
  const speeds=dynamic.map(e=>e.speedY); floors[1].moveElements();
  dynamic.forEach((e,i)=>{
   const a=box(e), s=stats[i]; s.minY=Math.min(s.minY,e.y);s.maxY=Math.max(s.maxY,e.y);
   if(speeds[i]*e.speedY<0)s.turns++;
   if(e instanceof Triangle && (a.top<e.restrictionY.min-Math.abs(e.speedY)-1e-8||a.bottom>e.restrictionY.max+Math.abs(e.speedY)+1e-8))s.boundViolations++;
   for(const o of floors.flatMap(f=>f.elements)) {
    if(o===e)continue;const b=box(o);
    const gap=Math.max(b.left-a.right,a.left-b.right,b.top-a.bottom,a.top-b.bottom);
    s.minGap=Math.min(s.minGap,gap);if(gap < -1e-8)s.overlaps++;
   }
  });
  if(step%480===0)samples.push(floors[1].elements.map(snapshot));
 }
 draw(); return {stats,samples,substeps:14400,seconds:14400/(60*cyclesPerTick)};
}'''
