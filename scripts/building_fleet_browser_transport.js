/* A fresh, autonomous BF01 Worker session for each browser page. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.BuildingFleetBrowserTransport=api;})(typeof globalThis!=='undefined'?globalThis:this,function(){
'use strict';
const SNAPSHOT='solidcraftbot.building-fleet-live-snapshot/1';
const clone=value=>JSON.parse(JSON.stringify(value));
const REQUEST_ID=/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}$/;
function require(ok,message){if(!ok)throw Error(message);}
const progressFields=['phase','vehicle_id','done','total','routes','received_bytes','total_bytes','verified_files','total_files'];
const startupLabels={
 loading_browser_engine:'Simulationsmotor wird gestartet',checking_browser_bundle:'Liste der Modelldateien wird geprüft',
 loading_python_runtime:'Laufzeit wird geladen',loading_runtime_assets:'Laufzeit und Modell werden geladen',
 initializing_python_runtime:'Python-Laufzeit wird initialisiert',checking_simulation_sources:'Modelldateien werden entpackt und geprüft',
 verifying_browser_bundle:'Modellquellen werden geprüft',restoring_checked_static_geometry:'Gebäudegeometrie wird vorbereitet',
 compact_static_geometry_ready:'Gebäudegeometrie ist bereit',checking_camera_geometry:'Kamerageometrie wird geprüft',
 checking_navigation:'Fahrwege werden geprüft',static_graph_cache_restore:'Fahrwege werden geladen',
 static_route_witnesses_bound:'Geprüfte Fahrwege werden zugeordnet',static_graph_cache_ready:'Fahrwege sind bereit',
 static_endpoint:'Routenziele werden geprüft',static_splice_repairs:'Routenanschlüsse werden geprüft',
 static_route_preparation:'Routen werden vorbereitet',static_resource_closure:'Fahrbereiche werden zugeordnet',
 native_scan_surfaces:'Hindernisflächen werden vorbereitet',native_scan_surfaces_ready:'Hindernisflächen sind bereit'
};
const formatMiB=new Intl.NumberFormat('de-DE',{minimumFractionDigits:1,maximumFractionDigits:1});
function startupDisplay(state){
 const detail=startupLabels[state.phase]??'Live-Patrouille wird vorbereitet';
 const count=(done,total)=>Number.isSafeInteger(done)&&Number.isSafeInteger(total)&&total>0&&done>=0&&done<=total;
 if(state.phase==='loading_runtime_assets'&&count(state.received_bytes,state.total_bytes)){
  const mib=bytes=>formatMiB.format(bytes/1048576);
  const files=count(state.verified_files,state.total_files)?' · '+state.verified_files+'/'+state.total_files+' Dateien geprüft':'';
  return {detail:detail+' · '+mib(state.received_bytes)+'/'+mib(state.total_bytes)+' MiB empfangen'+files,
   value:state.received_bytes,max:state.total_bytes};
 }
 if(count(state.done,state.total))return {detail:detail+' · '+state.done+'/'+state.total,value:state.done,max:state.total};
 return {detail,value:null,max:null};
}
function resolveConfig(config,base){
 require(config&&typeof config==='object','Browser simulation configuration required');
 const origin=new URL(base).origin;
 const local=value=>{require(typeof value==='string'&&value.length>0,'Named simulation asset URL required');const url=new URL(value,base);require(url.origin===origin&&['http:','https:'].includes(url.protocol)&&!url.username&&!url.password,'Simulation assets must use the page origin');return url.href;};
 const ref=value=>{require(value&&typeof value.url==='string'&&/^[a-f0-9]{64}$/.test(value.sha256),'Pinned browser simulation asset required');return{url:local(value.url),sha256:value.sha256};};
 return{module_url:local(config.module_url),manifest:ref(config.manifest),bundle:ref(config.bundle)};
}
function create(config,options={}){
 const base=options.baseURL??globalThis.location?.href;
 const resolved=resolveConfig(config,base);
 const factory=options.workerFactory??((url)=>new Worker(url,{type:'module',name:'BF01 live patrol'}));
 const worker=factory(resolved.module_url);
 let resolveReady;const ready=new Promise(resolve=>{resolveReady=resolve;});
 const settleReady=()=>{if(resolveReady){resolveReady({status:state.status});resolveReady=null;}};
 let state={format:'solidcraftbot.building-fleet-live-state/1',status:'starting',phase:'loading_browser_engine',paused:false},disposed=false,commandCount=0;
 const requests=new Map(),startupListeners=new Set();
 const startupState=()=>state.status==='starting'?clone(state):state.status==='error'?{status:'error',error:state.error}:{status:'ready'};
 function notifyStartup(){
  for(const listener of startupListeners)listener(startupState());
  if(state.status!=='starting')startupListeners.clear();
 }
 const fatal=error=>{state={...state,status:'error',error:String(error||'Browser simulation stopped')};settleReady();notifyStartup();};
 const send=command=>{require(!disposed,'This browser simulation has been closed');require(state.status!=='error','The browser simulation stopped; reload to start a new session');worker.postMessage({type:'command',id:++commandCount,command});return commandCount;};
 worker.onmessage=event=>{
  const message=event.data;
  if(disposed||state.status==='error'||!message||typeof message!=='object')return;
  if(message.type==='state'){
   const next=message.state;
   if(next?.format!==SNAPSHOT||typeof next.session_id!=='string'||!Number.isFinite(next.model_time_s)){fatal('Invalid executed simulation state');return;}
   if(state.format===SNAPSHOT&&state.session_id===next.session_id&&next.model_time_s<state.model_time_s){fatal('Simulation clock moved backwards');return;}
   state={...clone(next),status:'ready',command_errors:state.command_errors??[]};
   settleReady();if(startupListeners.size)notifyStartup();
  }else if(message.type==='progress'){
   const p=message.progress??{},progress={};
   for(const key of progressFields)if(p[key]!==undefined)progress[key]=p[key];
   if(state.status==='starting'){
    if(typeof progress.phase!=='string')return;
    for(const key of progressFields)delete state[key];
    Object.assign(state,progress);notifyStartup();
   }else state={...state,...progress};
  }else if(message.type==='command_error'){
   const errors=[...(state.command_errors??[]),{request_id:message.request_id??String(message.id),error:String(message.error)}];
   state={...state,command_errors:errors.slice(-100)};
  }else if(message.type==='error')fatal(message.error);
 };
 worker.onerror=event=>{event.preventDefault?.();fatal(event.message??'Browser simulation could not start');};
 worker.onmessageerror=()=>fatal('The browser simulation returned unreadable data');
 worker.postMessage({type:'boot',config:resolved});
 return Object.freeze({
  ready,
  subscribeStartup(listener){
   require(!disposed&&typeof listener==='function','Startup listener required for an open session');
   if(state.status==='starting')startupListeners.add(listener);
   listener(startupState());
   return ()=>startupListeners.delete(listener);
  },
  async request(url,body){
   require(!disposed,'This browser simulation has been closed');
   const address=new URL(url,base);require(address.origin===new URL(base).origin,'Simulation commands must use the page origin');const path=address.pathname;
   if(body===undefined){require(path==='/api/state','Unknown browser simulation query');return clone(state);}
   if(path==='/api/control'){
    require(body&&Object.keys(body).length===1&&['pause','resume'].includes(body.action),'Expected pause or resume');
    send({action:body.action});return{status:'queued_for_engine',action:body.action};
   }
   require(path==='/api/jobs'&&body&&Object.keys(body).sort().join(',')==='delivery,pickup,request_id','Expected one identified pickup-and-delivery request');
   require(typeof body.request_id==='string'&&REQUEST_ID.test(body.request_id),'A stable bounded request identity is required');
   for(const key of ['pickup','delivery'])require(body[key]&&Object.keys(body[key]).sort().join(',')==='area,level'&&['level','area'].every(k=>typeof body[key][k]==='string'&&body[key][k].length>0),'Named source targets required');
   require(body.pickup.level!==body.delivery.level||body.pickup.area!==body.delivery.area,'Pickup and delivery must differ');
   const fingerprint=JSON.stringify([body.pickup.level,body.pickup.area,body.delivery.level,body.delivery.area]);
   if(requests.has(body.request_id)){require(requests.get(body.request_id)===fingerprint,'Request identity already belongs to different targets');return{status:'queued_for_engine',request_id:body.request_id};}
   require(requests.size<100,'This bounded browser session already holds 100 test requests');
   send({action:'request_job',...clone(body)});requests.set(body.request_id,fingerprint);
   return{status:'queued_for_engine',request_id:body.request_id};
  },
  dispose(){if(disposed)return;disposed=true;startupListeners.clear();worker.terminate();},
  get state(){return clone(state);}
 });
}
return{create,resolveConfig,startupDisplay};
});
