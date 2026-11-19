// Usage: node tests/check_walkthrough_route.cjs <downloaded-or-local-index.html>
// Exercises actual native contacts and the existing lift state machine. No CAD.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const engine=require('../scripts/walkthrough_interaction.js');
const file=path.resolve(process.argv[2]),html=fs.readFileSync(file),source=fs.readFileSync(path.join(__dirname,'../scripts/walkthrough_interaction.js'));
assert(html.includes(source),'The downloaded page must embed this exact collision/lift engine');
const data=JSON.parse(html.toString('utf8').match(/<script id="walkthrough-data" type="application\/json">([\s\S]*?)<\/script>/)[1]);
const mesh=data.scenes.building;
function decode(s,T){const b=Buffer.from(s,'base64');return new T(b.buffer.slice(b.byteOffset,b.byteOffset+b.byteLength));}
const positions=decode(mesh.positions_base64,Float32Array),indices=decode(mesh.indices_base64,Uint32Array);for(let i=0;i<positions.length;i++)positions[i]/=1000;
const objects=new Map(data.objects.map(config=>{const state=config.initial_state||config.reference_state;return [config.id,{config,state,targetState:state,value:config.states[state],transition:null}];}));
const initialRoomStates=new Map([...objects].filter(([,o])=>o.config.mechanism==='room_door').map(([id,o])=>[id,o.state]));
const owners=new Map();for(const o of objects.values())for(const b of o.config.moving_body_ids)owners.set(b,o);
const multiply=(a,b)=>Array.from({length:16},(_,i)=>[0,1,2,3].reduce((s,k)=>s+a[k*4+i%4]*b[Math.floor(i/4)*4+k],0));
function matrix(o,closed=false){const m=engine.jointMatrix(o.config.joint,closed?o.config.states.closed:o.value,o.config.states[o.config.reference_state]);return o.config.parent_object_id?multiply(matrix(objects.get(o.config.parent_object_id)),m):m;}
const nav=data.navigation,collider=engine.createCameraCollider({positions,indices,groups:mesh.groups.filter(g=>!data.hidden_body_ids.building.includes(g.id)),radius:nav.camera_radius_mm/1000,margin:nav.contact_margin_mm/1000,iterations:nav.max_contact_iterations,slides:nav.max_slides});
const bounds=data.elevator.shaft_bounds_mm,barriers=[{id:'UnboardedLiftShaft',min:bounds.min.map(v=>v/1000),max:bounds.max.map(v=>v/1000)}];
const cabin=objects.get(data.elevator.object_id),phd=data.stops.find(s=>s.id==='phd'),lab=data.stops.find(s=>s.id==='lab');
let eye=phd.eye_mm.map(v=>v/1000),time=0;const trace=[],events=[];
function record(kind,extra={}){trace.push({time_s:time,kind,eye_mm:eye.map(v=>v*1000),...extra});}
function drive(id,name){const o=objects.get(id),target=o?.config.commands[name]?.target_state;if(!target)return {status:'unknown_target'};if(o.transition)return {status:'rejected_busy'};if(o.state===target)return {status:'already_in_state'};o.targetState=target;o.state=id===data.elevator.object_id?'moving':target==='open'?'opening':'closing';o.transition={from:o.value,to:o.config.states[target],start:time,duration:id===data.elevator.object_id?1.875*Math.abs(o.config.states[target]-o.value)/data.elevator.speed_mm_s:o.config.duration_s};return {status:'accepted'};}
const cycle=engine.createLiftDoorCycle(data.elevator,objects,drive),session=engine.createLiftSession(data.elevator,cabin,cycle.request,cycle);
function advance(dt){time+=dt;for(const o of objects.values())if(o.transition){const t=o.transition,u=Math.min(1,(time-t.start)/t.duration),s=u*u*u*(10+u*(-15+6*u));o.value=t.from+(t.to-t.from)*s;if(u===1){o.value=t.to;o.state=o.targetState;o.transition=null;}}cycle.advance();if(session.boarded)eye=session.attachedEye().map(v=>v/1000);}
function settle(){for(let i=0;cycle.busy||cabin.transition;i++){assert(i<20000,'Lift cycle did not settle');advance(1/60);record(session.boarded?'ride':'wait');}}
function walk(label,target){const goal=target.map(v=>v/1000);assert(Math.abs(eye[2]-goal[2])<1e-6,'Walking must stay on its floor');let stalled=0,contacts=new Set();const start=[...eye];
 for(let i=0;Math.hypot(goal[0]-eye[0],goal[1]-eye[1])>.005;i++){
  assert(i<10000,'Bounded walking duration');const delta=goal.map((v,k)=>k===2?0:v-eye[k]),distance=Math.hypot(...delta),step=Math.min(distance,data.settings.walk_speed_mm_s/1000/60),v=delta.map(x=>x/distance*step),before=[...eye],transforms=new Map();
  for(const [id,o] of owners){const values=[matrix(o)];if(o.transition&&['room_door','lift_door'].includes(o.config.mechanism))values.push(matrix(o,true));transforms.set(id,values);}
  const result=collider.move(eye,v,{barriers,transformsForBody:id=>transforms.get(id)||[null]});eye=result.eye;for(const id of result.contacts)contacts.add(id);advance(1/60);record('walk',{leg:label,contacts:result.contacts});
  stalled=Math.hypot(...eye.map((x,k)=>x-before[k]))<1e-7?stalled+1:0;
  assert(stalled<5,`${label}: blocked at ${JSON.stringify(eye.map(v=>v*1000))} by ${[...contacts]}`);
 }
 events.push({label,start_mm:start.map(v=>v*1000),target_mm:target,end_mm:eye.map(v=>v*1000),contacts:[...contacts]});
}
function outside(stop){const d=stop.target_mm.map((v,i)=>i===2?0:v-stop.eye_mm[i]),n=Math.hypot(...d);return stop.eye_mm.map((v,i)=>i===2?v:v-d[i]/n*(stop.anchor.inset_mm+500));}
cycle.initialize();settle();record('start');
const officeOutside=outside(phd),labOutside=outside(lab);
walk('office 3.002 to corridor',officeOutside);walk('corridor to laboratory entrance',labOutside);walk('enter laboratory 3.003',lab.eye_mm);walk('leave laboratory',labOutside);
const corridor=mesh.groups.find(g=>g.id==='OG3__Area_C3_020'),x=(corridor.bounds_mm.min[0]+corridor.bounds_mm.max[0])/2;
const upper=data.elevator.ports.find(p=>p.active&&p.level_id==='OG3'),ground=data.elevator.ports.find(p=>p.active&&p.level_id==='EG');
walk('corridor corner',[x,labOutside[1],upper.exit_eye_mm[2]]);walk('corridor to lift',[x,upper.exit_eye_mm[1],upper.exit_eye_mm[2]]);walk('lift call point',upper.exit_eye_mm);
assert.equal(session.call(upper.id).status,'accepted');settle();assert.equal(cabin.state,'OG3');assert.equal(session.boarded,false);
assert.equal(session.board(upper.id,eye.map(v=>v*1000),data.interaction.reach_mm).status,'accepted');eye=session.attachedEye().map(v=>v/1000);record('board');
assert.equal(session.select('EG').status,'accepted');settle();assert.equal(cabin.state,'EG');assert(cycle.canUsePort(ground));
const exit=session.exit(ground.side);assert.equal(exit.status,'accepted');assert.equal(session.boarded,false);eye=exit.eye_mm.map(v=>v/1000);record('exit');
const away=ground.exit_eye_mm.map((v,i)=>i===2?v:v+(v-ground.cabin_entry_mm[i])*.5/Math.hypot(...ground.exit_eye_mm.slice(0,2).map((x,k)=>x-ground.cabin_entry_mm[k]))*1000);
walk('walk away from EG lift',away);
const floorPicker=engine.createPicker({positions,indices,groups:mesh.groups.filter(g=>g.role==='concept_storey_slab')});
const floorBodies=new Set();
for(const sample of trace.filter(s=>s.kind==='walk')){
 const below=floorPicker.pick(sample.eye_mm.map(v=>v/1000),[0,0,-1],{reach:data.settings.eye_height_mm/1000+.01,targetForBody:id=>id,maxDistance:data.settings.eye_height_mm/1000+.01});
 assert(below,'An actual native floor must support every walked route sample');floorBodies.add(below.body_id);
}
assert([...initialRoomStates].every(([id,state])=>objects.get(id).state===state),'The entire route preserves room-door states');
const officeAndLabOpen=['OG3.D3_002N.Door','OG3.D3_003A.Door'].every(id=>objects.get(id).state==='open');
const technicalClosed=[...objects.values()].filter(o=>o.config.mechanism==='room_door'&&o.config.initial_state==='closed').every(o=>o.state==='closed');
assert(officeAndLabOpen&&technicalClosed,'Open passages and closed technical accesses stay distinct');
const report={passed:true,html_sha256:crypto.createHash('sha256').update(html).digest('hex'),events,trace,initial_doors_preserved:true,office_and_laboratory_open:officeAndLabOpen,technical_accesses_closed:technicalClosed,lift_destination:cabin.state,boarded_after_exit:session.boarded};
report.supporting_native_floor_bodies=[...floorBodies];
fs.writeFileSync(path.join(path.dirname(file),'complete-route-check.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify({...report,trace:`${trace.length} sampled positions`},null,2));
