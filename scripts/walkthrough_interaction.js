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
    return {nearby,call,board,select,exit,attachedEye,
      get boarded(){return Boolean(passenger);},get portId(){return passenger?.port_id||null;}};
  }
  const api={createPicker,jointMatrix,commandBlockers,createLiftDoorCycle,createLiftSession};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.WalkthroughInteraction=api;
})(globalThis);
