// Independent native-triangle fixtures: no CAD, browser, or network required.
const assert=require('node:assert/strict');
const {createCameraCollider,jointMatrix}=require('../scripts/walkthrough_interaction.js');
function collider(triangles,extra={}){
  const positions=Float64Array.from(triangles.flat(2));
  const vertices=triangles.flat(),indices=Uint32Array.from(vertices.map((_,i)=>i));
  const lo=[0,1,2].map(i=>Math.min(...vertices.map(v=>v[i]))*1000),hi=[0,1,2].map(i=>Math.max(...vertices.map(v=>v[i]))*1000);
  return createCameraCollider({positions,indices,groups:[{id:'fixture',bounds_mm:{min:lo,max:hi},index_start:0,index_count:indices.length}],
    radius:.15,margin:.001,iterations:64,slides:4,...extra});
}
const wall=[[[0,-2,-2],[0,2,-2],[0,2,2]],[[0,-2,-2],[0,2,2],[0,-2,2]]];
const hit=collider(wall).move([-1,0,0],[100,0,0]);
assert(hit.eye[0]<=-.151+1e-7,'Large movement cannot tunnel through a zero-thickness wall');
assert(hit.eye[0]>-.152);assert(hit.contacts.includes('fixture'));
const along=collider(wall).move([-1,0,0],[2,1,0]);
assert(along.eye[0]<=-.151+1e-7&&Math.abs(along.eye[1]-1)<1e-6,'Movement slides along a wall');
const away=collider(wall).move([-.151,0,0],[-1,1,0]);
assert(away.eye[0]<-1&&away.eye[1]===1,'Touching a wall must permit retreat');
const floor=wall.map(t=>t.map(([x,y,z])=>[y,z,x]));
assert(collider(floor).move([0,0,2],[0,0,-100]).eye[2]>=.151-1e-7,'Vertical controls cannot cross a floor');
// The actual opening is a gap between triangles, not its enclosing body box.
const left=wall.map(t=>t.map(([x,y,z])=>[x,y-3,z])),right=wall.map(t=>t.map(([x,y,z])=>[x,y+3,z]));
assert(collider([...left,...right]).move([-1,0,0],[2,0,0]).eye[0]===1,'An open doorway remains traversable');
const corner=wall.map(t=>t.map(([x,y,z])=>[y,x,z]));
const stopped=collider([...wall,...corner]).move([-1,-1,0],[10,10,0]);
assert(stopped.eye[0]<=-.151+1e-7&&stopped.eye[1]<=-.151+1e-7,'Two walls constrain a corner');
// Move the native door away from its reference mesh, including a parent cabin.
const translation=new Float32Array([1,0,0,0,0,1,0,0,0,0,1,0,3,0,0,1]);
const moved=collider(wall).move([1,0,0],[100,0,0],{transformsForBody:()=>[translation]});
assert(moved.eye[0]<2.85&&moved.eye[0]>2.848,'Dynamic poses determine contact, not stale reference bounds');
const opening=jointMatrix({type:'revolute',origin_mm:[0,-2000,0],axis:[0,0,1]},90,0);
assert(collider(wall).move([-1,0,0],[2,0,0],{transformsForBody:()=>[opening]}).eye[0]===1,'A fully open hinged leaf clears its doorway');
const closing=collider(wall).move([-1,0,0],[2,0,0],{transformsForBody:()=>[opening,null]});
assert(closing.eye[0]<0,'A closing doorway remains guarded until completion');
const shaft={id:'shaft',min:[-.5,-.5,-5],max:[.5,.5,20]};
const empty=createCameraCollider({positions:[],indices:[],groups:[],radius:.15,margin:.001,iterations:64,slides:4});
assert(empty.move([-2,0,12],[20,0,0],{barriers:[shaft]}).eye[0]<=-.651+1e-7,'Absent cabin does not expose an enterable shaft');
assert(empty.move([0,0,30],[0,0,-100],{barriers:[shaft]}).eye[2]>=20.151-1e-7,'Vertical entry into the shaft is blocked too');
const edge=collider([[[0,0,0],[0,1,0],[0,0,1]]]).move([-1,-.1,.2],[2,0,0]);
assert(edge.contacts.length,'The sphere catches triangle edges missed by a centre ray');
const grazing=collider(wall).move([-.151,0,0],[0,1,0]);assert(Math.abs(grazing.eye[1]-1)<1e-7);
assert.throws(()=>collider(wall).move([NaN,0,0],[1,0,0]),/Finite/);
assert.throws(()=>collider(wall,{radius:-1}),/Invalid/);
console.log('Passed continuous camera contacts: tunnelling, sliding, corners, floors, open/closed moving doors, shaft exclusion and edges.');
