// Interlocks are checked against both current and intended states, including
// the first and last instant of an animation and reduced-motion completion.
const assert=require('node:assert/strict');
const {commandBlockers,createLiftDoorCycle,createLiftSession}=require('../scripts/walkthrough_interaction.js');
const objects=new Map();
function object(id,states,state,commands={}){
  const o={config:{id,states,commands},state,targetState:state,value:states[state],transition:null};objects.set(id,o);return o;
}
const door=object('FreezerDoor',{closed:0,open:90},'open',{close:{requires:[]}});
const drawers=Array.from({length:6},(_,i)=>{
  const id='Drawer'+i;door.config.commands.close.requires.push({object_id:id,state:'closed'});
  return object(id,{closed:0,open:350},'closed',{open:{requires:[{object_id:door.config.id,state:'open'}]},close:{}});
});
assert.deepEqual(commandBlockers(objects,'FreezerDoor','close'),[]);
for(const drawer of drawers){
  drawer.targetState='open';drawer.transition={};
  assert.deepEqual(commandBlockers(objects,'FreezerDoor','close'),[drawer.config.id],'Opening intent blocks closure even at zero displacement');
  drawer.targetState='closed';drawer.value=1e-12;
  assert.deepEqual(commandBlockers(objects,'FreezerDoor','close'),[drawer.config.id],'Almost closed is still not closed');
  drawer.value=0;
  assert.deepEqual(commandBlockers(objects,'FreezerDoor','close'),[drawer.config.id],'Completion is required');
  drawer.transition=null;
}
door.targetState='closed';door.transition={};
for(const drawer of drawers)assert.deepEqual(commandBlockers(objects,drawer.config.id,'open'),['FreezerDoor']);
door.transition=null;door.state='closed';door.value=0;
for(const drawer of drawers)assert.deepEqual(commandBlockers(objects,drawer.config.id,'open'),['FreezerDoor']);
door.state=door.targetState='open';door.value=90;
for(const drawer of drawers)assert.deepEqual(commandBlockers(objects,drawer.config.id,'open'),[]);

objects.clear();
const cabin=object('Lift',{KG:-4250,EG:0,OG3:12750},'EG');
cabin.config.joint={type:'prismatic',axis:[0,0,1]};cabin.config.reference_state='EG';
const ports=[],doors=[];
for(const side of ['outward','inward'])for(const tag of ['Low','High']){
  const d=object('Cabin_'+side+tag,{closed:0,open:500},'closed');d.config.mechanism='lift_door';doors.push(d);
}
for(const level of ['KG','EG','OG3'])for(const side of ['outward','inward']){
  const active=level==='EG'||(level==='KG'?side==='inward':side==='outward'),ids=[];
  if(active)for(const tag of ['Low','High']){
    const d=object(level+side+tag,{closed:0,open:500},'closed');d.config.mechanism='lift_door';doors.push(d);
    ids.push(d.config.id,'Cabin_'+side+tag);
  }
  ports.push({id:level+side,level_id:level,side,active,door_object_ids:ids,cabin_entry_mm:[0,0,cabin.config.states[level]+1600],exit_eye_mm:[1000,0,cabin.config.states[level]+1600]});
}
const calls=[];
function drive(id,state){const o=objects.get(id);calls.push([id,state]);if(state==='close')state='closed';if(o.transition)return {status:'rejected_busy'};if(o.state===state)return {status:'already_in_state'};
  o.targetState=state;o.state='moving';o.transition={to:o.config.states[state]};return {status:'accepted'};}
function finish(o){o.value=o.config.states[o.targetState];o.state=o.targetState;o.transition=null;}
const config={object_id:'Lift',ports,speed_mm_s:1200,cabin_bounds_mm:{min:[-1000,-1000,-90],max:[1000,1000,2300]}};
const cycle=createLiftDoorCycle(config,objects,drive);
const session=createLiftSession(config,cabin,cycle.request,cycle);
cycle.initialize();assert.equal(cycle.phase,'opening');assert.equal(session.board('EGoutward',[1000,0,1600],2500).status,'rejected_busy');
doors.forEach(finish);cycle.advance();assert.equal(cycle.phase,'idle');
assert(cycle.canUsePort(ports.find(p=>p.id==='EGoutward')));
assert.equal(session.board('EGoutward',[1000,0,1600],2500).status,'accepted');
for(const destination of ['OG3','KG','EG']){
  const initialZ=cabin.value;
  assert.equal(session.select(destination).status,'accepted');assert.equal(cycle.phase,'closing');
  assert.equal(cabin.value,initialZ);assert.equal(cabin.transition,null,'Cabin cannot move while any door is closing');
  assert.equal(session.select('KG').status,'rejected_busy');assert.equal(session.exit('outward').status,'rejected_busy');
  const moving=doors.filter(o=>o.transition);moving.slice(1).forEach(finish);cycle.advance();assert.equal(cycle.phase,'closing');
  finish(moving[0]);cycle.advance();assert.equal(cycle.phase,'travelling');
  cabin.value=(initialZ+cabin.config.states[destination])/2;cycle.advance();
  assert(doors.every(o=>o.state==='closed'),'No door opens between floors');
  finish(cabin);cycle.advance();assert.equal(cycle.phase,'opening');
  const expected=new Set(ports.filter(p=>p.active&&p.level_id===destination).flatMap(p=>p.door_object_ids));
  assert.deepEqual(new Set(doors.filter(o=>o.targetState==='open').map(o=>o.config.id)),expected);
  assert.equal(session.exit(destination==='KG'?'inward':'outward').status,'rejected_busy');
  doors.forEach(finish);cycle.advance();assert.equal(cycle.phase,'idle');
  assert.deepEqual(session.attachedEye(),[0,0,cabin.config.states[destination]+1600]);
}
assert.equal(session.exit('inward').status,'accepted');
const groundPorts=ports.filter(p=>p.level_id==='EG'&&p.active);
assert.equal(groundPorts.length,2);
for(const callPort of groundPorts){
  // Park elsewhere before calling from each of the ground-floor sides.
  cabin.state=cabin.targetState='OG3';cabin.value=cabin.config.states.OG3;
  for(const door of doors){door.state=door.targetState='closed';door.value=0;door.transition=null;}
  assert.equal(session.call(callPort.id).status,'accepted');
  assert.equal(cycle.phase,'travelling');
  assert(doors.every(o=>o.state==='closed'));
  finish(cabin);cycle.advance();
  assert.equal(cycle.phase,'opening');
  const expected=groundPorts.flatMap(p=>p.door_object_ids).sort();
  assert.equal(expected.length,8,'Both cabin and landing door pairs open at EG');
  assert.deepEqual(doors.filter(o=>o.targetState==='open').map(o=>o.config.id).sort(),expected);
  const moving=doors.filter(o=>o.transition);
  moving.slice(1).forEach(finish);cycle.advance();
  assert(groundPorts.every(port=>!cycle.canUsePort(port)),'No threshold opens until both sides settle');
  finish(moving[0]);cycle.advance();
  assert(groundPorts.every(port=>cycle.canUsePort(port)));
}
console.log('Passed all six freezer drawer interlocks, in-flight conflicts, lift door sequencing, inactive exits and repeated floor changes.');
