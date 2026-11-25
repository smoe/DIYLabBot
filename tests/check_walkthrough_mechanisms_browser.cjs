// Usage: node tests/check_walkthrough_mechanisms_browser.cjs <index.html> <playwright> <chrome>
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url');
const {chromium}=require(process.argv[3]||'playwright');
(async()=>{
  const file=path.resolve(process.argv[2]),output=path.dirname(file);
  const model=JSON.parse(fs.readFileSync(file,'utf8').match(/<script id="walkthrough-data" type="application\/json">([\s\S]*?)<\/script>/)[1]);
  const native=new Map(model.scenes.building.groups.map(g=>[g.id,g]));
  const objects=new Map(model.objects.map(o=>[o.id,o]));
  const rooms=model.objects.filter(o=>o.mechanism==='room_door'),equipment=model.objects.filter(o=>o.mechanism==='equipment');
  const nativeDoors=model.scenes.building.groups.filter(g=>g.role?.startsWith('concept_open_')&&g.role.endsWith('_room_door'));
  assert.deepEqual(new Set(rooms.flatMap(o=>o.moving_body_ids).filter(id=>nativeDoors.some(g=>g.id===id))),new Set(nativeDoors.map(g=>g.id)));
  for(const o of model.objects)for(const id of o.moving_body_ids)assert(native.has(id),id+': native surface required');
  const browser=await chromium.launch({headless:true,executablePath:process.argv[4],args:['--enable-gpu','--enable-webgl','--ignore-gpu-blocklist','--use-gl=angle','--use-angle=metal']});
  const errors=[],report={room_door_count:rooms.length,equipment_count:equipment.length,public_interactions:[],passed:false};
  try{
    const page=await browser.newPage({viewport:{width:1280,height:950},reducedMotion:'reduce'});
    page.on('pageerror',e=>errors.push(e.message));
    await page.goto(pathToFileURL(file).href,{waitUntil:'load',timeout:120000});
    await page.waitForFunction(()=>window.__buildingWalkthrough?.ready||document.querySelector('#building-walkthrough').dataset.error,null,{timeout:120000});
    assert.equal(await page.locator('#building-walkthrough').getAttribute('data-error'),null,
      await page.locator('#walkthrough-error').textContent());
    const state=id=>page.evaluate(id=>window.__buildingWalkthrough.objects.find(o=>o.id===id),id);
    async function command(id,name){return page.evaluate(([id,name])=>window.__buildingWalkthrough.command(id,name),[id,name]);}
    async function settled(id,expected){await page.waitForFunction(([id,state])=>window.__buildingWalkthrough.objects.find(o=>o.id===id).state===state,[id,expected]);}
    const freezer='Lab3003.Freezer01.',outer=freezer+'OuterDoor';
    report.freezer_initial_states=[];
    for(const id of [outer,...Array.from({length:6},(_,index)=>freezer+'Drawer'+String(index+1).padStart(2,'0'))]){
      assert.equal(objects.get(id).initial_state,'closed',id+': explicit closed startup policy');
      const initial=await state(id);
      assert.equal(initial.state,'closed',id+': starts closed');
      assert.equal(initial.target_state,'closed',id+': starts without an opening intent');
      assert.equal(initial.joint_value,objects.get(id).states.closed,id+': closed joint endpoint');
      report.freezer_initial_states.push({id,state:initial.state,joint_value:initial.joint_value});
    }
    report.basic_laboratory_controls=[];
    for(const lab of model.laboratories.filter(lab=>lab.furnishing_profile)){
      const controls=model.objects.filter(o=>o.id.startsWith(lab.id+'.Hood01.'));
      assert.equal(controls.length,4,lab.id+': source-defined sash and three cabinet doors');
      for(const control of controls){
        assert.equal((await command(control.id,'open')).status,'accepted');await settled(control.id,'open');
        assert.equal((await state(control.id)).joint_value,control.states.open);
        assert.equal((await command(control.id,'close')).status,'accepted');await settled(control.id,'closed');
        assert.deepEqual((await state(control.id)).model_matrix,[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]);
        report.basic_laboratory_controls.push(control.id);
      }
    }
    // Every native room door completes a close/open cycle. Glazing and
    // handles share the rigid transform, including on steel basement leaves.
    for(const room of rooms){
      const initial=room.initial_state||room.reference_state;
      assert.equal((await state(room.id)).state,initial,'Source-defined initial pose');
      assert.equal((await command(room.id,'close')).status,initial==='closed'?'already_in_state':'accepted');await settled(room.id,'closed');
      const closed=await state(room.id);assert.equal(closed.angle_deg,0);
      const leaf=room.moving_body_ids[0];
      for(const side of ['Front','Back']){
        const handle=leaf+'_Handle'+side;
        assert.equal(native.get(handle)?.role,'concept_room_door_handle');
        assert.equal(closed.body_angles_deg[handle],0);
      }
      assert(Object.values(closed.body_angles_deg).every(v=>v===0));
      assert.equal((await command(room.id,'open')).status,'accepted');await settled(room.id,'open');
      assert.deepEqual((await state(room.id)).model_matrix,[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]);
      if(initial==='closed'){assert.equal((await command(room.id,'close')).status,'accepted');await settled(room.id,'closed');}
    }
    // Establish an open drawer explicitly before testing the closure interlock.
    assert.equal((await command(outer,'open')).status,'accepted');await settled(outer,'open');
    assert.equal((await command(freezer+'Drawer04','open')).status,'accepted');await settled(freezer+'Drawer04','open');
    assert.equal((await command(outer,'close')).status,'rejected_interlock');
    for(let n=1;n<=6;n++)await command(freezer+'Drawer'+String(n).padStart(2,'0'),'close');
    assert.equal((await command(outer,'close')).status,'accepted');
    for(let n=1;n<=6;n++)assert.equal((await command(freezer+'Drawer'+String(n).padStart(2,'0'),'open')).status,'rejected_interlock');
    assert.equal((await command(outer,'open')).status,'accepted');
    for(let n=1;n<=6;n++){
      const id=freezer+'Drawer'+String(n).padStart(2,'0');
      assert.equal((await command(id,'open')).status,'accepted');
      assert.deepEqual((await command(outer,'close')).blockers,[id]);
      assert.equal((await command(id,'close')).status,'accepted');
    }
    // Mouse events use the actual moved door and handle surfaces, without bypassing the
    // triangle picker, reach limit or occlusion test. viewObject only positions
    // the QA camera; it does not perform the interaction.
    async function lookAt(point){
      const camera=await page.evaluate(()=>window.__buildingWalkthrough.camera);
      const d=point.map((v,i)=>v-camera.eye_mm[i]);
      const turn=Math.atan2(Math.sin(Math.atan2(d[1],d[0])-camera.yaw_rad),Math.cos(Math.atan2(d[1],d[0])-camera.yaw_rad));
      const dx=-turn/model.settings.look_sensitivity,dy=-(Math.atan2(d[2],Math.hypot(d[0],d[1]))-camera.pitch_rad)/model.settings.look_sensitivity;
      if(Math.hypot(dx,dy)<.05)return;
      const box=await page.locator('#walkthrough-canvas').boundingBox(),x=box.x+box.width/2,y=box.y+box.height/2;
      const steps=Math.max(1,Math.ceil(Math.abs(dx)/(box.width*.25)),Math.ceil(Math.abs(dy)/(box.height*.25)));
      for(let n=0;n<steps;n++){
        await page.mouse.move(x,y);await page.mouse.down();
        if(Math.hypot(dx/steps,dy/steps)<8)await page.mouse.move(x+12,y,{steps:2});
        await page.mouse.move(x+dx/steps,y+dy/steps,{steps:4});await page.mouse.up();
      }
    }
    async function clickObject(id,expected){
      const config=objects.get(id);
      // Use the public kitchen entrance view: the generic appliance QA view
      // sits behind this small room's parked-open entrance leaf.
      if(id.startsWith('Kitchen3008.'))await page.locator('#walkthrough-stops button[data-stop="kitchen3008"]').click();
      else await page.evaluate(id=>window.__buildingWalkthrough.viewObject(id),id);
      const candidates=config.moving_body_ids.map(id=>native.get(id)).filter(g=>/handle|grip/i.test(g.role+' '+g.id));
      // A room-door lever can be occluded when its leaf parks beside a wall.
      if(config.mechanism==='room_door'||!candidates.length)candidates.push(native.get(config.moving_body_ids[0]));
      let success=false;
      for(const group of candidates){
        const point=group.bounds_mm.min.map((v,i)=>(v+group.bounds_mm.max[i])/2);
        const world=await page.evaluate(({id,point})=>{
          const viewer=window.__buildingWalkthrough,m=viewer.objects.find(o=>o.id===id).model_matrix,p=point.map(v=>v/1000);
          return [0,1,2].map(r=>(m[r]*p[0]+m[r+4]*p[1]+m[r+8]*p[2]+m[r+12])*1000);
        },{id,point});
        if(id.startsWith('Kitchen3008.'))await lookAt(world);
        const pixel=await page.evaluate(world=>{
          const projected=window.__buildingWalkthrough.projectPoint(world);
          const canvas=document.querySelector('#walkthrough-canvas'),rect=canvas.getBoundingClientRect();
          return {x:rect.left+projected.x*rect.width/canvas.width,y:rect.top+projected.y*rect.height/canvas.height,visible:projected.visible};
        },world);
        if(!pixel.visible)continue;
        await page.mouse.click(pixel.x,pixel.y);
        const hit=await page.evaluate(()=>window.__buildingWalkthrough.lastInteraction);
        if(hit?.id===id&&hit.status==='accepted'){success=true;break;}
      }
      if(!success)await page.screenshot({path:path.join(output,'mechanisms-pick-failure.png')});
      assert(success,id+': public click reaches the moving surface');await settled(id,expected);
      report.public_interactions.push({id,input:'click',state:expected});
    }
    report.laboratory_corridor_doors=[];
    const laboratoryDoors=rooms.filter(room=>room.laboratory_corridor);
    assert.equal(laboratoryDoors.length,27,'Every confirmed laboratory exit has a corridor opening binding');
    for(const room of laboratoryDoors){
      const lab=model.laboratories.find(lab=>lab.level_id===room.level_id&&lab.area===room.laboratory_corridor.laboratory);
      assert(lab,room.id+': actual laboratory assignment required');
      const centre=[0,1].map(i=>lab.interior_polygon_mm.reduce((sum,p)=>sum+p[i],0)/lab.interior_polygon_mm.length);
      assert(centre.reduce((sum,v,i)=>sum+(v-room.joint.origin_mm[i])*room.front[i],0)<0,
        room.id+': open leaf points away from the laboratory');
      await command(room.id,'close');await settled(room.id,'closed');
      await clickObject(room.id,'open');await clickObject(room.id,'closed');
      await command(room.id,room.initial_state||room.reference_state);
      await settled(room.id,room.initial_state||room.reference_state);
      report.laboratory_corridor_doors.push(room.id);
    }
    for(const id of [outer,freezer+'Drawer04','Lab3001.Hood01.Sash','LabEG003.Hood01.HoodBase_Door1',
      'Lab3003.Hood01.Sash','Lab3003.Hood01.HoodBase_Door1',
      'Lab3003.Hood01.HoodBase_Door2','Lab3003.Hood01.HoodBase_Door3','Lab3003.NanoDrop01.Hinge','Lab3003.Qubit01.Hinge',
      'Kitchen3008.Fridge.Door','Kitchen3008.Microwave.Door']){
      await command(id,'close');await clickObject(id,'open');
      await page.screenshot({path:path.join(output,'mechanisms-'+(id.startsWith('Lab3001.')||id.startsWith('LabEG003.')?id.replaceAll('.','-'):id.split('.').slice(1).join('-'))+'-open.png')});
      await clickObject(id,'closed');
      if(id===outer)await command(id,'open');
    }
    for(const room of [objects.get('OG3.D3_002N.Door'),objects.get('OG3.D3_002_001.Door'),
      objects.get('OG3.D3_008A.Door'),objects.get('OG3.D3_008AB.Door'),rooms.find(o=>o.level_id==='KG')]){
      await command(room.id,'close');await clickObject(room.id,'open');
      await page.locator('#walkthrough-canvas').focus();await page.keyboard.press('Space');await settled(room.id,'closed');
      report.public_interactions.push({id:room.id,input:'space',state:'closed'});
    }
    report.basic_laboratories=[];
    await page.setViewportSize({width:1600,height:1050});
    for(const id of ['Lab3001','LabEG003','LabEG015']){
      const lab=model.laboratories.find(lab=>lab.id===id);
      assert(lab&&lab.wet_pair_placed&&lab.central_double_bench_placed);
      const sideDoors=model.objects.filter(o=>o.id.startsWith(id+'.Side_'));
      const distance=o=>Math.hypot(...o.viewpoint.eye_mm.slice(0,2).map((v,i)=>v-lab.wet_corner.point_mm[i]));
      sideDoors.sort((a,b)=>distance(b)-distance(a));assert(sideDoors.length);
      await page.evaluate(id=>window.__buildingWalkthrough.viewObject(id),sideDoors[0].id);
      const island=lab.instances.find(i=>i.id==='IslandLeft');
      const middle=[0,1].map(i=>island.footprint_mm.reduce((sum,p)=>sum+p[i],0)/4);
      const level=model.levels.find(level=>level.id===lab.level_id);
      await lookAt(middle.map((v,i)=>.6*v+.4*lab.wet_corner.point_mm[i]).concat(level.z_mm+1400));
      const screenshot='browser-basic-'+id+'.png';
      await page.screenshot({path:path.join(output,screenshot),fullPage:true});
      report.basic_laboratories.push({id,body_count:lab.body_ids.length,compact:lab.compact_layout,
        screenshot,camera:await page.evaluate(()=>window.__buildingWalkthrough.camera)});
    }

    // A real timed cycle checks guards during motion, not only endpoints.
    await page.emulateMedia({reducedMotion:'no-preference'});
    report.laboratory_door_motion=[];
    for(const target of ['closed','open']){
      const ids=laboratoryDoors.map(room=>room.id);
      const samples=await page.evaluate(async({ids,target})=>{
        const viewer=window.__buildingWalkthrough,out=[];
        for(const id of ids){
          const result=viewer.command(id,target==='closed'?'close':'open');
          if(result.status!=='accepted')throw Error(id+': timed command '+result.status);
        }
        await new Promise((resolve,reject)=>{const started=performance.now();function sample(){
          const states=viewer.objects.filter(o=>ids.includes(o.id));
          out.push(states.map(o=>({id:o.id,state:o.state,angle:o.joint_value})));
          if(states.every(o=>o.state===target))resolve();
          else if(performance.now()-started>10000)reject(Error('Laboratory door motion timeout'));
          else requestAnimationFrame(sample);
        // Sample rendered frames. A synchronous read after the command batch
        // can observe performance.now() updates ahead of the next RAF timestamp.
        }requestAnimationFrame(sample);});return out;
      },{ids,target});
      for(const id of ids){
        const angles=samples.map(frame=>frame.find(o=>o.id===id).angle);
        assert(angles.some(a=>a>0&&a<90),id+': timed intermediate pose required');
        assert(angles.every(a=>a>=0&&a<=90),id+': hinge limits');
        assert(angles.every((a,i)=>!i||(target==='open'?a>=angles[i-1]:a<=angles[i-1])),id+': monotone hinge motion');
        assert.equal(angles.at(-1),target==='open'?90:0);
      }
      report.laboratory_door_motion.push({target,door_count:ids.length,samples:samples.length,passed:true});
    }
    const drawer=freezer+'Drawer03';await command(drawer,'open');
    assert.equal((await command(outer,'close')).status,'rejected_interlock');
    await settled(drawer,'open');await command(drawer,'close');
    assert.equal((await command(outer,'close')).status,'rejected_interlock');await settled(drawer,'closed');
    await command(outer,'close');assert.equal((await command(drawer,'open')).status,'rejected_interlock');await settled(outer,'closed');
    await command(outer,'open');await settled(outer,'open');
    const lift=model.elevator;
    await page.evaluate(id=>window.__buildingWalkthrough.viewObject(id),lift.object_id);
    const samples=await page.evaluate(async id=>{
      const v=window.__buildingWalkthrough,out=[];v.command(id,'OG3');
      await new Promise((resolve,reject)=>{const started=performance.now();function sample(){
        const e=v.elevator,doors=v.objects.filter(o=>o.id.startsWith('LiftCabinDoor_')||o.id.startsWith('LiftLandingDoor_'));
        out.push({phase:e.door_phase,state:e.state,value:e.value_mm,doors:doors.map(o=>({id:o.id,state:o.state,value:o.joint_value,matrix:o.model_matrix}))});
        if(e.state==='OG3'&&e.door_phase==='idle')resolve();else if(performance.now()-started>45000)reject(Error('Lift cycle timeout'));else requestAnimationFrame(sample);
      }sample();});return out;
    },lift.object_id);
    assert(samples.some(s=>s.phase==='closing'));assert(samples.some(s=>s.phase==='travelling'));assert(samples.some(s=>s.phase==='opening'));
    for(const s of samples.filter(s=>s.state==='moving')){
      assert(s.doors.every(d=>d.state==='closed'&&d.value===0));
      for(const d of s.doors.filter(d=>d.id.startsWith('LiftCabinDoor_')))assert(Math.abs(d.matrix[14]*1000-s.value)<.01,'Cabin door travels with the single cabin');
    }
    const arrival=samples.at(-1),openIds=new Set(lift.ports.filter(p=>p.active&&p.level_id==='OG3').flatMap(p=>p.door_object_ids));
    assert.deepEqual(new Set(arrival.doors.filter(d=>d.state==='open').map(d=>d.id)),openIds);
    report.lift={timed_samples:samples.length,phases:[...new Set(samples.map(s=>s.phase))],open_at_OG3:[...openIds],cabin_door_parent_motion:true};
    assert.deepEqual(errors,[]);report.passed=true;
  }finally{await browser.close();fs.writeFileSync(path.join(output,'mechanisms-browser-report.json'),JSON.stringify(report,null,2)+'\n');}
  console.log(JSON.stringify(report));
})().catch(error=>{console.error(error);process.exitCode=1;});
