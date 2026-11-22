// Usage: node tests/check_foyer_camera_wall_browser.cjs <index.html> <playwright-module> <chrome>
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const {pathToFileURL}=require('node:url'),{chromium}=require(process.argv[3]||'playwright');
(async()=>{
 const file=path.resolve(process.argv[2]),html=fs.readFileSync(file),data=JSON.parse(html.toString().match(/<script id="walkthrough-data" type="application\/json">([\s\S]*?)<\/script>/)[1]);
 const wall=data.camera_wall,{grid_rows:rows,grid_columns:columns,monitors}=wall;
 assert.deepEqual([columns,rows,monitors.length],[5,4,20]);
 const last=monitors.length-1,available=wall.cameras.filter(c=>c.availability==='available');
 assert.deepEqual(wall.default_assignments,available.slice(0,monitors.length).map(c=>c.id));
 const nativeIds=new Set(data.scenes.building.groups.map(g=>g.id));
 assert.equal(new Set(monitors.flatMap(m=>m.body_ids)).size,monitors.length*3);
 const dot=(a,b)=>a.reduce((sum,value,i)=>sum+value*b[i],0);
 const frame=monitors[0].screen_frame,origin=frame.origin_mm;
 const dx=dot(monitors[1].screen_frame.origin_mm.map((v,i)=>v-origin[i]),frame.x_axis);
 const dz=origin[2]-monitors[columns].screen_frame.origin_mm[2];
 assert.ok(dx>frame.width_mm&&dz>frame.height_mm,'Screen centers are separated by more than a screen width/height');
 for(const [index,monitor] of monitors.entries()){
  assert.equal(monitor.id,'FoyerMonitorWall.M'+String(index+1).padStart(2,'0'));
  assert.ok(monitor.body_ids.every(id=>nativeIds.has(id)));
  const delta=monitor.screen_frame.origin_mm.map((v,i)=>v-origin[i]);
  assert.ok(Math.abs(dot(delta,frame.x_axis)-dx*(index%columns))<1e-6);
  assert.ok(Math.abs(delta[2]+dz*Math.floor(index/columns))<1e-6);
  assert.ok(Math.abs(dot(delta,frame.normal))<1e-6);
 }
 const angle=process.argv[5]||'swiftshader';assert.ok(['swiftshader','metal'].includes(angle));
 const browser=await chromium.launch({headless:true,executablePath:process.argv[4],args:['--enable-webgl','--ignore-gpu-blocklist','--use-gl=angle','--use-angle='+angle,'--enable-unsafe-swiftshader']});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(()=>{
  window.__gpuCounts={};
  for(const kind of ['Texture','Framebuffer','Renderbuffer','Buffer','VertexArray'])for(const operation of ['create','delete']){
   const method=operation+kind,original=WebGL2RenderingContext.prototype[method];window.__gpuCounts[method]=0;
   WebGL2RenderingContext.prototype[method]=function(...args){window.__gpuCounts[method]++;return original.apply(this,args);};
  }
  window.__monitorReadbacks=0;
  const original=WebGL2RenderingContext.prototype.readPixels;WebGL2RenderingContext.prototype.readPixels=function(...args){window.__monitorReadbacks++;if(window.__monitorFault){window.__monitorFault=false;throw Error('Injected camera readback failure');}return original.apply(this,args);};
  const fill=CanvasRenderingContext2D.prototype.fillText;CanvasRenderingContext2D.prototype.fillText=function(...args){if(window.__monitorText)window.__monitorText.push(String(args[0]));return fill.apply(this,args);};
  const storage=WebGL2RenderingContext.prototype.renderbufferStorage;WebGL2RenderingContext.prototype.renderbufferStorage=function(...args){window.__monitorDepthFormat=args[1];return storage.apply(this,args);};
  window.__nonOpaqueCameraPixels=0;
  const put=CanvasRenderingContext2D.prototype.putImageData;CanvasRenderingContext2D.prototype.putImageData=function(image,...args){for(let i=3;i<image.data.length;i+=4)if(image.data[i]!==255)window.__nonOpaqueCameraPixels++;return put.call(this,image,...args);};
 });
 try{
  await page.goto(pathToFileURL(file).href,{timeout:120000});await page.waitForFunction(()=>window.__buildingWalkthrough?.ready,null,{timeout:120000});
  assert.equal(await page.evaluate(()=>window.__monitorDepthFormat===WebGL2RenderingContext.DEPTH_COMPONENT24),true,'Offscreen depth precision must match small near planes');
  assert.equal(wall.cameras.filter(c=>c.category==='fleet').length,20);
  assert.equal(wall.cameras.filter(c=>c.kind==='modeled_camera'&&c.availability==='available').length,6);
  const resources=await page.evaluate(()=>window.__buildingWalkthrough.monitorWall);
  assert.deepEqual(resources.slots.map(s=>s.id),monitors.map(m=>m.id));
  assert.deepEqual(resources.slots.map(s=>s.camera_id),wall.default_assignments);
  assert.equal(resources.texture_count,monitors.length+1);assert.equal(resources.framebuffer_count,1);assert.equal(resources.renderbuffer_count,1);
  const gpu=await page.evaluate(()=>window.__gpuCounts);
  for(const [kind,count] of [['Texture',monitors.length+1],['Framebuffer',1],['Renderbuffer',1]]){
   assert.equal(gpu['create'+kind],count,'WebGL '+kind+' creation count');
   assert.equal(gpu['delete'+kind],0);
  }
  await page.locator('[data-stop="camera-wall"]').click();
  const points=await page.evaluate(points=>points.map(p=>window.__buildingWalkthrough.projectPoint(p)),monitors.map(m=>m.screen_frame.origin_mm));
  assert.ok(points.every(p=>p.visible),'All 20 screen centers are visible from the foyer viewpoint');
  const canvas=page.locator('#walkthrough-canvas'),box=await canvas.boundingBox();
  const size=await canvas.evaluate(c=>({width:c.width,height:c.height}));
  const point=points[last];
  await page.mouse.click(box.x+point.x/size.width*box.width,box.y+point.y/size.height*box.height);
  await page.waitForFunction(last=>window.__buildingWalkthrough.monitorWall.selected===last,last);
  const clicked=await page.evaluate(()=>window.__buildingWalkthrough.lastInteraction);
  assert.equal(clicked.input,'click');assert.equal(clicked.id,monitors[last].id);
  await page.locator('.camera-wall-panel>button').click();
  await canvas.focus();await page.keyboard.press('Space');
  await page.waitForFunction(()=>window.__buildingWalkthrough.monitorWall.selected!==null);
  const aimed=await page.evaluate(()=>window.__buildingWalkthrough.lastInteraction);
  assert.equal(aimed.input,'space');assert.equal(aimed.id,monitors[Math.floor((rows-1)/2)*columns+Math.floor(columns/2)].id);
  const camera=wall.cameras.find(c=>c.id==='Lab3003.ArmA.C_tip'),fleet=wall.cameras.find(c=>c.category==='fleet');
  const capture=()=>page.evaluate(index=>window.__buildingWalkthrough.captureMonitor(index),last);
  const slot=()=>page.evaluate(index=>window.__buildingWalkthrough.monitorWall.slots[index],last);
  await page.evaluate(({index,id})=>{window.__buildingWalkthrough.assignMonitor(index,id);window.__buildingWalkthrough.selectMonitor(index);},{index:last,id:camera.id});
  assert.equal((await capture()).status,'captured');
  const before=await slot();
  assert.ok(before.image_hash&&before.frame.eye_mm.every(Number.isFinite));
  if(process.argv[6])assert.equal(before.image_hash,JSON.parse(fs.readFileSync(process.argv[6],'utf8')).initial_capture.image_hash,'Conservative culling preserves reference camera pixels');
  await page.locator('#walkthrough-isolate').click();
  await page.locator('#walkthrough-level').selectOption('EG');
  await capture();
  const isolated=await slot();
  assert.equal(isolated.image_hash,before.image_hash,'Full camera scene is independent of main view/isolation');
  await page.evaluate(()=>window.__buildingWalkthrough.robotCommand('Lab3003.ArmA','demo'));
  await page.waitForFunction(()=>!window.__buildingWalkthrough.robots[0].busy,null,{timeout:30000});
  await capture();
  const moved=await slot();
  assert.notDeepEqual(moved.frame.eye_mm,before.frame.eye_mm,'Arm-mounted optical frame follows its joint');
  assert.notEqual(moved.image_hash,before.image_hash,'Moving model changes the camera image');
  // The root remains alive when one camera readback fails, then recovers.
  const fault=await page.evaluate(index=>{window.__monitorFault=true;return window.__buildingWalkthrough.captureMonitor(index);},last);
  assert.equal(fault.status,'error');assert.equal(await page.evaluate(()=>window.__buildingWalkthrough.ready),true);
  assert.equal((await capture()).status,'captured');
  await page.locator('#camera-wall-select').selectOption(fleet.id);
  const offlineText=await page.evaluate(({index,id})=>{window.__monitorText=[];window.__buildingWalkthrough.assignMonitor(index,id);const text=window.__monitorText.join('\n');window.__monitorText=null;return text;},{index:last,id:fleet.id});
  assert.match(offlineText,/Flotte nicht angebunden/);assert.doesNotMatch(offlineText,/synthetisches Livebild/,'Disconnected placeholders never claim a live picture');
  const offlineReadbacks=await page.evaluate(()=>window.__monitorReadbacks);
  assert.equal((await capture()).status,'not_connected');
  await page.waitForTimeout(500);
  assert.equal(await page.evaluate(()=>window.__monitorReadbacks),offlineReadbacks,'An offline source on a hidden wall does not render frames');
  assert.ok((await page.locator('.camera-wall-panel').innerText()).includes('Flotte nicht angebunden'));
  const staticTransport=wall.cameras.find(c=>c.availability==='no_camera');
  await page.locator('#camera-wall-select').selectOption(staticTransport.id);
  assert.ok((await page.locator('.camera-wall-panel').innerText()).includes('Keine Kamera modelliert'));
  const allocationsBefore=await page.evaluate(()=>({...window.__gpuCounts}));
  await page.evaluate(({index,ids})=>{for(let i=0;i<50;i++)window.__buildingWalkthrough.assignMonitor(index,ids[i%ids.length]);},{index:last,ids:available.map(c=>c.id)});
  assert.deepEqual(await page.evaluate(()=>window.__gpuCounts),allocationsBefore,'Repeated selection allocates no new GPU resources');
  await page.evaluate(()=>{window.dispatchEvent(new PageTransitionEvent('pagehide',{persisted:true}));window.dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true}));});
  assert.equal(await page.locator('.camera-wall-panel').count(),1,'Persisted page transition retains the monitor UI');
  const micro=available.find(c=>c.label==='Mikroskop · 3.007');assert.ok(micro);
  await page.locator('#camera-wall-select').selectOption(micro.id);
  await capture();
  const labels=await page.locator('.camera-wall-panel').innerText();assert.doesNotMatch(labels,/Apotome|ZEISS|Nikon/i);
  await page.screenshot({path:path.join(path.dirname(file),'camera-wall-large-'+angle+'.png')});
  await page.locator('#camera-wall-select').selectOption(wall.default_assignments[last]);
  await page.locator('.camera-wall-panel>button').click();
  await page.locator('[data-stop="camera-wall"]').click();
  async function measureAutomaticRefresh(){
   const before=await page.evaluate(()=>({now:performance.now(),slots:window.__buildingWalkthrough.monitorWall.slots}));
   await page.waitForFunction(before=>performance.now()-before.now>=3000&&window.__buildingWalkthrough.monitorWall.slots.every((slot,i)=>slot.frames>before.slots[i].frames),before,{timeout:60000,polling:100});
   const after=await page.evaluate(()=>({now:performance.now(),slots:window.__buildingWalkthrough.monitorWall.slots}));
   const elapsed=(after.now-before.now)/1000;
   return {elapsed_browser_s:elapsed,forced_captures_during_interval:0,slots:after.slots.map((slot,i)=>({id:slot.id,camera_id:slot.camera_id,frames:slot.frames-before.slots[i].frames,rate_hz:(slot.frames-before.slots[i].frames)/elapsed,age_s:slot.age_s,render_duration_ms:slot.render_duration_ms}))};
  }
  const mosaicRates=await measureAutomaticRefresh();
  await page.screenshot({path:path.join(path.dirname(file),'camera-wall-foyer-'+angle+'.png')});
  await page.evaluate(index=>window.__buildingWalkthrough.selectMonitor(index),last);
  const selectedRates=await measureAutomaticRefresh();
  const renderer=await page.evaluate(()=>{const gl=document.getElementById('walkthrough-canvas').getContext('webgl2'),info=gl.getExtension('WEBGL_debug_renderer_info');return info?gl.getParameter(info.UNMASKED_RENDERER_WEBGL):gl.getParameter(gl.RENDERER);});
  assert.ok(mosaicRates.slots.every(slot=>slot.frames>0),'Every visible wall slot updates automatically');
  assert.ok(selectedRates.slots.every(slot=>slot.frames>0),'Every visible wall slot still updates when an enlarged view is selected');
  assert.deepEqual(errors,[]);
  assert.equal(await page.evaluate(()=>window.__nonOpaqueCameraPixels),0,'Composited camera images never blend previous placeholder text through glass');
  const report={passed:true,angle,initial_capture:before,html_sha256:crypto.createHash('sha256').update(html).digest('hex'),grid_rows:rows,grid_columns:columns,native_display_count:monitors.length,mouse_and_space_selection:true,independent_full_camera_scene:true,arm_frame_following:true,changed_camera_pixels:true,isolated_failure_and_recovery:true,disconnected_fleet:true,no_transporter_camera_claim:true,bounded_resources:true,gpu_allocation_counts:await page.evaluate(()=>window.__gpuCounts),neutral_microscope_label:true,errors,automatic_refresh:{mosaic:mosaicRates,selected:selectedRates},metrics_contains_manual_test_captures:true,metrics:await page.evaluate(()=>window.__buildingWalkthrough.monitorWall),qualification:'Local synthetic browser images; no fleet player, received frames, hardware or safety qualification. Automatic refresh rates measured in separate intervals without forced captures; general capture counters also contain test-triggered images.'};
  report.renderer=renderer;
  fs.writeFileSync(path.join(path.dirname(file),'camera-wall-browser-report-'+angle+'.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify({passed:true,slots:monitors.length,renderer,errors}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
