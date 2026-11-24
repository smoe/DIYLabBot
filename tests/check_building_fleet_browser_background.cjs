// Preparation may be slow; it must never hold the executed-world control loop.
const assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url');
const path=require('node:path');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const state=t=>({format:'solidcraftbot.building-fleet-live-snapshot/1',session_id:'fresh',model_time_s:t,integration_step_s:.05,paused:false});
(async()=>{
 const api=await import(pathToFileURL(path.resolve(__dirname,'../scripts/building_fleet_browser_worker.mjs')).href);
 const jobs=[{request_id:'own-1',kind:'full_route'}],effects=[],timers=[];let finish,time=0,requestCount=0;
 const runtime={background:true,initial:state(0),pendingJobs:()=>jobs.splice(0),
  tick(){effects.push('tick');time+=.05;return state(time);},
  completeJob(result){effects.push(['commit',result.request_id]);}};
 const controller=api.createController({post(){},loadRuntime:async()=>runtime,
  makePlanner:()=>({prepare(job){requestCount++;assert.equal(job.request_id,'own-1');return new Promise(resolve=>{finish=resolve;});},dispose(){}}),
  now:()=>0,setTimer:fn=>{timers.push(fn);return fn;},clearTimer(){}});
 controller.handle({type:'boot',config:{}});await flush();
 timers.shift()();await flush();timers.shift()();await flush();
 assert.deepEqual(effects,['tick','tick']);assert.equal(requestCount,1);
 assert.equal(controller.state.model_time_s,.1,'The world runs while full preparation is unresolved');
 finish({request_id:'own-1'});await flush();assert.deepEqual(effects,['tick','tick'],'A result cannot mutate a world outside its serialized cycle');
 timers.shift()();await flush();assert.deepEqual(effects.slice(-2),[['commit','own-1'],'tick']);controller.handle({type:'dispose'});
 let done;const posts=[],endpoint=api.createPreparationController({post:v=>posts.push(v),loadPlanner:async()=>({prepare:job=>new Promise(resolve=>{done=()=>resolve({request_id:job.request_id});})})});
 endpoint.handle({type:'planner_boot',config:{}});endpoint.handle({type:'prepare_route',id:7,job:{request_id:'own-7'}});await flush();
 assert.deepEqual(posts.map(v=>v.progress?.phase),['planner_ready','planner_job_start']);done();await flush();
 assert.equal(posts.at(-2).progress.phase,'planner_job_end');
 assert.deepEqual(posts.at(-1),{type:'prepared_route',id:7,result:{request_id:'own-7'}});
 const sent=[],fake={postMessage:v=>sent.push(v),terminate(){this.closed=true;}};
 const planner=api.createBackgroundPlanner({},()=>{},()=>fake);const result=planner.prepare({request_id:'own-8'});
 fake.onmessage({data:{type:'prepared_route',id:sent[1].id,result:{request_id:'own-8'}}});assert.deepEqual(await result,{request_id:'own-8'});
 fake.onmessage({data:{type:'planner_error',error:'geometry changed'}});
 await assert.rejects(planner.prepare({request_id:'own-9'}),/geometry changed/);planner.dispose();assert(fake.closed);
 const order=[];let releaseTask,priority;
 priority=api.createPreparationController({post(value){if(value.type==='prepared_route')order.push(value.id);},
  loadPlanner:async()=>({prepare:job=>({request_id:job.request_id})}),
  nextTask:()=>new Promise(resolve=>{releaseTask=resolve;})});
 priority.handle({type:'planner_boot',config:{}});
 priority.handle({type:'prepare_route',id:1,job:{kind:'full_route'}});
 priority.handle({type:'prepare_route',id:2,job:{kind:'full_route'}});await flush();
 assert.deepEqual(order,[1]);
 priority.handle({type:'prepare_route',id:3,job:{kind:'continuation'}});releaseTask();await flush();
 assert.deepEqual(order,[1,3],'Incoming continuations enter at the actual task boundary before queued full routes');
 releaseTask();await flush();assert.deepEqual(order,[1,3,2]);
 const fleet=Array.from({length:20},(_,i)=>'BF'+String(i+1).padStart(2,'0'));
 const completed=[],failures=[],received=new Set();let boot,finishActive,maxOutstanding=0;
 const intervals=api.createPreparationController({
  post(value){
   if(value.type==='planner_error')failures.push(value.error);
   if(value.type==='prepared_route'){completed.push(value.id);received.delete(value.id);}
  },
  loadPlanner:()=>new Promise(resolve=>{boot=()=>resolve({
   prepare:()=>new Promise(done=>{finishActive=()=>done({});})});}),
  nextTask:flush
 });
 intervals.handle({type:'planner_boot',config:{}});await flush();
 function offer(id,job){
  received.add(id);maxOutstanding=Math.max(maxOutstanding,received.size);
  intervals.handle({type:'prepare_route',id,job});
 }
 // Equal-headroom ties keep FIFO even across different vehicles. Both complete
 // waves reuse the same vehicles without overlapping interval ownership.
 offer('full',{kind:'full_route'});
 for(const [i,vehicle_id] of fleet.entries())offer('first'+i,{
  kind:'route_interval',vehicle_id,brake_headroom_mm:Math.floor((19-i)/2)});
 offer('join1',{kind:'continuation'});offer('join2',{kind:'continuation'});
 boot();await flush();
 for(let count=0;count<23;count++){finishActive();await flush();await flush();}
 const firstOrder=fleet.map((_,i)=>i).sort((a,b)=>Math.floor((19-a)/2)-Math.floor((19-b)/2));
 assert.deepEqual(completed,['join1','join2',...firstOrder.map(i=>'first'+i),'full']);
 for(const [i,vehicle_id] of fleet.entries())offer('second'+i,{
  kind:'route_interval',vehicle_id,brake_headroom_mm:i});
 for(let count=0;count<20;count++){finishActive();await flush();await flush();}
 assert.deepEqual(completed.slice(23),fleet.map((_,i)=>'second'+i));
 assert.equal(maxOutstanding,23);assert.equal(received.size,0);assert.deepEqual(failures,[]);
 const repeated={kind:'route_interval',vehicle_id:'BF01',brake_headroom_mm:12};
 offer('first-active',repeated);offer('duplicate-active',repeated);
 assert.match(failures.at(-1),/One interval per vehicle/);
 finishActive();await flush();assert(!completed.includes('first-active'),'Fail closed on overlapping requests');
 const cadence=[],quietTimers=[],quietPosts=[],staged=[{kind:'full_route',request_id:'1',vehicle_id:'BF06'}];
 let plannerStarts=0,preparedCount=0,modelTime=0,wall=0,plannerEvent,runtimeEvent;
 const quiet=api.createController({post:v=>quietPosts.push(v),now:()=>wall,
  loadRuntime:async(_,progress,compactAssetsReady)=>{
   runtimeEvent=progress;compactAssetsReady();assert.equal(plannerStarts,1,'Prewarm before simulator boot finishes');
   return{initial:state(0),background:true,snapshotIntervalSteps:4,
    tick(capture){cadence.push(capture);modelTime+=.05;wall+=80;return capture?state(modelTime):null;},pendingJobs:()=>staged.splice(0)};
  },
  makePlanner:(_,progress)=>{plannerStarts++;plannerEvent=progress;return{prepare(){preparedCount++;return new Promise(()=>{});},dispose(){}};},
  setTimer:fn=>{quietTimers.push(fn);return fn;},clearTimer(){}});
 quiet.handle({type:'boot',config:{}});await flush();
 quietTimers.shift()();await flush();assert.equal(preparedCount,1,'A submitted full route starts before visible motion');
 plannerEvent({phase:'planner_ready',planner_boot_wall_s:.1,planner_ready_wall_ms:100});
 quietTimers.shift()();await flush();
 const meta={kind:'full_route',request_id:'1',vehicle_id:'BF06'};
 plannerEvent({phase:'planner_job_start',...meta});
 plannerEvent({phase:'planner_job_phase',...meta,name:'compile_motion',wall_s:.17});
 runtimeEvent({phase:'starter_timing',wall_s:1.2,request_id:'1',vehicle_id:'BF06',installed:true,model_time_s:.1});
 quietTimers.shift()();await flush();
 assert.deepEqual(cadence,[false,false,false]);assert.equal(quietPosts.filter(v=>v.type==='state').length,1);
 plannerEvent({phase:'planner_job_end',...meta,total_wall_s:.21});
 wall+=20;quietTimers.shift()();await flush();assert.deepEqual(cadence,[false,false,false,true]);
 assert.equal(plannerStarts,1);assert.equal(preparedCount,1);assert.equal(quietPosts.filter(v=>v.type==='state').length,2);
 const timing=quiet.state.worker_timing;
 assert.deepEqual(Object.fromEntries(Object.entries(timing.cycles_by_planner).map(([k,v])=>[k,v.count])),{booting:1,idle:2,active:1});
 assert.equal(timing.last_cycle.realtime_factor,.5);assert.equal(timing.last_cycle.compute_wall_s,.08);
 assert.equal(timing.last_starter.wall_s,1.2);assert.equal(timing.planner_boot_wall_s,.1);
 assert.deepEqual(timing.planner_jobs.full_route,{request_id:'1',vehicle_id:'BF06',status:'complete',phase_wall_s:{compile_motion:.17},total_wall_s:.21});
 quiet.handle({type:'dispose'});
 console.log('Passed separate preparation, continued world ticks, serialized result commit, request matching and persistent failure checks.');
})().catch(error=>{console.error(error);process.exitCode=1;});
