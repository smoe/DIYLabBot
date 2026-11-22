// Usage: node tests/check_walkthrough_cold_storage_browser.cjs <index.html> <playwright> <chrome>
// Camera arrangement uses the QA view; device actions use real pointer/Space input.
'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const {pathToFileURL}=require('node:url');
const {jointMatrix}=require('../scripts/walkthrough_interaction.js');
const {chromium}=require(process.argv[3]||'playwright');

(async()=>{
  const file=path.resolve(process.argv[2]),output=path.dirname(file),bytes=fs.readFileSync(file);
  const data=JSON.parse(bytes.toString().match(/<script id="walkthrough-data" type="application\/json">([\s\S]*?)<\/script>/)[1]);
  const objects=new Map(data.objects.map(object=>[object.id,object]));
  const native=new Map(data.scenes.building.groups.map(group=>[group.id,group]));
  const fridge='Lab3003.Fridge01.OuterDoor',freezer='Lab3003.Freezer01.OuterDoor';
  const drawers=Array.from({length:6},(_,i)=>'Lab3003.Freezer01.Drawer'+String(i+1).padStart(2,'0'));
  const kitchens=['Kitchen1008.Fridge.Door','Kitchen3008.Fridge.Door'];
  const coldIds=[fridge,freezer,...drawers,...kitchens];
  for(const id of coldIds){
    const object=objects.get(id);assert(object,id+': source-defined joint is required');
    assert.equal(object.initial_state||object.reference_state,'closed',id+': closed initial state is source-defined');
    for(const body of object.moving_body_ids)assert(native.has(body),id+': native moving body '+body);
  }
  assert.deepEqual(new Set(data.objects.filter(object=>['fridge_4c','freezer_minus20'].includes(object.asset)
    ||/\.Fridge\.Door$/.test(object.id)).map(object=>object.id)),new Set(coldIds),'Every existing cooling appliance is covered');
  const report={passed:false,html_sha256:crypto.createHash('sha256').update(bytes).digest('hex'),
    initial_closed:[],public_interactions:[],guard_probes:[],geometry_cycles:[],errors:[]};
  const browser=await chromium.launch({headless:true,executablePath:process.argv[4],
    args:['--enable-gpu','--enable-webgl','--ignore-gpu-blocklist','--use-gl=angle','--use-angle=metal']});
  let page;
  try{
    page=await browser.newPage({viewport:{width:1280,height:950},reducedMotion:'reduce'});
    page.on('pageerror',error=>report.errors.push(error.message));
    await page.goto(pathToFileURL(file).href,{waitUntil:'load',timeout:120000});
    await page.waitForFunction(()=>window.__buildingWalkthrough?.ready||document.querySelector('#building-walkthrough').dataset.error,
      null,{timeout:120000});
    assert.equal(await page.locator('#building-walkthrough').getAttribute('data-error'),null,
      await page.locator('#walkthrough-error').textContent());
    const state=id=>page.evaluate(id=>window.__buildingWalkthrough.objects.find(object=>object.id===id),id);
    const settled=(id,expected)=>page.waitForFunction(([id,expected])=>
      window.__buildingWalkthrough.objects.find(object=>object.id===id).state===expected,[id,expected]);
    const point=(p,m)=>[0,1,2].map(i=>m[i]*p[0]+m[i+4]*p[1]+m[i+8]*p[2]+m[i+12]);
    const centre=group=>group.bounds_mm.min.map((value,i)=>(value+group.bounds_mm.max[i])/2000);
    function verifyPose(id,snapshot,expected){
      const object=objects.get(id),value=object.states[expected];
      assert.equal(snapshot.state,expected);assert.equal(snapshot.joint_value,value);
      const expectedMatrix=jointMatrix(object.joint,value,object.states[object.reference_state]);
      assert(snapshot.model_matrix.every((v,i)=>Math.abs(v-expectedMatrix[i])<1e-7),id+': source reference transform');
      const bodyValues=snapshot.body_angles_deg||snapshot.body_displacements_mm;
      assert.deepEqual(new Set(Object.keys(bodyValues)),new Set(object.moving_body_ids));
      assert(Object.values(bodyValues).every(v=>v===value),id+': all leaf/handle/support bodies share the joint');
    }
    for(const id of coldIds){const snapshot=await state(id);verifyPose(id,snapshot,'closed');report.initial_closed.push(id);}

    async function lookAt(target){
      const camera=await page.evaluate(()=>window.__buildingWalkthrough.camera),d=target.map((v,i)=>v-camera.eye_mm[i]);
      const turn=Math.atan2(Math.sin(Math.atan2(d[1],d[0])-camera.yaw_rad),Math.cos(Math.atan2(d[1],d[0])-camera.yaw_rad));
      const dx=-turn/data.settings.look_sensitivity,
        dy=-(Math.atan2(d[2],Math.hypot(d[0],d[1]))-camera.pitch_rad)/data.settings.look_sensitivity;
      if(Math.hypot(dx,dy)<.05)return;
      const box=await page.locator('#walkthrough-canvas').boundingBox(),x=box.x+box.width/2,y=box.y+box.height/2;
      const steps=Math.max(1,Math.ceil(Math.abs(dx)/(box.width*.25)),Math.ceil(Math.abs(dy)/(box.height*.25)));
      for(let i=0;i<steps;i++){
        await page.mouse.move(x,y);await page.mouse.down();
        if(Math.hypot(dx/steps,dy/steps)<8)await page.mouse.move(x+12,y,{steps:2});
        await page.mouse.move(x+dx/steps,y+dy/steps,{steps:4});await page.mouse.up();
      }
    }
    async function operate(id,expected,{status='accepted'}={}){
      const object=objects.get(id);
      if(id.startsWith('Kitchen3008.'))await page.locator('#walkthrough-stops button[data-stop="kitchen3008"]').click();
      else await page.evaluate(id=>window.__buildingWalkthrough.viewObject(id),id);
      const groups=object.moving_body_ids.map(id=>native.get(id));
      const handles=groups.filter(group=>/handle|grip/i.test(group.role+' '+group.id));
      let interaction;
      for(const group of [...handles,...groups.filter(group=>!handles.includes(group))]){
        const snapshot=await state(id),world=point(centre(group),snapshot.model_matrix).map(v=>v*1000);
        await lookAt(world);
        const pixel=await page.evaluate(world=>{
          const p=window.__buildingWalkthrough.projectPoint(world),canvas=document.querySelector('#walkthrough-canvas'),r=canvas.getBoundingClientRect();
          return {x:r.left+p.x*r.width/canvas.width,y:r.top+p.y*r.height/canvas.height,visible:p.visible};
        },world);
        if(!pixel.visible)continue;
        await page.mouse.click(pixel.x,pixel.y);
        interaction=await page.evaluate(()=>window.__buildingWalkthrough.lastInteraction);
        if(interaction?.id===id&&interaction.status===status)break;
        assert(interaction?.status!=='accepted',id+': a candidate must not operate another object');
      }
      if(interaction?.id!==id||interaction.status!==status){
        // The public Space action also selects an open door at its closed
        // aperture. It still uses the native picker, reach and occlusion rules.
        const reference=jointMatrix(object.joint,object.states.closed,object.states[object.reference_state]);
        await lookAt(point(centre(groups[0]),reference).map(v=>v*1000));
        await page.locator('#walkthrough-canvas').focus();await page.keyboard.press('Space');
        interaction=await page.evaluate(()=>window.__buildingWalkthrough.lastInteraction);
      }
      assert.equal(interaction?.id,id,id+': public input selects its native surface');
      assert.equal(interaction.status,status,id+': public command result');
      await settled(id,expected);verifyPose(id,await state(id),expected);
      report.public_interactions.push({id,expected,...interaction});return interaction;
    }
    async function cycle(id){
      const before=await state(id);verifyPose(id,before,'closed');
      await operate(id,'open');const open=await state(id);
      const movement=Object.fromEntries(objects.get(id).moving_body_ids.map(body=>{
        const p=centre(native.get(body)),a=point(p,before.model_matrix),b=point(p,open.model_matrix);
        const distance=Math.hypot(...a.map((v,i)=>v-b[i]))*1000;
        assert(distance>1,body+': native component moves with the opened joint');return [body,distance];
      }));
      await page.screenshot({path:path.join(output,'cold-storage-'+id.replaceAll('.','-')+'-open.png')});
      await operate(id,'closed');const after=await state(id);
      assert.deepEqual(after.model_matrix,before.model_matrix,id+': closed geometry is restored exactly');
      report.geometry_cycles.push({id,moving_body_centres_displacement_mm:movement});
    }
    await cycle(fridge);
    const drawer=drawers[3];
    // A closed outer door correctly hides its drawer from public picking.
    // Probe only rejected commands through the diagnostic API; every accepted
    // opening/closure below still comes from actual public input.
    const blockedDrawer=await page.evaluate(id=>window.__buildingWalkthrough.command(id,'open'),drawer);
    assert.equal(blockedDrawer.status,'rejected_interlock');
    assert.deepEqual(blockedDrawer.blockers,[freezer],'Closed outer door blocks drawer extension');
    verifyPose(drawer,await state(drawer),'closed');report.guard_probes.push(blockedDrawer);
    await operate(freezer,'open');await operate(drawer,'open');
    const blockedDoor=await page.evaluate(id=>window.__buildingWalkthrough.command(id,'close'),freezer);
    assert.equal(blockedDoor.status,'rejected_interlock');
    assert.deepEqual(blockedDoor.blockers,[drawer],'Extended drawer blocks freezer closure');
    verifyPose(freezer,await state(freezer),'open');report.guard_probes.push(blockedDoor);
    await operate(drawer,'closed');await operate(freezer,'closed');
    await cycle(freezer);
    for(const id of kitchens)await cycle(id);
    await page.emulateMedia({reducedMotion:'no-preference'});
    await page.evaluate(id=>{
      const capture={active:true,samples:[]};window.__coldStorageMotion=capture;
      function sample(){
        const object=window.__buildingWalkthrough.objects.find(object=>object.id===id);
        capture.samples.push({frame:window.__buildingWalkthrough.frames,state:object.state,value:object.joint_value});
        if(capture.active)requestAnimationFrame(sample);
      }
      requestAnimationFrame(sample);
    },fridge);
    await cycle(fridge);
    const samples=await page.evaluate(()=>{window.__coldStorageMotion.active=false;return window.__coldStorageMotion.samples;});
    const maximum=objects.get(fridge).states.open;
    for(const phase of ['opening','closing']){
      const values=samples.filter(sample=>sample.state===phase).map(sample=>sample.value);
      assert(values.some(value=>value>0&&value<maximum),fridge+': actual rendered intermediate '+phase+' pose');
      assert(values.every((value,i)=>value>=0&&value<=maximum&&(!i||(phase==='opening'?value>=values[i-1]:value<=values[i-1]))),
        fridge+': bounded monotone '+phase+' motion');
    }
    report.timed_fridge_motion=samples;
    for(const id of coldIds)verifyPose(id,await state(id),'closed');
    assert.deepEqual(report.errors,[]);report.passed=true;
  }catch(error){
    report.failure={message:error.message,stack:error.stack};
    if(page){
      report.failure.viewer=await page.evaluate(()=>({camera:window.__buildingWalkthrough?.camera,
        lastInteraction:window.__buildingWalkthrough?.lastInteraction,objects:window.__buildingWalkthrough?.objects})).catch(()=>null);
      await page.screenshot({path:path.join(output,'cold-storage-failure.png'),fullPage:true}).catch(()=>{});
    }
    throw error;
  }finally{
    await browser.close();fs.writeFileSync(path.join(output,'cold-storage-browser-report.json'),JSON.stringify(report,null,2)+'\n');
  }
  console.log(JSON.stringify(report,null,2));
})().catch(error=>{console.error(error);process.exitCode=1;});
