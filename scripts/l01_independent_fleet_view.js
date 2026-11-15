// Independent source tracks share only explicit station leases, never peer data.
function independentPhase(track,time){let lo=0,hi=track.phases.length-1;while(lo<hi){const m=Math.ceil((lo+hi)/2);if(track.phases[m].start_s<=time)lo=m;else hi=m-1}return track.phases[lo]}
function independentSnapshot(time){
 const raw=rawTrafficSnapshot(time),human=data.traffic.settings.person,pt=Math.max(0,time-data.traffic.person_epoch_s),lane=data.traffic.person_full_envelope.min[0]+human.radius_mm;raw.person=[lane+human.lateral_offset_mm*(pt<human.leaves_lane_s?1-Math.min(1,pt/human.arrives_at_lane_s):Math.min(1,(pt-human.leaves_lane_s)/(human.fully_clear_s-human.leaves_lane_s))),human.y_mm];
 const base=clone(data.fleet.initial_state),activeJobs=data.fleet.jobs.filter(j=>j.start_s<=time&&time<j.end_s),protectedPhases=[];
 const benches=Object.fromEntries(Object.keys(definition.work_areas).map(key=>[key,{status:'closed',vehicle:null,person_clear:false}]));
 const vehiclePhases=data.fleet.tracks.map((track,i)=>{
  const phase=independentPhase(track,time),past=track.phases.filter(p=>p.start_s<=time&&p.state),state=past.length?past[past.length-1].state:base;
  base.owners[i]=clone(state.owners[i]);base.covers[i]=state.covers[i];
  const job=activeJobs.find(j=>j.vehicle===track.id);
  if(job){
   base.joints[job.actor]=clone(state.joints[job.actor]);benches[job.area]=clone(state.benches[job.area]);
   if(phase.kind==='arm')base.joints[job.actor]=pose(data.handoffs[phase.station].transfers[phase.direction][phase.part],time-phase.start_s);
   if(['dock','arm','event'].includes(phase.kind))protectedPhases.push(phase);
  }
  return phase;
 });
 const vehicles=raw.vehicles.map((v,i)=>{
  const track=data.fleet.tracks[i],phase=vehiclePhases[i];let mode=v.mode;
  if(time>=track.complete_s)mode='arrived';else if(phase.kind==='resource_wait')mode='waiting';else if(phase.kind==='dock')mode=phase.reverse?'departing':'docking';else if(phase.kind==='arm')mode=phase.direction==='load'?'loading':'unloading';else if(phase.kind==='event')mode='confirmation';
  const curve=trafficCurves[i];let lo=0,hi=curve.points.length-2;while(lo<hi){const mid=(lo+hi+1)>>1;if(curve.points[mid][0]<=time)lo=mid;else hi=mid-1}const a=curve.points[lo],b=curve.points[lo+1],u=Math.max(0,Math.min(1,(time-a[0])/(b[0]-a[0]))),rate=curve.coefficients[lo].slice(0,2).map(c=>polynomial(c.slice(1).map((v,j)=>v*(j+1)),u)/(b[0]-a[0]));return {...v,mode,velocity_mm_s:Math.hypot(...rate)};
 });
 const cargoMatrices=base.owners.map((o,i)=>o.type==='bench'?o.matrix:o.type==='car'?mm(tr([raw.poses[i][0],raw.poses[i][1],0],raw.poses[i][2]),o.attachment):mm(tool(o.actor,base.joints[o.actor]),o.attachment));
 const only=activeJobs.length===1&&vehicles.filter(v=>v.mode!=='arrived').length===1?activeJobs[0]:null,complete=vehicles.every(v=>v.mode==='arrived'),control=protectedPhases[0];
 return {phase:complete?{kind:'complete'}:only?vehiclePhases[data.fleet.missions.findIndex(m=>m.id===only.vehicle)]:{kind:'parallel'},vehiclePhases,protectedPhases,vehicles,poses:raw.poses,person:raw.person,joints:base.joints,owners:base.owners,covers:base.covers,cargoMatrices,benches,protected:protectedPhases.length>0,activeJobs,activeVehicle:only?.vehicle??null,activeStation:only?.station??null,controlStation:control?.station??null};
}
function guardIndependentFleet(nextTime=trafficT){
 if(fleetBlocked)return false;
 for(const track of data.fleet.tracks)for(const phase of track.phases){
  if(!['dock','arm'].includes(phase.kind)||phase.start_s>nextTime||phase.start_s+phase.duration_s<trafficT)continue;
  const area=definition.stations[phase.station].work_area,lease=phase.state.benches[area];
  if(!lease?.person_clear||lease.vehicle!==track.id){fleetBlocked=fleetManualOccupied=true;return false}
 }
 return true;
}
function updateIndependentControls(){
 const s=trafficSnapshot(),control=s.controlStation,controlArea=control?definition.stations[control].work_area:null;
 benches.textContent=Object.entries(s.benches).map(([name,lease])=>(name==='LeftIsland'?'DNA / TapeStation':name==='QC'?'NanoDrop / Qubit':name)+': '+(fleetBlocked&&name===controlArea?(fleetManualOccupied?'belegt · GESPERRT · Freigabe ungültig':'Freigabe ausstehend · GESPERRT'):lease.status==='reserved'?'exklusiv '+lease.vehicle+' · GESPERRT für andere':'belegt/ungeklärt · GESPERRT')).join(' | ');
 const lease=controlArea?s.benches[controlArea]:null;occupied.disabled=!s.protected&&!fleetBlocked;occupied.checked=fleetBlocked?fleetManualOccupied:!lease?.person_clear;confirm.hidden=!fleetBlocked;confirm.disabled=fleetManualOccupied;confirm.textContent='Synthetisch: Arbeitsplatzfreigabe erneuern';
 const caption=root.querySelector('#tr01-occupancy-label');if(caption)caption.textContent=(control?control+' · ':'')+'Arbeitsbereich belegt oder ungeklärt · Transporte warten ohne Signalton';
 if(fleetBlocked){status.textContent='Schutzhalt der Vorschau · neue Arbeitsplatzbeobachtung und Freigabe erforderlich';play.textContent='Gesperrt'}
 else if(s.phase.kind==='complete')status.textContent='Alle drei unabhängigen Transporte und sechs Arm-Übergaben abgeschlossen';
 else {const words={arm:'Arm-Übergabe',dock:'Andock-/Abfahrt',event:'synthetischer Übergabebeleg',traffic:'lokale Fahrt',resource_wait:'wartet auf Arbeitsplatzbeobachtung / Ressource'};status.textContent='Unabhängig · '+s.vehiclePhases.map((p,i)=>data.fleet.tracks[i].id+': '+(trafficT>=data.fleet.tracks[i].complete_s?'fertig':words[p.kind]??p.kind)).join(' | ')}
}
