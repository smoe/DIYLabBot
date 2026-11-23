// Bounded experimental-preview smoke checks; no full fleet qualification.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const crypto=require('node:crypto'),zlib=require('node:zlib'),{pathToFileURL}=require('node:url');
const view=require('../scripts/building_fleet_view.js');
const digest=b=>crypto.createHash('sha256').update(b).digest('hex');

(async()=>{
 const target=path.resolve(process.argv[2]),bytes=fs.readFileSync(target),html=bytes.toString();
 const payload=JSON.parse(html.match(/<script id="building-fleet-data" type="application\/json">([\s\S]*?)<\/script>/)[1]);
 const normal=JSON.parse(html.match(/<script id="walkthrough-data" type="application\/json">([\s\S]*?)<\/script>/)[1]);
 const program=JSON.parse(zlib.gunzipSync(Buffer.from(payload.program_gzip_base64,'base64')));
 assert.equal(program.complete,false);assert.throws(()=>view.validateProgram(program),/Complete compiled/);
 assert(payload.experimental_preview,'Explicit experimental presentation contract required');
 assert.equal(payload.experimental_preview.playback_end_s,program.duration_s);
 const {chromium}=require(process.argv[3]||'playwright'),live=process.argv[5]?new URL(process.argv[5]):null;
 if(live)assert.equal(live.protocol,'https:');
 const gpu=process.env.SOLIDCRAFTBOT_WALKTHROUGH_GPU||'software';assert(['metal','software'].includes(gpu));
 const browser=await chromium.launch({headless:true,...(process.argv[4]?{executablePath:process.argv[4]}:{}),args:gpu==='metal'?['--enable-gpu','--enable-webgl','--ignore-gpu-blocklist','--use-gl=angle','--use-angle=metal']:['--enable-webgl','--ignore-gpu-blocklist','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 const page=await browser.newPage({viewport:{width:1400,height:1000}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 const report={format:'solidcraftbot.building-fleet-preview-browser-check/1',passed:false,
  scope:'Bounded WebGL smoke check of the recorded experimental prefix; no full native, export, mission-coverage or performance qualification.',
  html_sha256:digest(bytes),model_end_s:program.duration_s,recorded_end_s:program.duration_s,
  experimental_preview:true,complete:false,full_program_qualified:false,
  full_mission_coverage_verified:false,native_full_program_verified:false,independent_export_verified:false,
  browser:{engine:'chromium',version:browser.version(),gpu_profile:gpu}};
 try{
  if(live){
   const cdp=await page.context().newCDPSession(page),documents=[],requests=[];
   const size=bytes.length*2+1024*1024;
   await cdp.send('Network.enable',{maxResourceBufferSize:size,maxTotalBufferSize:size*2});
   cdp.on('Network.responseReceived',e=>{if(e.type==='Document'&&e.response.url===live.href)documents.push(e);});
   page.on('request',r=>{if(r.url()===live.href&&r.isNavigationRequest()&&r.frame()===page.mainFrame())requests.push(r.method());});
   const response=await page.goto(live.href,{waitUntil:'load',timeout:120000});
   assert(response);assert.equal(response.status(),200);assert.equal(response.url(),live.href);
   assert.equal(documents.length,1);assert.deepEqual(requests,['GET']);
   const captured=await cdp.send('Network.getResponseBody',{requestId:documents[0].requestId});
   const actual=Buffer.from(captured.body,captured.base64Encoded?'base64':'utf8');
   assert.equal(actual.length,bytes.length);assert.equal(digest(actual),report.html_sha256);
   report.live={passed:true,url:live.href,status:200,body_bytes:actual.length,body_sha256:digest(actual),main_requests:1};
   await cdp.detach();
  }else await page.goto(pathToFileURL(target).href,{timeout:120000});
  await page.waitForFunction(()=>window.__buildingFleet?.ready,null,{timeout:120000});
  await page.evaluate(()=>window.__buildingFleet.pause());
  const banner=page.locator('#building-fleet-preview-notice');assert(await banner.isVisible());
  const notice=await banner.innerText();assert(/experimentell/i.test(notice));assert(/unvollständig|nicht.*geprüft|ungeprüft|unbestätigt/i.test(notice));
  assert.equal(await page.locator('#walkthrough-fleet-link').getAttribute('href'),'../');
  await page.waitForFunction(()=>window.__buildingFleet.renderer_stats.last_instance_count===20);
  report.native_instances=await page.evaluate(()=>window.__buildingFleet.renderer_stats);
  assert(report.native_instances.native_mesh_groups>=34);
  const models=view.trajectories(program),times=[0,Math.min(60,program.duration_s/2),program.duration_s];
  for(const t of times){
   const actual=await page.evaluate(t=>{window.__buildingFleet.seek(t);return{states:window.__buildingFleet.states,room:window.__buildingFleet.control_room};},t);
   const lift=view.liftAt(program,t);
   models.forEach((m,i)=>{const expected=m.at(t,lift);actual.states[i].pose_xyz_mm.forEach((v,k)=>assert(Math.abs(v-expected.pose_xyz_mm[k])<1e-6));assert(Math.abs(actual.states[i].yaw_rad-expected.yaw_rad)<1e-8);});
   assert.deepEqual(actual.room,view.controlRoom(program.received_messages,t));
  }
  assert(/Ende der Aufzeichnung/i.test(await page.locator('[data-bf=status]').innerText()));
  assert(await page.evaluate(()=>{try{window.__buildingFleet.seek(window.__buildingFleet.model_duration_s+.001);return false;}catch{return true;}}));
  report.seek_limited_to_recording=true;
  report.recording_endpoint_visible=true;report.sampled_timeline=times;report.received_projection=true;report.experimental_notice=notice;
  await page.evaluate(()=>{window.__buildingFleet.seek(30);window.__buildingFleet.follow('BF04');});
  assert.equal(await page.evaluate(()=>window.__buildingFleet.instance_count),20);
  await page.evaluate(()=>window.__buildingFleet.stopFollowing());report.follow=true;
  assert.equal((await page.evaluate(id=>window.__buildingWalkthrough.command(id,'EG'),normal.elevator.object_id)).status,'rejected_busy');
  const door=program.room_route_object_ids[0];assert(door);
  await page.evaluate(()=>{window.__buildingFleet.seek(1);window.__buildingFleet.play();});
  await page.evaluate(id=>window.__buildingWalkthrough.command(id,'close'),door);
  await page.waitForFunction(()=>window.__buildingFleet.frozen);
  const frozen=await page.evaluate(()=>window.__buildingFleet.time_s);
  assert(await page.locator('[data-bf=time]').isDisabled());
  await page.waitForTimeout(100);assert.equal(await page.evaluate(()=>window.__buildingFleet.time_s),frozen);
  await page.waitForFunction(id=>window.__buildingWalkthrough.objects.find(o=>o.id===id)?.state==='closed',door);
  const opened=await page.evaluate(id=>window.__buildingWalkthrough.command(id,'open'),door);
  assert(['accepted','already_in_state'].includes(opened.status));
  await page.waitForFunction(()=>!window.__buildingFleet.frozen);
  await page.evaluate(()=>window.__buildingFleet.pause());report.route_door_freeze=true;
  const cameras=[],cameraTime=Math.min(60,program.duration_s),cameraRoom=view.controlRoom(program.received_messages,cameraTime);
  await page.evaluate(t=>window.__buildingFleet.seek(t),cameraTime);
  for(const row of program.trajectories){
   const perception=cameraRoom.vehicles[row.vehicle_id]?.perception;assert(perception);
   await page.locator('[data-bf=vehicle]').selectOption(row.vehicle_id);
   const result=await page.evaluate(()=>{const c=document.querySelector('[data-bf=camera]'),d=c.getContext('2d').getImageData(0,0,c.width,c.height).data,colors=new Set();let opaque=0;for(let i=0;i<d.length;i+=4){colors.add((d[i]<<16)|(d[i+1]<<8)|d[i+2]);if(d[i+3])opaque++;}return{reference:c.dataset.captureRef,colors:colors.size,opaque_pixels:opaque};});
   assert.equal(result.reference,perception.camera_ref);assert(result.opaque_pixels>0);cameras.push({vehicle_id:row.vehicle_id,...result});
  }
  // A parked camera can legitimately face a uniform wall. This smoke check
  // verifies capture ownership and actual pixels, not twenty distinct views.
  assert(cameras.some(c=>c.colors>2));
  report.camera_quality_qualified=false;
  report.camera_framebuffers=cameras;
  await page.evaluate(()=>{window.__buildingFleet.pause();window.__buildingFleet.seek(60);window.__buildingFleet.follow('BF04');});
  await page.screenshot({path:path.join(path.dirname(target),'preview-desktop.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});assert(await page.locator('[data-bf=play]').isVisible());
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2));
  await page.screenshot({path:path.join(path.dirname(target),'preview-mobile.png'),fullPage:true});
  assert.deepEqual(errors,[]);report.errors=errors;report.passed=true;
 }finally{fs.writeFileSync(path.join(path.dirname(target),'preview-browser-check.json'),JSON.stringify(report,null,2)+'\n');await browser.close();}
 console.log('Experimental preview smoke check passed. Full fleet qualification remains open.');
})().catch(error=>{console.error(error);process.exitCode=1;});
