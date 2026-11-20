/* Walking is a geometric transition, never a teleport or a shaft bypass. */
const assert=require('node:assert/strict');
const {createLiftSession}=require('../scripts/walkthrough_interaction.js');
const states={KG:-4250,EG:0,OG1:4250,OG2:8500,OG3:12750};
const object={config:{id:'lift',joint:{type:'prismatic',axis:[0,0,1]},states,reference_state:'EG'},state:'EG',targetState:'EG',value:0,transition:null};
const ports=Object.entries(states).flatMap(([level_id,z_mm])=>['outward','inward'].map(side=>({
  id:level_id+side,level_id,z_mm,side,active:side===(['EG','KG'].includes(level_id)?'inward':'outward'),
  plane_x_mm:side==='outward'?0:4000,wall_thickness_mm:200,height_mm:2200,
  exit_eye_mm:[side==='outward'?-400:4400,2000,z_mm+1600],cabin_entry_mm:[2000,2000,z_mm+1600]})));
const config={object_id:'lift',speed_mm_s:1200,ports,cabin_bounds_mm:{min:[900,900,-100],max:[3100,3100,2300]},
  shaft_bounds_mm:{min:[500,500,-4500],max:[3500,3500,15500]},
  walking:{cabin_interior_bounds_mm:{min:[1000,1000,0],max:[3000,3000,2200]},opening_y_mm:[1800,2200]}};
let doorsOpen=true;
const cycle={get busy(){return !doorsOpen;},canUsePort:p=>doorsOpen&&p.level_id===object.state};
const session=createLiftSession(config,object,()=>({status:'accepted'}),cycle);
const guarded=p=>session.walkingBarriers().some(b=>p.every((v,i)=>v>b.min[i]&&v<b.max[i]));
assert(guarded([600,2000,1600]),'Inactive EG side stays guarded');
assert(!guarded([3200,2000,1600]),'Docked active doorway is open for walking');
assert(guarded([3200,2000,5850]),'Absent upper-floor cabin does not open the shaft');
assert(guarded([2000,2000,3000]),'Shaft above cabin stays guarded');
assert(guarded([3200,1500,1600]),'Sideways entry outside the aperture stays guarded');
session.walkStep([3100,2000,1600],[2990,2000,1600]);
assert(session.boarded);assert.deepEqual(session.attachedEye(),[2990,2000,1600]);
assert(session.doorwayOccupied(session.attachedEye(),150),'Partial entry blocks door closure');
session.walkStep([2990,2000,1600],[2100,2400,1600]);
assert.deepEqual(session.attachedEye(),[2100,2400,1600],'Cabin walking retains exact lateral position');
assert(!session.doorwayOccupied(session.attachedEye(),150));
doorsOpen=false;assert(!session.walkingAllowed);assert(guarded([3200,2000,1600]));
session.walkStep([2100,2400,1600],[2200,2400,1600]);
assert.deepEqual(session.attachedEye(),[2100,2400,1600],'No walking while doors move');
object.state='moving';object.value=6400;object.transition={};
assert.equal(session.displayLevel(),'OG2');
assert.deepEqual(session.attachedEye(),[2100,2400,8000],'Absolute cabin attachment preserves the walked offset');
object.state='OG3';object.targetState='OG3';object.value=12750;object.transition=null;doorsOpen=true;
assert.equal(session.displayLevel(),'OG3');assert(session.walkingAllowed);
assert(guarded([3200,2000,14350]),'Upper inward port stays guarded');
assert(!guarded([600,2000,14350]),'Correct upper exit opens');
session.walkStep([2100,2400,14350],[900,2000,14350]);assert(session.boarded,'Stay attached through the threshold');
const result=session.walkStep([900,2000,14350],[-110,2000,14350]);
assert.equal(result.status,'walked_out');assert(!session.boarded);assert.equal(session.attachedEye(),null);
session.walkStep([3100,2000,14350],[2990,2000,14350]);assert(!session.boarded,'No boarding through inactive side');
session.walkStep([1100,800,14350],[1100,1200,14350]);assert(!session.boarded,'No boarding through cabin side wall');
console.log('Passed continuous lift entry/exit state, offset preservation, guarded shaft, doorway interlock and height-derived display checks.');
