"""Bounded production-physics replay evidence, no velocity injection after setup."""
import argparse,json
from pathlib import Path
from contextlib import ExitStack
from browser_test_support import start_browser_test,wait_for_boot_run
ROOT=Path(__file__).resolve().parent.parent

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--pairs',required=True);ap.add_argument('--output',required=True)
    ap.add_argument('--no-guards',action='store_true');ap.add_argument('--level');ap.add_argument('--pumps',default='0,1,2,3,5');ap.add_argument('--fractions',default='.2,.5,.8');ap.add_argument('--budget',type=int,default=1500);ap.add_argument('--aim-offset',type=float,default=0);ap.add_argument('--drop',type=float,default=30);ap.add_argument('--hold-ticks',type=int,default=0)
    a=ap.parse_args(); results=[]
    with ExitStack() as stack:
        url,b=start_browser_test(ROOT,stack.callback);p=b.new_page(viewport={'width':1280,'height':720})
        p.goto(url);wait_for_boot_run(p);p.add_script_tag(path=str(ROOT/'tools/probe_level_routes.js'))
        for pair in a.pairs.split(','):
            source,target=pair.split(':');count=0;skips=0
            for pumps in map(int,a.pumps.split(',')):
                for fraction in map(float,a.fractions.split(',')):
                    options=dict(source=source,target=target,pumps=pumps,fraction=fraction,budget=a.budget,guard=not a.no_guards,aimOffset=a.aim_offset,drop=a.drop,holdTicks=a.hold_ticks)
                    if a.level:options['level']=json.loads(Path(a.level).read_text())
                    r=p.evaluate('o=>ROUTE_PROBE.run(o)',options);results.append(r)
                    if r['hit']:
                        count+=1
                        if int(r['hit']['id'].split('-')[0][1:]) > int(source[1:])+1:skips+=1
            print(pair,'forward contacts/attachments',count,'skips',skips,flush=True)
    Path(a.output).parent.mkdir(parents=True,exist_ok=True)
    Path(a.output).write_text(json.dumps({'coverage':'Local zero-velocity drops, finite input policies; not a proof of global shortcut absence.','results':results},separators=(',',':')))
if __name__=='__main__':main()
