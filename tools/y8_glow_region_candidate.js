// TASK-280 candidate: composite the glow levels through a union-of-rectangles clip
// instead of one bounding box (page-injected for the experiment; the body between the
// BEGIN/END markers is what an ACCEPT pastes over the TASK-265 block in render/effects.js).
//
// Target (TASK-276 stages.json): the glow composite, N full-resolution 'lighter' upscales of
// the blur levels through the geometry destination clip, is the dominant stage of every
// renderer/mode pair (ambient: 38.8 ms bad / 49.3 ms classic median saving when switched off,
// REPEATED beyond noise). The integrated clip is the bounding box of everything drawn into
// level 0; for the ambient chain that box is the whole viewport (TASK-276 frozen profile:
// level0_dest_box_observed [0,0,1280,719] bad, [0,0,1270,719] classic) because the 40 motes are
// spread over the field, so the box removes nothing there. The level textures are opaque black
// wherever nothing was drawn, and 'lighter' adds src*alpha: black source pixels leave the
// destination unchanged, so every upscale pixel outside the dilated support of the drawn
// primitives is work with no effect on the image.
//
// Mechanism: record each primitive's own device-pixel rectangle (not only the running union),
// dilate every rectangle per level with the unchanged conservative rules (two source texels per
// transfer, rounded outwards, two target texels), merge them into a disjoint set of
// integer-aligned rectangles and clip the same full drawImage to that region. Same drawImage
// submissions, same alphas, blend order and bilinear sampling of the whole level; only the clip
// region shrinks. Integer-aligned edges keep an anti-aliased clip at coverage 0 or 1, so the
// result is pixel-identical by construction. When the region would not save at least
// (1 - REGION_MAX_AREA_RATIO) of the box, or the drawing is unknown/full, the box is used
// exactly as before.
(() => {
// BEGIN TASK-280 candidate body
// Bounds describe emitted geometry in level-zero device pixels. Unknown drawing
// falls back to the viewport. No pixel reads, recorded rectangles or source crops.
// Each primitive's rectangle is kept so the composite can clip to their union
// (a region) instead of their bounding box: black level texels add nothing under
// 'lighter', so the upscale outside the dilated primitives is work without effect.
const REGION_MAX_AREA_RATIO = 0.9;
(() => {
 const bounds = new WeakMap();
 const union = (s, x0,y0,x1,y1) => {
  if (![x0,y0,x1,y1].every(Number.isFinite)) {s.full=true;return;}
  s.box=[Math.min(s.box[0],x0),Math.min(s.box[1],y0),Math.max(s.box[2],x1),Math.max(s.box[3],y1)];
 };
 function rectangle(c,x,y,w,h,pad=0) {
  const s=bounds.get(c); if(!s?.active)return;
  if(c.filter!=='none'||c.shadowBlur||c.shadowOffsetX||c.shadowOffsetY) {s.full=true;return;}
  const m=c.getTransform();
  let x0=Infinity,y0=Infinity,x1=-Infinity,y1=-Infinity;
  for(const [u,v] of [[x-pad,y-pad],[x+w+pad,y-pad],[x-pad,y+h+pad],[x+w+pad,y+h+pad]]) {
   const a=m.a*u+m.c*v+m.e,b=m.b*u+m.d*v+m.f;
   union(s,a-2,b-2,a+2,b+2); // conservative raster antialias support
   x0=Math.min(x0,a-2);y0=Math.min(y0,b-2);x1=Math.max(x1,a+2);y1=Math.max(y1,b+2);
  }
  if(!s.full)s.rects.push([x0,y0,x1,y1]);
 }
 // Level-zero box -> destination canvas box for level i (unchanged TASK-265 rules).
 // Each unchanged downsample is bilinear. Expand by two source texels,
 // round outwards and add two target texels at every transfer.
 function dilate(b,renderer,i) {
  const target=renderer.levels[i].canvas;
  let previous=renderer.levels[0].canvas;
  for(let j=1;j<=i;j++) {
   const next=renderer.levels[j].canvas;
   b=[Math.floor((b[0]-2)*next.width/previous.width)-2,Math.floor((b[1]-2)*next.height/previous.height)-2,
      Math.ceil((b[2]+2)*next.width/previous.width)+2,Math.ceil((b[3]+2)*next.height/previous.height)+2];previous=next;
  }
  return [Math.max(0,Math.floor((b[0]-2)*renderer.canvas.width/target.width)),Math.max(0,Math.floor((b[1]-2)*renderer.canvas.height/target.height)),
          Math.min(renderer.canvas.width,Math.ceil((b[2]+2)*renderer.canvas.width/target.width)),Math.min(renderer.canvas.height,Math.ceil((b[3]+2)*renderer.canvas.height/target.height))];
 }
 // Union of integer rectangles as disjoint rectangles: scanline bands between
 // the distinct y edges, merged x spans per band, equal adjacent bands joined.
 function regionRects(rects) {
  const ys=Array.from(new Set(rects.flatMap(r=>[r[1],r[3]]))).sort((a,b)=>a-b);
  const out=[];let spans=null,band=null;
  const same=(p,q)=>p.length===q.length&&p.every((s,k)=>s[0]===q[k][0]&&s[1]===q[k][1]);
  const emit=()=>{for(const s of spans)out.push([s[0],band[0],s[1],band[1]])};
  for(let k=0;k<ys.length-1;k++) {
   const y0=ys[k],y1=ys[k+1],xs=[];
   for(const r of rects)if(r[1]<=y0&&r[3]>=y1)xs.push([r[0],r[2]]);
   xs.sort((a,b)=>a[0]-b[0]);
   const next=[];
   for(const x of xs){const last=next[next.length-1];if(last&&x[0]<=last[1])last[1]=Math.max(last[1],x[1]);else next.push([x[0],x[1]])}
   if(spans&&band[1]===y0&&same(spans,next))band[1]=y1;
   else{if(spans)emit();spans=next;band=[y0,y1]}
  }
  if(spans)emit();
  return out;
 }
 const area=rects=>rects.reduce((n,r)=>n+(r[2]-r[0])*(r[3]-r[1]),0);
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
  Object.assign(s,{active:true,full:false,box:[Infinity,Infinity,-Infinity,-Infinity],rects:[],circle:null,unknown:false,ribbon:false});
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
  let b=s?.box?.slice(),region=null,regionArea=null;
  if(!s||s.full)b=[0,0,renderer.canvas.width,renderer.canvas.height];
  else if(b[2]>=b[0]) {
   b=dilate(b,renderer,i);
   const merged=regionRects(s.rects.map(r=>dilate(r,renderer,i)).filter(r=>r[2]>r[0]&&r[3]>r[1]));
   regionArea=area(merged);
   if(regionArea<=REGION_MAX_AREA_RATIO*(b[2]-b[0])*(b[3]-b[1]))region=merged;
  } else b=null;
  if(window.__geometryObserve)window.__geometryObserve(renderer,i,b,!!s?.full);
  if(window.__regionObserve)window.__regionObserve(renderer,i,b,region,regionArea,s?s.rects.length:0);
  if(!b||b[2]<=b[0]||b[3]<=b[1])return;
  const c=renderer.ctx;
  c.save();c.beginPath();
  if(region)for(const r of region)c.rect(r[0],r[1],r[2]-r[0],r[3]-r[1]);
  else c.rect(b[0],b[1],b[2]-b[0],b[3]-b[1]);
  c.clip();
  c.drawImage(target,0,0,renderer.canvas.width,renderer.canvas.height);c.restore();
 };
 window.__geometryRegionCandidate={task:'TASK-280',ratio:REGION_MAX_AREA_RATIO,regionRects,dilate,area};
})();
// END TASK-280 candidate body
})();
