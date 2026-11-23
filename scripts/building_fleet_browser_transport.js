/* A fresh, autonomous BF01 Worker session for each browser page. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.BuildingFleetBrowserTransport=api;})(typeof globalThis!=='undefined'?globalThis:this,function(){
'use strict';
const SNAPSHOT='solidcraftbot.building-fleet-live-snapshot/1';
const clone=value=>JSON.parse(JSON.stringify(value));
const REQUEST_ID=/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}$/;
function require(ok,message){if(!ok)throw Error(message);}
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
 const requests=new Map();
 const fatal=error=>{state={...state,status:'error',error:String(error||'Browser simulation stopped')};settleReady();};
 const send=command=>{require(!disposed,'This browser simulation has been closed');require(state.status!=='error','The browser simulation stopped; reload to start a new session');worker.postMessage({type:'command',id:++commandCount,command});return commandCount;};
 worker.onmessage=event=>{
  const message=event.data;
  if(disposed||!message||typeof message!=='object')return;
  if(message.type==='state'){
   const next=message.state;
   if(next?.format!==SNAPSHOT||typeof next.session_id!=='string'||!Number.isFinite(next.model_time_s)){fatal('Invalid executed simulation state');return;}
   if(state.format===SNAPSHOT&&state.session_id===next.session_id&&next.model_time_s<state.model_time_s){fatal('Simulation clock moved backwards');return;}
   state={...clone(next),status:'ready',command_errors:state.command_errors??[]};
   settleReady();
  }else if(message.type==='progress'){
   const p=message.progress??{},progress={};
   for(const key of ['phase','vehicle_id','done','total','routes'])if(p[key]!==undefined)progress[key]=p[key];
   state={...state,...progress,status:state.format===SNAPSHOT?'ready':'starting'};
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
  dispose(){if(disposed)return;disposed=true;worker.terminate();},
  get state(){return clone(state);}
 });
}
return{create,resolveConfig};
});
