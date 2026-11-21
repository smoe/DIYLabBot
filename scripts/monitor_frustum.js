/* Conservative feed-only AABB visibility. The column-major matrix maps metres
 * to OpenGL clip space; source bounds remain in millimetres. No pose is inferred.
 */
(function(scope){
  'use strict';
  const finiteArray=(value,length)=>
    (Array.isArray(value)||ArrayBuffer.isView(value))&&value.length===length&&
    Array.from(value).every(v=>typeof v==='number'&&Number.isFinite(v));

  function visible(matrix,bounds){
    if(!finiteArray(matrix,16)||!bounds||!finiteArray(bounds.min,3)||!finiteArray(bounds.max,3)||
       bounds.min.some((v,i)=>v>bounds.max[i]))throw Error('Finite clip matrix and ordered AABB bounds required');
    const c=bounds.min.map((v,i)=>v/2000+bounds.max[i]/2000);
    const e=bounds.min.map((v,i)=>bounds.max[i]/2000-v/2000);
    for(let axis=0;axis<3;axis++)for(const sign of [-1,1]){
      const nx=matrix[3]+sign*matrix[axis],ny=matrix[7]+sign*matrix[4+axis];
      const nz=matrix[11]+sign*matrix[8+axis],d=matrix[15]+sign*matrix[12+axis];
      const x=nx*c[0],y=ny*c[1],z=nz*c[2];
      const radius=Math.abs(nx)*e[0]+Math.abs(ny)*e[1]+Math.abs(nz)*e[2];
      // Keep contacts and float32-sized uncertainty; false positives are safe.
      const tolerance=1e-7*(1+Math.abs(x)+Math.abs(y)+Math.abs(z)+Math.abs(d)+radius);
      if(x+y+z+d+radius < -tolerance)return false;
    }
    return true;
  }

  const api={visible};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  scope.MonitorFrustum=api;
})(typeof globalThis!=='undefined'?globalThis:this);
