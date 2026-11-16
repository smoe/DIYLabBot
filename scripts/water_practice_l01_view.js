// Local display replay only. No runtime act(), device call or journal write.
const waterButton=document.createElement('button');waterButton.type='button';waterButton.className='btn';waterButton.id='tr01-water';waterButton.textContent='Wasserübung / Transport';demoButton.parentNode.appendChild(waterButton);
const waterDetail=document.createElement('output');waterDetail.className='text-small tabular-nums';waterDetail.id='tr01-water-detail';waterDetail.setAttribute('aria-live','polite');status.parentNode.insertBefore(waterDetail,benches);
const waterPairLabels=['source','target'].map(role=>{const e=document.createElement('span');e.dataset.waterRole=role;root.querySelector('.labels')?.appendChild(e);return e});
const W=data.water,waterInitial=W.fixture.initial_volume_ul,waterDose=W.fixture.transfer_volume_ul,waterPhases=[];let waterDuration=0,waterActive=true,waterTime=0,waterRunning=false,waterFrame=0,waterLast=0,waterBlocked=false,waterOccupied=false;
const waterWriter=String(Date.now())+'-'+String(Math.random());let waterWriteRevision=0;
let waterBase={car:pose(data.routes[0],0),joints:Object.fromEntries(Object.entries(data.actors).map(([a,d])=>[a,d.park.map(v=>v*Math.PI/180)])),cargo:{type:'bench',matrix:tr(data.handoffs.DNA.bench_grip_mm)},cover:true};
for(const path of Object.values(W.paths)){waterBase.joints[path.actor]=path.park.map(v=>v*Math.PI/180);for(const c of Object.values(path.curves))prepare(c)}
let waterAmounts={A:[waterInitial,0],B:[waterInitial,0],C:[waterInitial,0]},waterCompleted=0,waterConfirmed=0;
function waterAdd(kind,label,path=null,curve=null,hold=0){const p={kind,label,path,station:path?W.paths[path].station:'DNA',actor:path?W.paths[path].actor:null,start:waterDuration,duration:curve?.duration??hold,curve,state:clone(waterBase),amounts:clone(waterAmounts),completed:waterCompleted,confirmed:waterConfirmed};waterPhases.push(p);waterDuration+=p.duration;return p}
for(const step of W.steps){const name=step[0],p=W.paths[name],c=p.curves;
 waterAdd('intent',step+' · Absicht gespeichert',name,null,.5);
 waterAdd('approach',step+' · Spitze eintauchen',name,c.approach);waterBase.joints[p.actor]=pose(c.approach,c.approach.duration);
 waterAdd('aspirate',step+' · '+waterDose+' µl Wasser aufnehmen',name,null,W.definition.holds_s.aspirate);waterAmounts[name][0]-=waterDose;
 waterAdd('loaded',step+' · fließender Transfer zur Zielöffnung',name,c.loaded);waterBase.joints[p.actor]=pose(c.loaded,c.loaded.duration);
 waterAdd('dispense',step+' · '+waterDose+' µl Wasser abgeben',name,null,W.definition.holds_s.dispense);waterAmounts[name][1]+=waterDose;waterCompleted++;
 waterAdd('retreat',step+' · leere Pipette zurückziehen',name,c.retreat);waterBase.joints[p.actor]=pose(c.retreat,c.retreat.duration);
 if(step!=='A2'){waterConfirmed++;waterAdd('confirmed',step+' · Transfer bestätigt',name,null,.7)}
}
waterAdd('unknown','Störfall A2 · Zugabe erfolgt, Quittung fehlt','A',null,3);
waterAdd('restart','Wiederanlauf · neue Sitzung, A2 bleibt unklar','A',null,2.5);
waterAdd('blocked','Erneute Zugabe gesperrt · Ressourcen bleiben gehalten','A',null,2.5);
waterAdd('reconcile','Abgleich · vorhandenen Transfer anhand der Belege zuordnen','A',null,3);
waterConfirmed++;waterAdd('reconciled','A2 bestätigt · keine erneute Zugabe','A',null,2);
waterAdd('complete','Wasserübung beendet · vier Zugaben, null Wiederholungen','A',null,2);
function waterSnapshot(time=waterTime){const p=waterPhases.find(p=>p.start+p.duration>time)??waterPhases.at(-1),u=Math.max(0,Math.min(p.duration,time-p.start)),s=clone(p.state),amounts=clone(p.amounts),smooth=x=>x*x*x*(10-15*x+6*x*x);let carried=0,completed=p.completed;
 if(p.curve)s.joints[p.actor]=pose(p.curve,u);
 if(p.kind==='aspirate'){carried=waterDose*smooth(u/p.duration);amounts[p.path][0]-=carried}
 if(p.kind==='loaded')carried=waterDose;
 if(p.kind==='dispense'){const added=waterDose*smooth(u/p.duration);amounts[p.path][1]+=added;carried=waterDose-added;if(u>=p.duration)completed++}
 return {...s,phase:{kind:'arm',station:p.station,label:p.label},waterPhase:p,amounts,carried,completed,confirmed:p.confirmed,local:u}
}
// Current native water-mode meshes replace every old arm and gripper.
for(const g of groups)if(g.kind>=400)g.hidden=true;
for(const g of groups)if(Object.values(W.actors).some(d=>g.kind===d.water_kind+7))g.displayKind=7;
const fluidGroup=groups.find(g=>g.kind===482);fluidGroup.hidden=true;
for(let i=0;i<6;i++)groups.push({...fluidGroup,kind:500+i,displayKind:9,waterFluid:true});
function waterVisibility(){for(const g of groups){if(g.kind>=400)g.hidden=!waterActive||g.kind===482;if(waterActive&&(g.kind===6||g.kind===9||g.kind>=100&&g.kind<160))g.hidden=true;else if(!waterActive&&(g.kind===6||g.kind===9||g.kind>=100&&g.kind<160))g.hidden=false}}
const labCurrent=current,labTransforms=transforms,labCamera=camera,labRender=render,labSave=save,labRestore=restore;
current=function(){return waterActive?waterSnapshot():labCurrent()};
transforms=function(s){const out=labTransforms(s);if(!waterActive)return out;for(const [actor,d]of Object.entries(W.actors)){const frames=fk(actor,s.joints[actor]);d.links.forEach((link,i)=>out[d.water_kind+i]=frames[link]);out[d.water_kind+7]=mm(frames[d.flange_link],tr(W.flange_reference_mm))}let i=0;const fixture=W.kit.cases[W.definition.fixture_case];for(const [name,p]of Object.entries(W.paths))for(let role=0;role<2;role++){const m=tr(p[(role?'target':'source')+'_mm']);m[2][3]+=fixture.plate_height_mm/8+fixture.tube_height_mm/3;m[2][2]=Math.max(.00001,s.amounts[name][role]/waterInitial);out[500+i++]=m}return out};
camera=function(w,h){if(!waterActive||view.value!=='auto')return labCamera(w,h);const p=waterSnapshot().waterPhase,path=W.paths[p.path??'A'],theta=p.station==='DNA'?Math.PI-az:az,centre=[(path.source_mm[0]+path.target_mm[0])/8000,.275,-(path.source_mm[1]+path.target_mm[1])/8000],dir=[Math.cos(theta)*Math.cos(el),Math.sin(el),Math.sin(theta)*Math.cos(el)],eye=centre.map((v,i)=>v+dir[i]*4),z=unit(dir),x=unit(cross([0,1,0],z)),y=cross(z,x),v=new Float32Array([x[0],y[0],z[0],0,x[1],y[1],z[1],0,x[2],y[2],z[2],0,-dot(x,eye),-dot(y,eye),-dot(z,eye),1]),half=.19*zoom,hw=half*w/h,projection=new Float32Array([1/hw,0,0,0,0,1/half,0,0,0,0,-2/30,0,0,0,-1,1]);return multiply(projection,v)};
render=function(){waterVisibility();for(const b of parks)b.disabled=waterActive;demoButton.disabled=trafficButton.disabled=waterActive;seek.disabled=waterActive&&waterBlocked;if(waterActive){const actor=W.paths[waterSnapshot().waterPhase.path??'A'].actor,active=W.actors[actor].water_kind;for(const g of groups)if(400<=g.kind&&g.kind<460)g.displayKind=g.kind%20===7?10:g.kind>=active&&g.kind<active+7?7:6}labRender();if(!waterActive){waterPairLabels.forEach(e=>e.hidden=true);waterDetail.hidden=true;waterButton.setAttribute('aria-pressed','false');return}const s=waterSnapshot(),p=s.waterPhase;waterDetail.hidden=false;waterButton.setAttribute('aria-pressed','true');seek.max=waterDuration;seek.value=waterTime;const movingTime=waterPhases.filter(p=>p.curve).reduce((sum,p)=>sum+Math.max(0,Math.min(p.duration,waterTime-p.start)),0);clock.textContent='Vorschau '+fmt(waterTime)+' / '+fmt(waterDuration)+' · Bewegung '+fmt(movingTime);status.textContent=waterBlocked?'Schutzhalt · Personenbereich belegt oder ungeklärt':p.label;
 const amounts=Object.entries(s.amounts).map(([k,a])=>k+': '+Math.round(a[0])+' → '+Math.round(a[1])+' µl').join(' | ');
 waterDetail.textContent=amounts+' | in Spitze '+Math.round(s.carried)+' µl | '+s.completed+' Zugaben · '+s.confirmed+' bestätigt'+(['unknown','restart','blocked','reconcile'].includes(p.kind)?' · A2 UNKLAR':'');
 benches.textContent='Bench-Bereiche für Personen und Transporter GESPERRT · '+p.station+' für Wasserübung reserviert · '+(waterBlocked?'Freigabe ungültig':'synthetische Personenfreigabe');
 play.textContent=waterRunning?'Pause':waterTime>=waterDuration?'Wasserübung erneut ansehen':'Abspielen';confirm.hidden=!waterBlocked;confirm.disabled=waterOccupied;confirm.textContent='Synthetische Freigabe erneuern';occupied.disabled=false;occupied.checked=waterOccupied;
 for(const b of parks)b.disabled=true;demoButton.disabled=true;trafficButton.disabled=true;seek.disabled=waterBlocked;
 for(const label of labels){label.hidden=label.dataset.station!==p.station;if(!label.hidden){label.style.left=canvas.clientWidth/2+'px';label.style.top='28px';label.textContent=names[p.station]+' · Weg '+(p.path??'A')}}
 if(p.path){const path=W.paths[p.path],spots=['source','target'].map(role=>project([...path[role+'_mm'].slice(0,2),960],canvas.clientWidth,canvas.clientHeight));waterPairLabels.forEach((e,i)=>{e.hidden=false;e.textContent=(i?'Ziel ':'Quelle ')+Math.round(s.amounts[p.path][i])+' µl';e.setAttribute('data-tooltip',W.display_bindings[p.path][(i?'target':'source')+'_vessel_id']);e.style.left=Math.max(65,Math.min(canvas.clientWidth-65,spots[i][0]+(i===(spots[0][0]<=spots[1][0]?0:1)?-75:75)))+'px';e.style.top=Math.max(24,Math.min(canvas.clientHeight-8,spots[i][1]-25))+'px'})}else waterPairLabels.forEach(e=>e.hidden=true);
 // Actual tip stroke and liquid in the tip, in world coordinates.
 if(p.actor){const d=data.actors[p.actor],frames=fk(p.actor,s.joints[p.actor]),flange=mm(frames[d.flange_link],tr(W.flange_reference_mm)),length=W.kit.cases[W.definition.pipette_case].tcp_length_mm,point=z=>flange.slice(0,3).map(row=>row[2]*z+row[3]);if(gl)gl.disable(gl.DEPTH_TEST);if(s.carried>.01)line([point(length-2),point(length-2-24*s.carried/waterDose)],palette[9]);const stroke=12*s.carried/waterDose;line([point(12+stroke),point(28+stroke)],palette[10]);if(gl)gl.enable(gl.DEPTH_TEST)}
};
function waterPersist(){const saved={water_writer:waterWriter,water_revision:++waterWriteRevision,waterActive,waterTime,waterBlocked,waterOccupied,speed:speed.value,view:view.value,az,el,zoom,daylight:lightChoice.value,minute:Number(timeOfDay.value),artificial:artificialChoice.value};window.openai?.setWidgetState?.({modelContent:{mode:'water_practice_l01',synthetic:true,phase:waterSnapshot().waterPhase.kind,additional_transfer_after_restart:false,e4_decisions_changed:false},privateContent:saved})?.catch(()=>{})}
save=function(){waterActive?waterPersist():labSave()};
restore=function(v){if(v?.privateContent?.water_writer===waterWriter&&v.privateContent.water_revision<=waterWriteRevision)return;if(fleetBlocked||waterActive&&waterBlocked)return;if(v?.privateContent?.trafficActive!==undefined&&!v.privateContent.waterActive)waterActive=false;if(v?.privateContent?.waterActive){const p=v.privateContent;waterActive=true;waterTime=Math.max(0,Math.min(waterDuration,Number(p.waterTime)||0));waterBlocked=!!p.waterBlocked;waterOccupied=!!p.waterOccupied;waterRunning=false;labRestore(v);speed.value=p.speed??'1';return}labRestore(v)};
function waterTick(now){if(!waterRunning||waterBlocked)return;const dt=waterLast?(now-waterLast)/1000*Number(speed.value):0;waterLast=now;waterTime=Math.min(waterDuration,waterTime+dt);if(waterTime>=waterDuration)waterRunning=false;render();if(waterRunning)waterFrame=requestAnimationFrame(waterTick);else save()}
function waterPlay(){if(waterBlocked)return;if(waterTime>=waterDuration)waterTime=0;waterRunning=!waterRunning;waterLast=0;if(waterRunning)waterFrame=requestAnimationFrame(waterTick);else cancelAnimationFrame(waterFrame);render();save()}
function capture(element,event,handler){element.addEventListener(event,e=>{if(!waterActive)return;e.stopImmediatePropagation();handler(e)},true)}
capture(play,'click',waterPlay);for(const element of [seek,speed,timeOfDay])capture(element,'change',()=>save());capture(seek,'input',()=>{if(waterBlocked)return;waterRunning=false;cancelAnimationFrame(waterFrame);waterTime=Math.max(0,Math.min(waterDuration,Number(seek.value)));render()});
capture(occupied,'change',()=>{waterOccupied=occupied.checked;waterBlocked=true;waterRunning=false;cancelAnimationFrame(waterFrame);render();save()});
capture(confirm,'click',()=>{if(waterOccupied)return;waterBlocked=false;render();save()});
waterButton.addEventListener('click',()=>{if(waterBlocked||fleetBlocked||blocked)return;waterActive=!waterActive;waterRunning=false;cancelAnimationFrame(waterFrame);if(waterActive){stopTraffic();playing=false;cancelAnimationFrame(frame);speed.value='1';waterTime=0}else{seek.max=duration;for(const b of parks)b.disabled=false;demoButton.disabled=false;trafficButton.disabled=false;seek.disabled=false}daylightRenderer.setTime(timeOfDay.value);render();save()});
root.waterPractice={phases:waterPhases,snapshot:waterSnapshot,get duration(){return waterDuration},get time(){return waterTime},get active(){return waterActive},get blocked(){return waterBlocked},get running(){return waterRunning}};
speed.value='1';zoom=.6;seek.max=waterDuration;waterVisibility();
if(!window.openai?.widgetState&&!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches){waterRunning=true;waterFrame=requestAnimationFrame(waterTick)}
