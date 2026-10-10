const fs=require('fs'),vm=require('vm'),assert=require('assert');
async function scenario(kind){
 const handlers={},calls=[];let callbacks;
 const sdk={init(app,ads){calls.push('init');assert.equal(app.autoLogin,false);assert.equal(app.appId,'6abfc17d100b7c96fc2d684e');assert.equal(ads.gameId,'285775');calls.push('anonymous-config');if(kind==='initThrow')throw Error('init throw');if(kind==='reject')return Promise.reject(Error('rejected'));if(kind==='hang')return new Promise(()=>{});if(kind==='late')return new Promise(r=>setTimeout(r,60));return Promise.resolve()},showAd(opts){calls.push('showAd');callbacks=opts;for(const key of Object.keys(opts)){if(typeof opts[key]==='function'){const fn=opts[key];opts[key]=(...args)=>{calls.push(key);return fn(...args)}}}if(kind==='adThrow')throw Error('throw');if(kind==='adReject')return Promise.reject(Error('reject'));return Promise.resolve()}};
 const storage=new Map();
 const box={console,navigator:{language:'ru-RU'},performance:{now:()=>0},setTimeout:(fn,ms)=>setTimeout(fn,Math.min(ms,40)),clearTimeout,window:{localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)},addEventListener:(n,fn)=>{calls.push('listen:'+n);handlers[n]=fn},removeEventListener:(n)=>{calls.push('remove:'+n);delete handlers[n]}}};
 if(kind!=='missing')box.window.y8={sdk:()=>{calls.push('sdk');return sdk},emitReadyEvent:()=>{calls.push('emitReadyEvent');if(kind!=='delayedReady' && handlers['y8sdk.ready']){calls.push('ready');const ready=handlers['y8sdk.ready'];ready();ready()}}};
 vm.createContext(box);vm.runInContext(fs.readFileSync('y8config.js','utf8')+'\n'+fs.readFileSync('platform.js','utf8')+'\nglobalThis.P=PLATFORM',box);
 if(kind==='storageDenied')Object.defineProperty(box.window,'localStorage',{get(){throw Error('denied')}});
 const P=box.P;const first=P.init();assert.strictEqual(first,P.init());
 if(kind==='delayedReady'){assert.equal(calls.includes('init'),false);calls.push('ready');handlers['y8sdk.ready']()}
 await first;calls.push('resolved:'+P.environment);
 if(kind!=='missing'){assert(calls.indexOf('listen:y8sdk.ready')<calls.indexOf('ready'));assert(calls.indexOf('ready')<calls.indexOf('sdk'));assert(calls.indexOf('sdk')<calls.indexOf('init'))}
 assert.equal(P.isInterstitialSupported(),false);
 console.log('TRACE startup',kind,JSON.stringify({calls,environment:P.environment,anonymous:true}));
 assert.equal(calls.filter(x=>x==='init').length,kind==='missing'?0:1);
 await P.storage.setMany({score:7});assert.equal((await P.storage.getMany(['score'])).score,'7');
 if(['missing','hang','reject','late','initThrow'].includes(kind)){assert.equal(P.isRewardedSupported(),false);if(kind==='late'){await new Promise(r=>setTimeout(r,40));assert.equal(P.isRewardedSupported(),false)}console.log('PASS startup',kind,JSON.stringify({calls,environment:P.environment,storage:'7',lateGuard:kind==='late'}));return}
 if(kind==='delayedReady'||kind==='storageDenied'){assert.equal(P.environment,'y8');console.log('PASS startup',kind,JSON.stringify({calls,storage:'7',environment:P.environment}));return}
 const events=[];P.onAdState(s=>events.push(s));let settled=false;
 const result=P.requestRewarded().then(r=>{settled=true;return r});
 if(kind==='adThrow'||kind==='adReject'){assert.equal((await result).status,'unavailable');console.log('PASS ad',kind,JSON.stringify({calls,events}));return}
 assert.equal((await P.requestRewarded()).reason,'busy');
 callbacks.beforeReward(()=>{});if(kind!=='noFill')callbacks.beforeAd();await Promise.resolve();assert.equal(settled,false,'promise resolution must not finish ad');
 if(kind==='viewed'){callbacks.adViewed();assert.equal(settled,false);callbacks.adBreakDone({breakStatus:'viewed'});callbacks.adBreakDone({breakStatus:'viewed'})}
 else if(kind==='dismissed'){callbacks.adDismissed();callbacks.adBreakDone({breakStatus:'dismissed'})}
 else if(kind==='noFill'){callbacks.adBreakDone({breakStatus:'noAdPreloaded'})}
 const r=await result; assert.equal(r.status,kind==='viewed'?'rewarded':'unavailable');
 callbacks.adViewed();callbacks.adBreakDone({breakStatus:'viewed'});
 assert.deepEqual(events,kind==='noFill'?['closed']:['opened','closed']);console.log('PASS ad',kind,JSON.stringify({calls,events,result:r}));
}
(async()=>{for(const k of ['missing','hang','reject','late','initThrow','delayedReady','storageDenied','viewed','dismissed','noFill','timeout','adThrow','adReject'])await scenario(k)})().catch(e=>{console.error(e);process.exitCode=1});
