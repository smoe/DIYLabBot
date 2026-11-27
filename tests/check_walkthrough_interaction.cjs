// Synthetic geometry contracts for native-triangle picking; no browser or CAD.
const assert=require('node:assert/strict');
const {createPicker,createStairWalker,createCameraCollider}=require('../scripts/walkthrough_interaction.js');
function mesh(parts){
  const positions=[],indices=[],groups=[];
  for(const part of parts){const base=positions.length/3,start=indices.length;for(const p of part.points)positions.push(...p);indices.push(...part.indices.map(i=>i+base));groups.push({id:part.id,role:part.role,index_start:start,index_count:part.indices.length,bounds_mm:{min:[0,1,2].map(k=>Math.min(...part.points.map(p=>p[k]))*1000),max:[0,1,2].map(k=>Math.max(...part.points.map(p=>p[k]))*1000)}});}
  return {positions:new Float32Array(positions),indices:new Uint32Array(indices),groups};
}
const panel=(id,z)=>({id,points:[[-1,-1,z],[1,-1,z],[1,1,z],[-1,1,z]],indices:[0,1,2,0,2,3]});
const targetForBody=id=>id.startsWith('Door')?id:null;
let picker=createPicker(mesh([panel('Door',1)]));
assert.equal(picker.pick([0,0,0],[0,0,1],{reach:2,targetForBody}).target_id,'Door');
assert.equal(picker.pick([0,0,0],[0,0,1],{reach:.9,targetForBody}),null,'Beyond reach is rejected');
assert.equal(picker.pick([0,0,0],[0,0,-1],{reach:2,targetForBody}),null,'Behind the camera is rejected');
picker=createPicker(mesh([panel('Door',1),panel('Wall',.5)]));
assert.equal(picker.pick([0,0,0],[0,0,1],{reach:2,targetForBody}),null,'A visible wall occludes the door');
assert.equal(picker.pick([0,0,0],[0,0,1],{reach:2,targetForBody,includeReference:true}),null,'Reference doorway cannot bypass a wall');
const miss={id:'WallTriangle',points:[[-1,-1,.5],[1,-1,.5],[1,.2,.5]],indices:[0,1,2]};
picker=createPicker(mesh([panel('Door',1),miss]));
assert.equal(picker.pick([0,0,0],[0,0,1],{reach:2,targetForBody}).target_id,'Door','Bounds alone must not hide an actual opening');
picker=createPicker(mesh([panel('DoorFar',2),panel('DoorNear',1)]));
assert.equal(picker.pick([0,0,0],[0,0,1],{reach:3,targetForBody}).target_id,'DoorNear');
const upright={id:'Door',points:[[1,-1,-1],[1,1,-1],[1,1,1],[1,-1,1]],indices:[0,1,2,0,2,3]};
const matrix=new Float32Array([0,1,0,0,-1,0,0,0,0,0,1,0,0,-2,0,1]);
picker=createPicker(mesh([upright]));const options={reach:3,targetForBody,transformForBody:()=>matrix};
assert.equal(picker.pick([0,0,0],[1,0,0],options),null,'Mouse must hit the current open leaf');
assert.equal(picker.pick([0,-2,0],[0,1,0],options).target_id,'Door','Picking follows a rotated leaf');
assert.equal(picker.pick([0,0,0],[1,0,0],{...options,includeReference:true}).target_id,'Door','Space can close an open doorway');
// Native equipment and room-door meshes can start open. Their keyboard target
// is the derived closed surface, not an invisible copy at the native open pose.
const movedNative={id:'Door',points:upright.points.map(p=>[p[0],p[1]+5,p[2]]),indices:upright.indices};
picker=createPicker(mesh([movedNative]));
const closedReference=new Float32Array([1,0,0,0,0,1,0,0,0,0,1,0,0,-5,0,1]);
assert.equal(picker.pick([0,0,0],[1,0,0],{reach:3,targetForBody,includeReference:true,referenceTransformForBody:()=>closedReference}).target_id,'Door');
assert.equal(picker.pick([0,0,0],[1,0,0],{reach:3,targetForBody}),null,'Mouse cannot click the invisible closed reference');
console.log('Passed native-mesh picking checks, including closed references derived from initially open meshes.');

const surface=(id,role,x1,x2,z)=>({id,role,
  points:[[x1,0,z],[x2,0,z],[x2,1,z],[x1,1,z]],indices:[0,1,2,0,2,3]});
const approach=surface('Approach','concept_storey_slab',0,1,0);
const tread=surface('Tread','concept_continuous_stair',1,1.2,.2);
const landing=surface('Landing','concept_external_stair_landing',1.2,2,.4);
const roof=surface('Roof','concept_roof_access_deck',2,3,.4);
const stairMesh=mesh([approach,tread,landing,roof]);
const eyeHeight=1.6,walker=createStairWalker({...stairMesh,eyeHeight});
const createCollider=geometry=>createCameraCollider({...geometry,radius:.15,margin:.002,iterations:32,slides:4});
const collider=createCollider(stairMesh);
const ground=[.96,.5,eyeHeight];
const top=walker.move(ground,[.28,0,0],collider);
assert(Math.abs(top.eye[2]-2)<1e-6,'Fast travel follows the individual tread before reaching the landing');
assert.equal(top.support.body_id,'Landing');
assert.equal(top.support.roof,true,'A coplanar upper landing can report the native roof level');
const back=walker.move(top.eye,[-.28,0,0],collider);
assert(Math.abs(back.eye[2]-eyeHeight)<1e-6,'The tread also leads down to the approach');
const unsupported=walker.move([1.1,.97,1.8],[0,.1,0],collider);
assert(unsupported.eye[1]<=1&&unsupported.contacts.length>0,'A horizontal stair move cannot step into a gap');
const manual=walker.move(ground,[.08,0,.1],collider);
assert(Math.abs(manual.eye[2]-1.7)<1e-6&&manual.support===undefined,
  'Explicit vertical movement remains independent of automatic stair following');
const blockedMesh=mesh([approach,tread,landing,roof,{...upright,id:'LandingDoor'}]);
const doorCollider=createCollider(blockedMesh);
const doorShift=new Float32Array([1,0,0,0,0,1,0,0,0,0,1,0,.25,0,1.6,1]);
const blocked=walker.move(ground,[.32,0,0],doorCollider,{transformsForBody:id=>id==='LandingDoor'?[doorShift]:[null]});
assert(blocked.eye[0]<1.1&&blocked.contacts.includes('LandingDoor'),'Stair following respects a transformed blocking door');
console.log('Passed stair transition, missing support, roof level, explicit-height and door collision checks.');
