const fs=require('node:fs'),assert=require('node:assert/strict'),path=require('node:path');
const root=path.resolve(__dirname,'..');
const {createCameraCollider,jointMatrix}=require(root+'/scripts/walkthrough_interaction.js');
const html=fs.readFileSync(process.argv[2],'utf8'),data=JSON.parse(html.match(/<script id="walkthrough-data" type="application\/json">([\s\S]*?)<\/script>/)[1]);
const mesh=data.scenes.building,decode=(s,T)=>{const b=Buffer.from(s,'base64');return new T(b.buffer.slice(b.byteOffset,b.byteOffset+b.byteLength));};
const positions=decode(mesh.positions_base64,Float32Array),indices=decode(mesh.indices_base64,Uint32Array);for(let i=0;i<positions.length;i++)positions[i]/=1000;
const objects=new Map(data.objects.map(o=>[o.id,o])),owners=new Map();for(const o of data.objects)for(const b of o.moving_body_ids)owners.set(b,o);
function multiply(a,b){return Array.from({length:16},(_,i)=>{const row=i%4,col=Math.floor(i/4);return [0,1,2,3].reduce((s,k)=>s+a[k*4+row]*b[col*4+k],0);});}
function matrix(o,state=o.initial_state||o.reference_state){const m=jointMatrix(o.joint,o.states[state],o.states[o.reference_state]);return o.parent_object_id?multiply(matrix(objects.get(o.parent_object_id)),m):m;}
function point(p,m){return [0,1,2].map(i=>m[i]*p[0]+m[i+4]*p[1]+m[i+8]*p[2]+m[i+12]);}
const transforms=new Map([...owners].map(([id,o])=>[id,[matrix(o)]]));
const nav=data.navigation,groups=mesh.groups.filter(g=>!data.hidden_body_ids.building.includes(g.id));
const collider=createCameraCollider({positions,indices,groups,radius:nav.camera_radius_mm/1000,margin:nav.contact_margin_mm/1000,iterations:nav.max_contact_iterations,slides:nav.max_slides});
const options={transformsForBody:id=>transforms.get(id)||[null]};
const evidence={doors:[],viewpoints:[]};
for(const id of ['OG3.D3_026.Door','OG3.D3_027.Door','OG3.D3_002N.Door','OG3.D3_003A.Door','OG3.D3_003B.Door']){
 const o=objects.get(id);assert(o,id);const g=groups.find(g=>g.id===o.moving_body_ids[0]);assert(g);
 const reference=g.bounds_mm.min.map((v,i)=>(v+g.bounds_mm.max[i])/2000),centre=point(reference,matrix(o,'closed'));centre[2]=o.joint.origin_mm[2]/1000+1.6;
 const n=o.front,start=centre.map((v,i)=>v+n[i]*.6),delta=n.map(v=>-v*1.2);const now=performance.now(),result=collider.move(start,delta,options),side=result.eye.reduce((sum,v,i)=>sum+(v-centre[i])*n[i],0);
 if(o.initial_state==='closed')assert(side>0,`${id}: camera crossed the closed door`);
 else assert(side<0,`${id}: open laboratory/office doorway unexpectedly blocked: ${result.contacts}`);
 evidence.doors.push({id,initial_state:o.initial_state,reference_state:o.reference_state,remaining_side_m:side,contacts:result.contacts,query_ms:performance.now()-now});
}
for(const stop of data.stops){const p=stop.eye_mm.map(v=>v/1000),result=collider.move(p,[.005,0,0],options);evidence.viewpoints.push({id:stop.id,contacts:result.contacts});assert(result.eye.every(Number.isFinite));}
const closed=data.objects.filter(o=>o.mechanism==='room_door'&&o.initial_state==='closed');assert.equal(closed.length,15);
// Adversarial case: even if landing leaves are fully open at an unoccupied
// upper floor, ordinary camera translation must not board or enter the shaft.
for(const o of data.objects.filter(o=>o.mechanism==='lift_door'))for(const id of o.moving_body_ids)transforms.set(id,[matrix(o,'open')]);
const port=data.elevator.ports.find(p=>p.level_id==='OG3'&&p.active),bounds=data.elevator.shaft_bounds_mm;
assert(bounds,'Full source-derived shaft envelope');
const start=port.exit_eye_mm.map(v=>v/1000),end=port.cabin_entry_mm.map(v=>v/1000);
const shaftResult=collider.move(start,end.map((v,i)=>v-start[i]),{...options,barriers:[{id:'shaft',min:bounds.min.map(v=>v/1000),max:bounds.max.map(v=>v/1000)}]});
assert(shaftResult.contacts.includes('shaft'),'Unboarded movement into the upper shaft is blocked with doors open');
evidence.absent_cabin_upper_floor={contacts:shaftResult.contacts,eye:shaftResult.eye};
evidence.closed_access_doors=closed.map(o=>o.id);evidence.native_bodies=groups.length;evidence.passed=true;
fs.writeFileSync(path.join(path.dirname(path.resolve(process.argv[2])),'camera-native-contacts.json'),JSON.stringify(evidence,null,2)+'\n');console.log(JSON.stringify(evidence,null,2));
