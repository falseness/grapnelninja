/* TASK-629 observation helpers. Placements are isolated archived route fixtures. */
window.READABILITY = {
    layout() {
        const css = getCanvasCssRect();
        return {coarsePointer:matchMedia('(pointer: coarse)').matches,touchFirst:isTouchFirstDevice(),
            viewport:{width:innerWidth,height:innerHeight},logical:{width,height},
            canvas:{width:css.width,height:css.height}};
    },
    view(spec) {
        BYPASS.setup(spec.start, spec.range, null);
        LAYOUT_PROBE.boxes = [];
        draw();
        const css = getCanvasCssRect();
        const project = p => {
            const q = YARD.client(p);
            return {x:q.x-css.left,y:q.y-css.top};
        };
        const bounds = points => {
            const ps=points.map(project);
            return {left:Math.min(...ps.map(p=>p.x)),right:Math.max(...ps.map(p=>p.x)),
                top:Math.min(...ps.map(p=>p.y)),bottom:Math.max(...ps.map(p=>p.y))};
        };
        const encounter=floors[0].level.encounters.find(e=>e.id===spec.id);
        const candidates=BYPASS.candidates(false).filter(e=>encounter.elements.includes(e.id) &&
            e.id!==spec.support && e.id!==spec.landing);
        // A next target can be visible before it enters acquisition range.
        const upcoming=[];
        for(const id of encounter.elements.filter(id=>id!==spec.support && id!==spec.landing)) {
            const e=floors[0].byId.get(id);
            if(!e || !/anchor|carrier|lift|projection|overhang|counterweight|shuttle/.test(id))continue;
            const ps=e.getPoints();
            for(let i=0;i<ps.length;i++) {
                const a=ps[i],b=ps[(i+1)%ps.length],dx=b.x-a.x,dy=b.y-a.y;
                const t=Math.max(0,Math.min(1,((ninja.x-a.x)*dx+(ninja.y-a.y)*dy)/(dx*dx+dy*dy)));
                const x=a.x+t*dx,y=a.y+t*dy;
                upcoming.push({id,x,y,distance:Math.hypot(x-ninja.x,y-ninja.y)});
            }
        }
        upcoming.sort((a,b)=>a.distance-b.distance);
        const target=candidates[0] || upcoming[0];
        const landing=floors[0].byId.get(spec.landing);
        const landmark=LANDMARKS.frame.drawn[0];
        const rect=landmark.rect;
        const logical=p=>({x:p.x*css.width/width,y:p.y*css.height/height});
        const a=logical({x:rect[0],y:rect[1]}),b=logical({x:rect[2],y:rect[3]});
        return {layout:this.layout(),id:spec.id,pose:spec.start.pose,phaseTick:spec.start.phaseTick,canvas:{width:css.width,height:css.height},
            camera:{x:screen.x,y:screen.y,scale:scale[version]},
            target:target?{...target,point:project(target),bounds:bounds(floors[0].byId.get(target.id).getPoints()),
                role:floors[0].byId.get(target.id).surfaceRole}:null,
            landing:{id:landing.id,bounds:bounds(landing.getPoints()),role:landing.surfaceRole},
            hud:LAYOUT_PROBE.boxes,landmark:{...landmark,bounds:{left:a.x,top:a.y,right:b.x,bottom:b.y}},
            palette:visualEffects.background.palette};
    }
};
