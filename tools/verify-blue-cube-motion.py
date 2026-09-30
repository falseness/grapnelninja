"""Capture ten one-second-spaced live bad-mode images per frame (Frames 7 and 9 by default).

Run a local HTTP server, then run this script with Python Playwright and Pillow.
Inspect every saved image before treating the automated measurements as a pass.
Only the player/camera are held still; generated cubes use live game physics.
Outputs are untracked evidence, defaulting to artifacts/TASK-024.
Frame 1 (--frames frame1Elements) also checks the cube's horizontal pillar bounces.
"""
import base64, hashlib, json, subprocess
from pathlib import Path
from playwright.sync_api import sync_playwright
from PIL import Image, ImageDraw
import argparse
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--url', default='http://127.0.0.1:8024/')
parser.add_argument('--output', type=Path, default=Path('artifacts/TASK-024'))
parser.add_argument('--frames', default='frame7Elements,frame9Elements', help='comma-separated frame types')
args=parser.parse_args()
out=args.output
out.mkdir(parents=True, exist_ok=True)
r={'commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'hashes':{f:hashlib.sha256(Path(f).read_bytes()).hexdigest() for f in subprocess.check_output(['git','ls-files'],text=True).splitlines()},'frames':[], 'harnessSha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
console=[]; errors=[]
with sync_playwright() as p:
 b=p.chromium.launch(args=['--no-sandbox'])
 page=b.new_page(viewport={'width':772,'height':630})
 page.on('console',lambda m:console.append(m.type+': '+m.text)); page.on('pageerror',lambda e:errors.append(str(e)))
 page.goto(args.url)
 page.evaluate("startGame('bad'); cancelAnimationFrame(game)")
 for frame in args.frames.split(','):
  initial=page.evaluate('''frame=>{
   cancelAnimationFrame(game); chooseVersion(); ninja.move=()=>{}; ninja.speedX=0; ninja.speedY=0;
   floors[1].elements=[]; floors[1].creations=[{type:frame,chance:100}]; floors[1].generatePrimaryElements();
   window.cube=floors[1].elements.find(e=>e instanceof JumpingCube);
   window.box=e=>{let p=e.getPoints();return {left:Math.min(...p.map(p=>p.x)),right:Math.max(...p.map(p=>p.x)),top:Math.min(...p.map(p=>p.y)),bottom:Math.max(...p.map(p=>p.y))}};
   window.probe={trace:[],collisions:[]};
   const collide=cube.collisionWithElements;
   cube.collisionWithElements=function(){
    let hits=[];const circle=this.getCircumscribedCircle(), lines=this.getLines();
    for(const [fi,f] of floors.entries()) for(const [ei,e] of f.elements.entries()) {
     if(circlesIntersect(circle,e.getCircumscribedCircle()) && e.getLines().some(a=>lines.some(b=>linesCollision(a,b)))) hits.push({floor:fi,index:ei,type:e.constructor.name,self:e===this,box:box(e)});
    }
    let before=this.speedY;collide.call(this);
    if(hits.length||this.speedY!==before) probe.collisions.push({step:probe.trace.length,y:this.y,before,after:this.speedY,hits});
   };
   const move=cube.move;
   cube.move=function(){const y=this.y,v=this.speedY;move.call(this);let a=box(this);
    const gaps=floors.flatMap(f=>f.elements).filter(e=>e!==this).map(e=>{let b=box(e);return {type:e.constructor.name,gap:Math.max(b.left-a.right,a.left-b.right,b.top-a.bottom,a.top-b.bottom)}});
    probe.trace.push({time:performance.now(),x:this.x,speedX:this.speedX,beforeY:y,beforeSpeed:v,y:this.y,speedY:this.speedY,minGap:Math.min(...gaps.map(g=>g.gap)),overlaps:gaps.filter(g=>g.gap<0)});
   };
   window.snapshot=()=>({time:performance.now(),x:cube.x,y:cube.y,speedX:cube.speedX,speedY:cube.speedY,box:box(cube),png:canvas.toDataURL('image/png')});
   resetPhysicsTiming();draw();
   return {gravity:GRAVITY,cyclesPerTick,scale:scale.bad,initial:snapshot(),pillars:floors[1].elements.filter(e=>e instanceof Trampoline).slice(0,2).map(box),objects:floors.map(f=>f.elements.map(e=>({type:e.constructor.name,box:box(e)})))};
  }''',frame)
  row={'frame':frame,**initial,'screens':[]}
  for i in range(10):
   if i==0: snap=row.pop('initial')
   else:
    if i==1: page.evaluate('game=requestAnimationFrame(gameLoop)')
    page.wait_for_timeout(1000);snap=page.evaluate('snapshot()')
   name=f'{frame}-{i:02}.png';(out/name).write_bytes(base64.b64decode(snap.pop('png').split(',')[1]));snap['path']=str(out/name);row['screens'].append(snap)
  page.evaluate('cancelAnimationFrame(game)')
  row.update(page.evaluate('probe'));r['frames'].append(row)
  ys=[s['y'] for s in row['trace']];duration=(row['screens'][-1]['time']-row['screens'][0]['time'])/1000
  assert duration>=9 and len(ys)>100
  assert all(b['time']-a['time']>=1000 for a,b in zip(row['screens'],row['screens'][1:]))
  assert max(ys)-min(ys)>100
  assert all(s['minGap']>=0 for s in row['trace'])
  assert len(row['collisions'])>=1
  if frame=='frame1Elements':
   xs=[s['x'] for s in row['screens']];sx=[s['speedX'] for s in row['trace']]
   row['speedXSignChanges']=sum(a*b<0 for a,b in zip(sx,sx[1:]))
   inner=(row['pillars'][0]['right'],row['pillars'][1]['left'])
   assert row['speedXSignChanges']>=2
   assert all(inner[0]-1e-6<=s['box']['left'] and s['box']['right']<=inner[1]+1e-6 for s in row['screens'])
   # Distinct positions: sorted x values more than 10 world px (~4.5 canvas px) apart.
   distinct=1+sum(b-a>10 for a,b in zip(sorted(xs),sorted(xs)[1:]))
   assert max(xs)-min(xs)>100 and distinct>=8, xs
   print(f"PASS {frame} horizontal: speedXSignChanges={row['speedXSignChanges']}; screenshot xRange={max(xs)-min(xs):.3f}; distinct x (>10px apart)={distinct}/10; xs={[round(x,1) for x in xs]}; inside pillars {inner[0]:.3f}..{inner[1]:.3f}",flush=True)
  for s in row['screens']: assert Image.open(s['path']).size==(772,630)
  print(f"PASS {frame}: screenshots=10; duration={duration:.3f}s; moveCalls={len(ys)}; yRange={max(ys)-min(ys):.6f}; initialSpeedY={row['screens'][0]['speedY']}; gravity={row['gravity']}; collisions={len(row['collisions'])}; overlapSubsteps={sum(s['minGap']<0 for s in row['trace'])}",flush=True)
 b.close()
r.update(console=console,errors=errors)
(out/'run.json').write_text(json.dumps(r,indent=2))
(out/'motion.json').write_text(json.dumps([{'frame':row['frame'],'pillars':row['pillars'],'speedXSignChanges':row.get('speedXSignChanges'),'screens':[{k:s[k] for k in ('path','time','x','y','speedX','speedY','box')} for s in row['screens']]} for row in r['frames']],indent=2));(out/'console.log').write_text('\n'.join(console));(out/'page-errors.log').write_text('\n'.join(errors))
assert not errors and not any(m.startswith('error:') for m in console)
print('PASS browser console errors=0; page errors=0')
for row in r['frames']:
 sheet=Image.new('RGB',(5*386,2*335),'#202020');d=ImageDraw.Draw(sheet)
 for i,s in enumerate(row['screens']):
  im=Image.open(s['path']).convert('RGB');im.thumbnail((386,315));x=i%5*386;y=i//5*335;sheet.paste(im,(x,y+20));d.text((x+5,y+3),f"{row['frame']} {i} y={s['y']:.2f}",fill='white')
 sheet.save(out/(row['frame']+'-contact-sheet.png'))
