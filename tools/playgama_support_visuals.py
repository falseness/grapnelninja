"""Deterministic combined-support fixtures; rendering evidence, never timing data."""
SCENARIOS = ('startup', 'gameplay', 'camera', 'edge-overlap', 'empty', 'death',
             'restart-shake', 'portrait-odd', 'landscape-odd')
CHECKPOINTS = [f'support:{mode}:{case}' for mode in ('classic', 'bad') for case in SCENARIOS]


def apply(page, checkpoint):
    _, mode, case = checkpoint.split(':')
    if case == 'startup':
        page.set_viewport_size({'width': 844, 'height': 390})
        page.evaluate('''mode => {onViewportResize(); startGame(mode); menu.gamePaused=false; window.onblur=null;
            window.savedMotes = visualEffects.particles.getAmbientMotes().map(m=>({...m}));
            draw();}''', mode)
    elif case == 'gameplay':
        page.evaluate('stepVisual(45)')
    elif case == 'camera':
        page.evaluate('screen.x -= 173.25; screen.y += 47.5; draw()')
    elif case == 'edge-overlap':
        page.evaluate('''() => {
            const p=visualEffects.particles, margin=STYLE.ambient.moteMaxSize*STYLE.ambient.moteHaloRatio;
            p.ambientMotes = [[0,0],[1,1],[LOGICAL_VIEWPORT.width,0],
                [0,LOGICAL_VIEWPORT.height],[LOGICAL_VIEWPORT.width,LOGICAL_VIEWPORT.height]]
                .map(([x,y],i)=>({...savedMotes[i],u:(x+margin)/(LOGICAL_VIEWPORT.width+2*margin),
                v:(y+margin)/(LOGICAL_VIEWPORT.height+2*margin),vx:0,vy:0,parallax:0}));
            const emitters = floors.flatMap(f=>f.elements).filter(f=>!(f instanceof Ground) && !(f instanceof Side));
            emitters.slice(0,3).forEach((f,i)=>{f.x=-screen.x+i*2;f.y=-screen.y+100+i*2});
            draw();
        }''')
    elif case == 'empty':
        page.evaluate('window.savedElements=floors.map(f=>f.elements); floors.forEach(f=>f.elements=f.elements.filter(e=>e instanceof Ground || e instanceof Side)); visualEffects.particles.ambientMotes=[]; draw()')
    elif case == 'death':
        page.evaluate('floors.forEach((f,i)=>f.elements=savedElements[i]); visualEffects.particles.ambientMotes=savedMotes; menu.gamePaused=false; continueOffer.visible=true; gameLoop(__snap.now)')
    elif case == 'restart-shake':
        page.evaluate('''mode => {startGame(mode); menu.gamePaused=false; stepVisual(25);
            visualEffects.particles.emitPlayerParticles(ninja);
            visualEffects.screenEffects.triggerDeath(ninja.x,ninja.y); draw()}''', mode)
    else:
        page.set_viewport_size({'width':391 if case=='portrait-odd' else 853,
                                'height':853 if case=='portrait-odd' else 391})
        page.evaluate('onViewportResize(); draw()')


def state(page):
    return page.evaluate("""() => ({camera:{x:screen.x,y:screen.y},
        viewport:[innerWidth,innerHeight],
        motes:visualEffects.particles.ambientMotes.length,
        mote_layout:Array.from(visualEffects.particles.moteLayout || []),
        has_lights:visualEffects.lightmap.hasLights,
        emitters:floors.flatMap(f=>f.elements).filter(f=>!(f instanceof Ground) && !(f instanceof Side)).length})""")
