// Real WebGL/UI check with controlled recorded-state HTTP fixtures, not a live-run proof.
// Usage: node check_building_fleet_live_browser.cjs <live.html> <recorded.html> <playwright> <chrome>
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),http=require('node:http'),zlib=require('node:zlib'),crypto=require('node:crypto');
const view=require('../scripts/building_fleet_view.js');
const {Curve}=require('../scripts/templates/quintic_motion.js');
const extract=(html,id)=>JSON.parse(html.match(new RegExp('<script id="'+id+'" type="application/json">([\\s\\S]*?)</script>'))[1]);
const sha=value=>crypto.createHash('sha256').update(value).digest('hex');
(async()=>{
 const target=path.resolve(process.argv[2]),recorded=extract(fs.readFileSync(process.argv[3],'utf8'),'building-fleet-data');
 const program=JSON.parse(zlib.gunzipSync(Buffer.from(recorded.program_gzip_base64,'base64'))),models=view.trajectories(program);
 let html=fs.readFileSync(target,'utf8');
 for(const [prefix,file]of [['/* BF01 compiled-program playback.','building_fleet_view.js'],['/* Active local BF01 presentation.','building_fleet_live_view.js'],['/* Local synthetic views and optional received','camera_monitor_wall.js']]){
  const start=html.indexOf(prefix),tail="})(typeof globalThis!=='undefined'?globalThis:this);",end=file==='camera_monitor_wall.js'?html.indexOf(tail,start)+tail.length:html.indexOf('</script>',start);assert(start>0&&end>start);html=html.slice(0,start)+fs.readFileSync(path.resolve(__dirname,'../scripts',file),'utf8').replaceAll('</script','<\\/script')+html.slice(end);
 }
 const payload=extract(html,'building-fleet-data'),normal=extract(html,'walkthrough-data');
 assert(payload.live&&payload.presentation.atrium_monitors);
 const captures=Object.values(view.controlRoom(program.received_messages,60).vehicles).filter(v=>v.perception).map(row=>row.perception);
 const at=t=>{const lift=view.liftAt(program,t);return{lift,states:models.map(model=>model.at(t,lift))};};
 const curves=new WeakMap();function pva(episode,time_s){if(!curves.has(episode))curves.set(episode,new Curve(episode.points,['pose_mm_rad','velocity_mm_rad_s','acceleration_mm_rad_s2']));const v=curves.get(episode).at(time_s);return{time_s,pose_mm_rad:v.p,velocity_mm_rad_s:v.v,acceleration_mm_rad_s2:v.a};}
 // The fixture restricts already recorded quintics using exact boundary PVA;
 // intermediate original knots stay present. Production supplies executed knots.
 function executedWindow(end){const start=Math.max(0,end-1);return{start_s:start,end_s:end,levels:program.levels,lift_initial_state:view.liftAt(program,start),lift_schedule:program.lift_schedule.filter(r=>r.start_s<end&&r.end_s>start).map(r=>({...r,...(r.kind==='doors'?{from_values:view.liftAt(program,r.start_s).door_values}:{})})),trajectories:program.trajectories.map(row=>({vehicle_id:row.vehicle_id,episodes:row.episodes.filter(e=>e.start_s<end&&e.end_s>start).map(e=>{const left=Math.max(start,e.start_s),right=Math.min(end,e.end_s),points=[pva(e,left),...e.points.filter(p=>p.time_s>left&&p.time_s<right),pva(e,right)];return{...e,start_s:left,end_s:right,points};})}))};}
 const cameraFrames=captures.map(p=>{const c=program.camera_captures[p.camera_ref],m=program.received_messages.find(m=>m.kind==='perception'&&m.payload.camera_ref===p.camera_ref);return{...c,vehicle_id:m.vehicle_id,camera_ref:p.camera_ref,received_s:m.received_s,...at(c.captured_s)};});
 assert.equal(cameraFrames.length,20);
 let time=60,paused=false,online=true,startup=2,failFirstJob=true;const jobs=new Map(),requests=[],controls=[];
 function state(){if(!paused)time=Math.round((time+.05)*1000)/1000;return{format:'solidcraftbot.building-fleet-live-snapshot/1',session_id:'controlled-browser-fixture',model_time_s:time,paused,...at(time),executed_window:executedWindow(time),targets:program.targets,jobs:[...jobs.values()],coverage:program.targets.map(t=>({...t,visits:0,last_visit_s:null})),camera_frames:cameraFrames,room_route_object_ids:program.room_route_object_ids,command_errors:[]};}
 const server=http.createServer(async(req,res)=>{
  if(req.url==='/'){res.writeHead(200,{'Content-Type':'text/html'});res.end(html);return;}
  let body='';for await(const chunk of req)body+=chunk;
  res.setHeader('Content-Type','application/json');res.setHeader('Cache-Control','no-store');
  if(req.url==='/api/state'){if(!online){res.writeHead(503);res.end(JSON.stringify({error:'controlled disconnect'}));return;}if(startup-->0){res.end(JSON.stringify({status:'starting',phase:'controlled initialization'}));return;}res.end(JSON.stringify(state()));return;}
  if(req.url==='/api/control'){const command=JSON.parse(body);controls.push(command.action);paused=command.action==='pause';res.end(JSON.stringify({status:'accepted'}));return;}
  if(req.url==='/api/jobs'){const job=JSON.parse(body);requests.push(job);jobs.set(job.request_id,{...job,status:'assigned',vehicle_id:'BF04',eta_s:2});if(failFirstJob){failFirstJob=false;res.writeHead(503);res.end(JSON.stringify({error:'controlled lost acknowledgement'}));return;}res.end(JSON.stringify({status:'accepted'}));return;}
  res.writeHead(404);res.end('{}');
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const url='http://127.0.0.1:'+server.address().port+'/';
 const {chromium}=require(process.argv[4]),browser=await chromium.launch({headless:true,executablePath:process.argv[5],args:['--enable-gpu','--enable-webgl','--ignore-gpu-blocklist','--use-gl=angle','--use-angle=metal']}),page=await browser.newPage({viewport:{width:1440,height:1100}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(/GL_INVALID|WebGL drawing error/.test(m.text()))errors.push(m.text());});
 const sources=['scripts/building_fleet_view.js','scripts/building_fleet_live_view.js','scripts/camera_monitor_wall.js','scripts/templates/quintic_motion.js','tests/check_building_fleet_live_browser.cjs'];
 const report={format:'solidcraftbot.building-fleet-live-fixture-browser-check/1',passed:false,fixture_only:true,input_html_sha256:sha(fs.readFileSync(target)),served_html_sha256:sha(html),recorded_fixture_html_sha256:sha(fs.readFileSync(process.argv[3])),source_files_sha256:Object.fromEntries(sources.map(name=>[name,sha(fs.readFileSync(path.resolve(__dirname,'..',name)))])),browser:{engine:'chromium',version:browser.version(),gpu_profile:'metal'},live_runner_motion_verified:false,native_motion_verified:false,scope:'Actual local HTML/WebGL controls and received camera presentation with a controlled recorded-state HTTP fixture. Current viewer modules are injected into the input HTML before serving; no active fleet geometry, route or native-motion qualification.'};
 try{
  await page.goto(url,{timeout:120000});await page.waitForFunction(()=>window.__buildingFleet?.ready||!document.querySelector('#walkthrough-error')?.hidden||/Verbindung unterbrochen/.test(document.querySelector('[data-bf=status]')?.textContent??''),null,{timeout:45000});
  assert.equal(await page.evaluate(()=>window.__buildingFleet?.ready),true,await page.locator('body').innerText());
  assert(await page.locator('#walkthrough-error').isHidden());assert.equal(await page.evaluate(()=>window.__buildingFleet.live),true);assert.equal(await page.evaluate(()=>window.__buildingFleet.instance_count),20);
  const interpolated=await page.evaluate(()=>({time:window.__buildingFleet.display_time_s,states:window.__buildingFleet.states,window:window.__buildingFleet.snapshot.executed_window}));assert(interpolated.time>=interpolated.window.start_s&&interpolated.time<=interpolated.window.end_s);const expected=at(interpolated.time).states;interpolated.states.forEach((s,i)=>s.pose_xyz_mm.forEach((v,k)=>assert(Math.abs(v-expected[i].pose_xyz_mm[k])<1e-6)));report.executed_pva_interpolation_matches_recorded_source=true;
  assert.equal(await page.evaluate(()=>window.__buildingWalkthrough.monitorWall.source_kind),'received_fleet_live');
  await page.evaluate(()=>window.__buildingFleet.pause());await page.waitForFunction(()=>window.__buildingFleet.snapshot.paused);
  const observed=await page.evaluate(()=>window.__buildingFleet.time_s);await page.waitForTimeout(350);assert.equal(await page.evaluate(()=>window.__buildingFleet.time_s),observed);assert(controls.includes('pause'));report.pause_observed_without_extrapolation=true;
  const captureResults=await page.evaluate(()=>Array.from({length:20},(_,i)=>window.__buildingWalkthrough.captureMonitor(i)));assert(captureResults.every(r=>r.status==='captured'));
  const wall=await page.evaluate(()=>window.__buildingWalkthrough.monitorWall);assert(wall.slots.every(s=>s.frame&&s.frame.received_s<=wall.model_time_s&&s.pixel_alpha_min===255));assert.equal(new Set(wall.slots.map(s=>s.frame.vehicle_id)).size,20);report.twenty_received_camera_sources=true;
  await page.locator('[data-bf=submit]').click();await page.waitForFunction(()=>/Bestätigung fehlt/.test(document.querySelector('[data-bf=request-status]').textContent));
  await page.locator('[data-bf=submit]').click();await page.waitForFunction(()=>/bestätigt/.test(document.querySelector('[data-bf=request-status]').textContent));
  assert.equal(requests.length,2);assert.equal(requests[0].request_id,requests[1].request_id);assert.equal(jobs.size,1);assert(/BF04/.test(await page.locator('[data-bf=jobs]').innerText()));report.idempotent_request_retry=true;report.assignment_visible=true;
  await page.evaluate(()=>window.__buildingFleet.play());await page.waitForFunction(t=>window.__buildingFleet.time_s>t,observed);assert(controls.includes('resume'));
  const door=program.room_route_object_ids[0],closed=await page.evaluate(id=>window.__buildingWalkthrough.command(id,'close'),door);assert(['accepted','already_in_state'].includes(closed.status));
  await page.waitForFunction(()=>window.__buildingFleet.snapshot.paused&&window.__buildingFleet.frozen,null,{timeout:30000});const resumes=controls.filter(v=>v==='resume').length;
  await page.evaluate(()=>window.__buildingFleet.play());assert.equal(controls.filter(v=>v==='resume').length,resumes,'A closed route door prevents engine resume');
  await page.evaluate(()=>window.__buildingFleet.pause());
  await page.waitForFunction(id=>window.__buildingWalkthrough.objects.find(o=>o.id===id)?.state==='closed',door,{timeout:30000});await page.evaluate(id=>window.__buildingWalkthrough.command(id,'open'),door);
  await page.waitForFunction(id=>window.__buildingWalkthrough.objects.find(o=>o.id===id)?.state==='open',door,{timeout:30000});await page.waitForTimeout(450);assert.equal(paused,true,'Manual pause survives opening a route door');report.route_door_controls_engine_and_respects_manual_pause=true;
  online=false;await page.waitForFunction(()=>!window.__buildingFleet.connected);const held=await page.evaluate(()=>window.__buildingFleet.time_s);await page.waitForTimeout(350);assert.equal(await page.evaluate(()=>window.__buildingFleet.time_s),held);report.disconnect_freezes_last_observation=true;
  online=true;await page.waitForFunction(()=>window.__buildingFleet.connected);assert(await page.locator('#walkthrough-error').isHidden());assert.deepEqual(errors,[]);
  report.renderer_stats=await page.evaluate(()=>window.__buildingFleet.renderer_stats);assert.equal(report.renderer_stats.last_instance_count,20);
  await page.locator('button[data-stop="camera-wall"]').click();await page.screenshot({path:path.join(path.dirname(target),'live-view-fixture-desktop.png'),fullPage:true});report.errors=errors;report.passed=true;
 }catch(error){report.failure={name:error.name,message:error.message};report.errors=errors;report.page_text=await page.locator('body').innerText().catch(()=>null);await page.screenshot({path:path.join(path.dirname(target),'live-view-fixture-failure.png'),fullPage:true}).catch(()=>{});throw error;}
 finally{fs.writeFileSync(path.join(path.dirname(target),'live-view-fixture-browser-check.json'),JSON.stringify(report,null,2)+'\n');await browser.close();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
 console.log('Active fleet WebGL/UI fixture check passed; active-run motion remains independently unverified.');
})().catch(error=>{console.error(error);process.exitCode=1;});
