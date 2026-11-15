// Synthetic geometry contracts for native-triangle picking; no browser or CAD.
const assert=require('node:assert/strict');
const {createPicker}=require('../scripts/walkthrough_interaction.js');
function mesh(parts){
  const positions=[],indices=[],groups=[];
  for(const part of parts){const base=positions.length/3,start=indices.length;for(const p of part.points)positions.push(...p);indices.push(...part.indices.map(i=>i+base));groups.push({id:part.id,index_start:start,index_count:part.indices.length,bounds_mm:{min:[0,1,2].map(k=>Math.min(...part.points.map(p=>p[k]))*1000),max:[0,1,2].map(k=>Math.max(...part.points.map(p=>p[k]))*1000)}});}
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
console.log('Passed 10 native-mesh picking checks: reach, direction, occlusion, exact triangles, nearest target, rotated leaf, reference doorway');
