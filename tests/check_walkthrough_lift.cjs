// Presentation lift contracts: one cabin object, source units and passenger attachment.
const assert=require('node:assert/strict');
const {jointMatrix,createLiftSession,createPicker}=require('../scripts/walkthrough_interaction.js');
const I=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1];
const slider={type:'prismatic',origin_mm:[4000,5000,0],axis:[0,0,1],limits_mm:[-4250,12750]};
assert.deepEqual([...jointMatrix(slider,0,0)],I);
assert.deepEqual([...jointMatrix(slider,12750,0)],[1,0,0,0,0,1,0,0,0,0,1,0,0,0,12.75,1]);
assert.deepEqual([...jointMatrix(slider,-4250,0)],[1,0,0,0,0,1,0,0,0,0,1,0,0,0,-4.25,1]);
assert.deepEqual([...jointMatrix(slider,1234,1234)],I,'A closed/low reference slider has an exact identity matrix');
const hinge={type:'revolute',origin_mm:[1000,2000,0],axis:[0,0,1]};
const turn=jointMatrix(hinge,90,0);
const transformed=[turn[0]*2+turn[4]*2+turn[12],turn[1]*2+turn[5]*2+turn[13]];
assert(Math.abs(transformed[0]-1)<1e-6&&Math.abs(transformed[1]-3)<1e-6,'Hinge origin remains fixed and 90 degrees remain degrees');
assert.throws(()=>jointMatrix({...slider,type:'unknown'},0,0));
assert.throws(()=>jointMatrix(slider,NaN,0));
const picker=createPicker({positions:new Float32Array([-1,-1,0,1,-1,0,1,1,0,-1,1,0]),indices:new Uint32Array([0,1,2,0,2,3]),groups:[{id:'Cabin',index_start:0,index_count:6,bounds_mm:{min:[-1000,-1000,0],max:[1000,1000,0]}}]});
const picked=picker.pick([0,0,0],[0,0,1],{reach:5,targetForBody:()=> 'Lift',transformForBody:()=>jointMatrix(slider,4250,0)});
assert.equal(picked.target_id,'Lift');assert.equal(picked.distance_m,4.25,'Picking follows the moving cabin without moving its static source');
const states={KG:-4250,EG:0,OG1:4250,OG2:8500,OG3:12750};
const ports=[];
for(const [level_id,z_mm] of Object.entries(states))for(const side of ['outward','inward']){
 const active=level_id==='EG'||(level_id==='KG'?side==='inward':side==='outward');
 ports.push({id:`LiftPort_${level_id}_${side}`,level_id,side,active,z_mm,trigger_body_ids:active?[`Frame_${level_id}_${side}`]:[],cabin_entry_mm:[4000,5000,z_mm+1600],exit_eye_mm:[side==='outward'?2000:6000,5000,z_mm+1600]});
}
const object={config:{id:'BuildingLift.Cabin.Travel',joint:slider,states,reference_state:'EG'},state:'EG',targetState:'EG',value:0,transition:null};
const requests=[];
const lift=createLiftSession({object_id:object.config.id,reference_level:'EG',speed_mm_s:1200,cabin_bounds_mm:{min:[3000,4000,-90],max:[5000,6000,2330]},ports},object,level=>{
 requests.push(level);
 if(object.transition)return {status:'rejected_busy'};
 if(object.state===level)return {status:'already_in_state'};
 object.targetState=level;object.state='moving';object.transition={to:states[level]};return {status:'accepted'};
});
const arrive=level=>{object.state=level;object.value=states[level];object.transition=null;};
assert.equal(lift.select('OG3').status,'rejected_not_aboard');
assert.equal(lift.call('LiftPort_KG_outward').status,'unknown_target','Inactive ports cannot call the lift');
assert.equal(lift.nearby([2000,5000,1600],2500).id,'LiftPort_EG_outward');
assert.equal(lift.nearby([0,0,100000],2500),null,'Other floors and distant points do not expose boarding controls');
assert.equal(lift.board('LiftPort_OG3_outward',[2000,5000,14350],2500).status,'rejected_not_here');
assert.equal(lift.board('LiftPort_EG_outward',[0,0,0],100).status,'rejected_out_of_reach');
assert.equal(lift.board('LiftPort_EG_outward',[2000,5000,1600],NaN).status,'rejected_out_of_reach');
assert.equal(lift.board('LiftPort_EG_outward',[2000,5000,1600],2500).status,'accepted');
assert(lift.boarded);assert.deepEqual(lift.attachedEye(),[4000,5000,1600]);
assert.equal(lift.select('OG3').status,'accepted');assert.equal(requests.at(-1),'OG3');
assert.equal(lift.select('EG').status,'rejected_busy');assert.equal(lift.exit('outward').status,'rejected_busy');
object.value=6375;assert.deepEqual(lift.attachedEye(),[4000,5000,7975],'Passenger height follows absolute cabin position during travel');
arrive('OG3');assert.deepEqual(lift.attachedEye(),[4000,5000,14350]);
assert.equal(lift.exit('inward').status,'rejected_inactive_exit','An upper-floor inner cabin cut is not an allowed exit');
assert.equal(lift.call('LiftPort_OG3_outward').status,'rejected_aboard');
for(let n=0;n<100;n++){
 object.value=states.EG;assert.deepEqual(lift.attachedEye(),[4000,5000,1600]);
 object.value=states.OG3;assert.deepEqual(lift.attachedEye(),[4000,5000,14350]);
}
assert.deepEqual(lift.exit('outward').eye_mm,[2000,5000,14350]);assert(!lift.boarded);assert.equal(lift.attachedEye(),null);
assert.equal(lift.call('LiftPort_KG_inward').status,'accepted','An empty cabin can be called from another served floor');
arrive('KG');
assert.equal(lift.board('LiftPort_KG_inward',[6000,5000,-2650],2500).status,'accepted');
assert.equal(lift.exit('outward').status,'rejected_inactive_exit');
assert.equal(lift.select('EG').status,'accepted');arrive('EG');
assert.deepEqual(lift.attachedEye(),[4000,5000,1600]);
assert.deepEqual(lift.exit('inward').eye_mm,[6000,5000,1600]);
assert.deepEqual([...jointMatrix(slider,object.value,0)],I,'Return to EG restores the cabin reference matrix exactly');
console.log('Passed presentation lift checks: mm translation, exact reference, hinge regression, moving picking, active ports, boarding, busy rejection, absolute camera attachment, repeated trips and exits');
