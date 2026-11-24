// Received live-view boundary checks; not a native motion or network qualification.
const assert=require('node:assert/strict');
const live=require('../scripts/building_fleet_live_view.js');
const states=()=>live.IDS.map((id,index)=>({id,pose_xyz_mm:[index*100,1000,0],yaw_rad:0,level_id:'EG',mode:'patrol',attached_cabin:false}));
function snapshot(){const current=states(),historical=states();return{format:'solidcraftbot.building-fleet-live-snapshot/1',session_id:'local-session',model_time_s:10,paused:false,states:current,lift:{z_mm:0,door_values:{door:1}},targets:[{level:'EG',area:'R0_001'}],jobs:[],coverage:[],camera_frames:[{vehicle_id:'BF01',camera_ref:'BF01-camera-1',captured_s:8,received_s:9,pose_xyz_mm:[...historical[0].pose_xyz_mm],yaw_rad:0,level_id:'EG',states:historical,lift:{z_mm:0,door_values:{door:1}}}]};}
assert.equal(live.validateSnapshot(snapshot()).model_time_s,10);
const rejected=mutate=>{const value=snapshot();mutate(value);assert.throws(()=>live.validateSnapshot(value));};
rejected(s=>s.states.pop());
rejected(s=>s.states[1].id='BF01');
rejected(s=>s.states[0].pose_xyz_mm[0]=Infinity);
rejected(s=>s.states[0].attached_cabin='false');
rejected(s=>s.lift.door_values.door=NaN);
rejected(s=>s.session_id='');
rejected(s=>s.model_time_s=-1);
rejected(s=>s.camera_frames[0].received_s=11);
rejected(s=>s.camera_frames[0].captured_s=9.5);
rejected(s=>s.camera_frames[0].states[0].pose_xyz_mm[0]++);
rejected(s=>s.camera_frames[0].level_id='OG3');
rejected(s=>s.camera_frames.push(structuredClone(s.camera_frames[0])));
rejected(s=>s.jobs.push({request_id:'j',status:'queued',pickup:null,delivery:{level:'EG',area:'R0_001'}}));
rejected(s=>s.coverage.push({level:'EG',area:'R0_001',visits:1,last_visit_s:11}));
assert.equal(live.endpoint('/api/state','http://127.0.0.1:8080/bf01/'),'http://127.0.0.1:8080/api/state');
assert.throws(()=>live.endpoint('https://example.com/api/state','http://127.0.0.1:8080/'));
assert.throws(()=>live.endpoint('file:///api/state','file:///index.html'));
assert.equal(live.targetKey({level:'OG3',area:'R3_003'}),'OG3/R3_003');
const locations={
 EG:{label:'EG',z_mm:0,areas:[{label:'Anlieferung',polygon_mm:[[-1,0],[50,0],[50,2000],[-1,2000]]}]},
 OG3:{label:'3. OG',z_mm:9000,areas:[{label:'Labor 3.003',polygon_mm:[[-1,0],[50,0],[50,2000],[-1,2000]]}]},
};
const views=snapshot();
Object.assign(views.states[0],{level_id:'OG3',pose_xyz_mm:[0,1000,9000]});
assert.equal(live.vehicleLocation(views.camera_frames[0].states[0],locations),'EG · Anlieferung');
assert.equal(live.vehicleLocation(views.states[0],locations),'3. OG · Labor 3.003');
assert.equal(live.vehicleLocation({...views.states[0],attached_cabin:true},locations),'Aufzug · 3. OG');
assert.equal(live.vehicleLocation({...views.states[0],attached_cabin:true,pose_xyz_mm:[0,1000,4500]},locations),'Aufzug · zwischen den Geschossen');
assert.equal(live.vehicleLocation(views.states[1],locations),'EG');
const window={start_s:9,end_s:10,levels:{EG:{z_mm:0}},lift_initial_state:{z_mm:0,door_values:{door:0}},lift_schedule:[{kind:'doors',start_s:8,end_s:12,from_values:{door:0},target_values:{door:1}}],trajectories:live.IDS.map(vehicle_id=>({vehicle_id,episodes:[{start_s:9,end_s:10,level_id:'EG',mode:'patrol',attached_cabin:false,points:[9,10].map(time_s=>({time_s,pose_mm_rad:[(time_s-9)*1000,0,0],velocity_mm_rad_s:[1000,0,0],acceleration_mm_rad_s2:[0,0,0]}))}]}))};
const curve=live.compileWindow(window,10);assert.equal(curve.at(9.5).states[0].pose_xyz_mm[0],500);assert.equal(curve.at(9.5).lift.door_values.door,.27520751953125);
assert.throws(()=>curve.at(10.001));assert.throws(()=>curve.at(8.999));
assert.throws(()=>live.compileWindow({...window,end_s:10.001},10));
const discontinuous=structuredClone(window);discontinuous.trajectories[0].episodes[0].points.at(-1).time_s=10.01;assert.throws(()=>live.compileWindow(discontinuous,10));
console.log('Active BF01 received-state/camera boundary checks passed.');
