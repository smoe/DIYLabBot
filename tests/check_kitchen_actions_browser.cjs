// Exercise actual native handles and lids through click and Space, without UI buttons.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url');
const {chromium}=require(process.argv[3]||'playwright');
(async()=>{
  const file=path.resolve(process.argv[2]),html=fs.readFileSync(file,'utf8');
  const model=JSON.parse(html.match(/<script id="walkthrough-data" type="application\/json">([\s\S]*?)<\/script>/)[1]);
  const browser=await chromium.launch({headless:true,...(process.argv[4]?{executablePath:process.argv[4]}:{}),args:['--enable-webgl','--ignore-gpu-blocklist','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  try{
    const page=await browser.newPage({viewport:{width:1280,height:950},reducedMotion:'reduce'}),errors=[];
    page.on('pageerror',e=>errors.push(e.message));await page.goto(pathToFileURL(file).href,{timeout:120000});
    await page.waitForFunction(()=>window.__buildingWalkthrough?.ready,null,{timeout:120000});
    assert.equal(await page.locator('[data-object-action]').count(),0);
    assert(model.scenes.building.groups.some(g=>g.id==='SideWindow_OG3_W005_Glass'));
    assert(!model.scenes.building.groups.some(g=>g.id==='OG3__Wall_W017'||g.id==='OG3__DoorLeaf_D3_009'));
    async function rendered(action){
      const before=await page.evaluate(()=>window.__buildingWalkthrough.frames);
      await action();
      await page.waitForFunction(before=>window.__buildingWalkthrough.frames>before,before,{timeout:120000});
    }
    // Park the entrance leaf at its closed pose; an open leaf can obscure a
    // test camera even though the visitor can simply walk around it.
    for(const o of model.objects.filter(o=>o.id.includes('D3_008A')))
      await page.evaluate(id=>window.__buildingWalkthrough.command(id,'close'),o.id);
    const objects=model.objects.filter(o=>o.id.startsWith('Kitchen3008.Cabinet.')||o.id==='Kitchen3008.Kettle.Lid');
    assert.equal(objects.length,10);
    const report={passed:false,objects:[],errors};
    const state=id=>page.evaluate(id=>window.__buildingWalkthrough.objects.find(o=>o.id===id),id);
    for(const object of objects){
      await rendered(()=>page.evaluate(id=>window.__buildingWalkthrough.viewObject(id),object.id));
      const body=object.moving_body_ids.find(id=>/Handle\d?$/.test(id))||object.moving_body_ids.find(id=>id.endsWith('_Lid'));
      assert(body,object.id+': selectable hardware');
      const group=model.scenes.building.groups.find(g=>g.id===body);
      const point=group.bounds_mm.min.map((v,i)=>(v+group.bounds_mm.max[i])/2);
      const untouched=await page.evaluate(id=>window.__buildingWalkthrough.objects.filter(o=>o.id!==id).map(o=>[o.id,o.state,o.joint_value]),object.id);
      for(const expected of ['open','closed']){
        const pixel=await page.evaluate(({id,point})=>{
          const v=window.__buildingWalkthrough,o=v.objects.find(o=>o.id===id),m=o.model_matrix,p=point.map(x=>x/1000);
          const world=[0,1,2].map(r=>(m[r]*p[0]+m[4+r]*p[1]+m[8+r]*p[2]+m[12+r])*1000);
          const q=v.projectPoint(world),c=document.querySelector('canvas'),rect=c.getBoundingClientRect();
          return{x:rect.x+q.x*rect.width/c.width,y:rect.y+q.y*rect.height/c.height,visible:q.visible};
        },{id:object.id,point});
        assert(pixel.visible,object.id+': moved handle remains visible');
        await rendered(()=>page.mouse.click(pixel.x,pixel.y));
        assert.equal((await state(object.id)).state,expected,object.id+': mouse toggle '+JSON.stringify(await page.evaluate(()=>window.__buildingWalkthrough.lastInteraction)));
        assert.equal((await state(object.id)).joint_value,object.states[expected]);
        if(expected==='open')await page.screenshot({path:path.join(path.dirname(file),'browser-'+object.id.replaceAll('.','-')+'-open.png')});
      }
      await page.locator('canvas').focus();
      for(const expected of ['open','closed']){
        await rendered(()=>page.keyboard.press('Space'));
        assert.equal((await state(object.id)).state,expected,object.id+': Space at reference opening');
      }
      assert.deepEqual(await page.evaluate(id=>window.__buildingWalkthrough.objects.filter(o=>o.id!==id).map(o=>[o.id,o.state,o.joint_value]),object.id),untouched,object.id+': other joints remain unchanged');
      report.objects.push({id:object.id,mouse_open_close:true,space_open_close:true,moving_body_ids:object.moving_body_ids});
    }
    const animated=await browser.newPage({viewport:{width:1280,height:950},reducedMotion:'no-preference'});
    animated.on('pageerror',e=>errors.push(e.message));
    await animated.goto(pathToFileURL(file).href,{timeout:120000});
    await animated.waitForFunction(()=>window.__buildingWalkthrough?.ready,null,{timeout:120000});
    // Advance animation time explicitly; a loaded software renderer may skip
    // every intermediate frame within a real 1.2-second interval.
    const epoch=new Date('2026-11-19T12:00:00Z');
    await animated.clock.install({time:epoch});
    await animated.clock.pauseAt(new Date(epoch.getTime()+1000));
    const drawer='Kitchen3008.Cabinet.Drawer3';
    await animated.evaluate(id=>window.__buildingWalkthrough.viewObject(id),drawer);
    // Submit the contradictory command in the same JS turn. Two protocol
    // round-trips may outlive the real animation on a loaded renderer.
    const started=await animated.evaluate(id=>{const v=window.__buildingWalkthrough;return {
      opening:v.command(id,'open'),duringOpening:v.command(id,'close')};},drawer);
    assert.equal(started.opening.status,'accepted');assert.equal(started.duringOpening.status,'rejected_busy');
    await animated.clock.runFor(320);
    const middle=await animated.evaluate(id=>window.__buildingWalkthrough.objects.find(o=>o.id===id),drawer);
    assert.equal(middle.state,'opening');assert(middle.displacement_mm>0&&middle.displacement_mm<392);
    assert(Object.values(middle.body_displacements_mm).every(v=>v===middle.displacement_mm));
    await animated.clock.runFor(1500);
    assert.equal((await animated.evaluate(id=>window.__buildingWalkthrough.objects.find(o=>o.id===id),drawer)).state,'open');
    report.animated_drawer={id:drawer,intermediate_displacement_mm:middle.displacement_mm,all_five_bodies_move_together:true,busy_rejected:true,timing:"Playwright-controlled animation time; rendering performance is not asserted"};
    await animated.close();
    assert.deepEqual(errors,[]);report.passed=true;
    fs.writeFileSync(path.join(path.dirname(file),'kitchen-actions-browser-report.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report,null,2));
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
