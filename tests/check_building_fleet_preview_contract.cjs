// Pure preview admission; these synthetic fixtures are not fleet evidence.
const assert=require('node:assert/strict'),view=require('../scripts/building_fleet_view.js');
const point=t=>({time_s:t,pose_mm_rad:[0,0,0],velocity_mm_rad_s:[0,0,0],acceleration_mm_rad_s2:[0,0,0]});
const program={format:'solidcraftbot.building-fleet-program/1',complete:false,duration_s:1,
 levels:[{id:'EG',z_mm:0}],targets:[],room_route_object_ids:[],received_messages:[],camera_captures:{},
 lift_initial_state:{z_mm:0,door_values:{}},lift_schedule:[],
 trajectories:Array.from({length:20},(_,i)=>({vehicle_id:'BF'+String(i+1).padStart(2,'0'),
  episodes:[{level_id:'EG',start_s:0,end_s:1,attached_cabin:false,points:[point(0),point(1)]}]}))};
const hash='a'.repeat(64),preview={format:'solidcraftbot.building-fleet-experimental-preview/1',
 recorded_end_s:1,playback_end_s:1,program_sha256:hash,original_program_sha256:hash,playback_sha256:'b'.repeat(64),
 interruption:{path:'exports/fixture/runtime-failure.json',sha256:'c'.repeat(64)},
 qualification:{full_mission_coverage_verified:false,native_full_program_verified:false,
 independent_export_verified:false,hardware_or_real_safety_qualified:false}};
assert.throws(()=>view.validateProgram(program),/Complete compiled/);
assert.equal(view.validateProgram(program,preview,hash),program);
assert.equal(program.complete,false,'Explicit preview never flips complete');
for(const change of [p=>p.recorded_end_s=.5,p=>p.playback_end_s=2,p=>p.program_sha256='d'.repeat(64),
 p=>p.original_program_sha256='e'.repeat(64),p=>p.playback_sha256='',p=>delete p.interruption,
 ...Object.keys(preview.qualification).map(key=>p=>p.qualification[key]=true)]){
 const changed=structuredClone(preview);change(changed);
 assert.throws(()=>view.validateProgram(program,changed,hash));
}
assert.throws(()=>view.validateProgram({...program,complete:true},preview,hash),/Explicit experimental/);
const broken=structuredClone(program);broken.trajectories[19].episodes[0].end_s=.5;
assert.throws(()=>view.validateProgram(broken,preview,hash),/Episode PVA/);
assert.equal(view.validateProgram({...program,complete:true}).complete,true,'Default full-program admission remains available');
console.log('Passed strict default rejection, explicit partial provenance/end/false-qualification admission, unchanged complete flag and endpoint mismatch checks.');
