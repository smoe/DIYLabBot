// BF01 pure playback, received projection and opt-in adapter checks.
// These fixtures are not exported, native-qualified or browser fleet programs.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),cp=require('node:child_process'),vm=require('node:vm');
const root=path.resolve(__dirname,'..'),view=require('../scripts/building_fleet_view.js');
const point=(t,p,v=[0,0,0],a=[0,0,0])=>({time_s:t,pose_mm_rad:p,velocity_mm_rad_s:v,acceleration_mm_rad_s2:a});
const points=[point(0,[0,0,0],[100,20,.2]),point(2,[200,60,.5],[30,5,-.1])],curve=view.compileCurve(points);
assert.deepEqual(curve(0),points[0].pose_mm_rad);curve(2).forEach((v,i)=>assert(Math.abs(v-points[1].pose_mm_rad[i])<1e-10));
const python=cp.execFileSync('python3',['-c',"import json,sys;sys.path.insert(0,'scripts');import tr01_floor_motion as f;p=json.loads(sys.argv[1]);c=f.motion.Curve(f.canonical(p));print(json.dumps([c.evaluate(t)[f.F[0]]for t in [0,.1,.5,1,1.9,2]]))",JSON.stringify(points)],{cwd:root,encoding:'utf8'});
JSON.parse(python).forEach((p,i)=>p.forEach((v,k)=>assert(Math.abs(curve([0,.1,.5,1,1.9,2][i])[k]-v)<1e-9,'JS playback must match shared Python quintic')));
assert.throws(()=>view.compileCurve([point(1,[0,0,0]),point(0,[1,0,0])]),/Increasing/);
const liftFixture={lift_initial_state:{z_mm:0,door_values:{A:100,B:0}},lift_schedule:[{kind:'doors',start_s:0,end_s:1,target_values:{A:0}},{kind:'travel',start_s:1,end_s:3,from_z_mm:0,to_z_mm:12750},{kind:'doors',start_s:3,end_s:4,target_values:{B:100}}]};
assert.equal(view.liftAt(liftFixture,2).z_mm,6375);assert.equal(view.liftAt(liftFixture,4).door_values.B,100);assert.equal(view.liftAt(liftFixture,2).door_values.A,0);
const messages=[
 {seq:1,vehicle_id:'BF01',sent_s:0,received_s:1,kind:'heartbeat',delivered_late:false,payload:{pose_mm:[1,2,0],level:'EG',area:'R0_004',mode:'drive',speed_mm_s:100}},
 {seq:2,vehicle_id:'BF01',sent_s:1,received_s:5,kind:'event',delivered_late:true,payload:{event:'inspection_completed',details:{level:'OG3',area:'R3_003'}}},
 {seq:3,vehicle_id:'BF01',sent_s:5,received_s:6,kind:'event',delivered_late:false,payload:{event:'lift_call',details:{start_port:'EG',destination_port:'OG3'}}}
];
const projection=new view.ReceivedProjection(messages);
assert.deepEqual(projection.at(.9).vehicles,{},'Undelivered states must not appear');
assert.equal(projection.at(2).vehicles.BF01.heartbeat.area,'R0_004');assert.equal(projection.at(2).vehicles.BF01.message_age_s,2,'Buffered sender timestamps govern message age');assert.deepEqual(projection.at(2).coverage,[]);
assert.deepEqual(projection.at(6).coverage,[{level:'OG3',area:'R3_003'}]);assert.deepEqual(projection.at(.9).coverage,[],'Seeking rebuilds received data only');
const duplicateStream=[...messages,messages[2]],received=view.controlRoom(duplicateStream,7);
assert.equal(received.events.length,2);assert.equal(received.duplicates,1,'Duplicates are counted and discarded');
const pythonRoom=JSON.parse(cp.execFileSync('python3',['-c',"import json,sys;sys.path.insert(0,'scripts');from building_fleet_comm import ReceivedControlRoom;r=ReceivedControlRoom();rows=json.loads(sys.argv[1]);[r.receive(m)for m in sorted(rows,key=lambda m:(m['received_s'],m['vehicle_id'],m['seq']))if m['received_s']<=7];print(json.dumps(r.snapshot(7)))",JSON.stringify(duplicateStream)],{cwd:root,encoding:'utf8'}));
assert.deepEqual(received,pythonRoom,'Browser control-room reducer must match independent Python receiver');
const mutableSnapshot=projection.at(7);mutableSnapshot.vehicles.BF01.heartbeat.pose_mm[0]=999;assert.equal(projection.at(7).vehicles.BF01.heartbeat.pose_mm[0],1,'Snapshots cannot modify received projection state');
assert.equal(view.targetLabel({level:'OG1',area:'R3_003',basis:'template_area_use_unconfirmed'}),'OG1 · Vorlagefläche R3_003 (Nutzung unbestätigt)');
assert.equal(view.stateLabel('capacity_wait'),'wartet auf zulässigen Folgeauftrag');
assert.equal(view.stateLabel('capacity_home'),'vorläufig am eigenen Stellplatz');
const capacityMessage={...messages[0],received_s:5,payload:{...messages[0].payload,mode:'capacity_home'}};
assert.equal(view.controlRoom([capacityMessage],4).vehicles.BF01,undefined,'Provisional home state must not appear before receipt');
assert.equal(view.controlRoom([capacityMessage],5).vehicles.BF01.heartbeat.mode,'capacity_home');
assert.equal(view.controlRoom([capacityMessage],5).events.length,0,'A provisional home heartbeat is not final home completion');
assert.equal(view.receivedLift(projection.at(5.9).events).queue.length,0);assert.equal(view.receivedLift(projection.at(7).events).queue[0].vehicle_id,'BF01','Lift queue is built only from received service events');
const validationFixture={...liftFixture,format:'solidcraftbot.building-fleet-program/1',complete:true,duration_s:4,levels:[{id:'EG',z_mm:0}],targets:[],room_route_object_ids:[],camera_captures:{},trajectories:Array.from({length:20},(_,i)=>({vehicle_id:'BF'+String(i+1).padStart(2,'0'),episodes:[{level_id:'EG',mode:'hold',start_s:0,end_s:4,attached_cabin:false,points:[point(0,[0,0,0]),point(4,[0,0,0])]}]})),received_messages:[]};
assert.throws(()=>view.validateProgram({...validationFixture,complete:false}),/Complete compiled/);
assert.throws(()=>view.validateProgram({...validationFixture,received_messages:[{vehicle_id:'BF01',seq:1,kind:'perception',received_s:1,sent_s:0,payload:{camera_ref:'missing'}}]}),/Missing delivered camera/);
const captureFixture={...validationFixture,camera_captures:{C:{captured_s:0,level_id:'EG',pose_xyz_mm:[0,0,0],yaw_rad:0}},received_messages:[{vehicle_id:'BF01',seq:1,kind:'perception',received_s:1,sent_s:0,payload:{captured_s:0,level:'EG',pose_mm:[10,0,0],camera_ref:'C'}}]};
assert.throws(()=>view.validateProgram(captureFixture),/sender-reported pose/);
const ownCapture=JSON.parse(JSON.stringify(captureFixture));ownCapture.received_messages[0].payload.pose_mm=[0,0,0];ownCapture.received_messages.push({...ownCapture.received_messages[0],vehicle_id:'BF02'});assert.throws(()=>view.validateProgram(ownCapture),/another vehicle/);
const adapterPython=`import sys,json
sys.path.insert(0,'scripts')
import build_building_fleet_demo as b
from pathlib import Path
p=Path('scripts/building_walkthrough_viewer.html');raw=p.read_bytes();text=raw.decode()
assert b.opt_in_html(text)==text
out=b.opt_in_html(text,{'test':'<script>'})
assert p.read_bytes()==raw
assert r'\\u003cscript>' in out
assert '{"test":"<script>"}' not in out
try:b.completed_program({'format':'solidcraftbot.building-fleet-program/1','complete':False})
except ValueError:pass
else:raise AssertionError('incomplete program admitted')
# This transform-only fixture is explicitly incomplete and never built or
# launched as a qualified fleet page. Original file bytes remain untouched.
import copy,gzip,tempfile
fields={key:None for key in b.PLAYBACK_FIELDS}
fields.update(format='projection-fixture-only',complete=False,seed=1,duration_s=1,
 levels=[{'id':'EG','z_mm':0}],room_route_object_ids=[],targets=[],homes={},
 trajectories=[{'vehicle_id':'BF01','episodes':[{'points':[{'time_s':0,'pose_mm_rad':[1,2,3],'velocity_mm_rad_s':[4,5,6],'acceleration_mm_rad_s2':[7,8,9]}]}]}],
 received_messages=[{'original_payload':[1,2,3]}],camera_captures={'own':{'captured_s':.125,'pose_xyz_mm':[1,2,3],'yaw_rad':.5}},
 lift_schedule=[{'kind':'doors','start_s':0,'end_s':.65,'level':'EG','target':'closed'}],
 qualification={'simulation_only':True},statistics={'original':123},source_files_sha256={'fixture':'unqualified'},artifacts={})
fields.update(geometry_checks=[{'opaque_audit':'x'*1000000}],resource_catalog={'audit_only':True},perception_checks={'audit_only':True})
manifest={'objects':[{'id':'D','mechanism':'lift_door','states':{'closed':0,'open':100}}],
 'elevator':{'reference_z_mm':0,'reference_level':'EG','ports':[{'active':True,'level_id':'EG','door_object_ids':['D']}]}}
serialized=json.dumps(fields,separators=(',',':')).encode()
with tempfile.TemporaryDirectory(dir='exports')as directory:
 original=Path(directory)/'incomplete-fixture-only.json';original.write_bytes(serialized)
 playback=b.view_program(json.loads(original.read_bytes()),manifest)
 assert original.read_bytes()==serialized
 assert 'geometry_checks'not in playback and 'resource_catalog'not in playback and 'perception_checks'not in playback
 for key in('trajectories','received_messages','camera_captures','targets','statistics','qualification','source_files_sha256'):
  assert playback[key]==fields[key]
  assert json.dumps(playback[key],separators=(',',':'))==json.dumps(fields[key],separators=(',',':'))
 restored=json.loads(gzip.decompress(gzip.compress(json.dumps(playback).encode())))
 assert restored['trajectories']==fields['trajectories']
 assert restored['received_messages']==fields['received_messages']
 assert restored['camera_captures']==fields['camera_captures']
 assert playback['lift_schedule'][0]['target_values']=={'D':0}
 assert fields['lift_schedule'][0].get('target_values')is None
 assert b.html_budget(b.ADDITIONAL_HTML_TARGET_BYTES)['budget_met']is True
 assert b.html_budget(b.ADDITIONAL_HTML_TARGET_BYTES+1)['budget_met']is False
 assert b.opt_in_html(text)==text and p.read_bytes()==raw
print(json.dumps({'html':out}))`;
const adapterJSON=cp.execFileSync('python3',['-c',adapterPython],{cwd:root,encoding:'utf8',maxBuffer:2*1024*1024});
const adapted=JSON.parse(adapterJSON).html;for(const match of adapted.matchAll(/<script([^>]*)>([\s\S]*?)<\/script>/g)){if(!match[1].includes('application/json'))new vm.Script(match[2]);}
assert(adapted.includes('elevator[key]=()=>fleetBusy()'),'Physical floor/call controls must not bypass fleet ownership');assert(adapted.includes('elevator.walkStep=()=>fleetBusy()'),'Walking cannot create an uncompiled passenger');assert(adapted.includes('if(!fleetActive)liftDoors?.initialize()'),'Compiled lift owns initialization');assert(adapted.includes('fleetHooks.draw'));
assert(view.mount.toString().includes('createFramebuffer'),'Camera inset renders the native scene into a framebuffer');assert(fs.readFileSync(path.join(root,'scripts/building_fleet_view.js'),'utf8').includes('drawElementsInstanced'));
console.log('Passed shared quintic/lift replay, Python-equivalent received-only reducer, capture ownership/pose, source labels, current manual-control guards, generated syntax, lossless playback projection/target reporting and normal-byte-preservation checks. Actual full-program WebGL verification remains separate.');

// Optional actual WebGL branch: <index.html> [playwright-module] [chrome].
// No dependency is installed and absence is an error, never a skipped pass.
if(process.argv[2]) (async()=>{
 const zlib=require('node:zlib'),crypto=require('node:crypto'),{pathToFileURL}=require('node:url'),{chromium}=require(process.argv[3]||'playwright');
 const target=path.resolve(process.argv[2]),bytes=fs.readFileSync(target),html=bytes.toString(),payload=JSON.parse(html.match(/<script id="building-fleet-data" type="application\/json">([\s\S]*?)<\/script>/)[1]),program=JSON.parse(zlib.gunzipSync(Buffer.from(payload.program_gzip_base64,'base64'))),normal=JSON.parse(html.match(/<script id="walkthrough-data" type="application\/json">([\s\S]*?)<\/script>/)[1]);
 const gpu=process.env.SOLIDCRAFTBOT_WALKTHROUGH_GPU||'software';assert(['metal','software'].includes(gpu));
 const browser=await chromium.launch({headless:true,...(process.argv[4]?{executablePath:process.argv[4]}:{}),args:gpu==='metal'?['--enable-gpu','--enable-webgl','--ignore-gpu-blocklist','--use-gl=angle','--use-angle=metal']:['--enable-webgl','--ignore-gpu-blocklist','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 const page=await browser.newPage({viewport:{width:1400,height:1000},reducedMotion:'no-preference'}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 const report={passed:false,html_sha256:crypto.createHash('sha256').update(bytes).digest('hex'),browser:{engine:'chromium',version:browser.version(),gpu_profile:gpu},scope:'Actual opt-in WebGL instancing, compiled timeline, received-message projection, camera framebuffer, follow and command/freeze checks. Controlled seek/clock verifies semantics, not real-time performance.'};
 try{
  await page.goto(pathToFileURL(target).href,{timeout:120000});await page.waitForFunction(()=>window.__buildingFleet?.ready,null,{timeout:120000});
  assert.equal(await page.evaluate(()=>window.__buildingFleet.instance_count),20);await page.waitForFunction(()=>window.__buildingFleet.draw_calls>0);const gpuInstances=await page.evaluate(()=>window.__buildingFleet.renderer_stats);assert.equal(gpuInstances.last_instance_count,20);assert(gpuInstances.native_mesh_groups>=34);report.native_instances=gpuInstances;
  const models=view.trajectories(program),duration=program.duration_s||Math.max(...program.trajectories.flatMap(t=>t.episodes.map(e=>e.end_s))),times=[0,duration,...program.lift_schedule.flatMap(r=>[r.start_s,(r.start_s+r.end_s)/2,r.end_s])];
  for(const t of [...new Set(times)].sort((a,b)=>a-b)){
   const actual=await page.evaluate(t=>{window.__buildingFleet.seek(t);return{states:window.__buildingFleet.states,room:window.__buildingFleet.control_room,elevator:window.__buildingWalkthrough.elevator};},t),lift=view.liftAt(program,t);
   models.forEach((m,i)=>{const expected=m.at(t,lift);actual.states[i].pose_xyz_mm.forEach((v,k)=>assert(Math.abs(v-expected.pose_xyz_mm[k])<1e-6));assert(Math.abs(actual.states[i].yaw_rad-expected.yaw_rad)<1e-8);});
   assert(Math.abs(actual.elevator.value_mm-lift.z_mm)<1e-6,'Cabin z comes only from the compiled schedule');assert.deepEqual(actual.room,view.controlRoom(program.received_messages,t),'Control room is only the received-message projection');
  }
  report.timeline_to_end=true;report.received_projection=true;
  assert.equal((await page.evaluate(id=>window.__buildingWalkthrough.command(id,'EG'),normal.elevator.object_id)).status,'rejected_busy');
  if(normal.robots?.length)assert.equal((await page.evaluate(id=>window.__buildingWalkthrough.robotCommand(id,'demo'),normal.robots[0].id)).status,'rejected_busy');report.manual_lift_and_robot_commands_rejected=true;
  const door=program.room_route_object_ids[0];assert(door,'A complete program has at least one source route door');await page.evaluate(()=>{window.__buildingFleet.seek(1);window.__buildingFleet.play();});const close=await page.evaluate(id=>window.__buildingWalkthrough.command(id,'close'),door);assert(['accepted','already_in_state'].includes(close.status));
  await page.waitForFunction(()=>window.__buildingFleet.frozen);const stopped=await page.evaluate(()=>window.__buildingFleet.time_s);assert(await page.locator('[data-bf=time]').isDisabled());assert(await page.evaluate(()=>{try{window.__buildingFleet.seek(2);return false;}catch(error){return /route doors/.test(error.message);}}),'A route-door freeze also blocks manual timeline changes');await page.waitForTimeout(150);assert.equal(await page.evaluate(()=>window.__buildingFleet.time_s),stopped);await page.evaluate(id=>window.__buildingWalkthrough.command(id,'open'),door);await page.waitForFunction(()=>!window.__buildingFleet.frozen);await page.waitForFunction(t=>window.__buildingFleet.time_s>t,stopped);await page.evaluate(()=>window.__buildingFleet.pause());report.route_door_freeze_and_resume=true;
  const aboard=program.trajectories.flatMap(r=>r.episodes.filter(e=>e.attached_cabin).map(e=>({id:r.vehicle_id,e})));assert(aboard.length,'Full building mission must include lift rides');const ride=aboard[0],t=(ride.e.start_s+ride.e.end_s)/2;
  await page.evaluate(({id,t})=>{window.__buildingFleet.pause();window.__buildingFleet.seek(t);window.__buildingFleet.follow(id);},{id:ride.id,t});const before=await page.evaluate(()=>window.__buildingWalkthrough.camera);await page.locator('#walkthrough-canvas').focus();await page.keyboard.press('w');const after=await page.evaluate(()=>window.__buildingWalkthrough.camera);assert.deepEqual(after.eye_mm,before.eye_mm,'Follow disables free movement');assert(Math.abs(after.eye_mm[2]-(view.liftAt(program,t).z_mm+normal.settings.eye_height_mm))<1e-6);await page.evaluate(()=>window.__buildingFleet.stopFollowing());report.follow_including_lift=true;
  const cameraChecks=[],hashes=new Set();
  for(const row of program.trajectories){
   const perceptions=program.received_messages.filter(m=>m.vehicle_id===row.vehicle_id&&m.kind==='perception');assert(perceptions.length,'Every vehicle reports captures');let chosen=null;
   for(const f of [.2,.4,.6,.8,1]){const message=perceptions[Math.min(perceptions.length-1,Math.floor((perceptions.length-1)*f))];await page.evaluate(t=>window.__buildingFleet.seek(t),Math.min(duration,message.received_s+1e-6));await page.locator('[data-bf=vehicle]').selectOption(row.vehicle_id);
    const pixels=await page.evaluate(()=>{const c=document.querySelector('[data-bf=camera]'),d=c.getContext('2d').getImageData(0,0,c.width,c.height).data,colors=new Set();let hash=2166136261;for(let i=0;i<d.length;i+=4){colors.add((d[i]<<16)|(d[i+1]<<8)|d[i+2]);for(let k=0;k<3;k++)hash=Math.imul(hash^d[i+k],16777619)>>>0;}return{hash,colors:colors.size,reference:c.dataset.captureRef};});assert(pixels.colors>2,'Camera framebuffer must contain actual scene variation');chosen={vehicle_id:row.vehicle_id,time_s:message.received_s,...pixels};if(!hashes.has(pixels.hash))break;
   }
   assert(!hashes.has(chosen.hash),'Each vehicle must demonstrate a distinct real synthetic camera viewpoint');hashes.add(chosen.hash);cameraChecks.push(chosen);
  }
  report.camera_framebuffers=cameraChecks;const rewound=await page.evaluate(()=>{window.__buildingFleet.seek(0);return[...document.querySelectorAll('[data-bf=camera],[data-bf=mosaic] canvas')].map(c=>c.dataset.captureRef).filter(Boolean);});const receivedAtZero=new Set(program.received_messages.filter(m=>m.kind==='perception'&&m.received_s<=0).map(m=>m.payload.camera_ref));assert(rewound.every(ref=>receivedAtZero.has(ref)),'Seeking backward must clear all future unreceived camera pixels');report.camera_seek_keeps_received_boundary=true;await page.evaluate(()=>{window.__buildingFleet.pause();window.__buildingFleet.seek(window.__buildingFleet.model_duration_s);});await page.screenshot({path:path.join(path.dirname(target),'fleet-desktop.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});await page.waitForTimeout(100);assert(await page.locator('[data-bf=play]').isVisible());assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2));await page.screenshot({path:path.join(path.dirname(target),'fleet-mobile.png'),fullPage:true});report.mobile_controls=true;assert.deepEqual(errors,[]);report.errors=errors;report.passed=true;
 }finally{fs.writeFileSync(path.join(path.dirname(target),'browser-check.json'),JSON.stringify(report,null,2)+'\n');await browser.close();}
 console.log('Passed actual BF01 browser checks; see browser-check.json and screenshots.');
})().catch(error=>{console.error(error);process.exitCode=1;});
