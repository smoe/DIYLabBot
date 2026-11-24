/* Live BF01 Python engine inside one visitor's module Worker; no recording. */
const SNAPSHOT='solidcraftbot.building-fleet-live-snapshot/1';
const HASH=/^[a-f0-9]{64}$/;
const CORE_FILES=['pyodide.mjs','pyodide.asm.mjs','pyodide.asm.wasm','python_stdlib.zip','pyodide-lock.json'];
function require(ok,message){if(!ok)throw Error(message);}
export function checkedPath(value){
 require(typeof value==='string'&&value.length>0&&!value.startsWith('/')&&!value.includes('\\')&&!value.includes('\0')&&value.split('/').every(part=>part&&part!=='.'&&part!=='..'),'Unsafe browser bundle path');return value;
}
export function validateManifest(manifest,config){
 require(['solidcraftbot.building-fleet-browser-bundle/1','solidcraftbot.building-fleet-browser-bundle/2'].includes(manifest?.format)&&manifest.root_dir==='/project','Named browser simulation bundle required');
 require(manifest.files&&typeof manifest.files==='object'&&!Array.isArray(manifest.files)&&Object.keys(manifest.files).length>0,'Exact browser bundle files required');
 for(const [path,ref]of Object.entries(manifest.files)){checkedPath(path);require(ref&&HASH.test(ref.sha256)&&Number.isSafeInteger(ref.bytes)&&ref.bytes>=0,'Bounded source file bytes and hash required');}
 checkedPath(manifest.bootstrap_path);require(manifest.files[manifest.bootstrap_path],'Pinned Python bootstrap required');
 require(manifest.archive&&manifest.archive.sha256===config.bundle.sha256&&Number.isSafeInteger(manifest.archive.bytes)&&manifest.archive.bytes>0,'Archive must match its page pin');
 const runtime=manifest.runtime,session=manifest.session;
 require(runtime?.engine==='pyodide'&&runtime.execution==='module_web_worker'&&runtime.pacing==='source_step_without_wall_clock_catchup'&&typeof runtime.version==='string','Declared browser Python runtime required');
 require(runtime.loader_module_url==='https://cdn.jsdelivr.net/pyodide/v'+runtime.version+'/full/pyodide.mjs','Official version-matched Pyodide loader required');
 require(session?.scope==='independent_live_session_per_page'&&session.start==='new_patrol_world'&&session.recording_fallback===false,'Every visitor must start an independent live world');
 const browser=manifest.browser_config;require(browser&&manifest.files[checkedPath(browser.path)]?.sha256===browser.sha256,'Leading browser configuration must be pinned in the bundle');
 require(manifest.inputs&&typeof manifest.inputs==='object'&&manifest.inputs.browser_source===browser.path,'Source-matched bootstrap inputs required');
 if(manifest.format.endsWith('/2')){
  require(runtime.static_geometry==='source_bound_lossless_runtime_cache'&&runtime.route_preparation==='background_worker_with_checked_rolling_prefix','Checked compact geometry and background preparation required');
  require(Object.keys(manifest.inputs).sort().join(',')==='browser_source,profile,static_runtime_cache'&&manifest.files[checkedPath(manifest.inputs.static_runtime_cache)],'Pinned static runtime derivation required');
  require(manifest.static_cache_verification&&typeof manifest.static_cache_verification==='object','Build-checked static operation receipt required');
 }
 if(runtime.delivery!==undefined){
  require(runtime.delivery==='same_origin_pinned_core','Unknown browser Python delivery policy');
  const core=manifest.python_core;require(core&&manifest.files[checkedPath(core.source?.path)]?.sha256===core.source.sha256,'Pinned original Python core descriptor required');
  checkedPath(core.directory);require(CORE_FILES.every(name=>core.files?.[name]&&HASH.test(core.files[name].sha256)&&Number.isSafeInteger(core.files[name].bytes)&&core.files[name].bytes>0),'Complete original Python core files required');
  for(const name of Object.keys(core.files))checkedPath(name);
 }else require(manifest.python_core===undefined,'Python delivery must be declared by the leading source');
 if(manifest.python_bytecode){
  const cache=manifest.python_bytecode;checkedPath(cache.prefix);
  require(cache.format==='solidcraftbot.building-fleet-import-cache/1'&&cache.cache_tag==='cpython-314'&&/^[a-f0-9]{8}$/.test(cache.magic_number_hex)&&cache.sources&&Object.keys(cache.sources).length>0,'Compatible source-bound import cache required');
  for(const [source,ref]of Object.entries(cache.sources)){
   checkedPath(source);checkedPath(ref.artifact);
   require(source.endsWith('.py')&&ref.artifact===cache.prefix+'/project/'+source.slice(0,-3)+'.'+cache.cache_tag+'.pyc'&&manifest.files[source]?.sha256===ref.source_sha256&&manifest.files[ref.artifact]?.sha256===ref.sha256&&manifest.files[ref.artifact]?.bytes===ref.bytes,'Import bytecode differs from its exact original source/artifact pins');
  }
 }
 return manifest;
}
async function digest(bytes){return [...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(v=>v.toString(16).padStart(2,'0')).join('');}
export async function download(url,expectedHash,expectedBytes=null){
 require(HASH.test(expectedHash),'Pinned simulation download required');
 // Fingerprinted assets may use the HTTP cache; every returned byte is still
 // checked against the page/manifest hash before it enters the simulation.
 const response=await fetch(url,{cache:'force-cache',credentials:'same-origin'});require(response.ok,'Simulation asset download failed: HTTP '+response.status);
 const limit=expectedBytes??1024*1024;
 let bytes;
 if(response.body?.getReader){const reader=response.body.getReader(),chunks=[];let count=0;for(;;){const result=await reader.read();if(result.done)break;count+=result.value.byteLength;if(count>limit){await reader.cancel();throw Error('Simulation asset exceeds its declared size');}chunks.push(result.value);}bytes=new Uint8Array(count);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.byteLength;}}
 else{bytes=new Uint8Array(await response.arrayBuffer());require(bytes.byteLength<=limit,'Simulation asset exceeds its declared size');}
 require(expectedBytes===null||bytes.byteLength===expectedBytes,'Simulation asset size differs from its manifest');
 require(await digest(bytes)===expectedHash,'Simulation asset hash differs from its page pin');return bytes;
}
const EXTRACT=String.raw`
import hashlib, json, os, stat, zipfile
_manifest = json.loads(_bf_manifest_json)
_expected = _manifest['files']
with zipfile.ZipFile('/tmp/bf01-runtime.zip') as _archive:
    _entries = _archive.infolist()
    _names = [entry.filename for entry in _entries]
    if len(_names) != len(set(_names)) or set(_names) != set(_expected):
        raise ValueError('Browser archive file list differs from the manifest')
    for _entry in _entries:
        _name = _entry.filename
        _mode = _entry.external_attr >> 16
        if (_entry.is_dir() or _name.startswith('/') or '\\' in _name or '\x00' in _name
                or any(part in ('', '.', '..') for part in _name.split('/'))
                or stat.S_IFMT(_mode) not in (0, stat.S_IFREG)):
            raise ValueError('Unsafe browser archive entry')
        _ref = _expected[_name]
        if _entry.file_size != _ref['bytes']:
            raise ValueError('Browser archive member size differs')
        _bytes = _archive.read(_entry)
        if hashlib.sha256(_bytes).hexdigest() != _ref['sha256']:
            raise ValueError('Browser archive member hash differs')
        _target = '/project/' + _name
        os.makedirs(os.path.dirname(_target), exist_ok=True)
        with open(_target, 'wb') as _output:
            _output.write(_bytes)
with open('/project/' + _manifest['browser_config']['path'], encoding='utf-8') as _input:
    _browser_source = json.load(_input)
if (_browser_source['runtime'] != _manifest['runtime']
        or _browser_source['session'] != _manifest['session']):
    raise ValueError('Derived browser runtime differs from its leading source')
if _manifest['runtime'].get('delivery') == 'same_origin_pinned_core':
    _core_ref = _browser_source['sources']['python_core']
    if _core_ref != _manifest['python_core']['source']:
        raise ValueError('Python core differs from its pinned leading source')
    with open('/project/' + _core_ref['path'], encoding='utf-8') as _input:
        _core_source = json.load(_input)
    if (_core_source['version'] != _manifest['runtime']['version']
            or _core_source['files'] != _manifest['python_core']['files']):
        raise ValueError('Python core delivery differs from its original byte manifest')
import sys
sys.path.insert(0, '/project/scripts')
`;
export async function extractArchive(pyodide,archive,manifest){
 // The deterministic package uses ordinary single-disk ZIP entries. Decode
 // their original bytes with the browser, verify before writing, then import
 // Python. No unverified member or Python pickle is executed.
 const b=archive,v=new DataView(b.buffer,b.byteOffset,b.byteLength),u16=i=>v.getUint16(i,true),u32=i=>v.getUint32(i,true);
 require(b.length>=22&&u32(b.length-22)===0x06054b50,'Plain ZIP end record required');
 const end=b.length-22,count=u16(end+10),start=u32(end+16),size=u32(end+12);
 require(u16(end+4)===0&&u16(end+6)===0&&u16(end+8)===count&&u16(end+20)===0&&start+size===end&&count===Object.keys(manifest.files).length,'Complete single-disk ZIP directory required');
 const decoder=new TextDecoder('utf-8',{fatal:true}),rows=[],seen=new Set();let at=start;
 for(let n=0;n<count;n++){
  require(at+46<=end&&u32(at)===0x02014b50,'Complete ZIP member directory required');
  const flags=u16(at+8),method=u16(at+10),packed=u32(at+20),bytes=u32(at+24),nameLength=u16(at+28),extra=u16(at+30),comment=u16(at+32),offset=u32(at+42),mode=(u32(at+38)>>>16)&0xf000;
  require((flags&~0x800)===0&&[0,8].includes(method)&&[0,0x8000].includes(mode)&&u16(at+34)===0&&at+46+nameLength+extra+comment<=end,'Only ordinary regular ZIP files may enter the live runtime');
  const name=checkedPath(decoder.decode(b.subarray(at+46,at+46+nameLength))),ref=manifest.files[name];
  require(!seen.has(name)&&ref&&bytes===ref.bytes,'ZIP file list or source byte count differs');seen.add(name);
  require(offset+30<=start&&u32(offset)===0x04034b50&&u16(offset+6)===flags&&u16(offset+8)===method&&u32(offset+18)===packed&&u32(offset+22)===bytes,'ZIP local source header differs');
  const localName=u16(offset+26),data=offset+30+localName+u16(offset+28);
  require(data+packed<=start&&decoder.decode(b.subarray(offset+30,offset+30+localName))===name,'ZIP source range or name differs');
  rows.push({name,ref,method,offset,data,end:data+packed});at+=46+nameLength+extra+comment;
 }
 require(at===end,'Unexpected ZIP directory bytes');let previous=0;
 for(const row of rows.slice().sort((a,b)=>a.offset-b.offset)){require(row.offset===previous,'Overlapping or undeclared ZIP source data');previous=row.end;}
 require(previous===start,'Undeclared ZIP source data');
 for(const row of rows){
  let raw=b.subarray(row.data,row.end);
  if(row.method===8){
   const reader=new Blob([raw]).stream().pipeThrough(new DecompressionStream('deflate-raw')).getReader(),chunks=[];let length=0;
   for(;;){const part=await reader.read();if(part.done)break;length+=part.value.byteLength;if(length>row.ref.bytes){await reader.cancel();throw Error('Decoded ZIP source exceeds its manifest');}chunks.push(part.value);}
   raw=new Uint8Array(length);let offset=0;for(const part of chunks){raw.set(part,offset);offset+=part.byteLength;}
  }
  require(raw.length===row.ref.bytes&&await digest(raw)===row.ref.sha256,'ZIP source bytes differ: '+row.name);
  const slash=row.name.lastIndexOf('/'),directory=slash<0?'':row.name.slice(0,slash);if(directory)pyodide.FS.mkdirTree('/project/'+directory);
  pyodide.FS.writeFile('/project/'+row.name,raw);
 }
}
function parseState(raw){const state=typeof raw==='string'?JSON.parse(raw):raw;require(state?.format===SNAPSHOT&&typeof state.session_id==='string'&&Number.isFinite(state.model_time_s)&&typeof state.paused==='boolean'&&Number.isFinite(state.integration_step_s)&&state.integration_step_s>0&&state.integration_step_s<=.05,'Executed Python simulation snapshot and source control step required');return state;}
export async function loadRuntimeAssets(manifest,config,{loadModule=url=>import(url),fetchArchive=download,fetchCore=download}={}){
 // Start the actual Python/Wasm initialization alongside the archive download,
 // rather than waiting for the entire model before starting the runtime.
 const python=(async()=>{
  let loader=manifest.runtime.loader_module_url,indexURL=new URL('.',loader).href;
  if(manifest.python_core){
   const core=manifest.python_core,base=new URL(core.directory+'/',config.manifest.url);
   require(base.origin===new URL(config.manifest.url).origin,'Python core must use the page origin');
   await Promise.all(CORE_FILES.map(name=>fetchCore(new URL(name,base).href,core.files[name].sha256,core.files[name].bytes)));
   loader=new URL('pyodide.mjs',base).href;indexURL=base.href;
  }
  const {loadPyodide}=await loadModule(loader);
  return loadPyodide({indexURL});
 })();
 const archive=fetchArchive(config.bundle.url,config.bundle.sha256,manifest.archive.bytes);
 return Promise.all([python,archive]);
}
async function loadPythonBridge(config,progress,onCompactAssetsReady){
 progress({phase:'checking_browser_bundle'});
 const raw=await download(config.manifest.url,config.manifest.sha256),text=new TextDecoder().decode(raw),manifest=validateManifest(JSON.parse(text),config);
 progress({phase:'loading_python_runtime'});
 const [pyodide,archive]=await loadRuntimeAssets(manifest,config);
 // Warm the planner before restoring either world. The simulator's verified
 // large downloads must finish first: concurrent cold Chromium cache writers
 // can abort the same WASM and model responses.
 if(manifest.format.endsWith('/2'))onCompactAssetsReady?.();
 progress({phase:'checking_simulation_sources'});
 pyodide.globals.set('_bf_manifest_json',text);
 if(typeof DecompressionStream==='function'){
  await extractArchive(pyodide,archive,manifest);
  const validation=EXTRACT.slice(EXTRACT.indexOf("with open('/project/'"));
  await pyodide.runPythonAsync('import json\n_manifest=json.loads(_bf_manifest_json)\n'+validation);
 }else{
  pyodide.FS.writeFile('/tmp/bf01-runtime.zip',archive);
  await pyodide.runPythonAsync(EXTRACT);pyodide.FS.unlink('/tmp/bf01-runtime.zip');
 }
 if(manifest.python_bytecode){
  pyodide.globals.set('_bf_bytecode_json',JSON.stringify(manifest.python_bytecode));
  await pyodide.runPythonAsync("import importlib.util,json,sys\n_bc=json.loads(_bf_bytecode_json)\nif sys.implementation.cache_tag!=_bc['cache_tag'] or importlib.util.MAGIC_NUMBER.hex()!=_bc['magic_number_hex']:raise ValueError('Python import cache is incompatible with the pinned runtime')\nsys.pycache_prefix='/project/'+_bc['prefix']\n");
 }
 const runtime=pyodide.pyimport('building_fleet_browser_runtime');
 if(manifest.format.endsWith('/2'))runtime.bind_verified_extraction(text);
 const inputs={...manifest.inputs,root:'/project',source_files_sha256:Object.fromEntries(Object.entries(manifest.files).map(([name,ref])=>[name,ref.sha256])),browser_config_sha256:config.manifest.sha256};
 return{runtime,inputs,manifest};
}
export async function loadPythonRuntime(config,progress,onCompactAssetsReady){
 const {runtime,inputs,manifest}=await loadPythonBridge(config,progress,onCompactAssetsReady);
 const state=parseState(runtime.boot(JSON.stringify(inputs),value=>progress(JSON.parse(value))));
 let hasMotion=Boolean(state.has_motion);
 return{initial:state,background:manifest.format.endsWith('/2'),
  snapshotIntervalSteps:state.snapshot_interval_steps??1,get hasMotion(){return hasMotion;},
  tick:(capture=true)=>{const value=JSON.parse(runtime.tick(capture));hasMotion=Boolean(value.has_motion);
   if(capture)return parseState(value);
   require(value.format==='solidcraftbot.building-fleet-live-step/1'&&Number.isFinite(value.model_time_s)&&typeof value.paused==='boolean'&&value.integration_step_s===state.integration_step_s,'Executed source step receipt required');return null;},
  command:command=>parseState(runtime.command(JSON.stringify(command))),
  pendingJobs:()=>JSON.parse(runtime.pending_jobs()),completeJob:value=>runtime.complete_job(value.result_json),
  dispose:()=>runtime.destroy?.()};
}
export async function loadPythonPlanner(config,progress){
 const {runtime,inputs}=await loadPythonBridge(config,progress);
 runtime.boot_planner(JSON.stringify(inputs),value=>progress(JSON.parse(value)));
 return{prepare:job=>({result_json:runtime.prepare_job(job.request_json,value=>progress(JSON.parse(value)))}),dispose:()=>runtime.destroy?.()};
}
export function createBackgroundPlanner(config,progress,workerFactory=url=>new Worker(url,{type:'module',name:'BF01 checked route preparation'})){
 const worker=workerFactory(import.meta.url);let sequence=0,disposed=false,failure=null;const pending=new Map();
 const rejectAll=error=>{failure=error;for(const row of pending.values())row.reject(error);pending.clear();};
 worker.onmessage=event=>{const value=event.data;if(disposed)return;
  if(value?.type==='planner_progress'){progress(value.progress);return;}
  if(value?.type==='planner_error'){rejectAll(Error(value.error));return;}
  if(value?.type==='prepared_route'){const row=pending.get(value.id);if(!row){rejectAll(Error('Unknown preparation response'));return;}pending.delete(value.id);row.resolve(value.result);}
 };
 worker.onerror=event=>{event.preventDefault?.();rejectAll(Error(event.message??'Background preparation failed'));};
 worker.onmessageerror=()=>rejectAll(Error('Unreadable background preparation result'));
 worker.postMessage({type:'planner_boot',config});
 return{prepare(job){if(failure)return Promise.reject(failure);require(!disposed&&pending.size<32,'Bounded active preparation queue required');const id=++sequence;
  return new Promise((resolve,reject)=>{pending.set(id,{resolve,reject});worker.postMessage({type:'prepare_route',id,job});});},
  dispose(){disposed=true;rejectAll(Error('Preparation worker closed'));worker.terminate();}};
}
export function createPreparationController({post,loadPlanner=loadPythonPlanner,now=()=>performance.now(),nextTask=()=>new Promise(resolve=>setTimeout(resolve,0))}){
 let planner=null,booted=false,failed=false,busy=false,active=null;
 const jobs=[],intervalVehicles=new Set();
 // Connectors unblock a checked join. Among interval receipts, serve the
 // smallest requested braking headroom first. All ties keep arrival order.
 const priority=job=>job.kind==='continuation'?-Infinity:
  job.kind==='route_interval'?job.brake_headroom_mm:Infinity;
 const fail=error=>{failed=true;post({type:'planner_error',error:String(error?.message??error)});};
 const progress=value=>post({type:'planner_progress',progress:value});
 async function pump(){if(busy||failed||!planner)return;busy=true;
  try{while(jobs.length&&!failed){
    active=jobs.shift();
    const {kind,request_id,vehicle_id}=active.job,began=now();
    progress({phase:'planner_job_start',kind,request_id,vehicle_id});
    const result=await planner.prepare(active.job);
    if(failed)return;
    progress({phase:'planner_job_end',kind,request_id,vehicle_id,total_wall_s:(now()-began)/1000});
    if(kind==='route_interval')intervalVehicles.delete(vehicle_id);
    post({type:'prepared_route',id:active.id,result});active=null;
    // A synchronous Python job only yields a microtask through await. Give
    // incoming continuation messages an actual task turn before the next job.
    if(jobs.length)await nextTask();}}
  catch(error){fail(error);}finally{busy=false;}}
 return{handle(message){if(failed)return;
  if(message?.type==='planner_boot'){
   if(booted){fail(Error('One immutable preparation context per Worker required'));return;}booted=true;
   const began=now();
   Promise.resolve().then(()=>loadPlanner(message.config,progress)).then(value=>{
    planner=value;const ready=now();
    progress({phase:'planner_ready',planner_boot_wall_s:(ready-began)/1000,planner_ready_wall_ms:performance.timeOrigin+ready});
    void pump();
   }).catch(fail);
  }else if(message?.type==='prepare_route'){
   if(!booted||jobs.length+Number(active!==null)>=32){fail(Error('Bounded preparation requests after boot required'));return;}
   const job=message.job;
   if(job.kind==='route_interval'){
    if(!job.vehicle_id||!Number.isFinite(job.brake_headroom_mm)||intervalVehicles.has(job.vehicle_id)){
     fail(Error('One interval per vehicle with finite braking headroom required'));return;
    }
    intervalVehicles.add(job.vehicle_id);
   }
   const rank=priority(job),before=jobs.findIndex(item=>priority(item.job)>rank);
   jobs.splice(before===-1?jobs.length:before,0,message);void pump();
  }
 }};
}
export function createController({post,loadRuntime=loadPythonRuntime,makePlanner=createBackgroundPlanner,now=()=>performance.now(),setTimer=setTimeout,clearTimer=clearTimeout}){
 let runtime=null,state=null,busy=false,booted=false,disposed=false,timer=null,planner=null,config=null,steps=0;
 const commands=[],prepared=[];
 let plannerState='idle',lastCycleEnd=null;
 const cycles=()=>({count:0,compute_wall_s:0,elapsed_wall_s:0,model_s:0});
 const timing={planner_boot_wall_s:null,planner_ready_wall_ms:null,last_starter:null,planner_jobs:{},
  cycles_by_planner:{booting:cycles(),active:cycles(),idle:cycles()},last_cycle:null};
 const emitState=value=>{state={...parseState(value),worker_timing:structuredClone(timing)};post({type:'state',state});};
 function startPlanner(){
  if(disposed||planner)return;
  plannerState='booting';
  planner=makePlanner(config,event=>{
   const {phase,kind,request_id,vehicle_id}=event;
   if(phase==='planner_ready'){
    plannerState='idle';
    timing.planner_boot_wall_s=event.planner_boot_wall_s;
    timing.planner_ready_wall_ms=event.planner_ready_wall_ms;
   }else if(phase==='planner_job_start'){
    plannerState='active';
    timing.planner_jobs[kind]={request_id,vehicle_id,status:'active',phase_wall_s:{}};
   }else if(phase==='planner_job_phase'){
    timing.planner_jobs[kind].phase_wall_s[event.name]=event.wall_s;
   }else if(phase==='planner_job_end'){
    plannerState='idle';
    Object.assign(timing.planner_jobs[kind],{status:'complete',total_wall_s:event.total_wall_s});
   }
  });
 }
 function runtimeProgress(event){
  if(event.phase==='starter_timing'){
   timing.last_starter={...event,start_wall_ms:performance.timeOrigin+now()-1000*event.wall_s};
  }else post({type:'progress',progress:event});
 }
 const fail=error=>{disposed=true;if(timer!==null)clearTimer(timer);planner?.dispose();post({type:'error',error:String(error?.message??error)});};
 const schedule=delay=>{if(disposed||timer!==null||!runtime)return;timer=setTimer(()=>{timer=null;void cycle();},delay);};
 async function cycle(){
  if(disposed||busy||!runtime)return;busy=true;const began=now(),cyclePlanner=plannerState;
  try{
   while(prepared.length)runtime.completeJob(prepared.shift());
   while(commands.length){const row=commands.shift();try{emitState(await runtime.command(row.command));if(state.paused)lastCycleEnd=null;}catch(error){post({type:'command_error',id:row.id,request_id:row.command.request_id,error:String(error?.message??error)});}}
   if(!state.paused){
    const next=await runtime.tick(++steps%(runtime.snapshotIntervalSteps??1)===0);
    if(runtime.background){
     for(const job of runtime.pendingJobs())planner.prepare(job).then(result=>{if(!disposed){prepared.push(result);schedule(0);}}).catch(fail);
    }
    // Wall time is observational only. One call still advances exactly one source step.
    const end=now(),compute=(end-began)/1000,elapsed=(end-(lastCycleEnd??began))/1000,dt=state.integration_step_s;
    lastCycleEnd=end;
    timing.last_cycle={planner_state:cyclePlanner,compute_wall_s:compute,elapsed_wall_s:elapsed,model_s:dt,
     realtime_factor:elapsed>0?dt/elapsed:null};
    const group=timing.cycles_by_planner[cyclePlanner];
    group.count++;group.compute_wall_s+=compute;group.elapsed_wall_s+=elapsed;group.model_s+=dt;
    if(next!==null)emitState(next);
   }
  }catch(error){fail(error);}finally{busy=false;if(!disposed&&(!state?.paused||commands.length))schedule(Math.max(0,state.integration_step_s*1000-(now()-began)));}
 }
 return{handle(message){
  if(disposed)return;
  if(message?.type==='boot'){
   if(booted){fail(Error('A browser Worker may boot only one live world'));return;}booted=true;busy=true;config=message.config;
   Promise.resolve().then(()=>loadRuntime(message.config,runtimeProgress,startPlanner)).then(value=>{
    if(disposed){value.dispose?.();return;}
    runtime=value;if(runtime.background)startPlanner();emitState(value.initial);busy=false;schedule(0);
   }).catch(fail);
  }else if(message?.type==='command'){
   const action=message.command?.action;
   if(!['pause','resume','request_job'].includes(action)){post({type:'command_error',id:message.id,error:'Unknown simulation command'});return;}
   if(commands.length>=100){post({type:'command_error',id:message.id,request_id:message.command?.request_id,error:'Browser command queue is full'});return;}
   commands.push({id:message.id,command:message.command});schedule(0);
  }else if(message?.type==='dispose'){disposed=true;if(timer!==null)clearTimer(timer);planner?.dispose();runtime?.dispose?.();}
 },get state(){return state;}};
}
if(typeof document==='undefined'&&typeof globalThis.postMessage==='function'&&typeof globalThis.addEventListener==='function'){
 let controller=null;
 globalThis.addEventListener('message',event=>{
  if(controller===null)controller=event.data?.type==='planner_boot'
   ?createPreparationController({post:message=>globalThis.postMessage(message)})
   :createController({post:message=>globalThis.postMessage(message)});
  controller.handle(event.data);
 });
}
