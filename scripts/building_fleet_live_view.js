/* Active local BF01 presentation. Routing and movement stay in the Python runner. */
(function(root,factory){const api=factory(typeof module==='object'&&module.exports?require('./building_fleet_view.js'):root.BuildingFleetView);if(typeof module==='object'&&module.exports)module.exports=api;else root.BuildingFleetLiveView=api;})(typeof globalThis!=='undefined'?globalThis:this,function(view){
'use strict';
const IDS=Array.from({length:20},(_,i)=>'BF'+String(i+1).padStart(2,'0'));
const finite=n=>typeof n==='number'&&Number.isFinite(n);
const vector=v=>Array.isArray(v)&&v.length===3&&v.every(finite);
const target=t=>t&&typeof t.level==='string'&&typeof t.area==='string';
function require(ok,message){if(!ok)throw Error(message);}
function validateStates(states){
 require(Array.isArray(states)&&states.length===IDS.length,'Twenty observed vehicle states required');
 const ids=new Set();for(const state of states){require(IDS.includes(state.id)&&!ids.has(state.id)&&vector(state.pose_xyz_mm)&&finite(state.yaw_rad)&&typeof state.level_id==='string'&&typeof state.mode==='string'&&typeof state.attached_cabin==='boolean','Invalid observed vehicle state');ids.add(state.id);}return states;
}
function validateLift(lift){require(lift&&finite(lift.z_mm)&&lift.door_values&&typeof lift.door_values==='object'&&!Array.isArray(lift.door_values)&&Object.values(lift.door_values).every(finite),'Numeric source-bound lift state required');return lift;}
function validateSnapshot(snapshot){
 require(snapshot?.format==='solidcraftbot.building-fleet-live-snapshot/1'&&typeof snapshot.session_id==='string'&&snapshot.session_id.length>0,'Named active fleet snapshot required');
 require(finite(snapshot.model_time_s)&&snapshot.model_time_s>=0&&typeof snapshot.paused==='boolean','Finite executed model clock required');
 validateStates(snapshot.states);validateLift(snapshot.lift);
 require(Array.isArray(snapshot.targets)&&snapshot.targets.every(target)&&Array.isArray(snapshot.jobs)&&Array.isArray(snapshot.coverage)&&Array.isArray(snapshot.camera_frames),'Bounded jobs, coverage and received frames required');
 require(snapshot.jobs.every(j=>j&&typeof j.request_id==='string'&&typeof j.status==='string'&&target(j.pickup)&&target(j.delivery)&&(j.vehicle_id==null||IDS.includes(j.vehicle_id))&&(j.eta_s==null||finite(j.eta_s)&&j.eta_s>=0)),'Identified test-job endpoints and assignment required');
 require(snapshot.coverage.every(t=>target(t)&&Number.isInteger(t.visits)&&t.visits>=0&&(t.last_visit_s===null||finite(t.last_visit_s)&&t.last_visit_s>=0&&t.last_visit_s<=snapshot.model_time_s)),'Observed coverage time must not be in the future');
 require(snapshot.camera_frames.length<=IDS.length,'At most one latest received camera frame per vehicle required');
 const seen=new Set();for(const frame of snapshot.camera_frames){
  require(IDS.includes(frame.vehicle_id)&&!seen.has(frame.vehicle_id)&&typeof frame.camera_ref==='string'&&frame.camera_ref.length>0&&[frame.captured_s,frame.received_s].every(finite)&&frame.captured_s>=0&&frame.captured_s<=frame.received_s&&frame.received_s<=snapshot.model_time_s&&vector(frame.pose_xyz_mm)&&finite(frame.yaw_rad)&&typeof frame.level_id==='string','Only already received, identified camera poses may be displayed');
  validateStates(frame.states);validateLift(frame.lift);seen.add(frame.vehicle_id);
  const own=frame.states.find(s=>s.id===frame.vehicle_id);require(own.level_id===frame.level_id&&Math.abs(own.yaw_rad-frame.yaw_rad)<1e-7&&own.pose_xyz_mm.every((v,i)=>Math.abs(v-frame.pose_xyz_mm[i])<1e-7),'Camera pose differs from its historical own state');
 }
 return snapshot;
}
function endpoint(path,base){const url=new URL(path,base);require(url.origin===new URL(base).origin&&['http:','https:'].includes(url.protocol),'Same-origin local fleet endpoint required');return url.href;}
function targetKey(target){return target.level+'/'+target.area;}
function translated(before,after){
 const previous=new Map(before.map(state=>[state.id,state]));
 return after.some(state=>{
  const start=previous.get(state.id);
  return start&&start.level_id===state.level_id&&!start.attached_cabin&&!state.attached_cabin&&
   Math.hypot(state.pose_xyz_mm[0]-start.pose_xyz_mm[0],state.pose_xyz_mm[1]-start.pose_xyz_mm[1])>1e-6;
 });
}
function observedDeparture(previous,current,motion,blocked){
 if(blocked||current.paused)return false;
 if(previous?.session_id===current.session_id&&current.model_time_s>previous.model_time_s&&
    translated(previous.states,current.states))return true;
 // A page may join a running session after the first vehicle has left.
 return Boolean(motion&&translated(motion.at(motion.start_s).states,motion.at(motion.end_s).states));
}
function vehicleLocation(state, locations){
 const floor=locations?.[state.level_id];
 const level=floor?.label??state.level_id;
 const [x,y,z]=state.pose_xyz_mm;
 if(state.attached_cabin){
  const atFloor=Object.values(locations??{}).find(row=>Math.abs(row.z_mm-z)<1e-6);
  return atFloor?'Aufzug · '+atFloor.label:
   floor?'Aufzug · zwischen den Geschossen':'Aufzug · '+level;
 }
 const area=floor?.areas.find(({polygon_mm:polygon})=>{
  let inside=false;
  for(let i=0,j=polygon.length-1;i<polygon.length;j=i++){
   const [ax,ay]=polygon[j], [bx,by]=polygon[i];
   if((ay>y)!==(by>y)&&x<(bx-ax)*(y-ay)/(by-ay)+ax)inside=!inside;
  }
  return inside;
 });
 return area?level+' · '+area.label:level;
}
function compileWindow(window,observedEnd){
 if(window==null)return null;
 require(finite(window.start_s)&&finite(window.end_s)&&window.start_s>=0&&window.start_s<window.end_s&&window.end_s<=observedEnd,'Executed interpolation window must end at an observed time');
 validateLift(window.lift_initial_state);require(Array.isArray(window.lift_schedule)&&Array.isArray(window.trajectories)&&window.trajectories.length===20,'Executed source curves and lift schedule required');
 const levels=Array.isArray(window.levels)?Object.fromEntries(window.levels.map(l=>[l.id,l])):window.levels;require(levels&&Object.values(levels).every(l=>finite(l.z_mm)),'Executed source floor heights required');
 const ids=new Set();for(const row of window.trajectories){
  require(IDS.includes(row.vehicle_id)&&!ids.has(row.vehicle_id)&&Array.isArray(row.episodes)&&row.episodes.length>0,'Unique executed vehicle curves required');ids.add(row.vehicle_id);
  require(row.episodes[0].start_s<=window.start_s&&row.episodes.at(-1).end_s>=window.end_s,'Executed curves must cover the display window');
  let previous=null;for(const episode of row.episodes){require(levels[episode.level_id]&&typeof episode.mode==='string'&&typeof episode.attached_cabin==='boolean'&&finite(episode.start_s)&&finite(episode.end_s)&&episode.start_s<episode.end_s&&(previous===null||episode.start_s===previous)&&episode.points[0].time_s===episode.start_s&&episode.points.at(-1).time_s===episode.end_s&&episode.end_s<=observedEnd,'No future or discontinuous executed PVA may be displayed');previous=episode.end_s;}
 }
 for(const row of window.lift_schedule){require(['travel','doors'].includes(row.kind)&&finite(row.start_s)&&finite(row.end_s)&&row.start_s<row.end_s,'Original lift interval required');if(row.kind==='travel')require(finite(row.from_z_mm)&&finite(row.to_z_mm),'Numeric source lift endpoints required');else require(row.from_values&&row.target_values&&Object.entries(row.target_values).every(([id,v])=>finite(v)&&finite(row.from_values[id])),'Door intervals require their original start values');}
 const models=view.trajectories(window);
 return{start_s:window.start_s,end_s:window.end_s,at(t){require(finite(t)&&t>=window.start_s&&t<=window.end_s,'Display cannot extrapolate beyond executed PVA');const lift={z_mm:window.lift_initial_state.z_mm,door_values:{...window.lift_initial_state.door_values}};for(const row of window.lift_schedule){if(t<row.start_s)continue;const u=view.blend(Math.max(0,Math.min(1,(t-row.start_s)/(row.end_s-row.start_s))));if(row.kind==='travel')lift.z_mm=row.from_z_mm+(row.to_z_mm-row.from_z_mm)*u;else for(const [id,value]of Object.entries(row.target_values))lift.door_values[id]=row.from_values[id]+(value-row.from_values[id])*u;}return{lift,states:models.map(m=>m.at(t,lift))};}};
}
// Display time advances only through received, executed PVA. All wall times here are seconds.
class ExecutedPlayback {
 constructor(){
  this.time=null;
  this.windows=[];
  this.rate=null;
  this.resetTiming();
 }
 resetTiming(){
  this.sample=null;
  this.frameWall=null;
  this.frameInterval=0;
  this.factor=0;
  this.underrun=false;
 }
 get motion(){return this.windows[0]??null;}
 observe(session,modelTime,motion,wall,running,hidden=false){
  const changed=this.session!==session;
  if(changed){
   this.session=session;
   this.sessionWall=wall;
   this.resyncCount=0;
   this.resyncWall=null;
   this.windows=[];
   this.time=null;
   this.rate=null;
   this.resetTiming();
  }
  if(!running||hidden)this.resetTiming();
  else if(!this.sample)this.sample={modelTime,wall};
  else if(modelTime>this.sample.modelTime&&wall>this.sample.wall){
   const measured=Math.min(1,(modelTime-this.sample.modelTime)/(wall-this.sample.wall));
   // A slower producer threatens the available buffer immediately. Rebuild
   // confidence in a faster cadence over several genuinely new arrivals.
   const weight = measured < this.rate ? 0.85 : 0.2;
   this.rate=this.rate===null?measured:this.rate+weight*(measured-this.rate);
   this.sample={modelTime,wall};
  }
  if(!motion){
   this.windows=[];
   this.time=modelTime;
   this.factor=0;
   this.underrun=false;
   return;
  }
  if(this.time===null){
   this.time=Math.max(motion.start_s,motion.end_s-.3);
   this.frameWall=null;
  }
  if(motion.start_s<=this.time)this.windows=[motion];
  else if(hidden||!this.motion){
   // The observation preceding a background suspension or snapshot-only interval
   // has expired. Reacquire a verified view without animating across the gap.
   this.reacquire(motion,wall);
  }else{
   // Keep overlapping windows only where needed to cover earlier playback. In
   // a prolonged render stall keep the playable prefix and the newest window.
   while(this.windows.length>=2&&this.windows.at(-2).end_s>=motion.start_s)this.windows.pop();
   if(this.windows.at(-1).start_s===motion.start_s||this.windows.length>=4)this.windows.pop();
   this.windows.push(motion);
  }
  this.underrun=running&&!hidden&&this.time===motion.end_s;
 }
 reacquire(motion,wall){
  this.time=Math.max(motion.start_s,motion.end_s-.3);
  this.windows=[motion];
  this.resyncCount++;
  this.resyncWall=wall;
  this.frameWall=null;
  this.factor=0;
 }
 advance(wall,running){
  if(!running){this.resetTiming();return;}
  const interval=this.frameWall===null?0:Math.max(0,wall-this.frameWall);
  // Discard debt from an isolated long frame. A stable low refresh rate gets
  // its measured cadence, including 5-fps displays, without extra catchup.
  const elapsed=Math.min(interval,Math.max(.25,this.frameInterval));
  this.frameWall=wall;
  this.frameInterval=interval;
  if(!this.motion)return;
  const end=this.windows.at(-1).end_s;
  const headroom=end-this.time;
  // A 0.3 model-second target fits the one-second history. Adjust gently to retain
  // a reserve against late snapshots while keeping the display at or below real time.
  const correction=Math.max(-.2,Math.min(.2,(headroom-.3)*.5));
  const speed=Math.min(1,(this.rate??1)*(1+correction));
  const nextTime=Math.min(end,this.time+elapsed*speed);
  while(this.windows.length>1&&this.windows[1].start_s<=nextTime){
   if(this.windows[1].start_s>this.motion.end_s)break;
   this.windows.shift();
  }
  if(this.time===this.motion.end_s&&this.windows.length>1){
   // No received PVA connects the views. State this discontinuity explicitly
   // instead of inventing a curve or reporting it as accelerated playback.
   this.reacquire(this.windows.at(-1),wall);
   return;
  }
  this.time=Math.min(this.motion.end_s,nextTime);
  this.underrun=this.time===end;
  this.factor=this.underrun?0:speed;
 }
}
function makeCameraRenderer(bridge,renderer,payload){
 const gl=bridge.gl,framebuffer=gl.createFramebuffer(),texture=gl.createTexture(),depth=gl.createRenderbuffer(),cache=new Map();let size='';
 return function image(frame,width,height,restoreLift,session){
  const key=session+':'+frame.vehicle_id+':'+frame.camera_ref+':'+width+'x'+height+':geometry'+(bridge.geometryRevision??0);
  if(cache.has(key))return cache.get(key);
  const canvas=document.createElement('canvas');canvas.width=width;canvas.height=height;
  const active=gl.getParameter(gl.ACTIVE_TEXTURE),previousFramebuffer=gl.getParameter(gl.FRAMEBUFFER_BINDING);gl.activeTexture(gl.TEXTURE0);const previousTexture=gl.getParameter(gl.TEXTURE_BINDING_2D);
  try{
   gl.bindFramebuffer(gl.FRAMEBUFFER,framebuffer);
   if(size!==width+'x'+height){gl.bindTexture(gl.TEXTURE_2D,texture);gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,width,height,0,gl.RGBA,gl.UNSIGNED_BYTE,null);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);gl.framebufferTexture2D(gl.FRAMEBUFFER,gl.COLOR_ATTACHMENT0,gl.TEXTURE_2D,texture,0);gl.bindRenderbuffer(gl.RENDERBUFFER,depth);gl.renderbufferStorage(gl.RENDERBUFFER,gl.DEPTH_COMPONENT16,width,height);gl.framebufferRenderbuffer(gl.FRAMEBUFFER,gl.DEPTH_ATTACHMENT,gl.RENDERBUFFER,depth);size=width+'x'+height;require(gl.checkFramebufferStatus(gl.FRAMEBUFFER)===gl.FRAMEBUFFER_COMPLETE,'Active camera framebuffer incomplete');}
   gl.bindTexture(gl.TEXTURE_2D,previousTexture===texture?null:previousTexture);bridge.applyLift(frame.lift);
   bridge.capture(frame,width,height,()=>renderer.draw(bridge.cameraMatrix(width/height),frame.states),payload.vehicle_mesh.scene.camera_frame,payload.camera_presentation.fov_deg);
   const pixels=new Uint8Array(width*height*4),flipped=new Uint8ClampedArray(pixels.length);gl.readPixels(0,0,width,height,gl.RGBA,gl.UNSIGNED_BYTE,pixels);
   for(let y=0;y<height;y++)flipped.set(pixels.subarray(y*width*4,(y+1)*width*4),(height-y-1)*width*4);
   canvas.getContext('2d').putImageData(new ImageData(flipped,width,height),0,0);
  }finally{bridge.applyLift(restoreLift);gl.bindFramebuffer(gl.FRAMEBUFFER,previousFramebuffer);gl.bindTexture(gl.TEXTURE_2D,previousTexture);gl.activeTexture(active);}
  cache.set(key,canvas);while(cache.size>60)cache.delete(cache.keys().next().value);return canvas;
 };
}
async function mount(bridge,payload){
 const config=payload.live;require(config&&typeof config==='object','Local active-fleet endpoint configuration required');
 const base=location.href,urls={state:endpoint(config.state_url??'/api/state',base),jobs:endpoint(config.jobs_url??'/api/jobs',base),control:endpoint(config.control_url??'/api/control',base)};
 let transport=config.transport??(config.worker&&globalThis.__bf01EarlyTransport?.manifest_sha256===config.worker.manifest.sha256?globalThis.__bf01EarlyTransport.transport:null);
 if(config.worker&&!transport){require(globalThis.BuildingFleetBrowserTransport?.create,'Live browser engine transport is unavailable');transport=globalThis.BuildingFleetBrowserTransport.create(config.worker);}
 const panel=document.getElementById('building-fleet-panel');require(panel,'Fleet panel missing');panel.hidden=false;panel.dataset.live='true';
 const notice=document.createElement('div');notice.className='bf-live-status';notice.style.cssText='position:absolute;top:76px;left:12px;right:12px;margin:0;padding:8px 12px;background:#f5f7f4ee;color:#173d37;border:1px solid #aebdb6;border-radius:8px;z-index:3;pointer-events:none;font:14px sans-serif';
 const noticeText=document.createElement('div'),progress=document.createElement('progress');
 progress.id='bf01-startup-progress';progress.setAttribute('aria-label','Start der Patrouille');
 progress.style.cssText='width:min(100%,32rem);height:10px;accent-color:#2e5146';
 notice.append(noticeText,progress);bridge.stage.append(notice);
 panel.innerHTML='<h2>BF01 · aktive Patrouille</h2><p>20 leere Transporter · fortlaufende Erkundung mit priorisierten Testaufträgen. Kamerabilder sind lokale synthetische Ansichten empfangener Modellposen; kein Video-Netzwerklasttest. Testabholung und Testabgabe sind Raumankünfte ohne Probe oder Roboterübergabe.</p><div class="bf-controls"><button data-bf="play" disabled>Pause</button><output data-bf="clock">Initialisierung</output><select data-bf="vehicle" aria-label="Fahrzeug"></select><button data-bf="follow">Fahrzeug folgen</button></div><p data-bf="status" role="status">Patrouille wird vorbereitet …</p><form data-bf="request"><label>Testabholung <select data-bf="pickup" aria-label="Testabholung" required></select></label> <label>Testabgabe <select data-bf="delivery" aria-label="Testabgabe" required></select></label> <button data-bf="submit" type="submit" disabled>Transport anfordern</button></form><p data-bf="request-status" role="status"></p><p data-bf="coverage"></p><ul data-bf="targets"></ul><h3>Testaufträge</h3><ol data-bf="jobs"></ol><div class="bf-table"><table><thead><tr><th>Fahrzeug</th><th>Beobachteter Zustand</th><th>Auftrag</th></tr></thead><tbody data-bf="rows"></tbody></table></div><p data-bf="camera-note">Noch keine empfangenen Kameraaufnahmen.</p>';
 const q=name=>panel.querySelector('[data-bf="'+name+'"]');for(const id of IDS){const option=document.createElement('option');option.value=option.textContent=id;q('vehicle').append(option);}
 function startupNotice({detail,value,max}){
  if(q('status').textContent!==detail)q('status').textContent=detail;
  noticeText.textContent=detail;progress.hidden=false;
  if(finite(value)&&finite(max)&&max>0){progress.max=max;progress.value=value;}
  else progress.removeAttribute('value');
  progress.setAttribute('aria-valuetext',detail);
 }
 startupNotice({detail:'Gebäude bereit · Live-Patrouille wird vorbereitet …'});
 if(config.worker){const note=document.createElement('p');note.textContent='Eigene Live-Simulation in diesem Browser. Beim Schließen endet diese Sitzung; beim nächsten Öffnen startet eine neue Patrouille.';panel.querySelector('p').after(note);}
 const renderer=view.makeRenderer(bridge,payload.vehicle_mesh),cameraImage=makeCameraRenderer(bridge,renderer,payload),labels=document.createElement('div');labels.className='bf-labels';bridge.stage.append(labels);
 const labelNodes=new Map(IDS.map(id=>{const node=document.createElement('span');node.textContent=id;labels.append(node);return[id,node];}));
 let snapshot=null,selected='BF01',follow=false,stopped=false,connected=false,lastResponse=0,pendingRequest=null,requestCount=0,targetsKey='',polling=false,manualPause=false,doorPause=false,controlPending=false,runtimeError=null,queuedControl=null,lastCommandError='';
 let departed=false;
 const playback=new ExecutedPlayback();
 let locations=new Map();
 const copy=value=>JSON.parse(JSON.stringify(value));
 const requestId=()=>globalThis.crypto?.randomUUID?.()??('browser-'+Date.now()+'-'+(++requestCount));
 const blockers=()=>snapshot?.room_route_object_ids?.filter(id=>!bridge.doorOpen(id))??[];
 function display(){return playback.motion?playback.motion.at(playback.time):snapshot?{lift:snapshot.lift,states:snapshot.states}:null;}
 function positionLabels(observed){labels.hidden=Boolean(payload.presentation?.atrium_monitors&&!follow&&bridge.atMonitorWall());for(const state of observed.states){const node=labelNodes.get(state.id),point=bridge.projectPoint(state.pose_xyz_mm.map((v,i)=>v+(i===2?payload.vehicle_mesh.scene.bounds_mm.max[2]:0)));node.hidden=!point?.visible;if(point){node.style.left=point.x*100+'%';node.style.top=point.y*100+'%';}}if(follow)bridge.follow(observed.states.find(state=>state.id===selected));}
 function setTargets(targets){const key=targets.map(targetKey).join('|');if(key===targetsKey)return;targetsKey=key;for(const field of ['pickup','delivery']){q(field).replaceChildren(...targets.map(target=>{const option=document.createElement('option');option.value=targetKey(target);option.textContent=view.targetLabel(target);return option;}));}if(targets.length>1)q('delivery').selectedIndex=1;}
 setTargets(config.targets??[]);
 const vehicleIdFromCamera=id=>id.slice('BF01.'.length,-'.Overview'.length);
 function followVehicle(id){
  require(IDS.includes(id),'Unknown vehicle');
  if(!follow)bridge.beginFollow();
  follow=true;
  selected=id;
  q('vehicle').value=id;
  q('follow').textContent='Folgemodus beenden';
  paint();
 }
 function stopFollowing(){
  follow=false;
  bridge.endFollow();
  q('follow').textContent='Fahrzeug folgen';
  paint();
 }
 function connectWall(){
  if(!payload.presentation?.atrium_monitors)return;
  bridge.connectMonitorFeeds({
   kind:'received_fleet_live',
   camera_ids:IDS.map(id=>'BF01.'+id+'.Overview'),
   clock:()=>snapshot?.model_time_s??0,
   locationAt:id=>locations.get(vehicleIdFromCamera(id))??null,
   followVehicle:id=>followVehicle(vehicleIdFromCamera(id)),
   frameAt:(id,width,height)=>{
    if(!snapshot)return null;
    const vehicle=vehicleIdFromCamera(id),frame=snapshot.camera_frames.find(f=>f.vehicle_id===vehicle);
    if(!frame||bridge.visualLevelReady?.(frame.level_id)===false)return null;
    const capturedVehicle=frame.states.find(state=>state.id===vehicle);
    return {canvas:cameraImage(frame,width,height,display().lift,snapshot.session_id),
     vehicle_id:vehicle,camera_ref:frame.camera_ref,captured_s:frame.captured_s,
     received_s:frame.received_s,program_time_s:snapshot.model_time_s,level_id:frame.level_id,
     location:vehicleLocation(capturedVehicle,payload.locations),session_id:snapshot.session_id,
     geometry_revision:bridge.geometryRevision??0};
   },
  });
 }
 function clockLabel(){
  q('clock').textContent=snapshot.model_time_s.toFixed(3)+' s Modellzeit · '+(performance.now()/1000-playback.sessionWall).toFixed(1)+' s Wandzeit · Anzeige '+playback.time.toFixed(3)+' s · Wiedergabe ×'+playback.factor.toFixed(2)+' Echtzeit';
 }
 function statusLabel(blocks){
  const age=(performance.now()-lastResponse)/1000;
  const reacquired=playback.resyncWall!==null&&performance.now()/1000-playback.resyncWall<1;
  const hold=runtimeError?'Patrouille angehalten · '+runtimeError:!connected?'Verbindung unterbrochen · letzte ausgeführte Positionen bleiben stehen':blocks.length?'Fahrwegtür gesperrt · Patrouille wird angehalten':snapshot.paused?'Patrouille pausiert':null;
  if(!departed){
   startupNotice({detail:hold??(snapshot.phase==='own_drive_prepare'&&snapshot.vehicle_id?'Erste Fahrbahn für '+snapshot.vehicle_id+' wird geprüft …':'Flotte bereit · wartet auf die erste Patrouillenfahrt …')});
   return;
  }
  progress.hidden=true;
  q('status').textContent=hold??(reacquired?'Anzeige nach einer Lücke im empfangenen Zeitfenster neu synchronisiert':playback.underrun?'Simulation rechnet · wartet auf den nächsten ausgeführten Schritt':snapshot.phase==='own_drive_prepare'?'Fahrbahn für '+snapshot.vehicle_id+' wird vorbereitet · letzte ausgeführte Positionen bleiben sichtbar':'Patrouille aktiv · '+age.toFixed(1)+' s seit letzter Zustandsmeldung');
  noticeText.textContent='Live · '+snapshot.model_time_s.toFixed(2)+' s · '+q('status').textContent;
 }
 function paint(){
  if(!snapshot)return;
  const observed=display();bridge.applyLift(observed.lift);const blocks=blockers();
  clockLabel();statusLabel(blocks);
  q('play').disabled=controlPending||!connected||Boolean(blocks.length);q('play').textContent=snapshot.paused?'Fortsetzen':'Pause';q('submit').disabled=!connected||!snapshot.targets.length;
  q('coverage').textContent='Gemeldete Zielbesuche: '+snapshot.coverage.filter(t=>t.visits>0).length+' / '+snapshot.targets.length;
  q('targets').replaceChildren(...snapshot.coverage.map(target=>{const li=document.createElement('li');li.textContent=view.targetLabel(target)+' · '+(target.last_visit_s==null?'noch nicht besucht':Math.max(0,snapshot.model_time_s-target.last_visit_s).toFixed(1)+' s seit letztem Besuch')+' · '+target.visits+' Besuche';return li;}));
  q('jobs').replaceChildren(...snapshot.jobs.slice(-30).map(job=>{const li=document.createElement('li'),winner=job.vehicle_id??job.winner?.vehicle_id,eta=job.eta_s??job.winner?.eta_s;li.textContent=job.request_id+' · '+view.targetLabel(job.pickup)+' → '+view.targetLabel(job.delivery)+' · '+job.status+(winner?' · '+winner:' · wartet auf verfügbares Fahrzeug')+(finite(eta)?' · geschätzte Abholankunft '+eta.toFixed(1)+' s':'');return li;}));
  q('rows').replaceChildren(...snapshot.states.map(state=>{
   const row=document.createElement('tr'),failure=snapshot.background_preparation?.failures?.[state.id];
   let status=view.stateLabel(state.controller_mode??state.mode);
   if(failure)status+=' · Abschnittsprüfung abgelehnt · '+failure;
   else if(finite(state.private_departure_horizon_mm))status=state.hold_condition==='observed_corridor_handover'?'Wartet im eigenen Depot auf die Flurfreigabe':'Geprüfte Parallelausfahrt im eigenen Depot';
   else if(state.queue_position)status='Warteschlange · Platz '+state.queue_position+(state.resource_holder?' · belegt durch '+state.resource_holder:'');
   else if(state.hold_reason==='await_checked_continuation')status='Wartet auf geprüfte Weiterfahrt';
   for(const value of [state.id,locations.get(state.id)+' · '+status,state.job_id??state.mission_id??'Patrouille']){
    const cell=document.createElement('td');cell.textContent=value;row.append(cell);
   }
   return row;
  }));
  q('camera-note').textContent=snapshot.camera_frames.length+' / 20 empfangene synthetische Kameraansichten · gemeinsame Modellzeit';
  const commandError=snapshot.command_errors?.at(-1);if(commandError){const key=commandError.request_id+':'+commandError.error;if(key!==lastCommandError){lastCommandError=key;q('request-status').textContent='Testauftrag abgelehnt · '+commandError.request_id+' · '+commandError.error;}}
  positionLabels(observed);bridge.syncMonitorFeeds?.();bridge.requestRender();
 }
 function receive(value){
  if(value.status==='starting'){
   if(!snapshot)startupNotice(globalThis.BuildingFleetBrowserTransport?.startupDisplay(value)??{detail:'Live-Patrouille wird vorbereitet …'});
   return;
  }
  if(value.status==='error'){connected=false;playback.resetTiming();runtimeError=value.error??'Laufzeitfehler';if(snapshot)paint();else startupNotice({detail:'Patrouille angehalten · '+runtimeError});return;}
  validateSnapshot(value);bridge.observeVisualGeometry?.(value);
  if(snapshot&&snapshot.session_id===value.session_id&&value.model_time_s<snapshot.model_time_s)return;
  const previous=snapshot,changed=!previous||previous.session_id!==value.session_id,nextMotion=compileWindow(value.executed_window,value.model_time_s);snapshot=value;
  if(changed)departed=false;
  if(!departed)departed=observedDeparture(connected?previous:null,value,nextMotion,Boolean(blockers().length)||manualPause);
  locations=new Map(value.states.map(state=>[state.id,vehicleLocation(state,payload.locations)]));
  connected=true;runtimeError=null;lastResponse=performance.now();
  playback.observe(value.session_id,value.model_time_s,nextMotion,lastResponse/1000,!snapshot.paused&&!blockers().length,document.hidden);
  setTargets(snapshot.targets);if(changed)connectWall();paint();
 }
 async function request(url,body){if(transport)return transport.request(url,body);const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),5000);try{const response=await fetch(url,{method:body===undefined?'GET':'POST',headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body),cache:'no-store',credentials:'same-origin',signal:controller.signal});const value=await response.json();if(!response.ok)throw Error(value.error??('HTTP '+response.status));return value;}finally{clearTimeout(timeout);}}
 async function control(action){if(action==='resume'&&blockers().length){q('status').textContent='Fortsetzen gesperrt · zuerst alle Fahrwegtüren öffnen';return;}if(controlPending){queuedControl=action;return;}controlPending=true;paint();try{const value=await request(urls.control,{action});if(value.format==='solidcraftbot.building-fleet-live-snapshot/1')receive(value);else await poll();}catch(error){connected=false;playback.resetTiming();q('status').textContent='Steuerung nicht bestätigt · '+error.message;}finally{controlPending=false;paint();if(queuedControl){const next=queuedControl;queuedControl=null;await control(next);}}}
 function userControl(action){if(action==='resume'&&blockers().length)return control(action);manualPause=action==='pause';if(action==='resume')doorPause=false;return control(action);}
 async function poll(){if(polling||stopped)return;polling=true;try{receive(await request(urls.state));}catch(error){connected=false;playback.resetTiming();const detail='Verbindung unterbrochen · '+error.message+' · keine Bewegungsvorhersage';if(departed){q('status').textContent=detail;noticeText.textContent=detail;}else startupNotice({detail});}finally{polling=false;}}
 async function cycle(){if(stopped)return;await poll();const blocks=blockers();if(snapshot&&connected&&!controlPending){if(blocks.length&&!snapshot.paused){doorPause=true;await control('pause');}else if(!blocks.length&&doorPause&&!manualPause){doorPause=false;await control('resume');}}setTimeout(cycle,Math.max(50,Math.min(2000,config.poll_interval_ms??200)));}
 q('play').onclick=()=>{if(snapshot)return userControl(snapshot.paused?'resume':'pause');};
 q('vehicle').onchange=()=>{selected=q('vehicle').value;paint();};
 q('follow').onclick=()=>{if(follow)stopFollowing();else followVehicle(selected);};
 q('request').onsubmit=async event=>{event.preventDefault();if(!snapshot)return;const pickup=snapshot.targets.find(t=>targetKey(t)===q('pickup').value),delivery=snapshot.targets.find(t=>targetKey(t)===q('delivery').value);if(!pickup||!delivery)return;const signature=targetKey(pickup)+'→'+targetKey(delivery);if(!pendingRequest||pendingRequest.signature!==signature)pendingRequest={signature,body:{request_id:requestId(),pickup:{level:pickup.level,area:pickup.area},delivery:{level:delivery.level,area:delivery.area}}};q('submit').disabled=true;try{const value=await request(urls.jobs,pendingRequest.body);q('request-status').textContent=(value.status==='queued_for_engine'?'Testauftrag vorgemerkt · ':'Testauftrag bestätigt · ')+pendingRequest.body.request_id;pendingRequest=null;if(value.format==='solidcraftbot.building-fleet-live-snapshot/1')receive(value);else await poll();}catch(error){q('request-status').textContent='Bestätigung fehlt · erneuter Klick wiederholt dieselbe Auftragskennung · '+error.message;}finally{q('submit').disabled=!connected;}};
 const hooks={get following(){return follow;},draw:matrix=>{const observed=display();if(observed){bridge.applyLift(observed.lift);renderer.draw(matrix,observed.states);}}};bridge.activate(hooks);if(payload.presentation?.start_stop)bridge.startAt(payload.presentation.start_stop);
 window.__buildingFleet=Object.freeze({get ready(){return Boolean(snapshot)&&!panel.dataset.error;},get live(){return true;},get execution_backend(){return config.worker?'browser':'local_service';},get time_s(){return snapshot?.model_time_s??0;},get display_time_s(){return playback.time;},get playback_factor(){return playback.factor;},get buffer_underrun(){return playback.underrun;},get display_resync_count(){return playback.resyncCount??0;},get states(){return snapshot?copy(display().states):[];},get snapshot(){return snapshot?copy(snapshot):null;},get connected(){return connected;},get frozen(){return !connected||Boolean(snapshot?.paused)||Boolean(blockers().length);},get instance_count(){return snapshot?.states.length??0;},get renderer_stats(){return renderer.stats;},pause:()=>userControl('pause'),play:()=>userControl('resume'),poll,follow:followVehicle,stopFollowing,dispose:()=>{stopped=true;document.removeEventListener('visibilitychange',resetFrame);transport?.dispose();}});
 function resetFrame(){playback.resetTiming();}
 document.addEventListener('visibilitychange',resetFrame);
 function animate(now){
  if(stopped)return;
  if(snapshot){
   const blocks=blockers(),wasUnderrun=playback.underrun,resyncCount=playback.resyncCount;
   const running=connected&&!snapshot.paused&&!blocks.length&&!document.hidden;
   playback.advance(now/1000,running);
   if(running&&playback.motion){
    const observed=display();bridge.applyLift(observed.lift);positionLabels(observed);bridge.requestRender();
   }
   clockLabel();if(playback.underrun!==wasUnderrun||resyncCount!==playback.resyncCount)statusLabel(blocks);
  }
  requestAnimationFrame(animate);
 }
 cycle();requestAnimationFrame(animate);return hooks;
}
return{IDS,validateStates,validateLift,validateSnapshot,compileWindow,ExecutedPlayback,endpoint,targetKey,vehicleLocation,mount};
});
