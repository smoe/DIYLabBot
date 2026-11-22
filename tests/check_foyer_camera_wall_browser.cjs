// Usage: node tests/check_foyer_camera_wall_browser.cjs <index.html> <playwright-module> <chrome>
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const {pathToFileURL}=require('node:url'),{chromium}=require(process.argv[3]||'playwright');
(async()=>{
 const file=path.resolve(process.argv[2]),html=fs.readFileSync(file),data=JSON.parse(html.toString().match(/<script id="walkthrough-data" type="application\/json">([\s\S]*?)<\/script>/)[1]);
 const angle=process.argv[5]||'swiftshader';assert.ok(['swiftshader','metal'].includes(angle));
 const browser=await chromium.launch({headless:true,executablePath:process.argv[4],args:['--enable-webgl','--ignore-gpu-blocklist','--use-gl=angle','--use-angle='+angle,'--enable-unsafe-swiftshader']});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(()=>{
  window.__gpuCounts={};
  for(const kind of ['Texture','Framebuffer','Renderbuffer','Buffer','VertexArray'])for(const operation of ['create','delete']){
   const method=operation+kind,original=WebGL2RenderingContext.prototype[method];window.__gpuCounts[method]=0;
   WebGL2RenderingContext.prototype[method]=function(...args){window.__gpuCounts[method]++;return original.apply(this,args);};
  }
  const original=WebGL2RenderingContext.prototype.readPixels;WebGL2RenderingContext.prototype.readPixels=function(...args){if(window.__monitorFault){window.__monitorFault=false;throw Error('Injected camera readback failure');}return original.apply(this,args);};
  const fill=CanvasRenderingContext2D.prototype.fillText;CanvasRenderingContext2D.prototype.fillText=function(...args){if(window.__monitorText)window.__monitorText.push(String(args[0]));return fill.apply(this,args);};
  const storage=WebGL2RenderingContext.prototype.renderbufferStorage;WebGL2RenderingContext.prototype.renderbufferStorage=function(...args){window.__monitorDepthFormat=args[1];return storage.apply(this,args);};
  window.__nonOpaqueCameraPixels=0;
  const put=CanvasRenderingContext2D.prototype.putImageData;CanvasRenderingContext2D.prototype.putImageData=function(image,...args){for(let i=3;i<image.data.length;i+=4)if(image.data[i]!==255)window.__nonOpaqueCameraPixels++;return put.call(this,image,...args);};
 });
 try{
  await page.goto(pathToFileURL(file).href,{timeout:120000});await page.waitForFunction(()=>window.__buildingWalkthrough?.ready,null,{timeout:120000});
  assert.equal(data.camera_wall.monitors.length,9);
  assert.equal(await page.evaluate(()=>window.__monitorDepthFormat===WebGL2RenderingContext.DEPTH_COMPONENT24),true,'Offscreen depth precision must match small near planes');
  assert.equal(data.camera_wall.cameras.filter(c=>c.category==='fleet').length,20);
  assert.equal(data.camera_wall.cameras.filter(c=>c.kind==='modeled_camera'&&c.availability==='available').length,6);
  await page.locator('[data-stop="camera-wall"]').click();
  const middle=data.camera_wall.monitors[4];
  const point=await page.evaluate(p=>window.__buildingWalkthrough.projectPoint(p),middle.screen_frame.origin_mm);
  const canvas=page.locator('#walkthrough-canvas'),box=await canvas.boundingBox();
  const size=await canvas.evaluate(c=>({width:c.width,height:c.height}));
  assert.ok(point.visible,'Monitor lies in the source-derived foyer view');
  await page.mouse.click(box.x+point.x/size.width*box.width,box.y+point.y/size.height*box.height);
  await page.waitForFunction(()=>window.__buildingWalkthrough.monitorWall.selected!==null);
  assert.equal((await page.evaluate(()=>window.__buildingWalkthrough.lastInteraction)).input,'click');
  await page.locator('.camera-wall-panel>button').click();
  await canvas.focus();await page.keyboard.press('Space');
  await page.waitForFunction(()=>window.__buildingWalkthrough.monitorWall.selected!==null);
  assert.equal((await page.evaluate(()=>window.__buildingWalkthrough.lastInteraction)).input,'space');
  const camera=data.camera_wall.cameras.find(c=>c.id==='Lab3003.ArmA.C_tip'),fleet=data.camera_wall.cameras.find(c=>c.category==='fleet');
  await page.evaluate(id=>{window.__buildingWalkthrough.assignMonitor(0,id);window.__buildingWalkthrough.selectMonitor(0);},camera.id);
  assert.equal((await page.evaluate(()=>window.__buildingWalkthrough.captureMonitor(0))).status,'captured');
  const before=await page.evaluate(()=>window.__buildingWalkthrough.monitorWall.slots[0]);
  assert.ok(before.image_hash&&before.frame.eye_mm.every(Number.isFinite));
  if(process.argv[6])assert.equal(before.image_hash,JSON.parse(fs.readFileSync(process.argv[6],'utf8')).initial_capture.image_hash,'Conservative culling preserves reference camera pixels');
  await page.locator('#walkthrough-isolate').click();
  await page.locator('#walkthrough-level').selectOption('EG');
  await page.evaluate(()=>window.__buildingWalkthrough.captureMonitor(0));
  const isolated=await page.evaluate(()=>window.__buildingWalkthrough.monitorWall.slots[0]);
  assert.equal(isolated.image_hash,before.image_hash,'Full camera scene is independent of main view/isolation');
  await page.evaluate(()=>window.__buildingWalkthrough.robotCommand('Lab3003.ArmA','demo'));
  await page.waitForFunction(()=>!window.__buildingWalkthrough.robots[0].busy,null,{timeout:30000});
  await page.evaluate(()=>window.__buildingWalkthrough.captureMonitor(0));
  const moved=await page.evaluate(()=>window.__buildingWalkthrough.monitorWall.slots[0]);
  assert.notDeepEqual(moved.frame.eye_mm,before.frame.eye_mm,'Arm-mounted optical frame follows its joint');
  assert.notEqual(moved.image_hash,before.image_hash,'Moving model changes the camera image');
  // The root remains alive when one camera readback fails, then recovers.
  const fault=await page.evaluate(()=>{window.__monitorFault=true;return window.__buildingWalkthrough.captureMonitor(0);});
  assert.equal(fault.status,'error');assert.equal(await page.evaluate(()=>window.__buildingWalkthrough.ready),true);
  assert.equal((await page.evaluate(()=>window.__buildingWalkthrough.captureMonitor(0))).status,'captured');
  await page.locator('#camera-wall-select').selectOption(fleet.id);
  const offlineText=await page.evaluate(id=>{window.__monitorText=[];window.__buildingWalkthrough.assignMonitor(0,id);const text=window.__monitorText.join('\n');window.__monitorText=null;return text;},fleet.id);
  assert.match(offlineText,/Flotte nicht angebunden/);assert.doesNotMatch(offlineText,/synthetisches Livebild/,'Disconnected placeholders never claim a live picture');
  assert.equal((await page.evaluate(()=>window.__buildingWalkthrough.captureMonitor(0))).status,'not_connected');
  assert.ok((await page.locator('.camera-wall-panel').innerText()).includes('Flotte nicht angebunden'));
  const staticTransport=data.camera_wall.cameras.find(c=>c.availability==='no_camera');
  await page.locator('#camera-wall-select').selectOption(staticTransport.id);
  assert.ok((await page.locator('.camera-wall-panel').innerText()).includes('Keine Kamera modelliert'));
  const available=data.camera_wall.cameras.filter(c=>c.availability==='available');
  const allocationsBefore=await page.evaluate(()=>({...window.__gpuCounts}));
  await page.evaluate(ids=>{for(let i=0;i<50;i++)window.__buildingWalkthrough.assignMonitor(0,ids[i%ids.length]);},available.map(c=>c.id));
  assert.deepEqual(await page.evaluate(()=>window.__gpuCounts),allocationsBefore,'Repeated selection allocates no new GPU resources');
  await page.evaluate(()=>{window.dispatchEvent(new PageTransitionEvent('pagehide',{persisted:true}));window.dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true}));});
  assert.equal(await page.locator('.camera-wall-panel').count(),1,'Persisted page transition retains the monitor UI');
  assert.equal((await page.evaluate(()=>window.__buildingWalkthrough.monitorWall)).texture_count,10);
  const resources=await page.evaluate(()=>window.__buildingWalkthrough.monitorWall);
  assert.equal(resources.texture_count,10);assert.equal(resources.framebuffer_count,1);
  const micro=available.find(c=>c.label==='Mikroskop · 3.007');assert.ok(micro);
  await page.locator('#camera-wall-select').selectOption(micro.id);
  await page.evaluate(()=>window.__buildingWalkthrough.captureMonitor(0));
  const labels=await page.locator('.camera-wall-panel').innerText();assert.doesNotMatch(labels,/Apotome|ZEISS|Nikon/i);
  await page.screenshot({path:path.join(path.dirname(file),'camera-wall-large-'+angle+'.png')});
  await page.locator('.camera-wall-panel>button').click();
  await page.locator('[data-stop="camera-wall"]').click();
  for(let i=0;i<9;i++)await page.evaluate(i=>window.__buildingWalkthrough.captureMonitor(i),i);
  await page.screenshot({path:path.join(path.dirname(file),'camera-wall-foyer-'+angle+'.png')});
  async function measureAutomaticRefresh(){
   const before=await page.evaluate(()=>({now:performance.now(),slots:window.__buildingWalkthrough.monitorWall.slots}));
   await page.waitForTimeout(3000);
   const after=await page.evaluate(()=>({now:performance.now(),slots:window.__buildingWalkthrough.monitorWall.slots}));
   const elapsed=(after.now-before.now)/1000;
   return {elapsed_browser_s:elapsed,forced_captures_during_interval:0,slots:after.slots.map((slot,i)=>({id:slot.id,camera_id:slot.camera_id,frames:slot.frames-before.slots[i].frames,rate_hz:(slot.frames-before.slots[i].frames)/elapsed,age_s:slot.age_s,render_duration_ms:slot.render_duration_ms}))};
  }
  const mosaicRates=await measureAutomaticRefresh();
  await page.evaluate(()=>window.__buildingWalkthrough.selectMonitor(0));
  const selectedRates=await measureAutomaticRefresh();
  const renderer=await page.evaluate(()=>{const gl=document.getElementById('walkthrough-canvas').getContext('webgl2'),info=gl.getExtension('WEBGL_debug_renderer_info');return info?gl.getParameter(info.UNMASKED_RENDERER_WEBGL):gl.getParameter(gl.RENDERER);});
  assert.ok(mosaicRates.slots.some(slot=>slot.frames>0),'Visible wall updates automatically');
  assert.ok(selectedRates.slots[0].frames>0,'Selected picture updates automatically');
  assert.ok(selectedRates.slots.slice(1).some(slot=>slot.frames>0),'A slow selected picture must not starve all other visible monitors');
  assert.deepEqual(errors,[]);
  assert.equal(await page.evaluate(()=>window.__nonOpaqueCameraPixels),0,'Composited camera images never blend previous placeholder text through glass');
  const report={passed:true,angle,initial_capture:before,html_sha256:crypto.createHash('sha256').update(html).digest('hex'),nine_native_displays:true,mouse_and_space_selection:true,independent_full_camera_scene:true,arm_frame_following:true,changed_camera_pixels:true,isolated_failure_and_recovery:true,disconnected_fleet:true,no_transporter_camera_claim:true,bounded_resources:true,gpu_allocation_counts:await page.evaluate(()=>window.__gpuCounts),neutral_microscope_label:true,errors,automatic_refresh:{mosaic:mosaicRates,selected:selectedRates},metrics_contains_manual_test_captures:true,metrics:await page.evaluate(()=>window.__buildingWalkthrough.monitorWall),qualification:'Local synthetic browser images; no fleet player, received frames, hardware or safety qualification. Automatic refresh rates measured in separate intervals without forced captures; general capture counters also contain test-triggered images.'};
  report.renderer=renderer;
  fs.writeFileSync(path.join(path.dirname(file),'camera-wall-browser-report-'+angle+'.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify({passed:true,slots:9,renderer,errors}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
