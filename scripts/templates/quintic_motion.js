/* Pure quintic PVA evaluator shared by the CF01 browser and its Node checks. */
(function (global) {
  'use strict';
  function derivative(c) {return c.slice(1).map((v,i)=>v*(i+1));}
  function polynomial(c,u) {let v=0;for(let i=c.length-1;i>=0;i--)v=v*u+c[i];return v;}
  class Curve {
    constructor(points, fields=['positions_rad','velocities_rad_s','accelerations_rad_s2']) {
      if(!Array.isArray(points)||!points.length)throw new Error('Motion points required');
      this.points=points;this.fields=fields;this.segments=[];
      const dim=points[0][fields[0]].length;
      for(let i=0;i<points.length;i++){
        const p=points[i];
        if(!Number.isFinite(p.time_s)||(i&&p.time_s<=points[i-1].time_s)||
          fields.some(f=>!Array.isArray(p[f])||p[f].length!==dim||!p[f].every(Number.isFinite)))throw new Error('Invalid PVA curve');
      }
      for(let i=1;i<points.length;i++){
        const a=points[i-1],b=points[i],T=b.time_s-a.time_s;
        const coeff=a[fields[0]].map((p,j)=>{
          const v=a[fields[1]][j]*T,A=a[fields[2]][j]*T*T;
          const D=b[fields[0]][j]-p-v-A/2;
          const E=b[fields[1]][j]*T-v-A;
          const F=b[fields[2]][j]*T*T-A;
          const c=[p,v,A/2,10*D-4*E+F/2,-15*D+7*E-F,6*D-3*E+F/2];
          return [c,derivative(c),derivative(derivative(c)),derivative(derivative(derivative(c)))];
        });
        this.segments.push({start:a.time_s,end:b.time_s,T,coeff});
      }
    }
    at(t) {
      const points=this.points,first=points[0],last=points[points.length-1],names=['p','v','a','j'];
      if(!Number.isFinite(t))throw new Error('Finite motion time required');
      if(t<first.time_s||t>last.time_s||points.length===1){
        const p=(t<first.time_s?first:last)[this.fields[0]].slice(),z=p.map(()=>0);
        return {p,v:z.slice(),a:z.slice(),j:z.slice()};
      }
      let lo=0,hi=this.segments.length-1;
      while(lo<hi){const m=(lo+hi)>>1;if(t<this.segments[m].end)hi=m;else lo=m+1;}
      const s=this.segments[lo],u=(t-s.start)/s.T,result={};
      names.forEach((name,order)=>{result[name]=s.coeff.map(c=>polynomial(c[order],u)/s.T**order);});
      return result;
    }
  }
  class Program {
    constructor(program){
      this.data=program;this.arm=new Curve(program.arm.points);
      this.station=new Curve(program.station.points,['p','v','a']);
      this.jaw=new Curve(program.jaw.points,['p','v','a']);
    }
    at(time){
      const p=this.data,t=Math.max(0,Math.min(p.duration_s,time));
      const arm=this.arm.at(t),station=this.station.at(t),jaw=this.jaw.at(t),owners={};
      p.samples.forEach(s=>owners[s.id]='rotor');
      let active=null,clear=true,phase='initial_post_spin';
      for(const e of p.events){if(e.time_s>t)break;phase=e.phase_key;
        if(e.kind==='active')active=e.sample_id;
        if(e.kind==='owner')owners[e.sample_id]=e.owner;
        if('workspace_clear'in e)clear=e.workspace_clear;
      }
      const values={};p.station.joint_names.forEach((n,i)=>values[n]=station.p[i]);
      return {time_s:t,values,station:values,joints_deg:arm.p.map(x=>x*180/Math.PI),
        joint_state:arm,jaw_gap_mm:jaw.p[0],owners,active_sample_id:active,
        phase_key:phase,phase,workspace_clear:clear};
    }
  }
  const api={Curve,Program};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  global.CF01Motion=api;
})(typeof globalThis!=='undefined'?globalThis:this);
