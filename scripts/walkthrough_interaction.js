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
    function nearest(origin,direction,{transformForBody=()=>null,targetForBody=()=>null,minDistance=0,maxDistance=Infinity,referenceOnly=false}={}){
      const candidates=[];
      for(const body of bodies){
        const target=targetForBody(body.group.id);if(referenceOnly&&!target)continue;
        const ray=inverseRay(origin,direction,referenceOnly?null:transformForBody(body.group.id));
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
  const api={createPicker};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.WalkthroughInteraction=api;
})(globalThis);
