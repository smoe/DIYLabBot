// Usage: node tests/check_foyer_camera_wall_browser.cjs <index.html> <playwright-module> <chrome>
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const {pathToFileURL}=require('node:url'),{chromium}=require(process.argv[3]||'playwright');

async function checkVisibility(page,html,data){
 const wall=data.camera_wall,foyer=data.stops.find(stop=>stop.id==='camera-wall');
 const distance=wall.settings.mosaic_max_view_distance_mm;
 const [floor,ceiling]=wall.mosaic_eye_z_bounds_mm;
 assert.equal(floor,data.levels.find(level=>level.id===wall.level_id).z_mm);
 assert.ok(foyer.eye_mm[2]>=floor&&foyer.eye_mm[2]<ceiling);
 const probes=[['OG1',4500],['OG3',4500],['EG',distance+1000]].map(([level_id,range])=>{
  const level=data.levels.find(row=>row.id===level_id),target=foyer.target_mm;
  return {id:'visibility-'+level_id,label:'Visibility '+level_id,level_id,scene:'building',target_mm:target,
    eye_mm:[target[0]+wall.front[0]*range,target[1]+wall.front[1]*range,level.z_mm+data.settings.eye_height_mm]};
 });
 // Change only the test viewpoints. Use the renderer and scene from the release bytes.
 const markup=html.toString().replace(/(<script id="walkthrough-data" type="application\/json">).*?(<\/script>)/s,
  (_,open,close)=>open+JSON.stringify({...data,stops:[...data.stops,...probes]}).replace(/</g,'\\u003c')+close);
 const url='http://walkthrough.test/monitor-visibility';
 await page.route(url,route=>route.fulfill({contentType:'text/html; charset=utf-8',body:markup}));
 await page.goto(url,{timeout:120000});
 await page.waitForFunction(()=>window.__buildingWalkthrough?.ready,null,{timeout:120000});
 await page.evaluate(()=>{
  const bind=WebGL2RenderingContext.prototype.bindFramebuffer;
  window.__monitorPassesStarted=0;
  WebGL2RenderingContext.prototype.bindFramebuffer=function(target,framebuffer){
   if(framebuffer!==null)window.__monitorPassesStarted++;
   return bind.call(this,target,framebuffer);
  };
 });
 const cases=[];
 for(const probe of probes){
  await page.locator('[data-stop="'+probe.id+'"]').click();
  const metrics=await page.evaluate(async frames=>{
   const viewer=window.__buildingWalkthrough,eye=viewer.camera.eye_mm;
   const candidates=frames.flatMap(f=>{
    const delta=eye.map((v,i)=>v-f.origin_mm[i]);
    const front=delta.reduce((sum,value,i)=>sum+value*f.normal[i],0);
    return front>0&&viewer.projectPoint(f.origin_mm).visible?[Math.hypot(...delta)]:[];
   });
   const start=performance.now(),before=window.__monitorPassesStarted;
   await new Promise(resolve=>setTimeout(resolve,3000));
   return {stop:viewer.stopId,eye_mm:eye,foreground:!document.hidden,in_frustum:candidates.length,
    nearest_in_frustum_mm:Math.min(...candidates),elapsed_browser_s:(performance.now()-start)/1000,
    automatic_passes:window.__monitorPassesStarted-before};
  },wall.monitors.map(m=>m.screen_frame));
  assert.equal(metrics.stop,probe.id);
  assert.ok(metrics.foreground&&metrics.in_frustum>0,'Probe must pass the original front-plane and frustum checks');
  if(probe.level_id===wall.level_id){
   assert.ok(metrics.eye_mm[2]>=floor&&metrics.eye_mm[2]<ceiling&&metrics.nearest_in_frustum_mm>distance,
    'Distance probe must isolate the viewing-distance limit');
  }else{
   assert.ok(metrics.eye_mm[2]>=ceiling&&metrics.nearest_in_frustum_mm<=distance,
    'Upper-storey probe must isolate the eye-height limit');
  }
  assert.ok(metrics.elapsed_browser_s>=2.99);
  assert.equal(metrics.automatic_passes,0,'No automatic pass at '+probe.id);
  cases.push(metrics);
 }
 const before=await page.evaluate(()=>window.__buildingWalkthrough.monitorWall.slots.map(slot=>slot.frames));
 await page.evaluate(()=>window.__buildingWalkthrough.selectMonitor(0));
 await page.waitForFunction(before=>window.__buildingWalkthrough.monitorWall.slots[0].frames>before[0],before,{timeout:60000,polling:100});
 const after=await page.evaluate(()=>window.__buildingWalkthrough.monitorWall.slots.map(slot=>slot.frames));
 assert.deepEqual(after.slice(1),before.slice(1),'Outside the mosaic limit only the selected view updates');
 return {cases,selected_view_outside_limits:after[0]-before[0],mosaic_max_view_distance_mm:distance,mosaic_eye_z_bounds_mm:[floor,ceiling]};
}

(async()=>{
 const file=path.resolve(process.argv[2]),html=fs.readFileSync(file),data=JSON.parse(html.toString().match(/<script id="walkthrough-data" type="application\/json">([\s\S]*?)<\/script>/)[1]);
 const wall=data.camera_wall,{grid_rows:rows,grid_columns:columns,monitors}=wall;
 assert.deepEqual([columns,rows,monitors.length],[5,4,20]);
 const last=monitors.length-1,available=wall.cameras.filter(c=>c.availability==='available');
 assert.equal(wall.default_assignments.length,monitors.length);
 assert.equal(new Set(wall.default_assignments).size,monitors.length);
 assert.ok(wall.default_assignments.every(id=>available.some(c=>c.id===id)));
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
  window.__meshActivity={base64_decodes:0,vertex_buffer_uploads:0,vertex_buffer_bytes:0,index_buffer_uploads:0,index_buffer_bytes:0};
  const decode=window.atob;
  window.atob=function(...args){window.__meshActivity.base64_decodes++;return decode.apply(this,args);};
  const bufferData=WebGL2RenderingContext.prototype.bufferData;
  WebGL2RenderingContext.prototype.bufferData=function(target,values,...args){
   const result=bufferData.call(this,target,values,...args);
   const kind=target===this.ARRAY_BUFFER?'vertex':target===this.ELEMENT_ARRAY_BUFFER?'index':null;
   if(kind){
    window.__meshActivity[kind+'_buffer_uploads']++;
    window.__meshActivity[kind+'_buffer_bytes']+=values.byteLength;
   }
   return result;
  };
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
  assert.equal(wall.cameras.filter(c=>c.category==='transporter'&&c.availability==='not_connected').length,20);
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
  const firstTile=await page.evaluate(index=>{
   const snapshot=()=>({...window.__meshActivity,create_buffer_calls:window.__gpuCounts.createBuffer,
    create_vertex_array_calls:window.__gpuCounts.createVertexArray,readbacks:window.__monitorReadbacks});
   const before=snapshot(),result=window.__buildingWalkthrough.captureMonitor(index),after=snapshot();
   const preparation=performance.getEntriesByName('walkthrough-monitor-scene-preparation','measure');
   return {before,after,status:result.status,preparations:preparation.map(entry=>entry.duration)};
  },wall.default_assignments.findIndex(id=>id!==null));
  assert.equal(firstTile.before.readbacks,0,'The test must measure the first tile before automatic updates');
  assert.equal(firstTile.status,'captured');
  assert.equal(firstTile.after.readbacks,1);
  assert.equal(firstTile.before.base64_decodes,3);
  assert.equal(firstTile.before.vertex_buffer_uploads,2);
  assert.equal(firstTile.before.vertex_buffer_bytes,data.scenes.building.vertex_count*3*4*2);
  for(const field of ['base64_decodes','vertex_buffer_uploads','vertex_buffer_bytes']){
   assert.equal(firstTile.after[field],firstTile.before[field],field+' is unchanged by monitor scene preparation');
  }
  assert.equal(firstTile.after.create_buffer_calls-firstTile.before.create_buffer_calls,1,'Only an element buffer is added for the camera draw order');
  assert.equal(firstTile.after.index_buffer_uploads-firstTile.before.index_buffer_uploads,1);
  assert.ok(firstTile.after.index_buffer_bytes>firstTile.before.index_buffer_bytes);
  assert.equal(firstTile.after.create_vertex_array_calls-firstTile.before.create_vertex_array_calls,1);
  assert.equal(firstTile.preparations.length,1);
  assert.ok(Number.isFinite(firstTile.preparations[0])&&firstTile.preparations[0]>=0);
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
  const groups=await page.locator('#camera-wall-select optgroup').evaluateAll(nodes=>nodes.map(node=>({
   label:node.label,options:[...node.children].map(option=>({id:option.value,text:option.textContent}))})));
  assert.deepEqual(groups.map(g=>g.label),['Transporter','Roboterkameras','Geräte']);
  assert.equal(groups[0].options.length,21);
  const statuses={available:'Ansicht verfügbar',not_connected:'Flotte nicht angebunden',no_camera:'Keine Kamera modelliert',missing_viewpoint:'Kein Blickpunkt vorhanden'};
  for(const [index,category] of ['transporter','robot','device'].entries()){
   const choices=wall.cameras.filter(c=>c.category===category);
   assert.deepEqual(groups[index].options.map(o=>o.id),choices.map(c=>c.id));
   assert.ok(groups[index].options.every((option,i)=>option.text.endsWith(statuses[choices[i].availability])));
  }
  const camera=wall.cameras.find(c=>c.id==='Lab3003.ArmA.C_tip'),fleet=wall.cameras.find(c=>c.availability==='not_connected');
  const capture=()=>page.evaluate(index=>window.__buildingWalkthrough.captureMonitor(index),last);
  const slot=()=>page.evaluate(index=>window.__buildingWalkthrough.monitorWall.slots[index],last);
  await page.evaluate(({index,id})=>{window.__buildingWalkthrough.assignMonitor(index,id);window.__buildingWalkthrough.selectMonitor(index);},{index:last,id:camera.id});
  assert.equal((await capture()).status,'captured');
  const before=await slot();
  assert.ok(before.image_hash&&before.frame.eye_mm.every(Number.isFinite));
  const referenceBytes=process.argv[6]?fs.readFileSync(process.argv[6]):null;
  let imageReference=null;
  if(referenceBytes){
   const reference=JSON.parse(referenceBytes);
   assert.equal(reference.angle,angle,'Reference pixels must use the same renderer mode');
   assert.equal(before.image_hash,reference.initial_capture.image_hash,'Shared buffers preserve the reference camera pixels');
   imageReference={report_sha256:crypto.createHash('sha256').update(referenceBytes).digest('hex'),
    reference_html_sha256:reference.html_sha256,image_hash:reference.initial_capture.image_hash};
  }
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
  assert.ok((await page.locator('.camera-wall-panel [role="status"]').innerText()).includes('Flotte nicht angebunden'));
  const staticTransport=wall.cameras.find(c=>c.availability==='no_camera');
  await page.locator('#camera-wall-select').selectOption(staticTransport.id);
  assert.ok((await page.locator('.camera-wall-panel [role="status"]').innerText()).includes('Keine Kamera modelliert'));
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
   const before=await page.evaluate(()=>{
    window.__mainFrameTimes=[];
    window.__mainFrameObserver=new MutationObserver(()=>window.__mainFrameTimes.push(performance.now()));
    window.__mainFrameObserver.observe(document.getElementById('building-walkthrough'),{attributeFilter:['data-frames']});
    return {now:performance.now(),slots:window.__buildingWalkthrough.monitorWall.slots};
   });
   await page.waitForFunction(before=>performance.now()-before.now>=3000&&window.__buildingWalkthrough.monitorWall.slots.every((slot,i)=>slot.frames>before.slots[i].frames),before,{timeout:60000,polling:100});
   const after=await page.evaluate(()=>{
    window.__mainFrameObserver.disconnect();
    return {now:performance.now(),slots:window.__buildingWalkthrough.monitorWall.slots,main_frame_times:window.__mainFrameTimes};
   });
   const elapsed=(after.now-before.now)/1000;
   const drawTimes=after.main_frame_times;
   const intervals=drawTimes.slice(1).map((time,i)=>time-drawTimes[i]).sort((a,b)=>a-b);
   const percentile=p=>intervals.length?intervals[Math.ceil(intervals.length*p)-1]:null;
   return {elapsed_browser_s:elapsed,forced_captures_during_interval:0,
    main_draw_interval_ms:{samples:intervals.length,median:percentile(.5),p95:percentile(.95),maximum:percentile(1)},
    slots:after.slots.map((slot,i)=>({id:slot.id,camera_id:slot.camera_id,frames:slot.frames-before.slots[i].frames,rate_hz:(slot.frames-before.slots[i].frames)/elapsed,age_s:slot.age_s,render_duration_ms:slot.render_duration_ms}))};
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
  assert.equal(await page.evaluate(()=>performance.getEntriesByName('walkthrough-monitor-scene-preparation','measure').length),1,
   'The camera scene is prepared just once across captures and view changes');
  report.shared_native_buffers={first_tile_before:firstTile.before,first_tile_after:firstTile.after,
   camera_scene_preparation_ms:firstTile.preparations[0],byte_basis:'WebGL bufferData bytes uploaded, excluding textures and driver overhead',
   main_draw_timing_basis:'Elapsed time between main view data-frames updates while automatic monitor refresh is active',
   reference_pixels:imageReference};
  report.visibility_checks=await checkVisibility(page,html,data);
  assert.deepEqual(errors,[]);
  report.renderer=renderer;
  report.transport_priority={groups:groups.map(g=>g.label),transporters:groups[0].options.length,availability_labels_verified:true};
  fs.writeFileSync(path.join(path.dirname(file),'camera-wall-browser-report-'+angle+'.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify({passed:true,slots:monitors.length,renderer,errors}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
