// Browser live transport and Worker scheduling without a Python or recorded fixture.
const assert=require('node:assert/strict');
const transport=require('../scripts/building_fleet_browser_transport.js');
const {pathToFileURL}=require('node:url');
const path=require('node:path');
const hash='a'.repeat(64);
const config={module_url:'worker.mjs?sha256='+hash,manifest:{url:'runtime-manifest.json',sha256:hash},bundle:{url:'runtime.zip',sha256:hash}};
const state=(time=0,paused=false,session='own-live-world')=>({format:'solidcraftbot.building-fleet-live-snapshot/1',session_id:session,model_time_s:time,integration_step_s:.05,paused,states:[{id:'BF01',pose_xyz_mm:[time,0,0]}],jobs:[],camera_frames:[]});
const job={request_id:'test-job-1',pickup:{level:'EG',area:'A'},delivery:{level:'EG',area:'B'}};
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const reservationId='b'.repeat(32);
const labState=(reserved=true,session='own-live-world',id=reservationId)=>({...state(0,true,session),lab3003_reservation_id:id,lab3003_reserved:reserved});
function labClient(initial=labState()){
 const sent=[],fake={postMessage:value=>sent.push(value),terminate(){this.closed=true;}};
 const client=transport.create(config,{baseURL:'https://example.test/patrol/',workerFactory:()=>fake});
 const emit=message=>fake.onmessage({data:message});
 emit({type:'state',state:initial});
 return{client,sent,emit};
}
const labAck=(id=1,session='own-live-world',reservation=reservationId)=>({type:'command_ack',id,action:'lab3003_docked',reservation_id:reservation,session_id:session,lab3003_reserved:false});
(async()=>{
 const sent=[],fake={postMessage:value=>sent.push(value),terminate(){this.closed=true;}};
 const client=transport.create(config,{baseURL:'https://example.test/patrol/',workerFactory:url=>{assert.match(url,/^https:\/\/example.test\/patrol\/worker.mjs/);return fake;}});
 assert.equal(sent[0].type,'boot');assert.equal(sent[0].config.bundle.url,'https://example.test/patrol/runtime.zip');
 assert.equal((await client.request('/api/state')).status,'starting');
 let initialized=false;client.ready.then(()=>{initialized=true;});await flush();assert.equal(initialized,false);
 const startup=[],unsubscribe=client.subscribeStartup(value=>startup.push(value));
 assert.equal(startup[0].phase,'loading_browser_engine');
 const assetProgress={phase:'loading_runtime_assets',received_bytes:1048576,total_bytes:2097152,verified_files:0,total_files:2};
 fake.onmessage({data:{type:'progress',progress:assetProgress}});
 assert.equal(startup.at(-1).received_bytes,1048576);
 assert.deepEqual(transport.startupDisplay(await client.request('/api/state')),{
  detail:'Laufzeit und Modell werden geladen · 1,0/2,0 MiB empfangen · 0/2 Dateien geprüft',value:1048576,max:2097152});
 let replay;const off=client.subscribeStartup(value=>{replay=value;});
 assert.equal(replay.received_bytes,1048576);off();
 fake.onmessage({data:{type:'progress',progress:{phase:'initializing_python_runtime'}}});
 const initializing=await client.request('/api/state');
 assert(!('total_bytes' in initializing));assert(!('verified_files' in initializing));
 assert.deepEqual(transport.startupDisplay(initializing),{detail:'Python-Laufzeit wird initialisiert',value:null,max:null});
 assert.equal(replay.phase,'loading_runtime_assets','Unsubscribed listeners stop at their last observation');
 const queued=await client.request('/api/jobs',job);assert.equal(queued.status,'queued_for_engine');assert(!queued.vehicle_id);
 await client.request('/api/jobs',{...job,pickup:{area:'A',level:'EG'}});assert.equal(sent.filter(m=>m.type==='command').length,1);
 await assert.rejects(client.request('/api/jobs',{...job,delivery:{level:'EG',area:'C'}}),/identity/);
 await assert.rejects(client.request('/api/jobs',{...job,pickup:{area:'B',level:'EG'}}),/must differ/);
 await assert.rejects(client.request('https://other.test/api/jobs',job),/origin/);
 fake.onmessage({data:{type:'state',state:state(.5)}});
 assert.deepEqual(await client.ready,{status:'ready'});
 assert.deepEqual(startup.at(-1),{status:'ready'});unsubscribe();
 fake.onmessage({data:{type:'progress',progress:{phase:'own_drive_prepare',vehicle_id:'BF01',states:[],model_time_s:100}}});
 assert.equal(client.state.status,'ready');assert.equal(client.state.model_time_s,.5);assert.equal(client.state.states.length,1);
 const detached=await client.request('/api/state');detached.states[0].id='changed';assert.equal(client.state.states[0].id,'BF01');
 const pause=await client.request('/api/control',{action:'pause'});assert.equal(pause.status,'queued_for_engine');assert.equal(client.state.paused,false,'A queued control is not an engine acknowledgement');
 fake.onmessage({data:{type:'command_error',id:1,request_id:'test-job-1',error:'invalid target'}});assert.equal(client.state.command_errors[0].request_id,job.request_id);
 fake.onmessage({data:{type:'error',error:'floor check failed'}});assert.equal(client.state.status,'error');assert.equal(client.state.model_time_s,.5);assert.equal(client.state.states[0].id,'BF01');
 fake.onmessage({data:{type:'progress',progress:assetProgress}});fake.onmessage({data:{type:'state',state:state(1)}});
 client.subscribeStartup(value=>{assert.deepEqual(value,{status:'error',error:'floor check failed'});});
 await assert.rejects(client.request('/api/control',{action:'resume'}),/stopped/);
 client.dispose();assert(fake.closed);await assert.rejects(client.request('/api/state'),/closed/);
 assert.throws(()=>transport.resolveConfig({...config,bundle:{...config.bundle,url:'https://other.test/runtime.zip'}},'https://example.test/'),/origin/);

 const lab=labClient();let confirmed=false;
 const docking=lab.client.reportLab3003Docked(reservationId).then(value=>{confirmed=true;return value;});
 assert.deepEqual(lab.sent.at(-1),{type:'command',id:1,command:{action:'lab3003_docked',reservation_id:reservationId}});
 await flush();assert.equal(confirmed,false,'Queueing is not a docking acknowledgement');
 lab.emit({type:'state',state:labState(false)});await flush();assert.equal(confirmed,false,'A changed snapshot alone is not a command acknowledgement');
 lab.emit(labAck());assert.deepEqual(await docking,{status:'confirmed',action:'lab3003_docked',reservation_id:reservationId,session_id:'own-live-world',lab3003_reserved:false});
 lab.emit(labAck());assert.equal(lab.client.state.status,'ready','Duplicate acknowledgements are harmless');
 const repeated=lab.client.reportLab3003Docked(reservationId);lab.emit(labAck(2));await repeated;
 await assert.rejects(lab.client.reportLab3003Docked(),/matching live/);
 await assert.rejects(lab.client.reportLab3003Docked('foreign'),/matching live/);assert.equal(lab.sent.length,3);
 lab.client.dispose();await assert.rejects(lab.client.reportLab3003Docked(reservationId),/closed/);
 const standard=labClient(state());await assert.rejects(standard.client.reportLab3003Docked(reservationId),/matching live/);standard.client.dispose();
 const stale=labClient(),old=stale.client.reportLab3003Docked(reservationId),oldRejected=assert.rejects(old,/different browser session/);
 stale.emit({type:'state',state:labState(true,'new-session','c'.repeat(32))});await oldRejected;stale.emit(labAck());assert.equal(stale.client.state.status,'ready');
 await assert.rejects(stale.client.reportLab3003Docked(reservationId),/matching live/);stale.client.dispose();
 const denied=labClient(),denial=assert.rejects(denied.client.reportLab3003Docked(reservationId),/no observation/);
 denied.emit({type:'command_error',id:1,error:'no observation'});await denial;
 const retry=denied.client.reportLab3003Docked(reservationId);denied.emit({type:'state',state:labState(false)});denied.emit(labAck(2));await retry;denied.client.dispose();
 for(const failure of ['dispose','fatal','early_ack','wrong_ack','extra_ack']){
  const item=labClient(),pending=item.client.reportLab3003Docked(reservationId),rejected=assert.rejects(pending,/closed|stopped|acknowledgement/);
  if(failure==='dispose')item.client.dispose();
  else if(failure==='fatal')item.emit({type:'error',error:'stopped'});
  else{
   if(failure!=='early_ack')item.emit({type:'state',state:labState(false)});
   const ack=labAck();if(failure==='wrong_ack')ack.reservation_id='foreign';if(failure==='extra_ack')ack.observed=true;
   item.emit(ack);
  }
  await rejected;item.client.dispose();
 }

 const worker=await import(pathToFileURL(path.resolve(__dirname,'../scripts/building_fleet_browser_worker.mjs')).href);
 for(const bad of ['/absolute','../escape','a/../escape','a\\b','a//b','a\0b'])assert.throws(()=>worker.checkedPath(bad),/Unsafe/);
 assert.equal(worker.checkedPath('model/source.json'),'model/source.json');
 const manifest={format:'solidcraftbot.building-fleet-browser-bundle/1',root_dir:'/project',files:{'scripts/building_fleet_browser_runtime.py':{sha256:hash,bytes:10},'model/browser.json':{sha256:hash,bytes:20}},bootstrap_path:'scripts/building_fleet_browser_runtime.py',archive:{sha256:hash,bytes:42},runtime:{engine:'pyodide',version:'314.0.8',loader_module_url:'https://cdn.jsdelivr.net/pyodide/v314.0.8/full/pyodide.mjs',execution:'module_web_worker',pacing:'source_step_without_wall_clock_catchup'},session:{scope:'independent_live_session_per_page',start:'new_patrol_world',recording_fallback:false},browser_config:{path:'model/browser.json',sha256:hash},inputs:{browser_source:'model/browser.json'}};
 assert.equal(worker.validateManifest(manifest,config),manifest);
 const reduced={...manifest,vehicle_count:6};
 assert.equal(worker.validateManifest(reduced,config),reduced);
 assert.throws(()=>worker.validateManifest({...manifest,vehicle_count:'6'},config),/fleet count/);
 assert.throws(()=>worker.validateManifest({...manifest,session:{...manifest.session,recording_fallback:true}},config),/independent live/);
 assert.throws(()=>worker.validateManifest({...manifest,runtime:{...manifest.runtime,loader_module_url:'https://other.test/python.mjs'}},config),/Official/);
 assert.throws(()=>worker.validateManifest({...manifest,archive:{...manifest.archive,sha256:'b'.repeat(64)}},config),/page pin/);
 assert.throws(()=>worker.validateManifest({...manifest,files:{...manifest.files,'../escape':{sha256:hash,bytes:1}}},config),/Unsafe/);
 const compact={...manifest,format:'solidcraftbot.building-fleet-browser-bundle/2',
  files:{...manifest.files,'exports/static.json':{sha256:hash,bytes:12}},
  runtime:{...manifest.runtime,static_geometry:'source_bound_lossless_runtime_cache',route_preparation:'background_worker_with_checked_rolling_prefix'},
  inputs:{browser_source:'model/browser.json',profile:'model/profile.json',static_runtime_cache:'exports/static.json'},static_cache_verification:{}};
 assert.equal(worker.validateManifest(compact,config),compact);
 const reserved={...compact,inputs:{...compact.inputs,lab3003_reserved:true}};
 assert.equal(worker.validateManifest(reserved,config),reserved);
 for(const value of [false,1,null,'true'])assert.throws(()=>worker.validateManifest({...compact,inputs:{...compact.inputs,lab3003_reserved:value}},config),/explicit compact/);
 assert.throws(()=>worker.validateManifest({...manifest,inputs:{...manifest.inputs,lab3003_reserved:true}},config),/explicit compact/);
 assert.throws(()=>worker.validateManifest({...reserved,inputs:{...reserved.inputs,lab3003_reservation_id:'caller-chosen'}},config),/Pinned static/);
 const coreFiles=Object.fromEntries(['pyodide.mjs','pyodide.asm.mjs','pyodide.asm.wasm','python_stdlib.zip','pyodide-lock.json'].map(name=>[name,{sha256:hash,bytes:12}]));
 const hosted={...manifest,runtime:{...manifest.runtime,delivery:'same_origin_pinned_core'},
  files:{...manifest.files,'model/python-core.json':{sha256:hash,bytes:30}},
  python_core:{source:{path:'model/python-core.json',sha256:hash},directory:'python/314.0.8-pinned',files:coreFiles}};
 assert.equal(worker.validateManifest(hosted,config),hosted);
 assert.throws(()=>worker.validateManifest({...hosted,python_core:{...hosted.python_core,directory:'../external'}},config),/Unsafe/);
 assert.throws(()=>worker.validateManifest({...hosted,python_core:{...hosted.python_core,files:{}}},config),/Complete original/);
 assert.throws(()=>worker.validateManifest({...manifest,python_core:hosted.python_core},config),/declared/);

 let clock=0,time=0,paused=false;const timers=[],messages=[],effects=[];
 const runtime={initial:state(),command(command){effects.push(command.action);if(command.action==='request_job')throw Error('unknown target');paused=command.action==='pause';return state(time,paused);},tick(){effects.push('tick');time=Math.round((time+.05)*100)/100;clock+=80;return state(time,paused);}};
 const controller=worker.createController({post:value=>messages.push(value),loadRuntime:async(config,progress)=>{progress({phase:'testing_live_boot'});return runtime;},now:()=>clock,setTimer:(fn,delay)=>{const item={fn,delay};timers.push(item);return item;},clearTimer:item=>{item.canceled=true;}});
 controller.handle({type:'boot',config});controller.handle({type:'command',id:1,command:{action:'pause'}});await flush();
 assert.equal(messages.filter(m=>m.type==='state').length,1);assert.equal(timers.length,1);
 timers.shift().fn();await flush();assert.deepEqual(effects,['pause']);assert.equal(controller.state.paused,true);assert.equal(timers.length,0,'Paused worlds wait for a command');
 controller.handle({type:'command',id:2,command:{action:'request_job',...job}});controller.handle({type:'command',id:3,command:{action:'resume'}});
 timers.shift().fn();await flush();assert.deepEqual(effects,['pause','request_job','resume','tick']);assert(messages.some(m=>m.type==='command_error'&&m.request_id===job.request_id));
 assert.equal(controller.state.model_time_s,.05);assert.equal(timers.length,1);assert.equal(timers[0].delay,0,'A slow step does not add multiple catch-up steps');
 controller.handle({type:'dispose'});assert(timers[0].canceled);
 let finishTick;const busyTimers=[],busyEffects=[],busyStates=[];
 const busyController=worker.createController({post:v=>busyStates.push(v),loadRuntime:async()=>({initial:state(),tick(){busyEffects.push('tick-start');return new Promise(resolve=>{finishTick=()=>resolve(state(.05));});},command(command){busyEffects.push(command.action);return state(.05,command.action==='pause');}}),now:()=>0,setTimer:(fn,delay)=>{const item={fn,delay};busyTimers.push(item);return item;},clearTimer:item=>{item.canceled=true;}});
 busyController.handle({type:'boot',config});await flush();busyTimers.shift().fn();await flush();assert.deepEqual(busyEffects,['tick-start']);
 busyController.handle({type:'command',id:5,command:{action:'pause'}});busyTimers.shift().fn();await flush();assert.deepEqual(busyEffects,['tick-start'],'A command may not enter a running Python step');
 assert.equal(busyController.state.model_time_s,0,'The cached scene remains at the last executed state');finishTick();await flush();busyTimers.shift().fn();await flush();assert.deepEqual(busyEffects,['tick-start','pause']);assert.equal(busyController.state.paused,true);busyController.handle({type:'dispose'});
 const failures=[],broken=worker.createController({post:v=>failures.push(v),loadRuntime:async()=>{throw Error('missing bundle');},setTimer:()=>assert.fail('Failed boot must not schedule motion')});broken.handle({type:'boot',config});await flush();assert.equal(failures.at(-1).type,'error');assert.match(failures.at(-1).error,/missing bundle/);
 async function labController(initial=labState(),release=true){
  const messages=[],timers=[],effects=[];let current=initial;
  const runtime={initial,command(command){effects.push(command);current={...current,lab3003_reserved:release?false:true};return current;},tick(){assert.fail('The paused laboratory fixture must not tick');}};
  const controller=worker.createController({post:v=>messages.push(v),loadRuntime:async()=>runtime,now:()=>0,
   setTimer:(fn,delay)=>{const row={fn,delay};timers.push(row);return row;},clearTimer:row=>{row.canceled=true;}});
  controller.handle({type:'boot',config});await flush();
  const send=async(id,command)=>{controller.handle({type:'command',id,command});assert(timers.length);timers.shift().fn();await flush();};
  return{controller,messages,effects,send};
 }
 const liveLab=await labController();
 for(const command of [{action:'lab3003_docked'},{action:'lab3003_docked',reservation_id:'stale'},
                       {action:'lab3003_docked',reservation_id:reservationId,extra:true}]){
  await liveLab.send(1,command);assert.equal(liveLab.messages.at(-1).type,'command_error');
 }
 assert.equal(liveLab.effects.length,0);assert.equal(liveLab.controller.state.lab3003_reserved,true);
 await liveLab.send(2,{action:'lab3003_docked',reservation_id:reservationId});
 assert.equal(liveLab.messages.at(-2).type,'state');assert.deepEqual(liveLab.messages.at(-1),labAck(2));
 await liveLab.send(3,{action:'lab3003_docked',reservation_id:reservationId});assert.deepEqual(liveLab.messages.at(-1),labAck(3));
 assert.equal(liveLab.effects.length,2);liveLab.controller.handle({type:'dispose'});
 const noLab=await labController(state(0,true));await noLab.send(1,{action:'lab3003_docked',reservation_id:reservationId});
 assert.equal(noLab.effects.length,0);assert.equal(noLab.messages.at(-1).type,'command_error');noLab.controller.handle({type:'dispose'});
 const unconfirmed=await labController(labState(),false);await unconfirmed.send(1,{action:'lab3003_docked',reservation_id:reservationId});
 assert.equal(unconfirmed.messages.at(-1).type,'command_error');assert.match(unconfirmed.messages.at(-1).error,/did not confirm/);
 assert.equal(unconfirmed.messages.filter(message=>message.type==='command_ack').length,0);unconfirmed.controller.handle({type:'dispose'});
 console.log('Passed independent live Worker boot, source pins, cached progress, serialized commands, idempotency, pause, no catch-up and visible failure checks.');
})().catch(error=>{console.error(error);process.exitCode=1;});
