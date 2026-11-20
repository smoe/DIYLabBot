/* Empty-arm command session. Geometry and joints are supplied by the compiler. */
(function(global){
  'use strict';
  function create(config,objects,Curve){
    const joints=config.joint_object_ids.map(id=>{const o=objects.get(id);if(!o)throw Error('Missing robot joint');return o;});
    let state='idle',trajectory=null,brake=null,time=0,last=null,lastCommand=null;
    let q=config.reference_deg.slice();
    function duration(target){
      const d=Math.max(...q.map((v,i)=>Math.abs(v-target[i]))),B=config.stop_ramp_s,L=config.limits;
      let lo=.001,hi=60;
      for(let n=0;n<45;n++){
        const t=(lo+hi)/2,v=d*1.875/t,a=d*(10/Math.sqrt(3))/t**2,j=d*60/t**3;
        if(v<=L.velocity_deg_s&&a+v*1.5/B<=L.acceleration_deg_s2&&j+3*a*1.5/B+v*6/B**2<=L.jerk_deg_s3)hi=t;else lo=t;
      }
      return hi*1.000001;
    }
    function advance(now){
      if(!trajectory)return false;
      if(last===null)last=now;
      const dt=Math.max(0,(now-last)/1000);last=now;
      if(brake){
        const u=Math.min(1,(now-brake.start)/1000/config.stop_ramp_s);
        time=brake.time+config.stop_ramp_s*(u-u**3+.5*u**4);
        if(u===1)state='stopped';
      }else time+=dt;
      const t=Math.min(time,trajectory.end),values=trajectory.curve.at(t).p;
      q=values.map(v=>v*180/Math.PI);
      joints.forEach((o,i)=>{o.value=q[i];});
      if(time>=trajectory.end||state==='stopped'){
        state=time>=trajectory.end?'idle':'stopped';trajectory=null;brake=null;last=null;
      }
      return Boolean(trajectory);
    }
    function command(name,now){
      advance(now);
      let result;
      if(!Object.hasOwn(config.commands,name))result={status:'unknown_command'};
      else if(name==='stop'){
        if(!trajectory)result={status:'already_stopped'};
        else if(brake)result={status:'already_stopping'};
        else{brake={time,start:now};state='stopping';result={status:'accepted'};}
      }else if(trajectory)result={status:'rejected_busy'};
      else{
        const target=(name==='home'?config.reference_deg:config.demo_deg).slice();
        if(q.every((v,i)=>Math.abs(v-target[i])<1e-7))result={status:'already_in_state'};
        else{
          const end=duration(target),points=[q,target].map((v,i)=>({time_s:i*end,positions_rad:v.map(x=>x*Math.PI/180),velocities_rad_s:v.map(()=>0),accelerations_rad_s2:v.map(()=>0)}));
          trajectory={curve:new Curve(points),end};time=0;last=now;brake=null;state=name==='home'?'homing':'moving';result={status:'accepted',duration_s:end};
        }
      }
      lastCommand={...result,id:config.id,command:name};return lastCommand;
    }
    return {config,advance,command,get snapshot(){return {id:config.id,state,joints_deg:q.slice(),time_s:time,last_command:lastCommand,busy:Boolean(trajectory)};}};
  }
  const api={create};if(typeof module!=='undefined'&&module.exports)module.exports=api;global.WalkthroughRobots=api;
})(typeof globalThis!=='undefined'?globalThis:this);
