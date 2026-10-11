'use strict';
const $ = id => document.getElementById(id);
let receipt;
const delay = ms => new Promise(r => setTimeout(r, ms));
function layout(w) {
  const c = w.document.getElementById('canvas');
  return {dpr:w.devicePixelRatio, backing:[c.width,c.height], viewport:[w.innerWidth,w.innerHeight],
    orientation:w.innerWidth>w.innerHeight?'landscape':'portrait'};
}
$('start').onclick = async () => {
  if (!['model','android','firefox'].every(id => $(id).value.trim())) { $('status').textContent='Enter all three identity fields.'; return; }
  $('start').disabled = true;
  receipt = {schema:1, provenance:$('attest').checked?'native-device':'desktop-emulated', quality:'unchanged',
    started_utc:new Date().toISOString(), environment:{device_model:$('model').value, android_version:$('android').value,
    firefox_version:$('firefox').value, user_agent:navigator.userAgent, platform:navigator.platform,
    webdriver:navigator.webdriver, owner_attested_native:$('attest').checked},runs:[]};
  try {
    const builds = await (await fetch('builds.json')).json();
    const probe = await (await fetch('probe.js')).text();
    for (const mode of ['classic','bad']) for (let pair=0;pair<3;pair++) for (const arm of pair%2?['repair','baseline']:['baseline','repair']) {
      $('status').textContent=`${mode} pair ${pair+1}: ${arm} (5s warmup + 30 active seconds)`;
      const frame=$('game');
      await new Promise((resolve,reject) => { const timer=setTimeout(()=>reject(Error('load timeout')),15000); frame.onload=()=>{clearTimeout(timer);resolve();};frame.src=`${arm}/index.html?run=${receipt.runs.length}`; });
      const w=frame.contentWindow;
      const deadline=performance.now()+180000;
      while (!w.eval('typeof menu !== "undefined" && menu.visible && typeof canvas !== "undefined"')) { if(performance.now()>deadline)throw Error('menu timeout');await delay(100); }
      await delay(500);
      w.eval(probe);
      const visibility=[];
      w.document.addEventListener('visibilitychange',()=>{visibility.push({t:w.performance.now(),hidden:w.document.hidden,utc:new Date().toISOString()}); if(w.document.hidden && w.perfReceipt?.frames.length) w.perfReceipt.frames.at(-1).after.hidden=true;});
      const gl=w.document.createElement('canvas').getContext('webgl');
      const graphics=gl?{version:gl.getParameter(gl.VERSION),renderer:gl.getParameter(gl.RENDERER),vendor:gl.getParameter(gl.VENDOR)}:{renderer:'UNAVAILABLE'};
      const run={layout_changes:[],graphics,mode,pair,arm,build_sha256:builds[arm].zip_sha256,layout:layout(w),visibility,started_utc:new Date().toISOString()};
      w.addEventListener('resize',()=>run.layout_changes.push(layout(w)));
      w.installProbe({mode,seed:292,inputs:Array.from({length:69},(_,i)=>({at_active_ms:(i+1)*500,type:i%2?'mouseup':'mousedown',x:650,y:100}))});
      while(!w.perfReceipt.done) {if(performance.now()>deadline)throw Error('active duration timeout');await delay(100);}
      Object.assign(run,{frames:w.perfReceipt.frames,inputs:w.perfReceipt.inputs,transitions:w.perfReceipt.transitions,end_layout:layout(w),ended_utc:new Date().toISOString()});
      receipt.runs.push(run);frame.src='about:blank';
    }
    $('status').textContent='Capture complete. Download and validate JSON; completion is not performance acceptance.';
  } catch(e) {receipt.error=String(e);$('status').textContent=`Failed: ${e}. Download partial evidence.`;}
  receipt.ended_utc=new Date().toISOString();$('download').disabled=false;
};
$('download').onclick=()=>{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(receipt)],{type:'application/json'}));a.download='android-benchmark.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);};
