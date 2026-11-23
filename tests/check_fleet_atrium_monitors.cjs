// Bounded integration check; no full mission, native-motion or safety qualification.
// Usage: node tests/check_fleet_atrium_monitors.cjs <index.html> <playwright-module> <chrome> [https-url]
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const crypto=require('node:crypto'),zlib=require('node:zlib'),{pathToFileURL}=require('node:url');
const view=require('../scripts/building_fleet_view.js');
const sha=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
const extract=(html,id)=>JSON.parse(html.match(new RegExp('<script id="'+id+'" type="application/json">([\\s\\S]*?)</script>'))[1]);

function installScreenAudit(monitors){
 const proto=WebGL2RenderingContext.prototype,contexts=new WeakMap(),locations=new WeakMap(),programs=new WeakMap(),textures=new WeakMap();
 let nextTexture=1;
 const audit=window.__atriumScreenAudit={screens:{},uploads:{},recursive_screen_draws:0,observed_gl_errors:[]};
 const context=gl=>{if(!contexts.has(gl))contexts.set(gl,{program:null,framebuffer:null,active:gl.TEXTURE0,bound:new Map()});return contexts.get(gl);};
 const program=p=>{if(!programs.has(p))programs.set(p,{screen:false,origin:null});return programs.get(p);};
 const texture=t=>{if(t&&!textures.has(t))textures.set(t,nextTexture++);return t?textures.get(t):null;};
 const wrap=(name,record)=>{const original=proto[name];proto[name]=function(...args){const value=original.apply(this,args);record(this,args,value);return value;};};
 wrap('getUniformLocation',(_gl,[p,name],location)=>{if(location)locations.set(location,{program:p,name});});
 wrap('useProgram',(gl,[p])=>{context(gl).program=p;});
 wrap('uniform1i',(_gl,[location,value])=>{const l=locations.get(location);if(l?.name==='screenEnabled')program(l.program).screen=Boolean(value);});
 wrap('uniform3fv',(_gl,[location,value])=>{const l=locations.get(location);if(l?.name==='screenOrigin')program(l.program).origin=Array.from(value);});
 wrap('activeTexture',(gl,[unit])=>{context(gl).active=unit;});
 wrap('bindTexture',(gl,[target,t])=>{if(target===gl.TEXTURE_2D)context(gl).bound.set(context(gl).active,t);});
 wrap('bindFramebuffer',(gl,[target,f])=>{if(target===gl.FRAMEBUFFER||target===gl.DRAW_FRAMEBUFFER)context(gl).framebuffer=f;});
 wrap('texImage2D',(gl,args)=>{
  const image=args.at(-1);if(!(image instanceof HTMLCanvasElement)||args.length!==6)return;
  const id=texture(context(gl).bound.get(context(gl).active));if(id===null)return;
  const {width,height}=image,d=image.getContext('2d')?.getImageData(0,0,width,height).data;if(!d)return;
  let opaque=0;const colors=new Set();
  for(let y=0;y<height;y++)for(let x=0;x<width;x++){const i=(y*width+x)*4;if(d[i+3]===255)opaque++;if(y>=31&&y<height-28)colors.add((d[i]<<16)|(d[i+1]<<8)|d[i+2]);}
  audit.uploads[id]={texture_id:id,width,height,opaque_pixels:opaque,interior_colors:colors.size,uploads:(audit.uploads[id]?.uploads||0)+1};
 });
 wrap('drawElements',(gl)=>{
  const c=context(gl),p=c.program&&program(c.program);if(!p?.screen||!p.origin)return;
  const monitor=monitors.find(m=>m.screen_frame.origin_mm.every((v,i)=>Math.fround(v/1000)===Math.fround(p.origin[i])));if(!monitor)return;
  if(c.framebuffer!==null){audit.recursive_screen_draws++;return;}
  const id=texture(c.bound.get(gl.TEXTURE0));audit.screens[monitor.screen_body_id]={screen_body_id:monitor.screen_body_id,texture_id:id,...audit.uploads[id]};
 });
 wrap('getError',(_gl,[],code)=>{if(code!==0)audit.observed_gl_errors.push(code);});
}

(async()=>{
 const target=path.resolve(process.argv[2]),bytes=fs.readFileSync(target),html=bytes.toString();
 const payload=extract(html,'building-fleet-data'),normal=extract(html,'walkthrough-data'),wall=normal.camera_wall;
 const program=JSON.parse(zlib.gunzipSync(Buffer.from(payload.program_gzip_base64,'base64')));
 assert.deepEqual([wall.grid_columns,wall.grid_rows,wall.monitors.length],[5,4,20]);
 assert.equal(payload.presentation?.atrium_monitors,true);assert.equal(payload.presentation.start_stop,'camera-wall');
 assert.equal(payload.presentation.autoplay,true);assert.equal(payload.presentation.follow,false);
 assert.equal(program.complete,false);assert.equal(payload.experimental_preview?.recorded_end_s,program.duration_s);assert(program.duration_s>=120);
 const ids=Array.from({length:20},(_,i)=>'BF'+String(i+1).padStart(2,'0'));
 const expectedCameras=ids.map(id=>'BF01.'+id+'.Overview'),screenIds=wall.monitors.map(m=>m.screen_body_id);
 const nativeIds=new Set(normal.scenes.building.groups.map(g=>g.id));assert.equal(new Set(screenIds).size,20);assert(screenIds.every(id=>nativeIds.has(id)));
 const {chromium}=require(process.argv[3]||'playwright'),live=process.argv[5]?new URL(process.argv[5]):null;if(live)assert.equal(live.protocol,'https:');
 const gpu=process.env.SOLIDCRAFTBOT_WALKTHROUGH_GPU||'software';assert(['metal','software'].includes(gpu));
 const browser=await chromium.launch({headless:true,...(process.argv[4]?{executablePath:process.argv[4]}:{}),args:gpu==='metal'?['--enable-gpu','--enable-webgl','--ignore-gpu-blocklist','--use-gl=angle','--use-angle=metal']:['--enable-webgl','--ignore-gpu-blocklist','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 const page=await browser.newPage({viewport:{width:1440,height:1100}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(/GL_INVALID|WebGL drawing error/.test(m.text()))errors.push(m.text());});
 await page.addInitScript(installScreenAudit,wall.monitors);
 const report={format:'solidcraftbot.building-fleet-atrium-monitors-browser-check/1',passed:false,html_sha256:sha(bytes),
  browser:{engine:'chromium',version:browser.version(),gpu_profile:gpu},experimental_preview:true,complete:false,
  recorded_end_s:program.duration_s,full_mission_coverage_verified:false,native_full_program_verified:false,
  independent_export_verified:false,hardware_or_real_safety_qualified:false,camera_quality_qualified:false,
  scope:'Bounded same-document fleet/physical-monitor presentation check of an interrupted recording; no full mission, native-motion, export, camera-quality, performance or real-safety qualification.'};
 try{
  if(live){
   const cdp=await page.context().newCDPSession(page),documents=[],requests=[],size=bytes.length*2+1024*1024;
   await cdp.send('Network.enable',{maxResourceBufferSize:size,maxTotalBufferSize:size*2});
   cdp.on('Network.responseReceived',e=>{if(e.type==='Document'&&e.response.url===live.href)documents.push(e);});
   page.on('request',r=>{if(r.url()===live.href&&r.isNavigationRequest()&&r.frame()===page.mainFrame())requests.push(r.method());});
   const response=await page.goto(live.href,{waitUntil:'load',timeout:120000});assert(response);assert.equal(response.status(),200);assert.equal(response.url(),live.href);
   assert.equal(documents.length,1);assert.deepEqual(requests,['GET']);const captured=await cdp.send('Network.getResponseBody',{requestId:documents[0].requestId});
   const actual=Buffer.from(captured.body,captured.base64Encoded?'base64':'utf8');assert.equal(actual.length,bytes.length);assert.equal(sha(actual),sha(bytes));
   report.live={passed:true,url:live.href,status:200,body_bytes:actual.length,body_sha256:sha(actual),main_requests:1};await cdp.detach();
  }else await page.goto(pathToFileURL(target).href,{timeout:120000});
  await page.waitForFunction(()=>window.__buildingFleet?.ready&&window.__buildingWalkthrough?.ready&&window.__buildingWalkthrough.monitorWall?.source_connected,null,{timeout:120000});
  assert(await page.locator('#walkthrough-error').isHidden());
  assert.equal(await page.evaluate(()=>window.__buildingWalkthrough.stopId),'camera-wall');
  const startup=await page.evaluate(()=>({camera:window.__buildingWalkthrough.camera,time:window.__buildingFleet.time_s,wall:window.__buildingWalkthrough.monitorWall}));
  assert.equal(startup.camera.level_id,'EG');assert.equal(startup.wall.source_kind,'received_fleet_recording');
  const startStop=normal.stops.find(stop=>stop.id==='camera-wall');assert(startStop);
  startup.camera.eye_mm.forEach((v,i)=>assert(Math.abs(v-startStop.eye_mm[i])<1e-6,'Startup must retain the foyer viewpoint without following a vehicle'));
  assert.deepEqual(startup.wall.slots.map(s=>s.camera_id),expectedCameras);assert.deepEqual(startup.wall.slots.map(s=>s.screen_body_id),screenIds);
  await page.waitForFunction(before=>window.__buildingFleet.time_s>before+.05,startup.time,{timeout:30000});
  await page.evaluate(()=>window.__buildingFleet.pause());report.default_start={stop:'camera-wall',autoplay_observed:true,follow:false};
  const notice=await page.locator('#building-fleet-preview-notice').innerText();assert(/experimentell/i.test(notice));assert(/unbestätigt|ungeprüft|unvollständig/i.test(notice));report.experimental_notice=notice;
  const models=view.trajectories(program),samples=[];
  for(const t of [0,60,120]){
   const actual=await page.evaluate(t=>{window.__buildingFleet.seek(t);return{states:window.__buildingFleet.states,room:window.__buildingFleet.control_room,wall:window.__buildingWalkthrough.monitorWall};},t);
   const lift=view.liftAt(program,t);models.forEach((m,i)=>{const p=m.at(t,lift);assert.equal(actual.states[i].id,p.id);actual.states[i].pose_xyz_mm.forEach((v,k)=>assert(Math.abs(v-p.pose_xyz_mm[k])<1e-6));assert(Math.abs(actual.states[i].yaw_rad-p.yaw_rad)<1e-8);});
   assert.deepEqual(actual.room,view.controlRoom(program.received_messages,t));assert.equal(actual.wall.model_time_s,t);samples.push({model_time_s:t,states:actual.states});
  }
  const moved=ids.filter((id,i)=>samples.slice(1).some(s=>Math.hypot(...s.states[i].pose_xyz_mm.map((v,k)=>v-samples[0].states[i].pose_xyz_mm[k]))>1e-6));assert(moved.length>0);
  report.sampled_timeline=[0,60,120];report.observed_moving_vehicle_ids=moved;report.native_instances=await page.evaluate(()=>window.__buildingFleet.renderer_stats);assert.equal(report.native_instances.last_instance_count,20);
  await page.evaluate(()=>window.__buildingFleet.seek(60));
  const captures=await page.evaluate(()=>Array.from({length:20},(_,i)=>window.__buildingWalkthrough.captureMonitor(i)));assert(captures.every(r=>r.status==='captured'));
  const snapshot=await page.evaluate(()=>window.__buildingWalkthrough.monitorWall),received=view.controlRoom(program.received_messages,60);
  const reception=new Map();for(const message of program.received_messages)if(message.kind==='perception'&&message.received_s<=60){const ref=message.payload.camera_ref;reception.set(ref,Math.min(reception.get(ref)??Infinity,message.received_s));}
  assert.equal(snapshot.source_connected,true);assert.equal(snapshot.model_time_s,60);
  for(const [i,slot]of snapshot.slots.entries()){
   const perception=received.vehicles[ids[i]]?.perception;assert(perception);const capture=program.camera_captures[perception.camera_ref];
   assert.equal(slot.frame.vehicle_id,ids[i]);assert.equal(slot.frame.camera_ref,perception.camera_ref);assert.equal(slot.frame.captured_s,capture.captured_s);
   assert.equal(slot.frame.model_time_s,capture.captured_s);assert.equal(slot.frame.received_s,reception.get(perception.camera_ref));assert.equal(slot.frame.program_time_s,60);
   assert(slot.frame.captured_s<=slot.frame.received_s&&slot.frame.received_s<=60);assert.equal(slot.pixel_alpha_min,255);assert(slot.frames>0&&slot.image_hash);assert(Number.isFinite(slot.age_s)&&slot.age_s>=0);
  }
  report.monitor_sources=snapshot.slots;report.shared_recording_clock=true;
  await page.evaluate(()=>{window.__atriumScreenAudit.screens={};});await page.locator('button[data-stop="camera-wall"]').click();
  await page.waitForFunction(()=>Object.keys(window.__atriumScreenAudit.screens).length===20,null,{timeout:30000});
  const screens=await page.evaluate(()=>window.__atriumScreenAudit);assert.deepEqual(Object.keys(screens.screens).sort(),[...screenIds].sort());
  const drawn=Object.values(screens.screens);assert.equal(new Set(drawn.map(s=>s.texture_id)).size,20);
  assert(drawn.every(s=>s.width===wall.settings.resolution_px[0]&&s.height===wall.settings.resolution_px[1]&&s.opaque_pixels===s.width*s.height));assert(drawn.some(s=>s.interior_colors>2));
  assert.equal(screens.recursive_screen_draws,0);assert.deepEqual(screens.observed_gl_errors,[]);report.physical_screen_draws=drawn;report.no_recursive_monitor_capture=true;
  const cameraPositions=await page.evaluate(points=>points.map(p=>window.__buildingWalkthrough.projectPoint(p)),wall.monitors.map(m=>m.screen_frame.origin_mm));assert(cameraPositions.every(p=>p.visible));report.all_physical_screens_visible=true;
  await page.screenshot({path:path.join(path.dirname(target),'atrium-fleet-monitors-desktop.png'),fullPage:true});
  const before=await page.evaluate(()=>window.__buildingFleet.time_s);await page.waitForTimeout(150);assert.equal(await page.evaluate(()=>window.__buildingFleet.time_s),before);assert.equal(await page.evaluate(()=>window.__buildingWalkthrough.monitorWall.model_time_s),before);report.pause_preserves_recording_clock=true;
  await page.evaluate(()=>window.__buildingFleet.seek(0));
  const rewound=await page.evaluate(()=>window.__buildingWalkthrough.monitorWall);assert.equal(rewound.model_time_s,0);assert(rewound.slots.every(s=>!s.frame?s.image_hash===null:(s.frame.captured_s<=0&&s.frame.received_s<=0)));report.backward_seek_clears_future_frames=true;
  const arm=wall.cameras.find(c=>c.category==='robot'&&c.availability==='available');assert(arm);
  await page.evaluate(id=>{window.__buildingFleet.seek(60);window.__buildingWalkthrough.assignMonitor(0,id);window.__buildingWalkthrough.selectMonitor(0);},arm.id);
  assert.equal((await page.evaluate(()=>window.__buildingWalkthrough.captureMonitor(0))).status,'captured');
  const armSlot=await page.evaluate(()=>window.__buildingWalkthrough.monitorWall.slots[0]);assert.equal(armSlot.camera_id,arm.id);assert(armSlot.frame.eye_mm.every(Number.isFinite));
  await page.evaluate(id=>window.__buildingWalkthrough.assignMonitor(0,id),expectedCameras[0]);assert.equal((await page.evaluate(()=>window.__buildingWalkthrough.captureMonitor(0))).status,'captured');
  const restored=await page.evaluate(()=>window.__buildingWalkthrough.monitorWall.slots[0]);assert.equal(restored.frame.vehicle_id,'BF01');assert.equal(restored.frame.camera_ref,received.vehicles.BF01.perception.camera_ref);report.arm_and_fleet_source_switch=true;
  await page.locator('.camera-wall-panel>button').click();
  const door=program.room_route_object_ids[0];assert(door);await page.evaluate(()=>{window.__buildingFleet.seek(60);window.__buildingFleet.play();});
  const closing=await page.evaluate(id=>window.__buildingWalkthrough.command(id,'close'),door);assert(['accepted','already_in_state'].includes(closing.status));await page.waitForFunction(()=>window.__buildingFleet.frozen,null,{timeout:30000});
  const frozen=await page.evaluate(()=>window.__buildingFleet.time_s);await page.waitForTimeout(150);assert.equal(await page.evaluate(()=>window.__buildingFleet.time_s),frozen);assert.equal(await page.evaluate(()=>window.__buildingWalkthrough.monitorWall.model_time_s),frozen);
  await page.waitForFunction(id=>window.__buildingWalkthrough.objects.find(o=>o.id===id)?.state==='closed',door,{timeout:30000});
  const opened=await page.evaluate(id=>window.__buildingWalkthrough.command(id,'open'),door);assert(['accepted','already_in_state'].includes(opened.status));await page.waitForFunction(()=>!window.__buildingFleet.frozen,null,{timeout:30000});await page.evaluate(()=>window.__buildingFleet.pause());report.route_door_freeze=true;
  await page.evaluate(t=>window.__buildingFleet.seek(t),program.duration_s);assert(/Ende der Aufzeichnung/i.test(await page.locator('[data-bf=status]').innerText()));
  assert.equal(await page.evaluate(()=>window.__buildingWalkthrough.monitorWall.model_time_s),program.duration_s);
  assert(await page.evaluate(()=>{try{window.__buildingFleet.seek(window.__buildingFleet.model_duration_s+.001);return false;}catch{return true;}}));report.recording_endpoint_visible=true;report.seek_limited_to_recording=true;
  assert(await page.locator('#walkthrough-error').isHidden());const finalAudit=await page.evaluate(()=>window.__atriumScreenAudit);assert.equal(finalAudit.recursive_screen_draws,0);assert.deepEqual(finalAudit.observed_gl_errors,[]);assert.deepEqual(errors,[]);
  report.main_scene_error_hidden=true;report.errors=errors;report.passed=true;
 }catch(error){report.failure={name:error.name,message:error.message};throw error;}
 finally{fs.writeFileSync(path.join(path.dirname(target),'atrium-fleet-monitors-browser-check.json'),JSON.stringify(report,null,2)+'\n');await browser.close();}
 console.log('Bounded physical atrium-monitor fleet check passed. Complete fleet qualification remains open.');
})().catch(error=>{console.error(error);process.exitCode=1;});
