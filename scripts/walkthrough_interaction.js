/* Exact native-mesh picking; all coordinates passed to the picker are metres. */
(function (root) {
  'use strict';
  const dot=(a,b)=>a[0]*b[0]+a[1]*b[1]+a[2]*b[2];
  const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
  const sub=(a,b)=>a.map((v,i)=>v-b[i]);
  function inverseRay(origin,direction,matrix){
    if(!matrix)return {origin,direction};
    const p=[origin[0]-matrix[12],origin[1]-matrix[13],origin[2]-matrix[14]];
    const rotate=v=>[0,4,8].map(i=>matrix[i]*v[0]+matrix[i+1]*v[1]+matrix[i+2]*v[2]);
    return {origin:rotate(p),direction:rotate(direction)};
  }
  function boundsHit(origin,direction,lo,hi,minDistance,maxDistance){
    let near=minDistance,far=maxDistance;
    for(let i=0;i<3;i++){
      if(Math.abs(direction[i])<1e-12){if(origin[i]<lo[i]||origin[i]>hi[i])return null;continue;}
      const a=(lo[i]-origin[i])/direction[i],b=(hi[i]-origin[i])/direction[i];
      near=Math.max(near,Math.min(a,b));far=Math.min(far,Math.max(a,b));if(near>far)return null;
    }
    return near;
  }
  function triangleHit(origin,direction,a,b,c,minDistance,maxDistance){
    const e1=sub(b,a),e2=sub(c,a),p=cross(direction,e2),det=dot(e1,p);
    if(Math.abs(det)<1e-12)return null;
    const inv=1/det,t=sub(origin,a),u=dot(t,p)*inv;if(u<0||u>1)return null;
    const q=cross(t,e1),v=dot(direction,q)*inv;if(v<0||u+v>1)return null;
    const distance=dot(e2,q)*inv;
    return distance>=minDistance&&distance<=maxDistance?distance:null;
  }
  function createPicker({positions,indices,groups}){
    const bodies=groups.map(group=>({group,lo:group.bounds_mm.min.map(v=>v/1000-1e-5),hi:group.bounds_mm.max.map(v=>v/1000+1e-5)}));
    const vertex=index=>[positions[index*3],positions[index*3+1],positions[index*3+2]];
    function nearest(origin,direction,{transformForBody=()=>null,referenceTransformForBody=()=>null,targetForBody=()=>null,minDistance=0,maxDistance=Infinity,referenceOnly=false}={}){
      const candidates=[];
      for(const body of bodies){
        const target=targetForBody(body.group.id);if(referenceOnly&&!target)continue;
        const ray=inverseRay(origin,direction,referenceOnly?referenceTransformForBody(body.group.id):transformForBody(body.group.id));
        const entry=boundsHit(ray.origin,ray.direction,body.lo,body.hi,minDistance,maxDistance);
        if(entry!==null)candidates.push({...body,ray,entry,target});
      }
      candidates.sort((a,b)=>a.entry-b.entry);let closest=null,limit=maxDistance;
      for(const candidate of candidates){
        if(candidate.entry>limit)break;
        const group=candidate.group;
        for(let i=group.index_start;i<group.index_start+group.index_count;i+=3){
          const distance=triangleHit(candidate.ray.origin,candidate.ray.direction,vertex(indices[i]),vertex(indices[i+1]),vertex(indices[i+2]),minDistance,limit);
          if(distance!==null){limit=distance;closest={body_id:group.id,target_id:candidate.target,distance_m:distance};}
        }
      }
      return closest;
    }
    function pick(origin,direction,{reach,includeReference=false,...options}){
      const visible=nearest(origin,direction,options);
      let target=visible?.target_id&&visible.distance_m<=reach?visible:null;
      if(includeReference){
        // Space operates the original doorway too, so an open leaf need not
        // still sit under the crosshair. A nearer visible wall always blocks it.
        const reference=nearest(origin,direction,{...options,referenceOnly:true,maxDistance:reach});
        if(reference&&(!visible||visible.distance_m>=reference.distance_m-1e-6||visible.target_id===reference.target_id)
          &&(!target||reference.distance_m<target.distance_m))target=reference;
      }
      return target;
    }
    return {pick};
  }
  // Joint values remain in their source units: degrees for hinges, mm for sliders.
  function jointMatrix(joint,value,reference){
    if(!joint||!['revolute','prismatic'].includes(joint.type)||!Array.isArray(joint.axis)||joint.axis.length!==3||!joint.axis.every(Number.isFinite)
      ||Math.abs(Math.hypot(...joint.axis)-1)>1e-7||!Number.isFinite(value)||!Number.isFinite(reference))throw Error('A finite joint value and unit axis are required.');
    const out=new Float32Array([1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]),delta=value-reference;
    if(delta===0)return out;
    if(joint.type==='prismatic'){
      for(let i=0;i<3;i++)out[12+i]=joint.axis[i]===0?0:joint.axis[i]*delta/1000;
      return out;
    }
    if(joint.type!=='revolute'||!Array.isArray(joint.origin_mm)||joint.origin_mm.length!==3||!joint.origin_mm.every(Number.isFinite))throw Error('A supported joint and finite hinge origin are required.');
    const [x,y,z]=joint.axis,[px,py,pz]=joint.origin_mm.map(v=>v/1000),angle=delta*Math.PI/180,c=Math.cos(angle),s=Math.sin(angle),t=1-c;
    out.set([t*x*x+c,t*x*y+s*z,t*x*z-s*y,0,t*x*y-s*z,t*y*y+c,t*y*z+s*x,0,t*x*z+s*y,t*y*z-s*x,t*z*z+c,0,0,0,0,1]);
    out[12]=px-(out[0]*px+out[4]*py+out[8]*pz);out[13]=py-(out[1]*px+out[5]*py+out[9]*pz);out[14]=pz-(out[2]*px+out[6]*py+out[10]*pz);
    return out;
  }
  function commandBlockers(objects,id,name){
    const object=objects.get(id),command=object?.config.commands[name];
    if(!command)return [];
    return (command.requires||[]).filter(rule=>{
      const other=objects.get(rule.object_id),value=other?.config.states[rule.state];
      return !other||!Number.isFinite(value)||other.transition||other.state!==rule.state
        ||other.targetState!==rule.state||other.value!==value;
    }).map(rule=>rule.object_id);
  }
  function createLiftDoorCycle(config,objects,drive){
    const cabin=objects.get(config.object_id),doors=[...objects.values()].filter(o=>o.config.mechanism==='lift_door');
    if(!doors.length)return null;
    const ids=new Set(doors.map(o=>o.config.id));
    if(!cabin||config.ports.some(p=>p.active&&(!p.door_object_ids?.length||p.door_object_ids.some(id=>!ids.has(id)))))throw Error('Complete active lift door bindings required.');
    let phase='idle',destination=cabin.state;
    const settled=(object,state)=>!object.transition&&object.state===state&&object.targetState===state&&object.value===object.config.states[state];
    const openingIds=level=>new Set(config.ports.filter(p=>p.active&&p.level_id===level).flatMap(p=>p.door_object_ids));
    function setDoors(open){
      for(const door of doors){const result=drive(door.config.id,open.has(door.config.id)?'open':'close');
        if(!['accepted','already_in_state'].includes(result.status))throw Error('Lift door command failed: '+result.status);}
    }
    function initialize(){phase='opening';setDoors(openingIds(cabin.state));advance();}
    function request(level){
      if(!Object.hasOwn(cabin.config.states,level))return {status:'unknown_target',id:config.object_id};
      if(phase!=='idle'||cabin.transition)return {status:'rejected_busy',id:config.object_id};
      if(cabin.state===level)return {status:'already_in_state',id:config.object_id,state:level};
      destination=level;phase='closing';setDoors(new Set());advance();
      return {status:'accepted',id:config.object_id,state:phase,target_state:level};
    }
    function advance(){
      // At most close -> travel -> open -> idle; instant reduced-motion poses
      // still pass through each interlock in the same order.
      for(let n=0;n<4;n++){
        if(phase==='closing'&&doors.every(o=>settled(o,'closed'))){
          phase='travelling';const result=drive(config.object_id,destination);
          if(!['accepted','already_in_state'].includes(result.status))throw Error('Lift travel command failed');
        }else if(phase==='travelling'&&settled(cabin,destination)){
          phase='opening';setDoors(openingIds(destination));
        }else if(phase==='opening'){
          const open=openingIds(cabin.state);
          if(doors.every(o=>settled(o,open.has(o.config.id)?'open':'closed')))phase='idle';else break;
        }else break;
      }
      return phase!=='idle';
    }
    function canUsePort(port){return phase==='idle'&&port.active&&cabin.state===port.level_id&&!cabin.transition
      &&port.door_object_ids.every(id=>settled(objects.get(id),'open'));}
    return {initialize,request,advance,canUsePort,get busy(){return phase!=='idle';},get phase(){return phase;},get destination(){return destination;}};
  }
  // Boarding owns only the passenger attachment. The existing articulated object
  // remains the single authority for cabin position, current floor and motion.
  function createLiftSession(config,object,request,doorCycle=null){
    const finite3=v=>Array.isArray(v)&&v.length===3&&v.every(Number.isFinite);
    if(!config||!object?.config||object.config.id!==config.object_id||object.config.joint.type!=='prismatic'
      ||!Array.isArray(config.ports)||!finite3(config.cabin_bounds_mm?.min)||!finite3(config.cabin_bounds_mm?.max)
      ||!Number.isFinite(config.speed_mm_s)||config.speed_mm_s<=0)throw Error('A source-bound lift cabin and ports are required.');
    const ports=config.ports.filter(p=>p.active),reference=object.config.states[object.config.reference_state];
    if(!Number.isFinite(reference)||!ports.length||ports.some(p=>!finite3(p.cabin_entry_mm)||!finite3(p.exit_eye_mm)
      ||!Number.isFinite(object.config.states[p.level_id])))throw Error('Active lift ports need source-derived boarding and exit points.');
    let passenger=null;
    const busy=()=>Boolean(object.transition||doorCycle?.busy);
    const status=(name,extra={})=>({status:name,id:config.object_id,...extra});
    const activePort=id=>ports.find(p=>p.id===id);
    function nearby(eye,reach){
      if(!finite3(eye)||!Number.isFinite(reach)||reach<=0)return null;
      return ports.map(port=>({port,distance:Math.hypot(...eye.map((v,i)=>v-port.exit_eye_mm[i]))}))
        .filter(v=>v.distance<=reach).sort((a,b)=>a.distance-b.distance)[0]?.port||null;
    }
    function call(portId){
      const port=activePort(portId);if(!port)return status('unknown_target');
      if(busy())return status('rejected_busy');
      if(passenger)return status('rejected_aboard');
      return request(port.level_id);
    }
    function board(portId,eye,reach){
      const port=activePort(portId);if(!port)return status('unknown_target');
      if(busy())return status('rejected_busy');
      if(passenger)return status('already_aboard');
      if(object.state!==port.level_id)return status('rejected_not_here');
      if(doorCycle&&!doorCycle.canUsePort(port))return status('rejected_doors_closed');
      if(!finite3(eye)||!Number.isFinite(reach)||reach<=0||Math.hypot(...eye.map((v,i)=>v-port.exit_eye_mm[i]))>reach)return status('rejected_out_of_reach');
      passenger={port_id:port.id,reference_eye_mm:port.cabin_entry_mm.map((v,i)=>v-object.config.joint.axis[i]*(object.value-reference))};
      return status('accepted',{eye_mm:attachedEye()});
    }
    function select(levelId){
      if(busy())return status('rejected_busy');
      if(!passenger)return status('rejected_not_aboard');
      if(!ports.some(p=>p.level_id===levelId))return status('unknown_target');
      return request(levelId);
    }
    function exit(side){
      if(busy())return status('rejected_busy');
      if(!passenger)return status('rejected_not_aboard');
      const port=ports.find(p=>p.level_id===object.state&&p.side===side);
      if(!port)return status('rejected_inactive_exit');
      if(doorCycle&&!doorCycle.canUsePort(port))return status('rejected_doors_closed');
      passenger=null;return status('accepted',{eye_mm:[...port.exit_eye_mm],level_id:port.level_id,port_id:port.id});
    }
    function attachedEye(){return passenger?passenger.reference_eye_mm.map((v,i)=>v+object.config.joint.axis[i]*(object.value-reference)):null;}
    const usablePorts=()=>ports.filter(p=>object.state===p.level_id&&!busy()&&(!doorCycle||doorCycle.canUsePort(p)));
    function walkingBounds(){
      const bounds=config.walking?.cabin_interior_bounds_mm;
      return bounds?{min:bounds.min.map((v,i)=>v+(i===2?object.value-reference:0)),
                    max:bounds.max.map((v,i)=>v+(i===2?object.value-reference:0))}:null;
    }
    function walkStep(from,to){
      const bounds=walkingBounds(),open=usablePorts();
      if(!bounds||!finite3(from)||!finite3(to)||!open.length)return status('no_walk_transition');
      const [lo,hi]=config.walking.opening_y_mm;
      const inHeight=to[2]>bounds.min[2]&&to[2]<bounds.max[2];
      const interior=inHeight&&to.slice(0,2).every((v,i)=>v>=bounds.min[i]&&v<=bounds.max[i]);
      if(!passenger&&interior){
        const port=open.find(p=>to[1]>lo&&to[1]<hi&&(p.side==='outward'?from[0]<=bounds.min[0]:from[0]>=bounds.max[0]));
        if(port)passenger={port_id:port.id,reference_eye_mm:to.map((v,i)=>v-(i===2?object.value-reference:0))};
      }else if(passenger){
        const port=open.find(p=>inHeight&&to[1]>lo&&to[1]<hi&&(p.side==='outward'?to[0]<p.plane_x_mm-p.wall_thickness_mm/2:to[0]>p.plane_x_mm+p.wall_thickness_mm/2));
        if(port){passenger=null;return status('walked_out',{level_id:port.level_id,port_id:port.id});}
      }
      if(passenger){passenger.reference_eye_mm=to.map((v,i)=>v-(i===2?object.value-reference:0));return status('walking_aboard');}
      return status('no_walk_transition');
    }
    function doorwayOccupied(eye,radius){
      const b=walkingBounds();if(!b||!finite3(eye)||!Number.isFinite(radius)||radius<=0)return false;
      const [lo,hi]=config.walking.opening_y_mm;
      return ports.some(p=>p.level_id===object.state&&eye[2]>p.z_mm&&eye[2]<p.z_mm+p.height_mm
        &&eye[1]>lo-radius&&eye[1]<hi+radius&&(p.side==='outward'
          ?eye[0]>p.plane_x_mm-p.wall_thickness_mm/2-radius&&eye[0]<b.min[0]+radius
          :eye[0]<p.plane_x_mm+p.wall_thickness_mm/2+radius&&eye[0]>b.max[0]-radius));
    }
    function walkingBarriers(){
      if(!config.shaft_bounds_mm)return [];
      let boxes=[config.shaft_bounds_mm];const b=walkingBounds(),open=usablePorts();
      // Carve only the docked cabin and its fully open active doorway from the
      // shaft exclusion. Other floors, inactive sides and the shaft roof remain
      // guarded; native walls/doors still participate in continuous collision.
      if(b&&open.length){
        const [lo,hi]=config.walking.opening_y_mm,cuts=[b,...open.map(p=>({
          min:[Math.min(p.exit_eye_mm[0],b.min[0]),lo,p.z_mm],
          max:[Math.max(p.exit_eye_mm[0],b.max[0]),hi,p.z_mm+p.height_mm]}))];
        for(const cut of cuts)boxes=boxes.flatMap(box=>{
          const low=box.min.map((v,i)=>Math.max(v,cut.min[i])),high=box.max.map((v,i)=>Math.min(v,cut.max[i]));
          if(low.some((v,i)=>v>=high[i]))return [box];
          const remaining=[],middle={min:[...box.min],max:[...box.max]};
          for(let axis=0;axis<3;axis++){
            if(middle.min[axis]<low[axis]){const piece={min:[...middle.min],max:[...middle.max]};piece.max[axis]=low[axis];remaining.push(piece);middle.min[axis]=low[axis];}
            if(middle.max[axis]>high[axis]){const piece={min:[...middle.min],max:[...middle.max]};piece.min[axis]=high[axis];remaining.push(piece);middle.max[axis]=high[axis];}
          }return remaining;
        });
      }
      return boxes.map((b,i)=>({id:'LiftShaftGuard'+i,min:[...b.min],max:[...b.max]}));
    }
    function displayLevel(){
      const ids=Object.keys(object.config.states);return ids.reduce((best,id)=>Math.abs(object.config.states[id]-object.value)<Math.abs(object.config.states[best]-object.value)?id:best,ids[0]);
    }
    return {nearby,call,board,select,exit,attachedEye,walkStep,walkingBarriers,doorwayOccupied,displayLevel,
      get walkingAllowed(){return Boolean(config.walking&&usablePorts().length);},
      get boarded(){return Boolean(passenger);},get portId(){return passenger?.port_id||null;}};
  }
  // Sphere translation against the native triangles. Conservative advancement
  // uses the distance function's Lipschitz bound, not fixed movement samples.
  function createCameraCollider({positions,indices,groups,radius,margin,iterations,slides}){
    const plus=(a,b,s=1)=>a.map((v,i)=>v+s*b[i]);
    const length=v=>Math.hypot(...v),unit=v=>{const n=length(v);return n>1e-15?v.map(x=>x/n):null;};
    if(![radius,margin].every(v=>Number.isFinite(v)&&v>0)||margin>=radius
      ||!Number.isInteger(iterations)||iterations<16||!Number.isInteger(slides)||slides<1)throw Error('Invalid camera envelope.');
    const vertex=i=>[positions[3*i],positions[3*i+1],positions[3*i+2]];
    function edgePoint(p,a,b){const ab=sub(b,a),n=dot(ab,ab);return plus(a,ab,n?Math.max(0,Math.min(1,dot(sub(p,a),ab)/n)):0);}
    function closest(p,a,b,c){
      const ab=sub(b,a),ac=sub(c,a),ap=sub(p,a);
      if(dot(cross(ab,ac),cross(ab,ac))<1e-24){
        return [[a,b],[b,c],[c,a]].map(([x,y])=>edgePoint(p,x,y)).sort((x,y)=>length(sub(p,x))-length(sub(p,y)))[0];
      }
      const d1=dot(ab,ap),d2=dot(ac,ap);if(d1<=0&&d2<=0)return a;
      const bp=sub(p,b),d3=dot(ab,bp),d4=dot(ac,bp);if(d3>=0&&d4<=d3)return b;
      const vc=d1*d4-d3*d2;if(vc<=0&&d1>=0&&d3<=0)return plus(a,ab,d1/(d1-d3));
      const cp=sub(p,c),d5=dot(ab,cp),d6=dot(ac,cp);if(d6>=0&&d5<=d6)return c;
      const vb=d5*d2-d1*d6;if(vb<=0&&d2>=0&&d6<=0)return plus(a,ac,d2/(d2-d6));
      const va=d3*d6-d5*d4;if(va<=0&&(d4-d3)>=0&&(d5-d6)>=0)return plus(b,sub(c,b),(d4-d3)/((d4-d3)+(d5-d6)));
      const denom=1/(va+vb+vc);return plus(plus(a,ab,vb*denom),ac,vc*denom);
    }
    function triangleHit(p,v,a,b,c,limit){
      const speed=length(v);if(speed<1e-15)return null;
      let time=0,normal;
      for(let i=0;i<iterations;i++){
        const point=plus(p,v,time),distanceVector=sub(point,closest(point,a,b,c)),distance=length(distanceVector);
        normal=unit(distanceVector)||unit(cross(sub(b,a),sub(c,a)))||v.map(x=>-x/speed);
        if(distance<1e-15&&dot(normal,v)>0)normal=normal.map(x=>-x);
        // A triangle is convex: nonnegative distance derivative cannot turn
        // into a later collision along this straight translation.
        if(dot(normal,v)>=-1e-12)return null;
        const gap=distance-radius-margin;
        if(gap<=1e-8)return {time,normal};
        const step=gap/speed;
        if(time+step>limit)return null;
        time+=step;
      }
      return {time,normal}; // Unresolved contact is a stop, never permission.
    }
    function overlaps(p,v,lo,hi,limit){
      return p.every((x,i)=>Math.min(x,x+v[i]*limit)<=hi[i]+radius+margin&&Math.max(x,x+v[i]*limit)>=lo[i]-radius-margin);
    }
    function boxTriangles(lo,hi){
      const q=Array.from({length:8},(_,i)=>lo.map((x,j)=>(i&(1<<j))?hi[j]:x));
      return [[0,2,6,4],[1,5,7,3],[0,4,5,1],[2,3,7,6],[0,1,3,2],[4,6,7,5]].flatMap(([a,b,c,d])=>[[q[a],q[b],q[c]],[q[a],q[c],q[d]]]);
    }
    function firstHit(p,v,{transformsForBody=()=>[null],barriers=[]}={}){
      let best=null;
      function consider(a,b,c,local,transform,id){
        const hit=triangleHit(local.origin,local.direction,a,b,c,best?best.time:1);
        if(!hit||best&&hit.time>=best.time)return;
        const n=hit.normal;
        const normal=transform?[0,1,2].map(i=>transform[i]*n[0]+transform[4+i]*n[1]+transform[8+i]*n[2]):n;
        best={...hit,normal,body_id:id};
      }
      for(const group of groups){
        const lo=group.bounds_mm.min.map(x=>x/1000),hi=group.bounds_mm.max.map(x=>x/1000);
        for(const transform of transformsForBody(group.id)){
          const local=inverseRay(p,v,transform);
          if(!overlaps(local.origin,local.direction,lo,hi,best?best.time:1))continue;
          for(let i=group.index_start;i<group.index_start+group.index_count;i+=3)
            consider(vertex(indices[i]),vertex(indices[i+1]),vertex(indices[i+2]),local,transform,group.id);
        }
      }
      for(const barrier of barriers)if(overlaps(p,v,barrier.min,barrier.max,best?best.time:1))
        for(const [a,b,c] of boxTriangles(barrier.min,barrier.max))consider(a,b,c,{origin:p,direction:v},null,barrier.id);
      return best;
    }
    function move(start,delta,options={}){
      if(![...start,...delta].every(Number.isFinite))throw Error('Finite camera translation required.');
      let point=[...start],remaining=[...delta];const contacts=[],normals=[];
      for(let i=0;i<slides&&length(remaining)>1e-10;i++){
        const hit=firstHit(point,remaining,options);
        if(!hit){point=plus(point,remaining);break;}
        point=plus(point,remaining,hit.time);remaining=remaining.map(x=>x*(1-hit.time));contacts.push(hit.body_id);normals.push(hit.normal);
        for(const n of normals){const into=dot(remaining,n);if(into<0)remaining=plus(remaining,n,-into);}
      }
      return {eye:point,contacts};
    }
    return {move,firstHit};
  }
  // Stair following is a visitor-camera aid. Use the same native surfaces as
  // the camera collider, and keep free movement elsewhere in the building.
  function createStairWalker({positions,indices,groups,eyeHeight}){
    const stairRoles=new Set(['concept_continuous_stair','concept_external_metal_stair','concept_external_stair_landing']);
    const floorRoles=new Set(['concept_storey_slab','concept_roof_slab','concept_roof_access_deck']);
    const stepLimit=.25,stepSpacing=.08,contactTolerance=.002,meshTolerance=1e-5;
    const bounds=[],surfaces=[],roofHeights=new Set();
    for(const group of groups){
      const stair=stairRoles.has(group.role);
      if(!group.index_count||!stair&&!floorRoles.has(group.role))continue;
      if(stair)bounds.push(group.bounds_mm);
      if(group.role==='concept_roof_access_deck')roofHeights.add(group.bounds_mm.max[2]/1000);
      for(let i=group.index_start;i<group.index_start+group.index_count;i+=3){
        const [a,b,c]=[indices[i],indices[i+1],indices[i+2]].map(j=>Array.from(positions.slice(3*j,3*j+3)));
        if(Math.max(Math.abs(b[2]-a[2]),Math.abs(c[2]-a[2]))>meshTolerance)continue;
        if(cross(sub(b,a),sub(c,a))[2]<=0)continue;
        surfaces.push({edges:[[a,b],[b,c],[c,a]],height:a[2],stair,body_id:group.id});
      }
    }
    function support(x,y,height,tolerance){
      let best=null;
      for(const surface of surfaces){
        if(Math.abs(surface.height-height)>tolerance||best&&surface.height<=best.height)continue;
        if(surface.edges.every(([a,b])=>(b[0]-a[0])*(y-a[1])-(b[1]-a[1])*(x-a[0])>=-meshTolerance*Math.hypot(b[0]-a[0],b[1]-a[1])))
          best=surface;
      }
      return best;
    }
    function move(start,delta,collider,options){
      const nearStair=bounds.some(b=>start.every((v,i)=>{
        const a=(i===2?v-eyeHeight:v)*1000,end=a+delta[i]*1000,margin=i===2?stepLimit*1000:meshTolerance*1000;
        return Math.min(a,end)<=b.max[i]+margin&&Math.max(a,end)>=b.min[i]-margin;
      }));
      if(!nearStair||delta[2]||!Math.hypot(delta[0],delta[1]))return collider.move(start,delta,options);
      let current=support(start[0],start[1],start[2]-eyeHeight,contactTolerance);
      if(!current)return collider.move(start,delta,options);
      let eye=start,followedStairs=false;
      const contacts=[],count=Math.ceil(Math.hypot(delta[0],delta[1])/stepSpacing),dx=delta[0]/count,dy=delta[1]/count;
      for(let i=0;i<count;i++){
        const next=support(eye[0]+dx,eye[1]+dy,current.height,stepLimit);
        if(!next&&current.stair){contacts.push(current.body_id);break;}
        const onStairs=current.stair||next?.stair;
        const dz=onStairs&&next?next.height+eyeHeight-eye[2]:0;
        const result=collider.move(eye,[dx,dy,dz],options);
        contacts.push(...result.contacts);
        const landed=support(result.eye[0],result.eye[1],result.eye[2]-eyeHeight,contactTolerance);
        if(onStairs&&!landed){contacts.push(current.body_id);break;}
        eye=result.eye;
        followedStairs||=Boolean(onStairs);
        current=landed;
        if(!current)break;
      }
      const landing=followedStairs&&current?{
        height:current.height,body_id:current.body_id,
        roof:[...roofHeights].some(height=>Math.abs(height-current.height)<meshTolerance)
      }:null;
      return {eye,contacts,support:landing};
    }
    return {move};
  }
  const api={createPicker,jointMatrix,commandBlockers,createLiftDoorCycle,createLiftSession,createCameraCollider,createStairWalker};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.WalkthroughInteraction=api;
})(globalThis);
