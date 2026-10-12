// Isolated TASK-265 experiment; loaded only by profile_y8_live_geometry.py.
// Bounds describe emitted geometry in level-zero device pixels. Unknown drawing
// falls back to the viewport. No pixel reads, recorded rectangles or source crops.
(() => {
 const bounds = new WeakMap();
 const union = (s, x0,y0,x1,y1) => {
  if (![x0,y0,x1,y1].every(Number.isFinite)) {s.full=true;return;}
  s.box=[Math.min(s.box[0],x0),Math.min(s.box[1],y0),Math.max(s.box[2],x1),Math.max(s.box[3],y1)];
 };
 function rectangle(c,x,y,w,h,pad=0) {
  const s=bounds.get(c); if(!s?.active)return;
  const filter=c.filter; // undefined in WebKit (no CanvasRenderingContext2D.filter): treat as 'none', TASK-311
  if((filter!==undefined&&filter!=='none')||c.shadowBlur||c.shadowOffsetX||c.shadowOffsetY) {s.full=true;return;}
  const m=c.getTransform();
  for(const [u,v] of [[x-pad,y-pad],[x+w+pad,y-pad],[x-pad,y+h+pad],[x+w+pad,y+h+pad]]) {
   const a=m.a*u+m.c*v+m.e,b=m.b*u+m.d*v+m.f;
   union(s,a-2,b-2,a+2,b+2); // conservative raster antialias support
  }
 }
 window.__geometryBegin=c=>{
  let s=bounds.get(c);
  if(!s){
   s={};bounds.set(c,s);
   const wrap=(name,before)=>{const original=c[name];c[name]=function(...args){before(...args);return original.apply(this,args)}};
   wrap('fillRect',(x,y,w,h)=>rectangle(c,x,y,w,h));
   wrap('beginPath',()=>{s.circle=null;s.unknown=false});
   wrap('arc',(x,y,r)=>{if(s.circle)s.unknown=true;s.circle=[x,y,r];});
   wrap('stroke',()=>{
    if(!s.active)return;
    if(s.unknown||!s.circle){s.full=true;return;}
    const [x,y,r]=s.circle;
    // Full circle envelope also contains every round/square cap. Miter joins
    // are bounded with miterLimit even though the emitted ring has no joins.
    rectangle(c,x-r,y-r,2*r,2*r,c.lineWidth*Math.max(1,c.miterLimit));
   });
   wrap('fill',()=>{if(s.active&&!s.ribbon)s.full=true;s.ribbon=false;});
   for(const name of ['moveTo','lineTo','bezierCurveTo','quadraticCurveTo','rect','ellipse','arcTo'])
    wrap(name,()=>{s.unknown=true});
   for(const name of ['drawImage','strokeRect','fillText','strokeText','putImageData'])
    wrap(name,()=>{if(s.active)s.full=true});
  }
  Object.assign(s,{active:true,full:false,box:[Infinity,Infinity,-Infinity,-Infinity],circle:null,unknown:false,ribbon:false});
 };
 window.__geometryRibbon=(c,positions,start,width)=>{
  const s=bounds.get(c);if(!s?.active)return;
  const config=STYLE.trails.player;
  const r=Math.abs(width)*Math.max(Math.abs(config.tailWidthRatio),Math.abs(config.headWidthRatio))/2;
  for(let i=Math.max(0,start-1);i<positions.length;i++)
   rectangle(c,positions[i].x+screen.x-r,positions[i].y+screen.y-r,2*r,2*r);
  s.ribbon=true;
 };
 window.__geometryEnd=c=>{bounds.get(c).active=false};
 window.__geometryDraw=(renderer,i)=>{
  const s=bounds.get(renderer.levels[0].ctx), target=renderer.levels[i].canvas;
  let b=s?.box?.slice();
  if(!s||s.full)b=[0,0,renderer.canvas.width,renderer.canvas.height];
  else if(b[2]>=b[0]) {
   let previous=renderer.levels[0].canvas;
   // Each unchanged downsample is bilinear. Expand by two source texels,
   // round outwards and add two target texels at every transfer.
   for(let j=1;j<=i;j++) {
    const next=renderer.levels[j].canvas;
    b=[Math.floor((b[0]-2)*next.width/previous.width)-2,Math.floor((b[1]-2)*next.height/previous.height)-2,
       Math.ceil((b[2]+2)*next.width/previous.width)+2,Math.ceil((b[3]+2)*next.height/previous.height)+2];previous=next;
   }
   b=[Math.max(0,Math.floor((b[0]-2)*renderer.canvas.width/target.width)),Math.max(0,Math.floor((b[1]-2)*renderer.canvas.height/target.height)),
      Math.min(renderer.canvas.width,Math.ceil((b[2]+2)*renderer.canvas.width/target.width)),Math.min(renderer.canvas.height,Math.ceil((b[3]+2)*renderer.canvas.height/target.height))];
  } else b=null;
  if(window.__geometryObserve)window.__geometryObserve(renderer,i,b,!!s?.full);
  if(!b||b[2]<=b[0]||b[3]<=b[1])return;
  renderer.ctx.save();renderer.ctx.beginPath();renderer.ctx.rect(b[0],b[1],b[2]-b[0],b[3]-b[1]);renderer.ctx.clip();
  renderer.ctx.drawImage(target,0,0,renderer.canvas.width,renderer.canvas.height);renderer.ctx.restore();
 };
})();
