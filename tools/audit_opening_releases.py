"""Vary a real ceiling traversal's final hold/release without resetting momentum."""
import argparse,copy,itertools,json
from contextlib import ExitStack
from pathlib import Path
from browser_test_support import start_browser_test,wait_for_boot_run
ROOT=Path(__file__).resolve().parent.parent

def main():
    p=argparse.ArgumentParser();p.add_argument('--level',required=True);p.add_argument('--inputs',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    level=json.loads(Path(a.level).read_text());record=json.loads(Path(a.inputs).read_text());inputs=record['inputs'] if 'inputs' in record else record['wins'][0]['inputs']
    with ExitStack() as stack:
        url,b=start_browser_test(ROOT,stack.callback);page=b.new_page(viewport={'width':1280,'height':720})
        page.goto(url);wait_for_boot_run(page);page.add_script_tag(path=str(ROOT/'tools/opening_combination_replay.js'))
        def run(es):return page.evaluate('o=>OPENING_REPLAY.run(o)',dict(level=level,fixture=dict(panel='P2',fraction=.5,drop=30),inputs=es,budget=2300))
        control=run(inputs)
        landing=next(c['tick'] for c in control['contacts'] if c['id']=='P4-body0')
        prefix=[e for e in inputs if e['tick']<landing]
        assert prefix[-1]['type']=='up'
        results=[]
        for delay,offset in itertools.product((-12,-6,0,6,12),(-120,0,120)):
            es=copy.deepcopy(prefix);es[-1]['tick']+=delay;es[-2]['aim'][0]+=offset
            log=run(es);highest=3;skips=[];encountered=[]
            for c in log['contacts']:
                if c['tick']<es[-1]['tick']:continue
                n=int(c['id'].split('-')[0][1:])
                if n>highest+1:skips.append(c)
                if n>highest:highest=n
                if not encountered or encountered[-1]!=c['id']:encountered.append(c['id'])
            results.append(dict(delay=delay,anchorOffset=offset,sequence=encountered,skips=skips,
                                maxStep=log['maxStep'],recoveredToStart=log['maxStep']>=200,contacts=log['contacts']))
        data=dict(layoutId=level['layoutId'],control=control,results=results,
                  passing=control['maxStep']<200 and all(not r['skips'] for r in results))
        Path(a.output).write_text(json.dumps(data,separators=(',',':')))
        print('RELEASE AUDIT',data['passing'],[(r['delay'],r['anchorOffset'],r['sequence']) for r in results if r['skips']])
        if not data['passing']:raise SystemExit(1)

if __name__=='__main__':main()
