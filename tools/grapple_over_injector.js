/* TEST ONLY. Loaded explicitly by Playwright; no production script or controls. */
(() => {
    if (window.GRAPPLE_OVER_TEST) throw new Error('RecorderAlreadyInstalled');
    let attempt = null, tick = 0, sequence = 0;
    const clone = value => JSON.parse(JSON.stringify(value));
    const state = () => ({simulation: captureClimbState(), camera: {x:screen.x,y:screen.y},
        rope: grapnel.pos.map(([x,y,e]) => ({x,y,id:e.id || null})),
        movers: clone(floors[0].level.movers)});
    const emit = (type, data) => {
        if (attempt) attempt.events.push({sequence:sequence++,tick,
            simulationTick:floors[0].elapsedSteps,type,...clone(data)});
    };
    const transition = (before, after) => {
        if (!before.simulation.grapple.grappled && after.simulation.grapple.grappled)
            emit('acquisition',{before,after});
        if (before.simulation.grapple.grappled && after.simulation.grapple.grappled &&
            before.rope.length !== after.rope.length) emit('wrap',{before,after});
        if (before.simulation.grapple.throwed && !after.simulation.grapple.throwed)
            emit('release',{before,after});
    };
    // Observe every production subcycle, including transient contacts/events.
    const originalCycle = calcPhysics;
    calcPhysics = function(...args) {
        if (!attempt) return originalCycle.apply(this,args);
        const before=state(), result=originalCycle.apply(this,args);
        transition(before,state()); return result;
    };
    for (const [method,type] of [['applySolidContact','contact'],['applyHazardContact','knockback']]) {
        const original=Ninja.prototype[method];
        Ninja.prototype[method]=function(contact) {
            const before=attempt?state():null;
            const result=original.call(this,contact);
            if (attempt) emit(type,{contact,before,after:state()});
            return result;
        };
    }
    // Observe reflection without altering the production result or velocity.
    const originalBounce=Ninja.prototype.applyBounce;
    Ninja.prototype.applyBounce=function(contact) {
        const before=attempt && contact.approaching ? state() : null;
        const result=originalBounce.call(this,contact);
        if (before) emit('bounce',{contact:{elementId:contact.element.id,
            nx:contact.nx,ny:contact.ny,line:contact.line},before,after:state()});
        return result;
    };
    let input = null;
    const originalAim = Grapnel.prototype.calcSpeed;
    Grapnel.prototype.calcSpeed=function(target) {
        if (input) input.resolvedTarget=clone(target);
        return originalAim.call(this,target);
    };
    for (const type of ['mousedown','mouseup','touchstart','touchend','touchcancel']) {
        document.addEventListener(type,event => {
            if (!attempt) return;
            const p=event.changedTouches ? event.changedTouches[0] : event;
            const client={x:p.clientX,y:p.clientY}, c=viewportCoordsToCanvasCoords(client);
            input={event:type,trusted:event.isTrusted,client,
                world:{x:c.x/scale[version]-screen.x,y:c.y/scale[version]-screen.y},
                before:state()};
        },true);
        // Registered after production's document handlers, so this is their result.
        document.addEventListener(type,() => {
            if (!input) return;
            input.after=state(); emit('input',input);
            transition(input.before,input.after); input=null;
        });
    }
    window.GRAPPLE_OVER_TEST = {
        attempts:[],
        begin(name) {
            if (attempt) throw new Error('FinishAttemptFirst');
            tick=0;sequence=0;
            attempt={name,metadata:{testOnly:true,setupOnlySpawns:[]},events:[],snapshots:[]};
            this.attempts.push(attempt);
        },
        spawn({level,player,camera}) {
            if (!attempt || tick || attempt.events.length) throw new Error('SetupOnly');
            if (version!=='grapple_over') throw new Error('ClimbModeRequired');
            if (level) floors=[loadFixedLevel(level)];
            Object.assign(ninja,player); grapnel.endShot();
            pressHeld=false; stalePress=false; gameplayPressOwned=false;
            if (camera) Object.assign(screen,camera);
            attempt.metadata.setupOnlySpawns.push({developerSpawn:true,setupOnly:true,
                fixture:clone({level,player,camera})});
            attempt.snapshots.push({tick,state:state()});
        },
        step(count=1) {
            if (!Number.isSafeInteger(count) || count<0 || !attempt) throw new Error('InvalidStep');
            for(let i=0;i<count;i++) {tick++;physics();attempt.snapshots.push({tick,state:state()});}
        },
        snapshot:state,
        finish(outcome) {if (!attempt) throw new Error('NoAttempt');attempt.outcome=outcome;attempt=null;},
        client(world) {return canvasCoordsToViewportCoords({x:(world.x+screen.x)*scale[version],
            y:(world.y+screen.y)*scale[version]});}
    };
})();
