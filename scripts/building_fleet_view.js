/* BF01 compiled-program playback. No route, controller, resource or dispatch policy. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.BuildingFleetView=api;})(typeof globalThis!=='undefined'?globalThis:this,function(){
'use strict';
const F=['pose_mm_rad','velocity_mm_rad_s','acceleration_mm_rad_s2'];
const finite=n=>typeof n==='number'&&Number.isFinite(n);
function require(ok,message){if(!ok)throw Error(message);}
function blend(u){return u*u*u*(10+u*(-15+6*u));}
function intervalIndex(times,t){let lo=0,hi=times.length;while(lo<hi){const mid=(lo+hi)>>1;if(times[mid]<=t)lo=mid+1;else hi=mid;}return Math.max(0,lo-1);}
function compileCurve(points){
 require(Array.isArray(points)&&points.length>=2,'Compiled PVA points required');
 for(let i=0;i<points.length;i++){const p=points[i];require(finite(p.time_s)&&F.every(k=>Array.isArray(p[k])&&p[k].length===3&&p[k].every(finite)),'Finite planar PVA required');if(i)require(p.time_s>points[i-1].time_s,'Increasing PVA time required');}
 const times=points.map(p=>p.time_s),segments=points.slice(1).map((b,i)=>{const a=points[i],h=b.time_s-a.time_s;return [0,1,2].map(k=>{const p=a[F[0]][k],d=b[F[0]][k]-p,v=a[F[1]][k]*h,w=b[F[1]][k]*h,A=a[F[2]][k]*h*h,B=b[F[2]][k]*h*h;return[p,v,A/2,10*d-6*v-4*w-1.5*A+.5*B,-15*d+8*v+7*w+1.5*A-B,6*d-3*v-3*w-.5*A+.5*B];});});
 return function(t){require(finite(t),'Finite playback time required');const i=Math.min(points.length-2,intervalIndex(times,t)),a=points[i],b=points[i+1],u=Math.max(0,Math.min(1,(t-a.time_s)/(b.time_s-a.time_s)));return segments[i].map(c=>c.reduceRight((v,x)=>v*u+x,0));};
}
function liftAt(program,t){
 const initial=program.lift_initial_state;require(initial&&finite(initial.z_mm)&&typeof initial.door_values==='object','Compiled initial lift pose required');let z=initial.z_mm;const values={...initial.door_values};
 for(const row of program.lift_schedule){if(t<row.start_s)break;require(row.end_s>row.start_s,'Positive compiled lift duration required');const u=blend(Math.max(0,Math.min(1,(t-row.start_s)/(row.end_s-row.start_s))));if(row.kind==='travel')z=row.from_z_mm+(row.to_z_mm-row.from_z_mm)*u;else if(row.kind==='doors'){for(const [id,target]of Object.entries(row.target_values)){require(finite(values[id])&&finite(target),'Compiled numeric lift door endpoints required');values[id]+=(target-values[id])*u;}}else throw Error('Unknown compiled lift segment');}
 return{z_mm:z,door_values:values};
}
function trajectories(program){
 const levels=Array.isArray(program.levels)?Object.fromEntries(program.levels.map(l=>[l.id,l])):program.levels;
 return program.trajectories.map(row=>({id:row.vehicle_id,starts:row.episodes.map(e=>e.start_s),episodes:row.episodes.map(e=>({...e,curve:compileCurve(e.points)})),at(t,lift){const e=this.episodes[Math.min(this.episodes.length-1,intervalIndex(this.starts,t))],p=e.curve(t);return{id:this.id,pose_xyz_mm:[p[0],p[1],e.attached_cabin?lift.z_mm:levels[e.level_id].z_mm],yaw_rad:p[2],level_id:e.level_id,mode:e.mode,attached_cabin:e.attached_cabin};}}));
}
class ReceivedProjection{
 constructor(messages){this.messages=messages.slice().sort((a,b)=>a.received_s-b.received_s||a.vehicle_id.localeCompare(b.vehicle_id)||a.seq-b.seq);this.reset();}
 reset(){this.vehicles={};this.coverage=new Set();this.events=[];this.sequence={};this.duplicates=0;this.cursor=0;this.time=-Infinity;}
 at(t,copy=true){require(finite(t),'Finite received-message clock required');if(t<this.time)this.reset();this.time=t;
  while(this.cursor<this.messages.length&&this.messages[this.cursor].received_s<=t){const m=this.messages[this.cursor++];if(m.seq<=(this.sequence[m.vehicle_id]||0)){this.duplicates++;continue;}this.sequence[m.vehicle_id]=m.seq;
   const row=this.vehicles[m.vehicle_id]||(this.vehicles[m.vehicle_id]={last_received_s:null,last_sent_s:null,connected:true,heartbeat:null,perception:null,mission:null,last_event:null});row.last_received_s=m.received_s;row.last_sent_s=m.sent_s;
   if(m.kind==='heartbeat')row.heartbeat=m.payload;else if(m.kind==='perception')row.perception=m.payload;else if(m.kind==='event'){this.events.push(m);const p=m.payload;row.last_event=p;if(p.event==='comm_lost')row.connected=false;if(p.event==='comm_restored')row.connected=true;if(p.event==='mission_assigned')row.mission=p.details;if(p.event==='inspection_completed')this.coverage.add(p.details.level+'/'+p.details.area);}
  }
  const vehicles=Object.fromEntries(Object.entries(this.vehicles).map(([id,row])=>[id,{...row,message_age_s:Math.max(0,t-row.last_sent_s)}]));
  const snapshot={vehicles,events:this.events,coverage:[...this.coverage].sort().map(key=>{const i=key.indexOf('/');return{level:key.slice(0,i),area:key.slice(i+1)};}),duplicates:this.duplicates};
  return copy?JSON.parse(JSON.stringify(snapshot)):snapshot;
 }
}
function controlRoom(messages,t){return new ReceivedProjection(messages).at(t);}
function targetLabel(target){return target.basis==='template_area_use_unconfirmed'?`${target.level} · Vorlagefläche ${target.area} (Nutzung unbestätigt)`:`${target.level} · ${target.area}`;}
function stateLabel(mode){return({capacity_wait:'wartet auf zulässigen Folgeauftrag',capacity_home:'vorläufig am eigenen Stellplatz'})[mode]||mode;}
function receivedLift(events){const vehicles={};let last=null;for(const message of events){if(message.payload.event.startsWith('lift_')){vehicles[message.vehicle_id]={event:message.payload.event,details:message.payload.details,received_s:message.received_s};last=message;}}return{queue:Object.entries(vehicles).filter(([,v])=>['lift_call','lift_slot_assigned'].includes(v.event)).map(([id,v])=>({vehicle_id:id,...v})),last};}
function validatePreview(program,preview,sourceHash){
 const hash=v=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v);
 require(program.complete===false&&preview?.format==='solidcraftbot.building-fleet-experimental-preview/1','Explicit experimental partial-preview contract required');
 require(finite(preview.recorded_end_s)&&preview.recorded_end_s===program.duration_s&&preview.playback_end_s===program.duration_s,'Experimental preview endpoint differs from recorded program');
 require(hash(sourceHash)&&preview.program_sha256===sourceHash&&preview.original_program_sha256===sourceHash&&hash(preview.playback_sha256),'Experimental preview must bind exact original and playback hashes');
 require(preview.interruption&&typeof preview.interruption.path==='string'&&hash(preview.interruption.sha256),'Original interruption reference required');
 const keys=['full_mission_coverage_verified','native_full_program_verified','independent_export_verified','hardware_or_real_safety_qualified'];
 require(preview.qualification&&keys.every(key=>preview.qualification[key]===false),'Experimental preview cannot claim complete-run qualification');
 return preview;
}
function validateProgram(program,preview=null,sourceHash=null){
 require(program.format==='solidcraftbot.building-fleet-program/1'&&(program.complete===true||preview!==null),'Complete compiled fleet program required');
 if(preview!==null)validatePreview(program,preview,sourceHash);
 require(finite(program.duration_s)&&program.duration_s>0,'Positive compiled model duration required');
 require(Array.isArray(program.trajectories)&&program.trajectories.length===20,'Complete20-vehicle program required');
 const ids=new Set(program.trajectories.map(t=>t.vehicle_id));require(ids.size===20&&Array.from({length:20},(_,i)=>'BF'+String(i+1).padStart(2,'0')).every(id=>ids.has(id)),'Exactly BF01..BF20 required');
 require(Array.isArray(program.received_messages)&&program.camera_captures&&Array.isArray(program.room_route_object_ids)&&Array.isArray(program.targets),'Compiled received telemetry/captures/source targets/route-door IDs required');
 const levels=Array.isArray(program.levels)?Object.fromEntries(program.levels.map(l=>[l.id,l])):program.levels;require(levels&&Object.values(levels).every(l=>finite(l.z_mm)),'Source floor heights required');
 for(const row of program.trajectories){require(Array.isArray(row.episodes)&&row.episodes.length>0,'Compiled episodes required');let previous=0;for(const e of row.episodes){require(levels[e.level_id]&&finite(e.start_s)&&finite(e.end_s)&&e.start_s===previous&&e.end_s>e.start_s&&typeof e.attached_cabin==='boolean','Continuous source-bound episode coverage required');require(Array.isArray(e.points)&&e.points.length>1&&e.points[0].time_s===e.start_s&&e.points[e.points.length-1].time_s===e.end_s,'Episode PVA must cover its interval');previous=e.end_s;}require(previous===program.duration_s,'Every vehicle must cover the full model duration');}
 const owners={};for(const m of program.received_messages){require(ids.has(m.vehicle_id)&&Number.isInteger(m.seq)&&m.seq>0&&finite(m.received_s)&&finite(m.sent_s)&&m.received_s>=m.sent_s,'Valid received message identity/time required');
  if(m.kind==='perception'){const p=m.payload,capture=program.camera_captures[p.camera_ref];require(capture,'Missing delivered camera capture record');require(finite(capture.captured_s)&&capture.captured_s<=m.sent_s&&capture.captured_s===p.captured_s&&capture.level_id===p.level&&Array.isArray(capture.pose_xyz_mm)&&capture.pose_xyz_mm.length===3&&capture.pose_xyz_mm.every(finite)&&finite(capture.yaw_rad),'Source own capture record required');require(Array.isArray(p.pose_mm)&&p.pose_mm.length===3&&p.pose_mm.every(finite)&&[capture.pose_xyz_mm[0],capture.pose_xyz_mm[1],capture.yaw_rad].every((v,i)=>Math.abs(v-p.pose_mm[i])<1e-7),'Capture pose must equal the sender-reported pose');require(!owners[p.camera_ref]||owners[p.camera_ref]===m.vehicle_id,'Camera reference belongs to another vehicle');owners[p.camera_ref]=m.vehicle_id;}
 }
 liftAt(program,0);return program;
}
async function decodeProgram(text,expectedHash=null){const bytes=Uint8Array.from(atob(text),c=>c.charCodeAt(0));require(typeof DecompressionStream==='function','Browser gzip decompression required');const raw=await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))).arrayBuffer();if(expectedHash!==null){require(globalThis.crypto?.subtle,'Browser SHA-256 verification required');const actual=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',raw)),v=>v.toString(16).padStart(2,'0')).join('');require(actual===expectedHash,'Experimental playback bytes differ from bound hash');}return JSON.parse(new TextDecoder().decode(raw));}
function makeRenderer(bridge,mesh){
 const gl=bridge.gl,scene=mesh.scene,decode=(text,C)=>{const raw=Uint8Array.from(atob(text),c=>c.charCodeAt(0));return new C(raw.buffer);};
 const positions=decode(scene.positions_base64,Float32Array);for(let i=0;i<positions.length;i++)positions[i]/=1000;
 const normals=decode(scene.normals_base64,Float32Array),indices=decode(scene.indices_base64,Uint32Array);
 const shader=(type,source)=>{const s=gl.createShader(type);gl.shaderSource(s,source);gl.compileShader(s);require(gl.getShaderParameter(s,gl.COMPILE_STATUS),gl.getShaderInfoLog(s));return s;};
 const p=gl.createProgram();gl.attachShader(p,shader(gl.VERTEX_SHADER,`#version 300 es
 precision highp float;in vec3 position;in vec3 normal;in mat4 instanceTransform;uniform mat4 vp;out vec3 n;void main(){n=mat3(instanceTransform)*normal;gl_Position=vp*instanceTransform*vec4(position,1.);}`));gl.attachShader(p,shader(gl.FRAGMENT_SHADER,`#version 300 es
 precision highp float;in vec3 n;uniform vec4 color;out vec4 outColor;void main(){float light=.65+.35*max(dot(normalize(n),normalize(vec3(-.45,-.35,1.))),0.);outColor=vec4(color.rgb*light,color.a);}`));gl.linkProgram(p);require(gl.getProgramParameter(p,gl.LINK_STATUS),gl.getProgramInfoLog(p));
 const vao=gl.createVertexArray();gl.bindVertexArray(vao);function attribute(name,values){const b=gl.createBuffer(),location=gl.getAttribLocation(p,name);gl.bindBuffer(gl.ARRAY_BUFFER,b);gl.bufferData(gl.ARRAY_BUFFER,values,gl.STATIC_DRAW);gl.enableVertexAttribArray(location);gl.vertexAttribPointer(location,3,gl.FLOAT,false,0,0);}
 attribute('position',positions);attribute('normal',normals);const element=gl.createBuffer();gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,element);gl.bufferData(gl.ELEMENT_ARRAY_BUFFER,indices,gl.STATIC_DRAW);const instances=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,instances);gl.bufferData(gl.ARRAY_BUFFER,20*16*4,gl.DYNAMIC_DRAW);const location=gl.getAttribLocation(p,'instanceTransform');for(let i=0;i<4;i++){gl.enableVertexAttribArray(location+i);gl.vertexAttribPointer(location+i,4,gl.FLOAT,false,64,i*16);gl.vertexAttribDivisor(location+i,1);}
 const vp=gl.getUniformLocation(p,'vp'),color=gl.getUniformLocation(p,'color');let draws=0,lastInstanceCount=0;
 return{draw(matrix,states){lastInstanceCount=states.length;const transforms=new Float32Array(states.length*16);states.forEach((s,i)=>{const c=Math.cos(s.yaw_rad),v=Math.sin(s.yaw_rad),[x,y,z]=s.pose_xyz_mm;transforms.set([c,v,0,0,-v,c,0,0,0,0,1,0,x/1000,y/1000,z/1000,1],i*16);});gl.useProgram(p);gl.bindVertexArray(vao);gl.bindBuffer(gl.ARRAY_BUFFER,instances);gl.bufferSubData(gl.ARRAY_BUFFER,0,transforms);gl.uniformMatrix4fv(vp,false,matrix);for(const group of scene.groups){gl.uniform4fv(color,[...group.color,group.opacity]);if(group.opacity<.99){gl.enable(gl.BLEND);gl.blendFunc(gl.SRC_ALPHA,gl.ONE_MINUS_SRC_ALPHA);gl.depthMask(false);}else{gl.disable(gl.BLEND);gl.depthMask(true);}gl.drawElementsInstanced(gl.TRIANGLES,group.index_count,gl.UNSIGNED_INT,group.index_start*4,states.length);draws++;}gl.depthMask(true);gl.disable(gl.BLEND);},get draws(){return draws;},get stats(){return{draw_calls:draws,last_instance_count:lastInstanceCount,native_mesh_groups:scene.groups.length};}};
}
async function mount(bridge,payload){
 const preview=payload.experimental_preview??null,program=validateProgram(await decodeProgram(payload.program_gzip_base64,preview?.playback_sha256??null),preview,payload.program_source_sha256),models=trajectories(program),projection=new ReceivedProjection(program.received_messages),renderer=makeRenderer(bridge,payload.vehicle_mesh),panel=document.getElementById('building-fleet-panel');require(panel,'Fleet panel missing');
 panel.hidden=false;panel.dataset.reducedMotion=String(Boolean(globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches));const duration=program.duration_s||Math.max(...program.trajectories.flatMap(t=>t.episodes.map(e=>e.end_s)));let time=0,playing=false,factor=1,selected='BF01',follow=false,frozen=false,last=null,cameraTick=-Infinity,mosaicTick=-Infinity,mosaicIndex=0,lastTableKey='',lastEventKey='',lastTargetKey='';
 const labels=document.createElement('div');labels.className='bf-labels';bridge.stage.append(labels);const labelNodes=models.map(m=>{const label=document.createElement('span');label.textContent=m.id;labels.append(label);return label;});
 panel.innerHTML='<h2>BF01 · synthetische Gebäudeflotte</h2><p>20 leere Transporter · Mosaik: ein Bild pro Sekunde im Rundlauf · Kameraaufnahmen sind synthetische Darstellungen, keine reale Kamera oder Bilderkennung. Freie Rundgangkamera ist kein Hindernis.</p><div class="bf-controls"><button data-bf="play">Abspielen</button><input data-bf="time" type="range" min="0" max="'+duration+'" step="0.001" aria-label="Modellzeit"><output data-bf="clock"></output><label>Wiedergabefaktor <select data-bf="speed"><option>1</option><option>2</option><option>4</option></select></label><select data-bf="vehicle" aria-label="Fahrzeug"></select><button data-bf="follow">Fahrzeug folgen</button></div><p data-bf="status" role="status"></p><p data-bf="coverage"></p><ul data-bf="targets"></ul><p data-bf="lift"></p><div class="bf-camera"><div><canvas data-bf="camera" aria-label="Empfangene synthetische Fahrzeugaufnahme"></canvas><p data-bf="camera-meta"></p></div><div data-bf="mosaic" class="bf-mosaic"></div></div><div class="bf-table"><table><thead><tr><th>Fahrzeug</th><th>Empfangener Zustand</th><th>Meldungsalter</th><th>Verbindung</th><th>Auftrag</th></tr></thead><tbody data-bf="rows"></tbody></table></div><label>Ereignisfilter <input data-bf="filter" type="search"></label><ol data-bf="events"></ol>';
 if(preview){const notice=document.createElement('p');notice.id='building-fleet-preview-notice';notice.setAttribute('role','note');notice.textContent='Experimentelle Teilvorschau · Aufzeichnung bis '+duration.toFixed(3)+' s. Vollständiger Missionslauf, native Gesamtprüfung und unabhängige Exportprüfung unbestätigt.';notice.style.cssText='position:absolute;top:8px;left:8px;right:8px;margin:0;padding:10px 14px;background:#fff0c7;color:#342500;border:2px solid #936b13;border-radius:8px;z-index:12;pointer-events:none;font:600 14px sans-serif';bridge.stage.append(notice);panel.dataset.experimentalPreview='true';}
 const q=name=>panel.querySelector('[data-bf="'+name+'"]'),select=q('vehicle');for(const m of models){const option=document.createElement('option');option.value=option.textContent=m.id;select.append(option);}
 const mosaic=models.map(m=>{const box=document.createElement('figure'),canvas=document.createElement('canvas'),label=document.createElement('figcaption');label.textContent=m.id;box.append(canvas,label);q('mosaic').append(box);return{canvas,box,id:m.id};});const [cameraWidth,cameraHeight]=payload.camera_presentation.resolution_px;q('camera').width=cameraWidth;q('camera').height=cameraHeight;for(const m of mosaic){m.canvas.width=160;m.canvas.height=90;}
 const captureReceivedAt=new Map();for(const m of program.received_messages)if(m.kind==='perception'){const previous=captureReceivedAt.get(m.payload.camera_ref);if(previous===undefined||m.received_s<previous)captureReceivedAt.set(m.payload.camera_ref,m.received_s);}
 const framebuffer=bridge.gl.createFramebuffer(),texture=bridge.gl.createTexture(),depth=bridge.gl.createRenderbuffer();let framebufferSize='';
 function cameraImage(canvas,capture){const gl=bridge.gl,width=canvas.width,height=canvas.height,key=width+'x'+height;gl.bindFramebuffer(gl.FRAMEBUFFER,framebuffer);if(framebufferSize!==key){gl.bindTexture(gl.TEXTURE_2D,texture);gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,width,height,0,gl.RGBA,gl.UNSIGNED_BYTE,null);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);gl.framebufferTexture2D(gl.FRAMEBUFFER,gl.COLOR_ATTACHMENT0,gl.TEXTURE_2D,texture,0);gl.bindRenderbuffer(gl.RENDERBUFFER,depth);gl.renderbufferStorage(gl.RENDERBUFFER,gl.DEPTH_COMPONENT16,width,height);gl.framebufferRenderbuffer(gl.FRAMEBUFFER,gl.DEPTH_ATTACHMENT,gl.RENDERBUFFER,depth);framebufferSize=key;require(gl.checkFramebufferStatus(gl.FRAMEBUFFER)===gl.FRAMEBUFFER_COMPLETE,'Camera framebuffer incomplete');}
  const captureTime=capture.captured_s,lift=liftAt(program,captureTime),states=models.map(m=>m.at(captureTime,lift));try{bridge.applyLift(lift);bridge.capture(capture,width,height,()=>renderer.draw(bridge.cameraMatrix(width/height),states),payload.vehicle_mesh.scene.camera_frame,payload.camera_presentation.fov_deg);const pixels=new Uint8Array(width*height*4);gl.readPixels(0,0,width,height,gl.RGBA,gl.UNSIGNED_BYTE,pixels);const flipped=new Uint8ClampedArray(pixels.length);for(let y=0;y<height;y++)flipped.set(pixels.subarray(y*width*4,(y+1)*width*4),(height-y-1)*width*4);canvas.getContext('2d').putImageData(new ImageData(flipped,width,height),0,0);canvas.dataset.captureRef=capture.camera_ref||'';canvas.title='synthetische Aufnahme '+capture.captured_s.toFixed(3)+' s · '+(capture.camera_ref||'');}finally{gl.bindFramebuffer(gl.FRAMEBUFFER,null);apply(time);}}
 function apply(t){const lift=liftAt(program,t);bridge.applyLift(lift);return models.map(m=>m.at(t,lift));}
 function blocked(){return program.room_route_object_ids.filter(id=>!bridge.doorOpen(id));}
 function ui(){
  const received=projection.at(time,false),states=apply(time),blocks=blocked();frozen=blocks.length>0;
  q('status').textContent=frozen?'Flottenvorschau gesperrt: Fahrwegtür öffnen · '+blocks.join(', '):'Modellzeit '+time.toFixed(3)+' s · Aufzug im Flottenbetrieb · '+(preview&&time===duration?'Ende der Aufzeichnung · Gesamtlauf unbestätigt':playing?'läuft':'pausiert');
  q('clock').textContent=time.toFixed(3)+' / '+duration.toFixed(3)+' s';q('time').value=time;q('time').disabled=frozen;
  q('coverage').textContent='Empfangene Zielabdeckung: '+received.coverage.length+' / '+program.targets.length;
  const tableKey=projection.cursor+':'+Math.floor(time*10);
  if(tableKey!==lastTableKey){lastTableKey=tableKey;
   q('rows').replaceChildren(...models.map(m=>{const r=received.vehicles[m.id],row=document.createElement('tr'),mission=r?.mission,goal=mission?.goal||mission;
    const values=[m.id,r?.heartbeat?`${r.heartbeat.level} · ${r.heartbeat.area} · ${stateLabel(r.heartbeat.mode)}`:'noch keine Meldung',r?.last_sent_s==null?'unbekannt':r.message_age_s.toFixed(1)+' s',r?.connected===false?'Funkloch':r?.connected===true?'verbunden':'unbekannt',goal?.level&&goal?.area?targetLabel(goal):mission?.mission_id||'unbekannt'];
    for(const value of values){const cell=document.createElement('td');cell.textContent=value;row.append(cell);}return row;}));
  }
  const filter=q('filter').value.toLowerCase(),eventKey=received.events.length+':'+filter;
  if(eventKey!==lastEventKey){lastEventKey=eventKey;
   q('events').replaceChildren(...received.events.filter(e=>JSON.stringify(e).toLowerCase().includes(filter)).slice(-120).map(e=>{const li=document.createElement('li');li.textContent=`${e.received_s.toFixed(3)}s ${e.vehicle_id} #${e.seq} ${e.payload.event}${e.delivered_late?' · verspätet':''} ${JSON.stringify(e.payload.details)}`;return li;}));
   const lift=receivedLift(received.events),queue=lift.queue.map(r=>r.vehicle_id+' ('+r.event+')').join(', ');
   q('lift').textContent='Empfangene Aufzugwarteschlange: '+(queue||'keine wartende Meldung')+(lift.last?' · Letzte Meldung: '+lift.last.vehicle_id+' '+lift.last.payload.event+' bei '+lift.last.received_s.toFixed(3)+' s':' · Noch keine Dienstmeldung');
  }
  const targetKey=received.coverage.map(row=>row.level+'/'+row.area).join(',');
  if(targetKey!==lastTargetKey||!q('targets').childElementCount){lastTargetKey=targetKey;const covered=new Set(received.coverage.map(row=>row.level+'/'+row.area));
   q('targets').replaceChildren(...program.targets.map(target=>{const li=document.createElement('li');li.textContent=targetLabel(target)+' · '+(covered.has(target.level+'/'+target.area)?'Durchfahrt gemeldet':'noch keine Durchfahrt gemeldet');return li;}));
  }
  if(follow)bridge.follow(states.find(state=>state.id===selected));
  states.forEach((state,i)=>{const point=bridge.projectPoint(state.pose_xyz_mm.map((v,k)=>v+(k===2?payload.vehicle_mesh.scene.bounds_mm.max[2]:0))),node=labelNodes[i];node.hidden=!point?.visible;if(point){node.style.left=(point.x*100)+'%';node.style.top=(point.y*100)+'%';}});
  for(const cell of mosaic)cell.box.hidden=cell.id===selected;
  // Seeking cannot leave a not-yet-received future capture in any inset.
  for(const canvas of [q('camera'),...mosaic.map(m=>m.canvas)]){const ref=canvas.dataset.captureRef;if(ref&&!(captureReceivedAt.get(ref)<=time)){canvas.getContext('2d').clearRect(0,0,canvas.width,canvas.height);canvas.dataset.captureRef='';if(canvas===q('camera'))cameraTick=-Infinity;}}
  const wallNow=performance.now()/1000;
  if(wallNow-cameraTick>=1/payload.camera_presentation.selected_rate_hz){cameraTick=wallNow;const own=received.vehicles[selected]?.perception;
   if(own){const capture=program.camera_captures[own.camera_ref];q('camera-meta').textContent=selected+' · Aufnahme '+capture.captured_s.toFixed(3)+' s · empfangene synthetische Darstellung';if(q('camera').dataset.captureRef!==own.camera_ref)cameraImage(q('camera'),{...capture,camera_ref:own.camera_ref});}
   else{q('camera-meta').textContent='Noch keine empfangene Aufnahme für '+selected;q('camera').getContext('2d').clearRect(0,0,cameraWidth,cameraHeight);q('camera').dataset.captureRef='';}
  }
  if(wallNow-mosaicTick>=1/payload.camera_presentation.mosaic_rate_hz){mosaicTick=wallNow;let next;do{next=mosaic[mosaicIndex++%mosaic.length];}while(next.id===selected);const perception=received.vehicles[next.id]?.perception;
   if(perception){const capture=program.camera_captures[perception.camera_ref];if(next.canvas.dataset.captureRef!==perception.camera_ref)cameraImage(next.canvas,{...capture,camera_ref:perception.camera_ref});}
   else{next.canvas.getContext('2d').clearRect(0,0,next.canvas.width,next.canvas.height);next.canvas.dataset.captureRef='';}
  }
  bridge.requestRender();return{received,states,blocked_doors:blocks};
 }
 const hooks={get following(){return follow;},draw:matrix=>renderer.draw(matrix,apply(time))};bridge.activate(hooks);
 q('play').onclick=()=>{playing=!playing;q('play').textContent=playing?'Pause':'Abspielen';last=null;ui();};q('time').oninput=()=>{if(blocked().length){ui();return;}time=Number(q('time').value);last=null;ui();};q('speed').onchange=()=>factor=Number(q('speed').value);select.onchange=()=>{selected=select.value;cameraTick=-Infinity;ui();};q('follow').onclick=()=>{follow=!follow;if(follow)bridge.beginFollow();else bridge.endFollow();q('follow').textContent=follow?'Folgemodus beenden':'Fahrzeug folgen';bridge.clearMovement();ui();};q('filter').oninput=ui;
 document.addEventListener('visibilitychange',()=>{last=null;});
 function frame(now){try{frozen=blocked().length>0;if(last!==null&&playing&&!frozen&&!document.hidden)time=Math.min(duration,time+(now-last)/1000*factor);last=now;if(time===duration){playing=false;q('play').textContent='Abspielen';}ui();requestAnimationFrame(frame);}catch(error){playing=false;q('status').textContent='BF01-Fehler: '+error.message;panel.dataset.error=error.message;console.error(error);}}
 window.__buildingFleet=Object.freeze({seek:t=>{require(finite(t)&&t>=0&&t<=duration,'Time outside program');require(!blocked().length,'Open route doors before seeking');time=t;return ui();},play:()=>{playing=true;last=null;q('play').textContent='Pause';},pause:()=>{playing=false;q('play').textContent='Abspielen';},follow:id=>{require(models.some(m=>m.id===id),'Unknown vehicle');if(!follow)bridge.beginFollow();selected=id;select.value=id;follow=true;q('follow').textContent='Folgemodus beenden';return ui();},stopFollowing:()=>{follow=false;bridge.endFollow();q('follow').textContent='Fahrzeug folgen';return ui();},get time_s(){return time;},get states(){const lift=liftAt(program,time);return models.map(m=>m.at(time,lift));},get control_room(){return controlRoom(program.received_messages,time);},get frozen(){return frozen;},get instance_count(){return models.length;},get draw_calls(){return renderer.draws;},get renderer_stats(){return renderer.stats;},get ready(){return !panel.dataset.error;},get model_duration_s(){return duration;},get playback_factor(){return factor;},get experimental_preview(){return preview?JSON.parse(JSON.stringify({...preview,at_recorded_end:time===duration})):null;}});
 if(preview){window.__buildingFleet.follow('BF04');window.__buildingFleet.play();}
 ui();requestAnimationFrame(frame);return hooks;
}
return{compileCurve,liftAt,trajectories,controlRoom,ReceivedProjection,targetLabel,stateLabel,receivedLift,validateProgram,validatePreview,mount};
});
