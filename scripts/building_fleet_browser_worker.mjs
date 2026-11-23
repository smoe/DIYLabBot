/* Live BF01 Python engine inside one visitor's module Worker; no recording. */
const SNAPSHOT='solidcraftbot.building-fleet-live-snapshot/1';
const HASH=/^[a-f0-9]{64}$/;
function require(ok,message){if(!ok)throw Error(message);}
export function checkedPath(value){
 require(typeof value==='string'&&value.length>0&&!value.startsWith('/')&&!value.includes('\\')&&!value.includes('\0')&&value.split('/').every(part=>part&&part!=='.'&&part!=='..'),'Unsafe browser bundle path');return value;
}
export function validateManifest(manifest,config){
 require(manifest?.format==='solidcraftbot.building-fleet-browser-bundle/1'&&manifest.root_dir==='/project','Named browser simulation bundle required');
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
 return manifest;
}
async function digest(bytes){return [...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(v=>v.toString(16).padStart(2,'0')).join('');}
async function download(url,expectedHash,expectedBytes=null){
 require(HASH.test(expectedHash),'Pinned simulation download required');
 const response=await fetch(url,{cache:'no-store',credentials:'same-origin'});require(response.ok,'Simulation asset download failed: HTTP '+response.status);
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
import sys
sys.path.insert(0, '/project/scripts')
`;
function parseState(raw){const state=typeof raw==='string'?JSON.parse(raw):raw;require(state?.format===SNAPSHOT&&typeof state.session_id==='string'&&Number.isFinite(state.model_time_s)&&typeof state.paused==='boolean'&&Number.isFinite(state.integration_step_s)&&state.integration_step_s>0&&state.integration_step_s<=.05,'Executed Python simulation snapshot and source control step required');return state;}
export async function loadPythonRuntime(config,progress){
 progress({phase:'checking_browser_bundle'});
 const raw=await download(config.manifest.url,config.manifest.sha256),text=new TextDecoder().decode(raw),manifest=validateManifest(JSON.parse(text),config);
 progress({phase:'loading_python_runtime'});
 const [{loadPyodide},archive]=await Promise.all([
  import(manifest.runtime.loader_module_url),download(config.bundle.url,config.bundle.sha256,manifest.archive.bytes)]);
 const pyodide=await loadPyodide({indexURL:new URL('.',manifest.runtime.loader_module_url).href});
 progress({phase:'checking_simulation_sources'});
 pyodide.FS.writeFile('/tmp/bf01-runtime.zip',archive);pyodide.globals.set('_bf_manifest_json',text);
 await pyodide.runPythonAsync(EXTRACT);pyodide.FS.unlink('/tmp/bf01-runtime.zip');
 const runtime=pyodide.pyimport('building_fleet_browser_runtime');
 const inputs={...manifest.inputs,root:'/project',source_files_sha256:Object.fromEntries(Object.entries(manifest.files).map(([name,ref])=>[name,ref.sha256])),browser_config_sha256:config.manifest.sha256};
 const state=parseState(runtime.boot(JSON.stringify(inputs),value=>progress(JSON.parse(value))));
 return{initial:state,tick:()=>parseState(runtime.tick()),command:command=>parseState(runtime.command(JSON.stringify(command))),dispose:()=>runtime.destroy()};
}
export function createController({post,loadRuntime=loadPythonRuntime,now=()=>performance.now(),setTimer=setTimeout,clearTimer=clearTimeout}){
 let runtime=null,state=null,busy=false,booted=false,disposed=false,timer=null;const commands=[];
 const emitState=value=>{state=parseState(value);post({type:'state',state});};
 const fail=error=>{disposed=true;if(timer!==null)clearTimer(timer);post({type:'error',error:String(error?.message??error)});};
 const schedule=delay=>{if(disposed||timer!==null||!runtime)return;timer=setTimer(()=>{timer=null;void cycle();},delay);};
 async function cycle(){
  if(disposed||busy||!runtime)return;busy=true;const began=now();
  try{
   while(commands.length){const row=commands.shift();try{emitState(await runtime.command(row.command));}catch(error){post({type:'command_error',id:row.id,request_id:row.command.request_id,error:String(error?.message??error)});}}
   if(!state.paused)emitState(await runtime.tick());
  }catch(error){fail(error);}finally{busy=false;if(!disposed&&(!state?.paused||commands.length))schedule(Math.max(0,state.integration_step_s*1000-(now()-began)));}
 }
 return{handle(message){
  if(disposed)return;
  if(message?.type==='boot'){
   if(booted){fail(Error('A browser Worker may boot only one live world'));return;}booted=true;busy=true;
   Promise.resolve().then(()=>loadRuntime(message.config,progress=>post({type:'progress',progress}))).then(value=>{if(disposed){value.dispose?.();return;}runtime=value;emitState(value.initial);busy=false;schedule(0);}).catch(fail);
  }else if(message?.type==='command'){
   const action=message.command?.action;
   if(!['pause','resume','request_job'].includes(action)){post({type:'command_error',id:message.id,error:'Unknown simulation command'});return;}
   if(commands.length>=100){post({type:'command_error',id:message.id,request_id:message.command?.request_id,error:'Browser command queue is full'});return;}
   commands.push({id:message.id,command:message.command});schedule(0);
  }else if(message?.type==='dispose'){disposed=true;if(timer!==null)clearTimer(timer);runtime?.dispose?.();}
 },get state(){return state;}};
}
if(typeof document==='undefined'&&typeof globalThis.postMessage==='function'&&typeof globalThis.addEventListener==='function'){
 const controller=createController({post:message=>globalThis.postMessage(message)});
 globalThis.addEventListener('message',event=>controller.handle(event.data));
}
