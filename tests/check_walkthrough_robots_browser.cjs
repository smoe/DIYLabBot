// Usage: node tests/check_walkthrough_robots_browser.cjs <index.html> <playwright> <chrome>
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const {pathToFileURL}=require('node:url');const {chromium}=require(process.argv[3]||'playwright');
(async()=>{
 const file=path.resolve(process.argv[2]),html=fs.readFileSync(file),model=JSON.parse(html.toString().match(/<script id="walkthrough-data" type="application\/json">([\s\S]*?)<\/script>/)[1]);
 const browser=await chromium.launch({headless:true,executablePath:process.argv[4],args:['--enable-webgl','--ignore-gpu-blocklist','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 const page=await browser.newPage({viewport:{width:1280,height:950}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 try{
  await page.goto(pathToFileURL(file).href,{timeout:120000});await page.waitForFunction(()=>window.__buildingWalkthrough?.ready,null,{timeout:120000});
  const robot=model.robots[0],id=robot.id;
  await page.evaluate(id=>window.__buildingWalkthrough.viewRobot(id),id);
  await page.waitForFunction(()=>window.__buildingWalkthrough.sceneId==='building');
  const pixels=await page.evaluate(ids=>{const data=JSON.parse(document.getElementById('walkthrough-data').textContent),v=window.__buildingWalkthrough,c=document.querySelector('canvas'),r=c.getBoundingClientRect();return data.scenes.building.groups.filter(g=>ids.includes(g.id)).map(g=>{const p=v.projectPoint(g.bounds_mm.min.map((x,i)=>(x+g.bounds_mm.max[i])/2));return {x:r.x+p.x*r.width/c.width,y:r.y+p.y*r.height/c.height,visible:p.visible};}).filter(p=>p.visible);},robot.trigger_body_ids);
  let clicked=false;
  for(const pixel of pixels){await page.mouse.click(pixel.x,pixel.y);if(await page.evaluate(id=>window.__buildingWalkthrough.lastInteraction?.id===id,id)){clicked=true;break;}}
  assert(clicked,'A native arm body must be selectable by mouse');await page.locator('#walkthrough-robot').waitFor({state:'visible'});
  console.log('Native robot selected by click');
  // Time control checks semantics, not GPU frame rate.
  const epoch=new Date('2026-11-20T12:00:00Z');await page.clock.install({time:epoch});await page.clock.pauseAt(new Date(+epoch+1000));
  const unchanged=await page.evaluate(ids=>window.__buildingWalkthrough.objects.filter(o=>!ids.includes(o.id)).map(o=>[o.id,o.joint_value]),robot.joint_object_ids);
  const initial=await page.evaluate(()=>window.__buildingWalkthrough.objects.filter(o=>o.id.startsWith('Lab3003.ArmA.')).map(o=>o.model_matrix));
  await page.locator('[data-robot-command=demo]').click({force:true});await page.clock.fastForward(500);
  const middle=await page.evaluate(()=>window.__buildingWalkthrough.robots[0]);assert.equal(middle.state,'moving');
  assert.notDeepEqual(await page.evaluate(()=>window.__buildingWalkthrough.objects.filter(o=>o.id.startsWith('Lab3003.ArmA.')).map(o=>o.model_matrix)),initial);
  assert(await page.locator('[data-robot-command=home]').isDisabled());
  await page.screenshot({path:path.join(path.dirname(file),'robot-demo-moving.png')});
  await page.locator('[data-robot-command=stop]').click({force:true});assert.equal((await page.evaluate(()=>window.__buildingWalkthrough.robots[0])).state,'stopping');
  await page.clock.fastForward(robot.stop_ramp_s*1000+50);const stopped=await page.evaluate(()=>window.__buildingWalkthrough.robots[0]);assert.equal(stopped.state,'stopped');
  await page.clock.fastForward(500);assert.deepEqual((await page.evaluate(()=>window.__buildingWalkthrough.robots[0])).joints_deg,stopped.joints_deg);
  await page.locator('[data-robot-command=home]').click({force:true});await page.clock.fastForward(robot.duration_s*1000+500);
  const home=await page.evaluate(()=>window.__buildingWalkthrough.robots[0]);assert.equal(home.state,'idle');home.joints_deg.forEach((v,i)=>assert(Math.abs(v-robot.reference_deg[i])<1e-7));
  await page.locator('[data-robot-command=demo]').click({force:true});await page.clock.fastForward(robot.duration_s*1000+500);
  const end=await page.evaluate(()=>window.__buildingWalkthrough.robots[0]);end.joints_deg.forEach((v,i)=>assert(Math.abs(v-robot.demo_deg[i])<1e-7));
  assert.deepEqual(await page.evaluate(ids=>window.__buildingWalkthrough.objects.filter(o=>!ids.includes(o.id)).map(o=>[o.id,o.joint_value]),robot.joint_object_ids),unchanged);
  await page.locator('[data-robot-command=home]').click({force:true});await page.clock.fastForward(robot.duration_s*1000+500);
  await page.evaluate(id=>window.__buildingWalkthrough.viewRobot(id),id);await page.clock.fastForward(20);
  await page.locator('canvas').focus();await page.keyboard.press('Space');await page.clock.fastForward(20);
  assert.equal((await page.evaluate(()=>window.__buildingWalkthrough.lastInteraction)).id,id,'Face robot and Space opens its commands');
  assert.deepEqual(errors,[]);
  const report={passed:true,html_sha256:crypto.createHash('sha256').update(html).digest('hex'),mouse_selection:true,space_selection:true,demo:true,home:true,smooth_stop:true,other_objects_unchanged:true,errors,timing:'Playwright-controlled animation time; no real-time performance claim.'};
  fs.writeFileSync(path.join(path.dirname(file),'robot-commands-browser-report.json'),JSON.stringify(report,null,2)+'\n');console.log(report);
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
