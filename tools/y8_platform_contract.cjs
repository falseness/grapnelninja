const fs=require('fs'),vm=require('vm'),assert=require('assert');
async function scenario(kind){
 const handlers={},calls=[];let callbacks;
 const sdk={init(){calls.push('init');if(kind==='reject')return Promise.reject(Error('rejected'));if(kind==='hang')return new Promise(()=>{});if(kind==='late')return new Promise(r=>setTimeout(r,60));return Promise.resolve()},showAd(opts){calls.push('showAd');callbacks=opts;for(const key of Object.keys(opts)){if(typeof opts[key]==='function'){const fn=opts[key];opts[key]=(...args)=>{calls.push(key);return fn(...args)}}}if(kind==='adThrow')throw Error('throw');if(kind==='adReject')return Promise.reject(Error('reject'));return Promise.resolve()}};
 const storage=new Map();
 const box={console,navigator:{language:'ru-RU'},performance:{now:()=>0},setTimeout:(fn,ms)=>setTimeout(fn,Math.min(ms,40)),clearTimeout,window:{localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)},addEventListener:(n,fn)=>handlers[n]=fn,removeEventListener:(n)=>delete handlers[n]}};
 if(kind!=='missing')box.window.y8={sdk:()=>sdk,emitReadyEvent:()=>handlers['y8sdk.ready'] && handlers['y8sdk.ready']()};
 vm.createContext(box);vm.runInContext(fs.readFileSync('y8config.js','utf8')+'\n'+fs.readFileSync('platform.js','utf8')+'\nglobalThis.P=PLATFORM',box);
 const P=box.P; await Promise.all([P.init(),P.init()]);
 assert.equal(calls.filter(x=>x==='init').length,kind==='missing'?0:1);
 await P.storage.setMany({score:7});assert.equal((await P.storage.getMany(['score'])).score,'7');
 if(['missing','hang','reject','late'].includes(kind)){assert.equal(P.isRewardedSupported(),false);if(kind==='late'){await new Promise(r=>setTimeout(r,40));assert.equal(P.isRewardedSupported(),false)}console.log('PASS startup',kind);return}
 const events=[];P.onAdState(s=>events.push(s));let settled=false;
 const result=P.requestRewarded().then(r=>{settled=true;return r});
 if(kind==='adThrow'||kind==='adReject'){assert.equal((await result).status,'unavailable');console.log('PASS ad',kind);return}
 assert.equal((await P.requestRewarded()).reason,'busy');
 callbacks.beforeReward(()=>{});callbacks.beforeAd();await Promise.resolve();assert.equal(settled,false,'promise resolution must not finish ad');
 if(kind==='viewed'){callbacks.adViewed();assert.equal(settled,false);callbacks.adBreakDone({breakStatus:'viewed'});callbacks.adBreakDone({breakStatus:'viewed'})}
 else if(kind==='dismissed'){callbacks.adDismissed();callbacks.adBreakDone({breakStatus:'dismissed'})}
 else if(kind==='noFill'){callbacks.adBreakDone({breakStatus:'noAdPreloaded'})}
 const r=await result; assert.equal(r.status,kind==='viewed'?'rewarded':'unavailable');
 callbacks.adViewed();callbacks.adBreakDone({breakStatus:'viewed'});
 assert.deepEqual(events,['opened','closed']);console.log('PASS ad',kind,JSON.stringify({calls,events,result:r}));
}
(async()=>{for(const k of ['missing','hang','reject','late','viewed','dismissed','noFill','timeout','adThrow','adReject'])await scenario(k)})().catch(e=>{console.error(e);process.exitCode=1});
