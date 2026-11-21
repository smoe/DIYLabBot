// Native meshes + real pointer/keyboard input, with controlled test time.
// Usage: node this.cjs <index.html> <playwright> <chrome>
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url'),crypto=require('node:crypto');
const {chromium}=require(process.argv[3]||'playwright');
(async()=>{
  const file=path.resolve(process.argv[2]),html=fs.readFileSync(file,'utf8'),output=path.dirname(file);
  const data=JSON.parse(html.match(/<script id="walkthrough-data" type="application\/json">([\s\S]*?)<\/script>/)[1]);
  const lift=data.elevator,groups=new Map(data.scenes.building.groups.map(g=>[g.id,g]));
  const cabin=data.objects.find(o=>o.id===lift.object_id),moving=new Set(cabin.moving_body_ids);
  const report={passed:false,html_sha256:crypto.createHash('sha256').update(html).digest('hex'),floors:[],walk_samples:[],errors:[],timing:'Controlled test clock; no real-time performance claim.'};
  const browser=await chromium.launch({headless:true,executablePath:process.argv[4],args:['--enable-gpu','--enable-webgl','--ignore-gpu-blocklist','--use-gl=angle','--use-angle=metal']});
  try{
    const page=await browser.newPage({viewport:{width:1280,height:1000},reducedMotion:'no-preference'});
    page.on('pageerror',e=>report.errors.push(e.message));
    await page.goto(pathToFileURL(file).href,{waitUntil:'load',timeout:120000});
    await page.waitForFunction(()=>window.__buildingWalkthrough?.ready||document.querySelector('#building-walkthrough').dataset.error,null,{timeout:120000});
    assert.equal(await page.locator('#building-walkthrough').getAttribute('data-error'),null,await page.locator('#walkthrough-error').textContent());
    await page.clock.install();
    const read=()=>page.evaluate(()=>({camera:window.__buildingWalkthrough.camera,lift:window.__buildingWalkthrough.elevator}));
    async function settle(){for(let n=0;n<40;n++){await page.clock.fastForward(3000);const s=await read();if(s.lift.state!=='moving'&&s.lift.door_phase==='idle')return s;}throw Error('Lift did not settle');}
    async function lookAt(point){
      const {camera}=await read(),d=point.map((v,i)=>v-camera.eye_mm[i]);
      const turn=Math.atan2(Math.sin(Math.atan2(d[1],d[0])-camera.yaw_rad),Math.cos(Math.atan2(d[1],d[0])-camera.yaw_rad));
      const dx=-turn/data.settings.look_sensitivity,dy=-(Math.atan2(d[2],Math.hypot(d[0],d[1]))-camera.pitch_rad)/data.settings.look_sensitivity;
      if(Math.hypot(dx,dy)<.05)return;
      const box=await page.locator('#walkthrough-canvas').boundingBox(),x=box.x+box.width/2,y=box.y+box.height/2;
      const count=Math.max(1,Math.ceil(Math.abs(dx)/(box.width*.22)),Math.ceil(Math.abs(dy)/(box.height*.22)));
      for(let n=0;n<count;n++){
        await page.mouse.move(x,y);await page.mouse.down();
        if(Math.hypot(dx/count,dy/count)<8)await page.mouse.move(x+12,y);
        await page.mouse.move(x+dx/count,y+dy/count,{steps:3});await page.mouse.up();
      }await page.clock.runFor(30);
    }
    async function point(id,sign=1){
      const b=groups.get(id).bounds_mm,s=await read();
      const axis=lift.fittings.panel.body_ids.includes(id)?1:0;
      return [0,1,2].map(i=>(i===axis?b[sign>0?'max':'min'][i]:(b.min[i]+b.max[i])/2)
        +(i===2&&moving.has(id)?s.lift.value_mm-lift.reference_z_mm:0));
    }
    async function clickBody(id,sign=1){
      const target=await point(id,sign);await lookAt(target);
      const p=await page.evaluate(p=>{const v=window.__buildingWalkthrough.projectPoint(p),c=document.querySelector('canvas');return {...v,width:c.width,height:c.height};},target);
      assert(p.visible,id+': visible native button');
      const box=await page.locator('#walkthrough-canvas').boundingBox();await page.mouse.click(box.x+p.x*box.width/p.width,box.y+p.y*box.height/p.height);
      await page.clock.runFor(20);
      const result=await page.evaluate(()=>window.__buildingWalkthrough.lastInteraction);
      assert(['accepted','already_in_state'].includes(result?.status),id+': '+JSON.stringify(result));
      return result;
    }
    async function walk(target,{blocked=false,untilBoarded=false}={}){
      const before=await read();await lookAt([target[0],target[1],before.camera.eye_mm[2]]);
      await page.locator('#walkthrough-canvas').focus();await page.keyboard.down('w');
      let previous=before.camera.eye_mm,stalled=0,reached=false;
      try{for(let n=0;n<100;n++){
        await page.clock.runFor(50);const s=await read(),eye=s.camera.eye_mm,distance=Math.hypot(eye[0]-target[0],eye[1]-target[1]);
        const step=Math.hypot(...eye.map((v,i)=>v-previous[i]));
        assert(step<120,'Walking must not teleport on entry/exit: '+step);
        report.walk_samples.push({eye_mm:eye,boarded:s.lift.boarded,level:s.camera.level_id});
        stalled=step<.1?stalled+1:0;previous=eye;
        if(distance<90||(untilBoarded&&s.lift.boarded)){reached=true;break;}
        if(stalled>4)break;
      }}finally{await page.keyboard.up('w');await page.clock.runFor(20);}
      assert.equal(reached,!blocked,JSON.stringify({target,blocked,current:await read()}));return read();
    }
    async function checkDisplay(display,sign){
      const centre=await point(display.id+'_LED_2_1',sign);await lookAt(centre);await page.clock.runFor(30);
      const expected=(await read()).lift.display_level,positions=[];
      for(const cell of display.cells)positions.push({id:cell.body_id,point:await point(cell.body_id,sign),on:cell.levels.includes(expected)});
      const pixels=await page.evaluate(points=>{
        const canvas=document.querySelector('canvas'),gl=canvas.getContext('webgl2');
        return points.map(({id,point,on})=>{const p=window.__buildingWalkthrough.projectPoint(point),rgba=new Uint8Array(4);
          gl.readPixels(Math.floor(p.x),canvas.height-1-Math.floor(p.y),1,1,gl.RGBA,gl.UNSIGNED_BYTE,rgba);
          return {id,on,visible:p.visible,projected:p,rgba:Array.from(rgba)};});
      },positions);
      try{for(const pixel of pixels){assert(pixel.visible,display.id+': LED is visible');assert.equal(pixel.rgba[0]>170&&pixel.rgba[1]<140,pixel.on,display.id+': '+JSON.stringify(pixel));}}
      catch(error){
        report.display_failure={id:display.id,expected,positions,pixels,state:await read()};
        await page.screenshot({path:path.join(output,'lift-display-failure.png')});throw error;
      }
      assert.equal(await page.locator('#walkthrough-lift-readout').textContent(),lift.controls.floor_labels[expected]);
      return {id:display.id,level:expected,pixels};
    }
    await settle();
    // The existing 2.8 m cellar leaf intersects the shaft when open. Keep this
    // control/walking scenario explicit; it is not a clearance proof for DK015.
    report.room_door_setup={id:'KG.DK015.Door',state:'closed',reason:'Existing open cellar leaf intrudes into the cabin; separate room-door geometry issue.'};
    const setup=await page.evaluate(id=>window.__buildingWalkthrough.command(id,'close'),report.room_door_setup.id);
    assert(['accepted','already_in_state'].includes(setup.status));await page.clock.runFor(1000);
    await page.evaluate(id=>window.__buildingWalkthrough.viewObject(id),lift.object_id);await page.clock.runFor(30);
    const ground=lift.ports.find(p=>p.active&&p.level_id==='EG');
    assert.equal((await page.evaluate(id=>window.__buildingWalkthrough.command(id,'OG3'),lift.object_id)).status,'accepted');await settle();
    await walk(ground.cabin_entry_mm,{blocked:true});assert(!(await read()).lift.boarded);
    await walk(ground.exit_eye_mm);
    report.absent_cabin_display=await checkDisplay(lift.controls.displays.find(d=>d.port_id===ground.id),1);
    assert.equal(report.absent_cabin_display.level,'OG3','Ground landing shows the actual cabin floor, not its own floor');
    for(const destination of ['KG','EG','OG1','OG2','OG3']){
      const current=(await read()).camera.level_id,port=lift.ports.find(p=>p.active&&p.level_id===current);
      const landing=lift.controls.landing_panels.find(p=>p.port_id===port.id),sign=port.side==='outward'?-1:1;
      const call=await clickBody(landing.button_body_ids[0],sign);await settle();
      const hallDisplay=await checkDisplay(lift.controls.displays.find(d=>d.port_id===port.id),sign);
      await walk(port.cabin_entry_mm,{untilBoarded:true});assert((await read()).lift.boarded);
      const blocked=await page.evaluate(([id,floor])=>window.__buildingWalkthrough.command(id,floor),[lift.object_id,destination]);
      if(destination!==current)assert.equal(blocked.status,'rejected_doorway_occupied');
      await walk(port.cabin_entry_mm);
      const selection=lift.controls.floor_buttons.find(b=>b.level_id===destination);
      await clickBody(selection.body_ids[1]);
      await page.clock.fastForward(2000);const during=await read();
      await page.locator('#walkthrough-canvas').focus();await page.keyboard.down('w');await page.clock.runFor(150);await page.keyboard.up('w');
      const after=await read();assert.deepEqual(after.camera.eye_mm.slice(0,2),during.camera.eye_mm.slice(0,2),'Walking locked while moving');
      assert(after.camera.eye_mm.every((v,i)=>Math.abs(v-after.lift.attached_eye_mm[i])<.01));
      await settle();assert.equal((await read()).lift.state,destination);
      const cabinDisplay=await checkDisplay(lift.controls.displays.find(d=>d.port_id===null),1);
      if(['KG','OG3'].includes(destination)){
        const s=await read();await lookAt(lift.fittings.panel.center_mm.map((v,i)=>v+(i===2?s.lift.value_mm-lift.reference_z_mm:0)));
        await page.clock.runFor(30);await page.screenshot({path:path.join(output,'lift-cabin-'+destination+'.png')});
      }
      const exit=lift.ports.find(p=>p.active&&p.level_id===destination);
      await walk(exit.exit_eye_mm);assert(!(await read()).lift.boarded,'Ordinary walking exits at '+destination);
      const outDisplay=await checkDisplay(lift.controls.displays.find(d=>d.port_id===exit.id),exit.side==='outward'?-1:1);
      report.floors.push({destination,call,hallDisplay,cabinDisplay,outDisplay,walked_out:true});
      if(destination==='OG3')await page.screenshot({path:path.join(output,'lift-landing-OG3.png')});
    }
    assert.deepEqual(report.errors,[]);report.passed=true;
  }finally{await browser.close();fs.writeFileSync(path.join(output,'lift-walking-browser-report.json'),JSON.stringify(report,null,2)+'\n');}
  console.log(JSON.stringify({passed:report.passed,floors:report.floors.length,walk_samples:report.walk_samples.length,errors:report.errors}));
})().catch(error=>{console.error(error);process.exitCode=1;});
