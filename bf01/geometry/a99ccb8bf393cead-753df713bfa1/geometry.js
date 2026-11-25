/* Exact visual geometry arrives by level; live physics has its own full world. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.WalkthroughProgressiveGeometry=api;})(typeof globalThis!=='undefined'?globalThis:this,function(){
'use strict';
const FORMAT='solidcraftbot.walkthrough-progressive-geometry/1',CHUNK='solidcraftbot.walkthrough-geometry-chunk/1';
const require=(ok,message)=>{if(!ok)throw Error(message);},copy=x=>JSON.parse(JSON.stringify(x));
function bytes(text){const raw=atob(text),out=new Uint8Array(raw.length);for(let i=0;i<raw.length;i++)out[i]=raw.charCodeAt(i);return out;}
function unpack(text,count,float){const raw=bytes(text);require(raw.length===count*4,'Native visual buffer size differs');const view=new DataView(raw.buffer),out=float?new Float32Array(count):new Uint32Array(count);for(let i=0;i<count;i++){out[i]=float?view.getFloat32(i*4,true):view.getUint32(i*4,true);require(Number.isFinite(out[i]),'Finite native visual values required');}return out;}
function decode(scene){
 require(Number.isSafeInteger(scene.vertex_count)&&scene.vertex_count>=0&&Number.isSafeInteger(scene.index_count)&&scene.index_count>=0&&scene.index_count%3===0&&Array.isArray(scene.groups),'Bounded native geometry chunk required');
 const buffers={positions:unpack(scene.positions_base64,scene.vertex_count*3,true),normals:unpack(scene.normals_base64,scene.vertex_count*3,true),indices:unpack(scene.indices_base64,scene.index_count,false)};
 for(const i of buffers.indices)require(i<scene.vertex_count,'Visual triangle is outside its native vertex array');
 let expected=0;for(const g of scene.groups.slice().sort((a,b)=>a.index_start-b.index_start||a.index_count-b.index_count)){require(Number.isSafeInteger(g.index_count)&&g.index_count>=0&&g.index_count%3===0&&g.index_start===expected,'Visual groups must partition every native triangle');expected+=g.index_count;}require(expected===scene.index_count,'Visual groups omit native triangles');
 return{...scene,geometry_buffers:buffers};
}
function canonical(value){if(Array.isArray(value))return value.map(canonical);if(value&&typeof value==='object')return Object.fromEntries(Object.keys(value).sort().map(k=>[k,canonical(value[k])]));return value;}
function metadata(group){const x={...group};for(const key of ['index_start','index_count','pending_geometry','pending_index_count'])delete x[key];return JSON.stringify(canonical(x));}
function createComposer(initial,descriptor){
 require(descriptor?.format===FORMAT&&descriptor.scene_id==='building'&&Array.isArray(descriptor.chunks)&&descriptor.shared_geometry_loaded===true,'Pinned progressive native scene required');
 const source=decode(initial),expected=new Map(),levels=new Set(descriptor.initial_levels),chunks=new Map([['initial',source]]),order=['initial',...descriptor.chunks.map(c=>c.level_id)];
 require(new Set(order).size===order.length,'Unique progressive geometry levels required');
 for(const g of initial.groups){require(typeof g.id==='string'&&!expected.has(g.id),'Unique native visual body required');expected.set(g.id,{group:g,count:g.pending_geometry?g.pending_index_count:g.index_count});}
 require(expected.size===descriptor.full_group_count,'Complete semantic native body manifest required');
 const declared=new Map(descriptor.chunks.map(c=>[c.level_id,c]));
 function add(chunk){
  require(chunk?.format===CHUNK&&chunk.scene_id==='building'&&chunk.source_scene_sha256===descriptor.source_scene_sha256&&declared.has(chunk.level_id)&&!levels.has(chunk.level_id),'A new source-bound visual level is required');
  const checked=decode(chunk),wanted=[...expected.values()].filter(e=>e.group.level_id===chunk.level_id),ids=new Set();
  require(checked.groups.length===wanted.length&&checked.index_count===declared.get(chunk.level_id).index_count,'Visual level differs from its native partition');
  for(const g of checked.groups){const e=expected.get(g.id);require(e&&e.group.level_id===chunk.level_id&&!ids.has(g.id)&&g.index_count===e.count&&metadata(g)===metadata(e.group),'Visual body metadata or triangle count differs from its source');ids.add(g.id);}
  require(wanted.every(e=>ids.has(e.group.id)),'Visual level omits a native body');chunks.set(chunk.level_id,checked);levels.add(chunk.level_id);return snapshot();
 }
 function snapshot(){
  const rows=order.filter(k=>chunks.has(k)).map(k=>chunks.get(k)),vertexCount=rows.reduce((n,c)=>n+c.vertex_count,0),indexCount=rows.reduce((n,c)=>n+c.index_count,0),positions=new Float32Array(vertexCount*3),normals=new Float32Array(vertexCount*3),indices=new Uint32Array(indexCount),loaded=new Map();let vertexOffset=0,indexOffset=0;
  for(const row of rows){const b=row.geometry_buffers;positions.set(b.positions,vertexOffset*3);normals.set(b.normals,vertexOffset*3);for(let i=0;i<b.indices.length;i++)indices[indexOffset+i]=b.indices[i]+vertexOffset;for(const g of row.groups)if(!g.pending_geometry)loaded.set(g.id,{...g,index_start:g.index_start+indexOffset});vertexOffset+=row.vertex_count;indexOffset+=row.index_count;}
  const groups=initial.groups.map(g=>loaded.get(g.id)??{...g,index_start:indexCount,index_count:0});
  const complete=levels.size===descriptor.initial_levels.length+descriptor.chunks.length;
  if(complete)require(indexCount===descriptor.full_index_count&&loaded.size===descriptor.full_group_count,'Complete visual world must retain every source triangle and body');
  const scene={...initial,vertex_count:vertexCount,index_count:indexCount,groups,geometry_buffers:{positions,normals,indices}};for(const k of ['positions_base64','normals_base64','indices_base64'])delete scene[k];
  return{scene,loaded_levels:[...levels],complete,loaded_groups:loaded.size};
 }
 return{add,snapshot};
}
function pendingLevelForMove(levels,loaded,eye,delta,radius){
 const sorted=levels.slice().sort((a,b)=>a.z_mm-b.z_mm),lo=Math.min(eye[2],eye[2]+delta[2])*1000-radius,hi=Math.max(eye[2],eye[2]+delta[2])*1000+radius;
 return sorted.find((l,i)=>!loaded.has(l.id)&&hi>=l.z_mm&&lo<(sorted[i+1]?.z_mm??Infinity))?.id??null;
}
async function checkedFetch(ref,base=globalThis.location?.href){
 require(ref&&typeof ref.url==='string'&&/^[a-f0-9]{64}$/.test(ref.sha256)&&Number.isSafeInteger(ref.bytes)&&ref.bytes>0,'Pinned visual asset required');const url=new URL(ref.url,base);require(url.origin===new URL(base).origin&&['https:','http:'].includes(url.protocol),'Visual chunks must use the page origin');const response=await fetch(url,{cache:'force-cache',credentials:'same-origin',priority:'low'});require(response.ok,'Visual geometry download failed: HTTP '+response.status);const raw=new Uint8Array(await response.arrayBuffer());require(raw.length===ref.bytes,'Visual asset size differs');const hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',raw))].map(v=>v.toString(16).padStart(2,'0')).join('');require(hash===ref.sha256,'Visual asset hash differs');return raw;
}
function attach({data,stage,root,apply,currentLevel,announce}){
 const descriptor=data.progressive_geometry;require(descriptor?.format===FORMAT,'Progressive scene descriptor required');const loaded=new Set(descriptor.initial_levels),status=document.createElement('p');status.id='walkthrough-geometry-status';status.setAttribute('role','status');status.style.cssText='margin:.4rem 1rem;font:13px sans-serif;color:#314e46';stage.after(status);
 let worker=null,starting=false,revision=0,complete=false,error=null,intent=null,requestNumber=0,initialPoses=null,loadedGroups=descriptor.initial_loaded_groups,loadedIndices=data.scenes.building.index_count;
 const label=id=>data.levels.find(l=>l.id===id)?.label??id;
 const text=()=>{status.textContent=error?'Weitere Etagen konnten nicht geladen werden. Bereits geladene Etagen bleiben verfügbar.':complete?'Alle Etagen vollständig geladen.':`${[...loaded].map(label).join(', ')} vollständig geladen · Weitere Etagen werden nach Fahrtbeginn im Hintergrund geladen.`;};text();
 const levelReady=id=>id==null||loaded.has(id);
 const fail=e=>{error=String(e?.message??e);root.dataset.visualGeometryError=error;text();worker?.terminate();};
 async function start(){if(worker||starting||complete||error)return;starting=true;try{
  const workerRef=descriptor.assets['worker.mjs'];await checkedFetch(workerRef);worker=new Worker(new URL(workerRef.url,location.href),{type:'module',name:'Gebäudegeometrie'});
  worker.onmessage=event=>{const m=event.data;if(m?.type==='geometry'){loaded.clear();for(const id of m.loaded_levels)loaded.add(id);complete=m.complete;loadedGroups=m.loaded_groups;loadedIndices=m.scene.index_count;revision++;apply(m.scene);root.dataset.visualGeometryComplete=String(complete);text();if(intent&&loaded.has(intent.level)){const action=intent.action;intent=null;action();}if(complete){worker.terminate();worker=null;}}else if(m?.type==='error')fail(Error(m.error));};worker.onerror=event=>{event.preventDefault();fail(Error(event.message));};
  const absolute=ref=>({...ref,url:new URL(ref.url,location.href).href});worker.postMessage({type:'boot',initial:data.scenes.building,descriptor:{...descriptor,chunks:descriptor.chunks.map(absolute),assets:Object.fromEntries(Object.entries(descriptor.assets).map(([k,v])=>[k,absolute(v)]))},base:location.href});if(intent)worker.postMessage({type:'prioritize',level_id:intent.level});
 }catch(e){fail(e);}finally{starting=false;}}
 function ensure(level){if(levelReady(level))return;if(error){announce(label(level)+' ist derzeit nicht verfügbar. Bereits geladene Etagen bleiben verfügbar.');return;}require(descriptor.chunks.some(c=>c.level_id===level),'Unknown visual level');void start();worker?.postMessage({type:'prioritize',level_id:level});announce(label(level)+' wird geladen. Der aktuelle Blick bleibt verfügbar.');}
 return{levelReady,
  requestView(level,action){if(levelReady(level)){action();return;}intent={level,action,id:++requestNumber};ensure(level);},
  allowMove(eye,delta){const level=pendingLevelForMove(data.levels,loaded,eye,delta,data.navigation.camera_radius_mm+data.navigation.contact_margin_mm);if(level){root.dataset.cameraGeometryPending=level;ensure(level);return false;}delete root.dataset.cameraGeometryPending;return true;},
  observe(snapshot){if(complete||error)return;initialPoses??=Object.fromEntries(snapshot.states.map(s=>[s.id,s.pose_xyz_mm]));if(snapshot.paused||snapshot.states.some(s=>Math.hypot(...s.pose_xyz_mm.map((v,i)=>v-initialPoses[s.id][i]))>=1))void start();},
  get revision(){return revision;},
  get snapshot(){return{loaded_levels:[...loaded],complete,revision,loaded_groups:loadedGroups,loaded_indices:loadedIndices,total_groups:descriptor.full_group_count,error,source_scene_sha256:descriptor.source_scene_sha256};}};
}
return{FORMAT,CHUNK,decode,createComposer,pendingLevelForMove,checkedFetch,attach};
});
