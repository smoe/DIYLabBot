// Usage: node tests/check_building_walkthrough.cjs <index.html> [playwright-module] [chrome-executable]
// SOLIDCRAFTBOT_WALKTHROUGH_GPU=metal selects the native macOS GPU for local QA.
// Exercise the derived native scene through the same controls exposed to visitors.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const {pathToFileURL} = require('node:url');
const {chromium} = require(process.argv[3] || 'playwright');
const {detourOpenDoor} = require('./walkthrough_route_detour.cjs');

(async () => {
  assert(process.argv[2], 'A generated walk-through HTML file is required.');
  const target = path.resolve(process.argv[2]);
  const html = fs.readFileSync(target, 'utf8');
  const inline = html.match(/<script id="walkthrough-data" type="application\/json">([\s\S]*?)<\/script>/);
  assert(inline, 'A standalone inline scene is required.');
  const model = JSON.parse(inline[1]);
  assert.deepEqual(Object.keys(model.scenes), ['building'], 'The complete walkthrough uses one building frame.');
  assert(model.stops.every(stop => stop.scene === 'building'), 'Every viewpoint belongs to the same building.');
  const nativeScene = model.scenes.building;
  assert.equal(nativeScene.coordinate_frame, 'building_presentation');
  const equippedLabs=model.laboratories.filter(lab=>lab.layout_source);
  assert.equal(equippedLabs.length, 1, 'The existing equipment layout remains bound once.');
  const laboratory = equippedLabs[0];
  assert.equal(laboratory.level_id, 'OG3'); assert.equal(laboratory.area, 'R3_003');
  assert.equal(laboratory.device_instances.length, 17, 'All seventeen existing equipment instances are bound.');
  const nativeIds = nativeScene.groups.map(group => group.id);
  assert.equal(new Set(nativeIds).size, nativeIds.length, 'Native bodies appear exactly once.');
  const equipment = nativeScene.equipment_instances;
  assert.equal(equipment.length, 17);
  assert.deepEqual(equipment.map(item => item.id).sort(), laboratory.device_instances.map(item => laboratory.id+'.'+item.id).sort());
  for (const device of laboratory.device_instances) {
    const coverage = equipment.find(item => item.id === laboratory.id+'.'+device.id);
    const groups = nativeScene.groups.filter(group => group.laboratory_id === laboratory.id && group.instance_id === device.id);
    assert.equal(groups.length, coverage.body_count, `${device.id}: complete native equipment body coverage`);
    assert(groups.length > 0 && groups.every(group => group.level_id === laboratory.level_id));
    assert.equal(new Set(groups.map(group => group.original_body_id)).size, groups.length);
  }
  assert.equal(nativeScene.equipment_placement_checks.length, 17);
  assert(nativeScene.equipment_placement_checks.every(check => check.passed && check.host_anchor_checked));
  const auxiliary=nativeScene.auxiliary_instances;
  assert.deepEqual(auxiliary.map(item=>item.id).sort(),['Lab3003.MountArmA','Lab3003.MountArmB','Lab3003.MountArmC']);
  const supportGroups=nativeScene.groups.filter(group=>group.supporting_device_id);
  assert.equal(supportGroups.length,3,'The three functional native arm risers remain in the building');
  assert.deepEqual(supportGroups.map(group=>group.supporting_device_id).sort(),['ArmA','ArmB','ArmC']);
  for(const support of auxiliary){
    const groups=supportGroups.filter(group=>laboratory.id+'.'+group.instance_id===support.id);
    assert.equal(groups.length,support.body_count);
    assert(groups.every(group=>group.laboratory_id===laboratory.id&&group.level_id===laboratory.level_id));
  }
  const duplicatedShellRoles = new Set(['provisional_floor', 'provisional_wall', 'quadratic_facade_approximation', 'illustrative_glazing']);
  assert(!nativeScene.groups.some(group => duplicatedShellRoles.has(group.role)), 'The L01 shell is not merged over the building shell.');
  assert(!nativeScene.groups.some(group => /^People_|VehicleRoute/.test(group.original_body_id || group.id)), 'Standalone study bodies are not placed in the building.');
  // A merged Pages build must preserve the latest master furnishings too.
  // Resolve expected native parts from the pinned sources, rather than accepting
  // an older lab-only snapshot merely because its lab/lift checks still pass.
  const repositoryRoot=path.resolve(__dirname,'..');
  function pinnedJson(name){
    const bytes=fs.readFileSync(path.join(repositoryRoot,name));
    assert.equal(crypto.createHash('sha256').update(bytes).digest('hex'),model.source_files_sha256[name],
      `${name}: browser coverage must use the exact published source bytes`);
    return JSON.parse(bytes.toString('utf8'));
  }
  const socialSourceName='model/furnishings/building-social.json',socialSource=pinnedJson(socialSourceName);
  const socialCatalog=pinnedJson(socialSource.catalog.source);
  assert.equal(model.source_files_sha256[socialSource.catalog.source],socialSource.catalog.source_sha256);
  const socialArticulations=pinnedJson('model/furniture/social.articulations.json');
  assert.equal(socialArticulations.catalog.source_sha256,socialSource.catalog.source_sha256);
  const officeComputerCoverage=[],socialObjectCoverage=[];
  const nativeById=new Map(nativeScene.groups.map(group=>[group.id,group]));
  const laboratorySource=pinnedJson('model/furnishings/building-laboratories.json');
  assert.deepEqual(model.laboratories.map(lab=>lab.id).sort(),
    [...laboratorySource.laboratories,...laboratorySource.basic_laboratories].map(lab=>lab.id).sort());
  for(const assignment of laboratorySource.basic_laboratories){
    const lab=model.laboratories.find(lab=>lab.id===assignment.id);
    assert.equal(lab.level_id,assignment.level);assert.equal(lab.area,assignment.area);
    assert(lab.wet_pair_placed,assignment.id+': sink and adjacent hood');
    assert(lab.body_ids.every(id=>nativeById.has(id)&&nativeById.get(id).level_id===lab.level_id),
      assignment.id+': complete native furniture coverage');
    assert(lab.body_ids.every(id=>!model.isolation.body_ids.includes(id)),
      'Isolating L01 must not reveal furniture from other laboratories');
  }
  for(const room of socialSource.rooms)for(const instance of room.instances){
    const parts=socialCatalog.types[instance.type];
    const prefix=room.id+'_'+instance.id+'_';
    if(instance.type==='office_computer'){
      assert(Array.isArray(parts),'The office computer reuses its existing portable catalog parts');
      const expected=parts.filter(part=>part.action==='create').map(part=>prefix+part.body);
      assert(expected.length>0);
      const present=nativeScene.groups.filter(group=>group.id.startsWith(prefix));
      assert.deepEqual(present.map(group=>group.id).sort(),[...expected].sort(),`${room.id}.${instance.id}: complete native computer coverage`);
      assert(present.every(group=>group.level_id===room.level&&group.index_count>0));
      officeComputerCoverage.push({id:room.id+'.'+instance.id,level_id:room.level,body_ids:expected});
    }
    for(const [jointId,joint] of Object.entries(socialArticulations.types[instance.type]||{})){
      const identity=room.id+'.'+instance.id+'.'+jointId,object=model.objects.find(value=>value.id===identity);
      assert(object,`${identity}: every instance of an articulated social type remains available`);
      assert(Array.isArray(parts),'Social articulated parts use their shared catalog definition');
      const byPart=new Map(parts.filter(part=>part.action==='create').map(part=>[part.id,part]));
      const expected=joint.moving_parts.map(part=>prefix+byPart.get(part).body);
      assert.deepEqual([...object.moving_body_ids].sort(),[...expected].sort(),`${identity}: native moving-part coverage`);
      assert(expected.every(id=>nativeById.has(id)),`${identity}: all articulated native bodies are rendered`);
      socialObjectCoverage.push({id:identity,moving_body_ids:expected});
    }
  }
  assert.equal(officeComputerCoverage.filter(instance=>instance.id.startsWith('PhD3002.')).length,4,
    'The corrected doctoral room retains its four source-defined workstations');
  assert(officeComputerCoverage.some(instance=>instance.id==='Office3009.Computer'),
    'The latest master office workstation remains in the building');
  const microscopy=model.microscopy;
  assert(microscopy&&microscopy.level_id==='OG3'&&microscopy.area==='R3_007');
  assert.equal(microscopy.scale,1,'The microscope retains its own dimensions');
  const microscopeSource=pinnedJson(microscopy.instrument_source.source);
  const microscopeGroups=microscopy.instrument_body_ids.map(id=>nativeById.get(id));
  assert(microscopeGroups.every(group=>group&&group.level_id==='OG3'&&group.index_count>0));
  assert.equal(microscopeGroups.filter(group=>group.role==='microscope_objective').length,microscopeSource.objectives.length);
  assert.equal(microscopeGroups.filter(group=>group.role==='microscope_support_foot').length,4);
  const microscopeTop=nativeById.get(microscopy.support_body_id);
  for(const group of microscopeGroups){
    assert(group.bounds_mm.min[2]>=microscopeTop.bounds_mm.max[2]-.001,'All microscope parts stand above the bench');
    for(const axis of [0,1])assert(group.bounds_mm.min[axis]>=microscopeTop.bounds_mm.min[axis]-.001&&group.bounds_mm.max[axis]<=microscopeTop.bounds_mm.max[axis]+.001);
  }
  const kitchen3008=model.kitchenette;
  assert(kitchen3008&&kitchen3008.level_id==='OG3'&&kitchen3008.area==='R3_008A');
  assert.equal(kitchen3008.scale,1);
  const kitchenEquipment=pinnedJson(kitchen3008.equipment_source.source);
  pinnedJson(kitchenEquipment.furnishings.source);
  const kitchenGroups=kitchen3008.body_ids.map(id=>nativeById.get(id));
  assert(kitchenGroups.every(group=>group&&group.level_id==='OG3'&&group.index_count>0),'Complete native kitchen coverage in the first room');
  assert.equal(kitchen3008.door_sweep_checks.length,2);
  for(const check of kitchen3008.door_sweep_checks){
    assert.equal(check.opening_axis[0],-1);assert.equal(Math.abs(check.opening_axis[1]),0);
    assert(check.minimum_clearance_mm>100);
    const door=model.objects.find(o=>o.id==='OG3.'+check.opening_id+'.Door');
    assert(door&&Math.abs(door.front[0]+1)<1e-8&&Math.abs(door.front[1])<1e-8,'The rendered room door opens toward the window');
  }
  for(const level of ['KG','EG'])assert.deepEqual(model.elevator.ports.filter(p=>p.level_id===level&&p.active).map(p=>p.side),['inward']);
  assert.equal(model.elevator.fittings.panel.side,'southwest');
  assert(model.elevator.fittings.interior.rail_body_ids.every(id=>nativeById.has(id)));
  const seminar = model.seminar_room;
  assert.equal(seminar.area_id, 'R0_010');
  assert(seminar.body_ids.includes(seminar.screen_body_id));
  assert(seminar.body_ids.every(id => nativeById.get(id)?.level_id === 'EG'), 'Seminar geometry comes from the native EG scene.');
  for (const id of ['phd', 'lab', 'microscopy', 'kitchen3008', 'kitchen', 'atrium', 'seating', 'seminar']) {
    assert(model.stops.some(stop => stop.id === id), `The ${id} viewpoint is required.`);
  }
  assert(!/<script[^>]+src=|<link[^>]+href=["']https?:/i.test(html), 'The viewer must work without external libraries.');
  const output = path.dirname(target);
  const progress=stage=>console.log(JSON.stringify({stage,time:new Date().toISOString()}));
  progress('native bundle assertions passed');
  const gpuProfile=process.env.SOLIDCRAFTBOT_WALKTHROUGH_GPU||'software';
  assert(['software','metal'].includes(gpuProfile),'Supported QA GPU profiles are software and metal.');
  const browser = await chromium.launch({headless: true,
    ...(process.argv[4] ? {executablePath: process.argv[4]} : {}),
    args: gpuProfile==='metal'?['--enable-gpu','--enable-webgl','--ignore-gpu-blocklist','--use-gl=angle','--use-angle=metal']
      :['--enable-webgl','--ignore-gpu-blocklist','--use-angle=swiftshader','--enable-unsafe-swiftshader'],
  });
  try {
    const page = await browser.newPage({viewport: {width: 1280, height: 950}, reducedMotion: 'reduce'});
    const errors = [], network = [];
    // Model and camera regression tests run without external film data.
    const filmUrl = seminar.film?.video_url;
    if (filmUrl) await page.route(url => url.href === filmUrl, route => route.fulfill({status: 204}));
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => {if (message.type() === 'error') errors.push(message.text());});
    page.on('request', request => {if (/^https?:/.test(request.url())) network.push(request.url());});
    await page.goto(pathToFileURL(target).href, {waitUntil: 'load', timeout: 120000});
    await page.waitForFunction(() => document.querySelector('#building-walkthrough').dataset.ready === 'true'
      || Boolean(document.querySelector('#building-walkthrough').dataset.error), null, {timeout: 120000});
    assert.equal(await page.locator('#building-walkthrough').getAttribute('data-error'), null,
      await page.locator('#walkthrough-error').textContent());
    const read = () => page.evaluate(() => {
      const viewer = window.__buildingWalkthrough;
      return {ready: viewer.ready, scene: viewer.sceneId, stop: viewer.stopId, camera: viewer.camera,
        stats: viewer.sceneStats, frames: viewer.frames};
    });
    const waitForStop = async id => page.waitForFunction(value => document.querySelector('#building-walkthrough').dataset.stop === value,
      id, {timeout: 120000});
    const cameraDistance = (a, b) => Math.hypot(...a.map((value, i) => value - b[i]));
    const report = {target, html_sha256: crypto.createHash('sha256').update(html).digest('hex'),
      browser: {engine: 'chromium', version: browser.version(),launch_profile:gpuProfile}, viewpoints: [], detail_views: [], interactions: []};
    report.social_source_coverage={furnishings_sha256:model.source_files_sha256[socialSourceName],
      catalog_sha256:socialSource.catalog.source_sha256,office_computers:officeComputerCoverage,articulated_instances:socialObjectCoverage};
    report.microscopy={id:microscopy.id,room:microscopy.area,level:microscopy.level_id,
      native_body_count:microscopeGroups.length,source_sha256:microscopy.instrument_source.source_sha256,
      complete_source_coverage:true,bench_support_checked:true,scale:1};
    report.kitchen3008={room:kitchen3008.area,scale:1,native_body_count:kitchenGroups.length,
      complete_source_coverage:true,room_door_sweeps:kitchen3008.door_sweep_checks};
    // New traversal tests drive exactly the pointer and keyboard controls exposed
    // to visitors. They read camera state for feedback but never assign a camera.
    const nativePositions = Buffer.from(nativeScene.positions_base64, 'base64');
    const nativeIndices = Buffer.from(nativeScene.indices_base64, 'base64');
    const groupById = new Map(nativeScene.groups.map(group => [group.id, group]));
    const centre = bounds => bounds.min.map((value, axis) => (value+bounds.max[axis])/2);
    function publicControls(surface) {
      const state = () => surface.evaluate(() => {
        const v=window.__buildingWalkthrough;
        return {camera:v.camera,scene:v.sceneId,stop:v.stopId,frames:v.frames,objects:v.objects,
          elevator:v.elevator,isolated:v.isolated,target:v.interactionTarget,lastInteraction:v.lastInteraction};
      });
      async function frameAfter(before) {
        await surface.waitForFunction(before => window.__buildingWalkthrough.frames>before,before,{timeout:120000});
      }
      async function lookAt(point) {
        const before=await state(),vector=point.map((value,axis)=>value-before.camera.eye_mm[axis]);
        const yaw=Math.atan2(vector[1],vector[0]),pitch=Math.atan2(vector[2],Math.hypot(vector[0],vector[1]));
        const turn=Math.atan2(Math.sin(yaw-before.camera.yaw_rad),Math.cos(yaw-before.camera.yaw_rad));
        const sensitivity=model.settings.look_sensitivity,dx=-turn/sensitivity,dy=-(pitch-before.camera.pitch_rad)/sensitivity;
        if(Math.abs(dx)+Math.abs(dy)<.05)return;
        const box=await surface.locator('#walkthrough-canvas').boundingBox(),x=box.x+box.width/2,y=box.y+box.height/2;
        const count=Math.max(1,Math.ceil(Math.abs(dx)/(box.width*.25)),Math.ceil(Math.abs(dy)/(box.height*.25)));
        for(let step=0;step<count;step++){
          await surface.mouse.move(x,y);await surface.mouse.down();
          // Even a small final correction must be a drag rather than a click.
          if(Math.hypot(dx/count,dy/count)<8)await surface.mouse.move(x+12,y,{steps:2});
          await surface.mouse.move(x+dx/count,y+dy/count,{steps:4});await surface.mouse.up();
        }
        await frameAfter(before.frames);
      }
      // Feedback is sampled across the browser protocol: releasing a held key
      // can take another rendered frame. A 200 mm arrival radius avoids
      // oscillation while remaining well inside the source door/room insets.
      async function walkTo(point, tolerance=200) {
        for(let attempt=0;attempt<6;attempt++){
          const before=await state(),delta=point.map((value,axis)=>value-before.camera.eye_mm[axis]);
          assert(Math.abs(delta[2])<100,'A corridor traversal must not fly between floors');
          const distance=Math.hypot(delta[0],delta[1]);if(distance<=tolerance)return before.camera.eye_mm;
          await lookAt([point[0],point[1],before.camera.eye_mm[2]]);
          const origin=(await state()).camera.eye_mm,direction=delta.slice(0,2).map(value=>value/distance);
          await surface.locator('#walkthrough-canvas').focus();
          const fast=distance>1000;
          if(fast)await surface.keyboard.down('Shift');
          await surface.keyboard.down('w');
          try{
            await surface.waitForFunction(({origin,direction,distance,tolerance})=>{
              const eye=window.__buildingWalkthrough.camera.eye_mm;
              return direction.reduce((sum,value,axis)=>sum+value*(eye[axis]-origin[axis]),0)>=distance-tolerance*.4;
            },{origin,direction,distance,tolerance},{timeout:180000,polling:'raf'});
          }finally{await surface.keyboard.up('w');if(fast)await surface.keyboard.up('Shift');}
        }
        const final=(await state()).camera.eye_mm;
        assert(Math.hypot(final[0]-point[0],final[1]-point[1])<=tolerance,`Public controls did not reach ${JSON.stringify(point)}: ${JSON.stringify(final)}`);
        return final;
      }
      async function aimNative(targetId, bodyIds) {
        const current=await state(),object=current.objects.find(object=>object.id===targetId);
        const world=point=>{
          if(!object)return point;
          const m=object.model_matrix,p=point.map(value=>value/1000);
          return [0,1,2].map(row=>(m[row]*p[0]+m[4+row]*p[1]+m[8+row]*p[2]+m[12+row])*1000);
        };
        const candidates=[];
        for(const id of bodyIds){
          const group=groupById.get(id);assert(group,`Missing native interaction body ${id}`);
          candidates.push(world(centre(group.bounds_mm)));
          for(let i=group.index_start;i<group.index_start+group.index_count;i+=3){
            const points=[0,1,2].map(offset=>{
              const index=nativeIndices.readUInt32LE((i+offset)*4);
              return [0,1,2].map(axis=>nativePositions.readFloatLE((index*3+axis)*4));
            });
            candidates.push(world([0,1,2].map(axis=>points.reduce((sum,point)=>sum+point[axis],0)/3)));
          }
        }
        candidates.sort((a,b)=>cameraDistance(a,current.camera.eye_mm)-cameraDistance(b,current.camera.eye_mm));
        let previous=null,attempts=0;
        for(const point of candidates){
          if(previous&&cameraDistance(previous,point)<10)continue;
          previous=point;if(++attempts>24)break;
          await lookAt(point);
          const hit=(await state()).target;
          if(hit?.target_id===targetId)return point;
        }
        throw Error(`No visible native surface for ${targetId}; ${JSON.stringify(await state())}`);
      }
      async function activate(targetId,bodyIds,input='space') {
        await aimNative(targetId,bodyIds);const before=await state();
        if(input==='space'){await surface.locator('#walkthrough-canvas').focus();await surface.keyboard.press('Space');}
        else{
          const box=await surface.locator('#walkthrough-canvas').boundingBox();
          await surface.mouse.click(box.x+box.width/2,box.y+box.height/2);
        }
        const interactionFrame=await surface.evaluate(()=>window.__buildingWalkthrough.lastInteraction?.frame);
        await frameAfter(Number.isFinite(interactionFrame)?interactionFrame:before.frames);
        const after=await state();assert.equal(after.lastInteraction?.input,input);
        assert.equal(after.lastInteraction?.id,model.objects.some(object=>object.id===targetId)?targetId:model.elevator.object_id);
        assert(['accepted','already_in_state'].includes(after.lastInteraction?.status),`${targetId}: native ${input} interaction failed: ${JSON.stringify(after.lastInteraction)}`);
        return after;
      }
      return {state,lookAt,walkTo,aimNative,activate,frameAfter};
    }
    assert.equal((await read()).ready, true);
    assert.equal(await page.locator('#walkthrough-stops button').count(), model.stops.length);
    for (const stop of model.stops) {
      await page.locator('#walkthrough-stops button').filter({hasText: stop.label}).click();
      await waitForStop(stop.id);
      const state = await read();
      assert.equal(state.stop, stop.id);
      assert.equal(state.scene, stop.scene);
      assert(cameraDistance(state.camera.eye_mm, stop.eye_mm) < .01, `${stop.id}: source-derived viewpoint`);
      assert(state.stats.triangles > 0 && state.stats.native_groups > 0, `${stop.id}: native geometry`);
      assert.equal(await page.locator('#walkthrough-level').isDisabled(), stop.scene !== 'building');
      assert(!/separate local room model/.test(await page.locator('#walkthrough-context').textContent()));
      const pixels = await page.evaluate(() => {
        const canvas = document.querySelector('#walkthrough-canvas'), gl = canvas.getContext('webgl2');
        const bytes = new Uint8Array(canvas.width * canvas.height * 4);
        gl.readPixels(0, 0, canvas.width, canvas.height, gl.RGBA, gl.UNSIGNED_BYTE, bytes);
        const colors = new Set(); let samples = 0, geometry = 0;
        for (let i = 0; i < bytes.length; i += 4 * 23) {
          colors.add(`${bytes[i] >> 3},${bytes[i + 1] >> 3},${bytes[i + 2] >> 3}`); samples++;
          if (Math.abs(bytes[i] - 201) + Math.abs(bytes[i + 1] - 217) + Math.abs(bytes[i + 2] - 214) > 12) geometry++;
        }
        const debug=gl.getExtension('WEBGL_debug_renderer_info');
        return {colors: colors.size, geometry_fraction: geometry / samples, gl_error: gl.getError(),
          gpu:{renderer:gl.getParameter(gl.RENDERER),unmasked_renderer:debug?gl.getParameter(debug.UNMASKED_RENDERER_WEBGL):null,
            unmasked_vendor:debug?gl.getParameter(debug.UNMASKED_VENDOR_WEBGL):null}};
      });
      assert.equal(pixels.gl_error, 0, `${stop.id}: WebGL error`);
      assert(pixels.colors > 6 && pixels.geometry_fraction > .04, `${stop.id}: blank or featureless image ${JSON.stringify(pixels)}`);
      report.browser.gpu=pixels.gpu;
      const screenshot = `browser-${String(stop.id).replace(/[^a-z0-9_-]/gi, '-')}.png`;
      await page.screenshot({path: path.join(output, screenshot), fullPage: true});
      report.viewpoints.push({id: stop.id, scene: stop.scene, stats: state.stats, pixels, screenshot});
      if (stop.id === 'seminar') {
        const sashes = seminar.window_front.sashes;
        assert(sashes.length > 1);
        await page.locator('#seminar-window-controls summary').click();
        const selector = page.locator('#seminar-window-select');
        assert.equal(await selector.locator('option').count(), sashes.length);
        await selector.selectOption(sashes[0].id+'.Hinge');
        const toggle = page.locator('#seminar-window-toggle');
        const hingeIds = sashes.map(sash => sash.id+'.Hinge');
        const readWindows = () => page.evaluate(ids => window.__buildingWalkthrough.objects.filter(obj => ids.includes(obj.id)), hingeIds);
        await toggle.click();
        await page.waitForFunction(id => window.__buildingWalkthrough.objects.find(obj => obj.id === id)?.state === 'open',
          sashes[0].id+'.Hinge');
        const open = await readWindows();
        assert.deepEqual(open.filter(obj => obj.state === 'open').map(obj => obj.id), [sashes[0].id+'.Hinge']);
        await toggle.click();
        await page.waitForFunction(id => window.__buildingWalkthrough.objects.find(obj => obj.id === id)?.state === 'closed',
          sashes[0].id+'.Hinge');
      }
      progress('viewpoint '+stop.id+' passed');
    }

    // The cabinet is beside the entry, behind a forward-facing doorway camera.
    // Turn through the public drag control toward its exported native bounds.
    const phd = model.stops.find(stop => stop.id === 'phd' && stop.scene === 'building');
    const cabinet = model.scenes.building.groups.filter(group => /PhD3002.*FirstAid/.test(group.id));
    if (phd && cabinet.length) {
      await page.locator('#walkthrough-stops button[data-stop="phd"]').click(); await waitForStop(phd.id);
      await page.locator('#walkthrough-canvas').focus();
      for (const [key, distance] of [['w', 450], ['d', 1100]]) {
        const before = (await read()).camera.eye_mm;
        await page.keyboard.down(key);
        try {
          await page.waitForFunction(({before, distance}) => Math.hypot(...window.__buildingWalkthrough.camera.eye_mm
            .map((value, axis) => value - before[axis])) >= distance, {before, distance}, {timeout: 60000});
        } finally {await page.keyboard.up(key);}
      }
      const target = [0, 1, 2].map(axis => (Math.min(...cabinet.map(group => group.bounds_mm.min[axis]))
        + Math.max(...cabinet.map(group => group.bounds_mm.max[axis]))) / 2);
      const current = await read(), vector = target.map((value, axis) => value - current.camera.eye_mm[axis]);
      const angle = Math.atan2(vector[1], vector[0]), pitch = Math.atan2(vector[2], Math.hypot(vector[0], vector[1]));
      const turn = Math.atan2(Math.sin(angle - current.camera.yaw_rad), Math.cos(angle - current.camera.yaw_rad));
      const sensitivity = model.settings.look_sensitivity || .0025;
      let dx = -turn / sensitivity, dy = -(pitch - current.camera.pitch_rad) / sensitivity;
      const area = await page.locator('#walkthrough-canvas').boundingBox(), centre = {x: area.x + area.width / 2, y: area.y + area.height / 2};
      while (Math.abs(dx) + Math.abs(dy) > .1) {
        const x = Math.max(-area.width * .3, Math.min(area.width * .3, dx));
        const y = Math.max(-area.height * .3, Math.min(area.height * .3, dy));
        await page.mouse.move(centre.x, centre.y); await page.mouse.down();
        await page.mouse.move(centre.x + x, centre.y + y, {steps: 4}); await page.mouse.up(); dx -= x; dy -= y;
      }
      await page.waitForTimeout(100);
      await page.screenshot({path: path.join(output, 'browser-phd-entry.png'), fullPage: true});
      report.detail_views.push({id: 'phd-entry', source_body_ids: cabinet.map(group => group.id),
        camera: (await read()).camera, target_mm: target, controls: 'step forward, step right, drag to look back',
        screenshot: 'browser-phd-entry.png'});
    }

    const building = model.stops.find(stop => stop.scene === 'building');
    await page.locator(`#walkthrough-stops button[data-stop="${building.id}"]`).click();
    await waitForStop(building.id);
    const initial = await read();
    await page.locator('#walkthrough-canvas').focus();
    await page.keyboard.down('w');
    try {
      await page.waitForFunction(before => Math.hypot(...window.__buildingWalkthrough.camera.eye_mm
        .map((value, axis) => value - before[axis])) > 100, initial.camera.eye_mm, {timeout: 60000});
    } finally {await page.keyboard.up('w');}
    const walked = await read();
    assert(cameraDistance(initial.camera.eye_mm, walked.camera.eye_mm) > 100, 'W moves the camera');
    report.interactions.push('keyboard horizontal movement');
    await page.keyboard.down('e');
    try {
      await page.waitForFunction(z => window.__buildingWalkthrough.camera.eye_mm[2] > z + 80,
        walked.camera.eye_mm[2], {timeout: 60000});
    } finally {await page.keyboard.up('e');}
    const elevated = await read();
    assert(elevated.camera.eye_mm[2] > walked.camera.eye_mm[2] + 80, 'E raises the camera');
    const canvas = await page.locator('#walkthrough-canvas').boundingBox();
    await page.mouse.move(canvas.x + canvas.width / 2, canvas.y + canvas.height / 2);
    await page.mouse.down(); await page.mouse.move(canvas.x + canvas.width / 2 + 100, canvas.y + canvas.height / 2 + 30, {steps: 4}); await page.mouse.up();
    const looked = await read();
    assert(Math.abs(looked.camera.yaw_rad - elevated.camera.yaw_rad) > .1, 'Dragging turns the camera');
    report.interactions.push('keyboard vertical movement', 'pointer look');
    const forward = await page.locator('[data-move="forward"]').boundingBox();
    await page.mouse.move(forward.x + forward.width / 2, forward.y + forward.height / 2);
    await page.mouse.down();
    try {
      await page.waitForFunction(before => Math.hypot(...window.__buildingWalkthrough.camera.eye_mm
        .map((value, axis) => value - before[axis])) > 100, looked.camera.eye_mm, {timeout: 60000});
    } finally {await page.mouse.up();}
    const touched = await read();
    assert(cameraDistance(touched.camera.eye_mm, looked.camera.eye_mm) > 100, 'On-screen movement control moves the camera');
    report.interactions.push('on-screen movement');
    await page.locator('#walkthrough-return').click(); await waitForStop(building.id);
    assert(cameraDistance((await read()).camera.eye_mm, building.eye_mm) < .01, 'Return restores the source viewpoint');
    const index = model.stops.findIndex(stop => stop.id === building.id);
    await page.locator('#walkthrough-next').click(); await waitForStop(model.stops[(index + 1) % model.stops.length].id);
    await page.locator('#walkthrough-previous').click(); await waitForStop(building.id);
    report.interactions.push('return to viewpoint', 'next and previous stops');
    const otherLevel = model.levels?.find(level => level.id !== building.level_id && Number.isFinite(level.z_mm));
    if (otherLevel) {
      await page.locator('#walkthrough-level').selectOption(otherLevel.id);
      assert(Math.abs((await read()).camera.eye_mm[2] - otherLevel.z_mm - (model.settings.eye_height_mm || 1600)) < .01,
        'The level control derives eye height from its source datum');
      report.interactions.push('building level selector');
    }
    for (const width of [320, 600, 1280]) {
      await page.setViewportSize({width, height: 900});
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `Page overflow at ${width}px`);
    }
    await page.setViewportSize({width: 390, height: 844});
    await page.locator('#walkthrough-return').click();
    await page.screenshot({path: path.join(output, 'browser-mobile.png'), fullPage: true});
    assert(network.every(url => url === filmUrl), 'Only the configured film may request external data');
    assert.deepEqual(errors, [], 'No browser or renderer errors');
    assert((await read()).frames > initial.frames, 'Controls request new rendered frames');

    const object = model.objects?.find(item => item.id === 'Kitchen1008.Fridge.Door');
    assert(object, 'A source-defined articulated object is required.');
    assert.equal(await page.locator('#walkthrough-objects,[data-object-action]').count(),0,'No object-command buttons are shown');
    const identityMatrix = [1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1];
    const objectState = () => page.evaluate(id => window.__buildingWalkthrough.objects.find(v => v.id === id), object.id);
    const rendered = async action => {
      const before = await page.evaluate(() => window.__buildingWalkthrough.frames);
      const result = await action();
      await page.waitForFunction(before => window.__buildingWalkthrough.frames > before, before, {timeout: 120000});
      return result;
    };
    await page.setViewportSize({width:1280,height:950});
    await page.locator('#walkthrough-stops button[data-stop="kitchen"]').click(); await waitForStop('kitchen');
    await rendered(() => page.evaluate(id=>window.__buildingWalkthrough.viewObject(id),object.id));
    assert(cameraDistance((await read()).camera.eye_mm,object.viewpoint.eye_mm)<.01,'Object camera is derived from placed source geometry');
    assert.deepEqual((await objectState()).model_matrix,identityMatrix,'Reference pose is exactly identity');
    assert.equal((await page.evaluate(() => window.__buildingWalkthrough.command('missing','open'))).status,'unknown_target');
    assert.equal((await page.evaluate(id=>window.__buildingWalkthrough.command(id,'close'),object.id)).status,'already_in_state');
    const scene=model.scenes[object.scene], group=scene.groups.find(v=>v.id===object.moving_body_ids[0]);
    const pos=Buffer.from(scene.positions_base64,'base64'), idx=Buffer.from(scene.indices_base64,'base64');let hingeError=Infinity;
    for(let i=group.index_start;i<group.index_start+group.index_count;i++){
      const v=idx.readUInt32LE(i*4),point=[0,1,2].map(k=>pos.readFloatLE((v*3+k)*4));
      hingeError=Math.min(hingeError,Math.hypot(...point.map((x,k)=>x-object.joint.origin_mm[k])));
    }
    const hingeFloat32Error=Math.hypot(...object.joint.origin_mm.map((v,i)=>v-new Float32Array(object.joint.origin_mm)[i]));
    assert(hingeError<=hingeFloat32Error+1e-6,'Compiled hinge coincides with the Float32-quantized native vertex');
    const penguin=scene.groups.find(v=>v.id==='Kitchen1008_Penguin_Body');assert(penguin);
    const penguinPoint=penguin.bounds_mm.min.map((v,i)=>(v+penguin.bounds_mm.max[i])/2);
    // Sample the black body flank, away from the intentionally white belly.
    penguinPoint[0]+=.36*(penguin.bounds_mm.max[0]-penguin.bounds_mm.min[0]);
    // The fixed lower body flank is below the existing middle shelf; the head is partly occluded at standing eye height.
    penguinPoint[2]=penguin.bounds_mm.min[2]+.16*(penguin.bounds_mm.max[2]-penguin.bounds_mm.min[2]);
    const pixel = () => page.evaluate(point => {
      const v=window.__buildingWalkthrough,p=v.projectPoint(point),canvas=document.querySelector('#walkthrough-canvas');
      if(!p.visible)throw Error('Penguin body point is outside the source-derived camera.');
      const gl=canvas.getContext('webgl2'),rgba=new Uint8Array(4);
      gl.readPixels(Math.floor(p.x),canvas.height-1-Math.floor(p.y),1,1,gl.RGBA,gl.UNSIGNED_BYTE,rgba);
      return {rgba:[...rgba],pixel:p};
    },penguinPoint);
    const closedPixel=await pixel();
    await page.screenshot({path:path.join(output,'browser-fridge-closed.png'),fullPage:true});
    const doorCentre=group.bounds_mm.min.map((v,i)=>(v+group.bounds_mm.max[i])/2);
    const clickDoor = async () => {
      const screen=await page.evaluate(({id,point})=>{
        const v=window.__buildingWalkthrough,o=v.objects.find(o=>o.id===id),m=o.model_matrix,p=point.map(x=>x/1000);
        const world=[0,1,2].map(r=>(m[r]*p[0]+m[4+r]*p[1]+m[8+r]*p[2]+m[12+r])*1000);
        const pixel=v.projectPoint(world),c=document.querySelector('canvas'),rect=c.getBoundingClientRect();
        return {x:rect.left+pixel.x/c.width*rect.width,y:rect.top+pixel.y/c.height*rect.height,visible:pixel.visible};
      },{id:object.id,point:doorCentre});
      assert(screen.visible,'Current door leaf must be visible before clicking');await page.mouse.click(screen.x,screen.y);
      await page.waitForFunction(()=>{const v=window.__buildingWalkthrough;return v.lastInteraction?.input==='click'&&v.frames>v.lastInteraction.frame;},null,{timeout:120000});
      assert.equal((await page.evaluate(()=>window.__buildingWalkthrough.lastInteraction)).status,'accepted','Mouse click hits the visible nearby door');
    };
    await clickDoor();
    assert.equal((await objectState()).state,'open');assert.equal((await objectState()).angle_deg,object.states.open);
    assert(Object.values((await objectState()).body_angles_deg).every(v=>v===object.states.open),'Door and handle rotate together');
    const openPixel=await pixel(),brightness=p=>p.rgba.slice(0,3).reduce((a,b)=>a+b,0)/3;
    assert(brightness(closedPixel)>140,'Closed sample must show the light fridge door');
    assert(brightness(openPixel)<brightness(closedPixel)-50,`Open sample must reveal the darker penguin: ${JSON.stringify({closedPixel,openPixel})}`);
    await page.screenshot({path:path.join(output,'browser-fridge-open.png'),fullPage:true});
    await clickDoor();assert.equal((await objectState()).state,'closed','Mouse can close the rotated leaf');
    await clickDoor();
    assert.equal((await page.evaluate(id=>window.__buildingWalkthrough.command(id,'open'),object.id)).status,'already_in_state');
    await page.locator('#walkthrough-level').selectOption('EG');
    await page.evaluate(()=>window.dispatchEvent(new Event('blur')));
    assert.equal((await objectState()).state,'open','Level and focus changes preserve object state');
    await page.locator('#walkthrough-stops button[data-stop="lab"]').click();await waitForStop('lab');
    assert.notEqual((await page.evaluate(()=>window.__buildingWalkthrough.interactionTarget))?.target_id, object.id, 'The distant fridge cannot be operated from laboratory 3.003');
    await page.locator('#walkthrough-stops button[data-stop="kitchen"]').click();await waitForStop('kitchen');assert.equal((await objectState()).state,'open');
    await rendered(() => page.evaluate(id=>window.__buildingWalkthrough.viewObject(id),object.id));
    await page.locator('#walkthrough-canvas').focus();
    await page.keyboard.press('Space');
    await page.waitForFunction(()=>{const v=window.__buildingWalkthrough;return v.frames>v.lastInteraction.frame;});
    assert.equal((await page.evaluate(()=>window.__buildingWalkthrough.lastInteraction)).status,'accepted','Space closes the nearby open doorway');
    assert.equal((await objectState()).state,'closed');assert.deepEqual((await objectState()).model_matrix,identityMatrix);
    // Holding Space must not repeatedly toggle, and dragging must never activate a door.
    await page.keyboard.down('Space');await page.keyboard.down('Space');await page.keyboard.up('Space');
    assert.equal((await objectState()).state,'open','Repeated keydown is ignored');
    await page.keyboard.press('Space');assert.equal((await objectState()).state,'closed');
    const area=await page.locator('#walkthrough-canvas').boundingBox();
    await page.mouse.move(area.x+area.width/2,area.y+area.height/2);await page.mouse.down();
    await page.mouse.move(area.x+area.width/2+50,area.y+area.height/2+20,{steps:3});await page.mouse.up();
    assert.equal((await objectState()).state,'closed','Camera dragging does not activate doors');
    await page.locator('#walkthrough-stops button[data-stop="phd"]').click();await waitForStop('phd');
    await page.locator('#walkthrough-canvas').focus();await page.keyboard.press('Space');
    assert.equal((await objectState()).state,'closed','Space cannot operate a distant or occluded door');
    assert.equal((await page.evaluate(()=>window.__buildingWalkthrough.lastInteraction)).status,'no_target');
    for(const width of [320,600,1280]){
      await page.setViewportSize({width,height:950});
      await rendered(() => page.evaluate(id=>window.__buildingWalkthrough.viewObject(id),object.id));
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`Viewer overflows at ${width}px`);
      const hint=await page.locator('#walkthrough-interaction-hint').boundingBox();assert(hint,'Nearby door hint is visible');
      for(const selector of ['.move-controls','.height-controls']){
        const controls=await page.locator(selector).boundingBox();
        const overlaps=hint.x<controls.x+controls.width&&hint.x+hint.width>controls.x&&hint.y<controls.y+controls.height&&hint.y+hint.height>controls.y;
        assert(!overlaps,`Door hint overlaps movement controls at ${width}px`);
      }
    }
    // A second context exercises actual animation, independently of reduced motion.
    const animatedContext=await browser.newContext({viewport:{width:1280,height:950},reducedMotion:'no-preference'});
    try{
      const animated=await animatedContext.newPage();await animated.goto(pathToFileURL(target).href,{waitUntil:'load',timeout:120000});
      await animated.waitForFunction(()=>window.__buildingWalkthrough?.ready,null,{timeout:120000});
      await animated.evaluate(id=>window.__buildingWalkthrough.viewObject(id),object.id);
      await animated.evaluate(id=>{
        const viewer=window.__buildingWalkthrough,qa={opening:{samples:[]},closing:{samples:[]}};
        window.__walkthroughFridgeQA=qa;
        const record=(phase,transient)=>{
          const before=viewer.frames;
          function sample(){
            const object=viewer.objects.find(value=>value.id===id);
            if(viewer.frames>before&&object.angle_deg>0&&object.angle_deg<90)
              qa[phase].samples.push({angle_deg:object.angle_deg,frame:viewer.frames});
            if(object.state===transient)requestAnimationFrame(sample);
          }
          requestAnimationFrame(sample);
        };
        qa.record=record;
        window.addEventListener('keydown',function opening(event){
          if(event.code!=='Space')return;
          window.removeEventListener('keydown',opening);
          qa.opening.busy=viewer.command(id,'close');
          record('opening','opening');
        });
      },object.id);
      await animated.locator('#walkthrough-canvas').focus();await animated.keyboard.press('Space');
      assert.equal((await animated.evaluate(()=>window.__buildingWalkthrough.lastInteraction)).status,'accepted');
      await animated.waitForFunction(()=>window.__walkthroughFridgeQA.opening.samples.length>0,null,{timeout:10000});
      const opening=await animated.evaluate(()=>window.__walkthroughFridgeQA.opening);
      const intermediate=opening.samples[0];
      assert(intermediate.angle_deg>0&&intermediate.angle_deg<object.states.open);
      assert.equal(opening.busy.status,'rejected_busy');
      await animated.waitForFunction(id=>window.__buildingWalkthrough.objects.find(v=>v.id===id).state==='open',object.id,{timeout:10000});
      assert.equal(await animated.evaluate(id=>window.__buildingWalkthrough.objects.find(v=>v.id===id).angle_deg,object.id),object.states.open);
      const interrupted=await animated.evaluate(id=>{
        const viewer=window.__buildingWalkthrough,qa=window.__walkthroughFridgeQA;
        const started=viewer.command(id,'close');
        const result=viewer.command(id,'open');
        window.dispatchEvent(new Event('blur'));
        qa.record('closing','closing');
        return {started,result,state:viewer.objects.find(v=>v.id===id).state};
      },object.id);
      assert.equal(interrupted.started.status,'accepted');
      assert.equal(interrupted.result.status,'rejected_busy');assert.equal(interrupted.state,'closing');
      await animated.waitForFunction(()=>window.__walkthroughFridgeQA.closing.samples.length>0,null,{timeout:10000});
      await animated.waitForFunction(id=>window.__buildingWalkthrough.objects.find(v=>v.id===id).state==='closed',object.id,{timeout:10000});
      const closed=await animated.evaluate(id=>window.__buildingWalkthrough.objects.find(v=>v.id===id),object.id);
      assert.equal(closed.angle_deg,object.states.closed);assert.deepEqual(closed.model_matrix,identityMatrix);
      report.articulation={mouse_open_close:true,space_open_close:true,no_object_buttons:true,drag_does_not_activate:true,distant_space_rejected:true,id:object.id,hinge_vertex_error_mm:hingeError,hinge_float32_error_mm:hingeFloat32Error,closed_pixel:closedPixel,open_pixel:openPixel,intermediate_angle_deg:intermediate.angle_deg,reduced_motion:true,animated:true,animated_close:true,focus_loss_during_close:true,busy_rejected:true,state_preserved_across_viewpoints:true};
    }finally{await animatedContext.close();}
    assert.deepEqual(errors,[], 'Object commands produce no browser errors');
    report.interactions.push('native door picking','mouse click open/close','Space near doorway','open/close','reduced and animated hinge motion','persistent in-memory scene state');
    progress('fridge and movement regressions passed');

    // Follow the viewer's hint through the nearer lab door into the east aisle.
    // Keep the existing A-side camera point for the lab viewpoint and exit.
    const controls=publicControls(page),labStop=model.stops.find(stop=>stop.id==='lab');
    function entryOutside(stop){
      assert.equal(stop.anchor.kind,'room_entry');
      const delta=stop.target_mm.slice(0,2).map((value,axis)=>value-stop.eye_mm[axis]),length=Math.hypot(...delta);
      const inward=delta.map(value=>value/length);
      return stop.eye_mm.map((value,axis)=>axis===2?value:value-inward[axis]*(stop.anchor.inset_mm+500));
    }
    const phdOutside=entryOutside(phd),labOutside=entryOutside(labStop);
    const nearDoor=model.objects.find(object=>object.level_id===labStop.level_id&&object.opening_id==='D3_003B');
    assert(nearDoor?.mechanism==='room_door'&&nearDoor.initial_state==='open');
    const nearDoorCenter=[...nearDoor.viewpoint.target_mm.slice(0,2),labStop.eye_mm[2]];
    const approachInset=500;
    const nearDoorOutside=nearDoorCenter.map((value,axis)=>value+nearDoor.front[axis]*approachInset);
    const nearDoorInside=nearDoorCenter.map((value,axis)=>value-nearDoor.front[axis]*approachInset);
    const nearDoorEntry={level_id:labStop.level_id,eye_mm:nearDoorInside,
      target_mm:nearDoorInside.map((value,axis)=>value-nearDoor.front[axis]*approachInset),
      anchor:{opening:nearDoor.opening_id,inset_mm:approachInset}};
    const officeLink=model.topology.find(edge=>edge.opening===phd.anchor.opening&&edge.level_id===phd.level_id);
    const laboratoryLink=model.topology.find(edge=>edge.opening===nearDoor.opening_id&&edge.level_id===labStop.level_id);
    assert(officeLink.areas.includes('R3_002')&&laboratoryLink.areas.includes(laboratory.area));
    const commonCorridor=officeLink.areas.find(area=>laboratoryLink.areas.includes(area));
    assert(commonCorridor,'Office and laboratory doors connect to the same source corridor');
    function nativeTriangles(group){
      const triangles=[];
      for(let index=group.index_start;index<group.index_start+group.index_count;index+=3)
        triangles.push([0,1,2].map(offset=>{
          const vertex=nativeIndices.readUInt32LE((index+offset)*4);
          return [0,1,2].map(axis=>nativePositions.readFloatLE((vertex*3+axis)*4));
        }));
      return triangles;
    }
    const dot=(a,b)=>a.reduce((sum,value,axis)=>sum+value*b[axis],0);
    const minus=(a,b)=>a.map((value,axis)=>value-b[axis]);
    const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
    function rayTriangle(origin,direction,[a,b,c]){
      const e1=minus(b,a),e2=minus(c,a),p=cross(direction,e2),det=dot(e1,p);
      if(Math.abs(det)<1e-8)return Infinity;
      const inv=1/det,t=minus(origin,a),u=dot(t,p)*inv;if(u<0||u>1)return Infinity;
      const q=cross(t,e1),v=dot(direction,q)*inv;if(v<0||u+v>1)return Infinity;
      const distance=dot(e2,q)*inv;return distance>1e-4?distance:Infinity;
    }
    function doorway(stop){
      const delta=stop.target_mm.slice(0,2).map((value,axis)=>value-stop.eye_mm[axis]),length=Math.hypot(...delta);
      const normal=delta.map(value=>value/length),tangent=[-normal[1],normal[0],0];
      const origin=stop.eye_mm.map((value,axis)=>axis===2?value:value-normal[axis]*stop.anchor.inset_mm);
      const walls=nativeScene.groups.filter(group=>group.role==='concept_storey_wall'&&group.level_id===stop.level_id
        &&origin.every((value,axis)=>value>=group.bounds_mm.min[axis]-.01&&value<=group.bounds_mm.max[axis]+.01));
      assert.equal(walls.length,1,`${stop.anchor.opening}: one native entrance wall bounds the source doorway`);
      const triangles=nativeTriangles(walls[0]);
      const low=Math.min(...triangles.map(triangle=>rayTriangle(origin,tangent.map(value=>-value),triangle)));
      const high=Math.min(...triangles.map(triangle=>rayTriangle(origin,tangent,triangle)));
      assert(Number.isFinite(low)&&Number.isFinite(high)&&low>0&&high>0,`${stop.anchor.opening}: native jambs enclose an actual wall aperture`);
      return {opening:stop.anchor.opening,wall_body_id:walls[0].id,origin_mm:origin,inward:normal,tangent,
        aperture_tangent_interval_mm:[-low,high]};
    }
    const doorways=[doorway(phd),doorway(nearDoorEntry)];
    const routeFloorIds=[...phd.anchor.areas,commonCorridor,...labStop.anchor.areas].map(area=>phd.level_id+'__Area_'+area);
    const routeFloorTriangles=routeFloorIds.flatMap(id=>{
      const group=groupById.get(id);assert(group,`The source route floor ${id} is present`);
      return nativeTriangles(group).filter(triangle=>triangle.every(point=>Math.abs(point[2]-group.bounds_mm.max[2])<.01));
    });
    assert(routeFloorTriangles.length>0);
    const onRouteFloor=point=>routeFloorTriangles.some(triangle=>{
      const distances=triangle.map((a,index)=>{
        const b=triangle[(index+1)%3],length=Math.hypot(b[0]-a[0],b[1]-a[1]);
        return ((b[0]-a[0])*(point[1]-a[1])-(b[1]-a[1])*(point[0]-a[0]))/length;
      });
      return distances.every(value=>value>=-2)||distances.every(value=>value<=2);
    });
    await page.setViewportSize({width:1280,height:950});
    await page.locator('#walkthrough-stops button[data-stop="phd"]').click();await waitForStop('phd');
    const routeHint=page.locator('#walkthrough-lab-route');
    await routeHint.waitFor({state:'visible'});
    assert.match(await routeHint.textContent(),/ersten Tür.*3\.003 Labor/);
    const nearDoorState=()=>page.evaluate(id=>window.__buildingWalkthrough.objects.find(object=>object.id===id)?.state,nearDoor.id);
    assert.equal(await nearDoorState(),'open');
    await page.evaluate(()=>{
      const viewer=window.__buildingWalkthrough,trace={active:true,samples:[{frame:viewer.frames,time_ms:performance.now(),eye_mm:viewer.camera.eye_mm}]};
      window.__walkthroughRouteQA=trace;
      function sample(){
        if(!trace.active)return;
        const eye=viewer.camera.eye_mm,previous=trace.samples[trace.samples.length-1];
        if(viewer.frames!==previous.frame&&Math.hypot(...eye.map((value,axis)=>value-previous.eye_mm[axis]))>1)
          trace.samples.push({frame:viewer.frames,time_ms:performance.now(),eye_mm:eye});
        requestAnimationFrame(sample);
      }
      requestAnimationFrame(sample);
    });
    const route=[];
    for(const [label,point] of [['office exit',phdOutside],['corridor at laboratory door B',nearDoorOutside],
      ['entry through laboratory door B into the lab',nearDoorInside]]){
      const observed=await controls.walkTo(point);
      assert.equal(await nearDoorState(),'open','Walking preserves the state of the outward-opening door');
      assert.equal((await controls.state()).scene,'building');
      assert.equal((await controls.state()).stop,'phd','Walking must not invoke the lab viewpoint shortcut');
      route.push({label,target_mm:point,observed_mm:observed});
      progress('route waypoint '+label+' reached');
    }
    await controls.lookAt(labStop.target_mm);
    const routeTrace=await page.evaluate(()=>{const trace=window.__walkthroughRouteQA;trace.active=false;return trace.samples;});
    assert(routeTrace.length>2,'The public walk records actual rendered camera samples');
    const frameIntervals=routeTrace.slice(1).flatMap((sample,index)=>sample.frame===routeTrace[index].frame+1?[sample.time_ms-routeTrace[index].time_ms]:[]).sort((a,b)=>a-b);
    assert(frameIntervals.length>0,'The route records timing of consecutive rendered movement frames');
    report.browser.movement_frame_intervals_ms={samples:frameIntervals.length,min:frameIntervals[0],
      median:frameIntervals[Math.floor(frameIntervals.length/2)],p95:frameIntervals[Math.floor((frameIntervals.length-1)*.95)],max:frameIntervals[frameIntervals.length-1]};
    const sourceLevel=model.levels.find(level=>level.id===phd.level_id);
    for(const sample of routeTrace){
      assert(Math.abs(sample.eye_mm[2]-sourceLevel.z_mm-model.settings.eye_height_mm)<.01,'The office/lab route remains on OG3');
      assert(onRouteFloor(sample.eye_mm),`A rendered route sample left the source office/corridor/lab floors: ${JSON.stringify(sample)}`);
    }
    const doorBounds=nearDoor.moving_body_ids.map(id=>groupById.get(id).bounds_mm);
    const routeDoorClearance=Math.min(...routeTrace.map(sample=>Math.min(...doorBounds.map(bounds=>
      Math.hypot(...sample.eye_mm.map((value,axis)=>Math.max(bounds.min[axis]-value,0,value-bounds.max[axis])))))));
    assert(routeDoorClearance>=model.navigation.camera_radius_mm+model.navigation.contact_margin_mm,
      'The rendered camera path clears the open B leaf and all of its details');
    const crossings=[];
    for(const [index,door] of doorways.entries()){
      for(let i=1;i<routeTrace.length;i++){
        const a=routeTrace[i-1],b=routeTrace[i],side=sample=>dot(minus(sample.eye_mm,door.origin_mm).slice(0,2),door.inward);
        const sa=side(a),sb=side(b),outward=index===0;
        if(!(outward?sa>0&&sb<=0:sa<0&&sb>=0))continue;
        const u=sa/(sa-sb),point=a.eye_mm.map((value,axis)=>value+u*(b.eye_mm[axis]-value));
        const offset=dot(minus(point,door.origin_mm),door.tangent),[low,high]=door.aperture_tangent_interval_mm;
        assert(offset>low+2&&offset<high-2,`${door.opening}: the recorded wall crossing must lie between its native jambs`);
        crossings.push({opening:door.opening,wall_body_id:door.wall_body_id,eye_mm:point,tangent_offset_mm:offset,
          aperture_tangent_interval_mm:[low,high],from_frame:a.frame,to_frame:b.frame});
      }
      assert(crossings.some(crossing=>crossing.opening===door.opening),`${door.opening}: a rendered doorway crossing is required`);
    }
    await page.screenshot({path:path.join(output,'browser-lab-from-corridor.png'),fullPage:true});
    report.laboratory={id:laboratory.id,level:laboratory.level_id,room:laboratory.area,
      equipment_instances:equipment.map(value=>({id:value.id,body_count:value.body_count})),
      duplicate_shell:false,corridor:commonCorridor,door_route:[officeLink.opening,laboratoryLink.opening],
      near_door_open_preserved:true,walking_hint_visible:true,
      minimum_open_door_bounds_distance_mm:routeDoorClearance,
      public_control_route:route,rendered_camera_trace:routeTrace,native_floor_body_ids:routeFloorIds,native_doorway_crossings:crossings,
      scope:'Free-camera traversal through native doorway apertures and source floor footprints; physical passability remains unqualified'};
    progress('public 3.002 to equipped 3.003 route passed');

    const labDoor=model.objects.find(value=>value.id.startsWith(laboratory.id+'.')&&value.joint.type==='revolute');
    const stool=model.objects.find(value=>value.id.startsWith(laboratory.id+'.')&&value.joint.type==='prismatic');
    assert(labDoor&&stool,'Recipe cabinet doors and stool lift must both be available');
    for(const config of [labDoor,stool]){
      let approach=config.viewpoint.eye_mm;
      if(config===stool){
        // A tucked-under stool must be approached from the aisle, rather than
        // looking through its neighbouring window worktop from the side.
        const delta=labStop.target_mm.slice(0,2).map((value,axis)=>value-labStop.eye_mm[axis]);
        const length=Math.hypot(...delta),distance=Math.hypot(...config.viewpoint.eye_mm.slice(0,2).map((value,axis)=>value-config.viewpoint.target_mm[axis]));
        approach=config.viewpoint.target_mm.map((value,axis)=>axis<2?value-delta[axis]/length*distance:config.viewpoint.eye_mm[2]);
      }
      await controls.walkTo(approach);
      let state=await controls.activate(config.id,config.moving_body_ids,'space');
      let object=state.objects.find(value=>value.id===config.id);
      assert.equal(object.state,'open');assert.equal(object.joint_value,config.states.open);
      if(config.joint.type==='prismatic'){
        assert(Object.values(object.body_displacements_mm).every(value=>value===config.states.open),'Seat and stem move together');
        assert(Math.abs(object.model_matrix[14]-(config.states.open-config.states.closed)/1000)<1e-7);
      }else assert(Object.values(object.body_angles_deg).every(value=>value===config.states.open),'Cabinet leaf and handle move together');
      await page.screenshot({path:path.join(output,config===labDoor?'browser-lab-door-open.png':'browser-stool-raised.png'),fullPage:true});
      state=await controls.activate(config.id,config.moving_body_ids,'space');object=state.objects.find(value=>value.id===config.id);
      assert.equal(object.state,'closed');assert.deepEqual(object.model_matrix,identityMatrix);
    }
    report.laboratory.public_articulations={door:labDoor.id,stool:stool.id,reference_matrices_restored:true};
    progress('laboratory door and stool passed');
    const fullTriangles=(await read()).stats.triangles;
    const beforeIsolation=(await controls.state()).frames;
    await page.locator('#walkthrough-isolate').click();
    await page.waitForFunction(fullTriangles=>{
      const viewer=window.__buildingWalkthrough;
      return viewer.isolated&&viewer.sceneStats&&viewer.sceneStats.triangles<fullTriangles;
    },fullTriangles,{timeout:120000});
    await controls.frameAfter(beforeIsolation);
    assert.equal((await read()).scene,'building');
    assert(cameraDistance((await read()).camera.eye_mm,labStop.eye_mm)<.01,'Isolation retains the building-frame lab camera');
    assert((await read()).stats.triangles<fullTriangles,'Isolation filters geometry from the same scene');
    const isolationIds=new Set(model.isolation.body_ids);
    assert(laboratory.furniture_body_ids.every(id=>isolationIds.has(id)));
    assert(nativeScene.groups.filter(group=>group.laboratory_id===laboratory.id).every(group=>isolationIds.has(group.id)));
    assert(!object.moving_body_ids.some(id=>isolationIds.has(id)),'Kitchen geometry is outside the lab filter');
    await page.screenshot({path:path.join(output,'browser-lab-isolated.png'),fullPage:true});
    await page.locator('#walkthrough-isolate').click();
    await page.waitForFunction(()=>!window.__buildingWalkthrough.isolated);
    assert.equal((await read()).scene,'building');report.laboratory.same_frame_isolation=true;
    progress('same-frame laboratory isolation passed');

    const lift=model.elevator,liftObject=model.objects.find(object=>object.id===lift.object_id);
    assert(lift&&liftObject&&liftObject.moving_body_ids.filter(id=>nativeById.get(id)?.role==='concept_existing_elevator_cabin').length===1,'Exactly one native cabin moves with its fittings');
    const port=(level,side=(['KG','EG'].includes(level)?'inward':'outward'))=>lift.ports.find(port=>port.level_id===level&&port.side===side&&port.active);
    const liftState=surface=>surface.evaluate(()=>window.__buildingWalkthrough.elevator);
    const cabinState=surface=>surface.evaluate(id=>window.__buildingWalkthrough.objects.find(object=>object.id===id),lift.object_id);
    async function checkExitButtons(surface,level){
      const shown=await surface.locator('[data-lift-exit]').evaluateAll(nodes=>nodes.map(node=>node.dataset.liftExit).sort());
      assert.deepEqual(shown,lift.ports.filter(port=>port.active&&port.level_id===level).map(port=>port.side).sort(),`${level}: only active source exits are offered`);
      return shown;
    }
    async function enter(surface,selectedPort){
      await surface.waitForFunction(()=>!window.__buildingWalkthrough.elevator.door_phase||window.__buildingWalkthrough.elevator.door_phase==='idle');
      await surface.locator(`[data-lift-enter="${selectedPort.id}"]`).click();
      const state=await liftState(surface);assert.equal(state.boarded,true);
      const eye=await surface.evaluate(()=>window.__buildingWalkthrough.camera.eye_mm);
      assert(cameraDistance(eye,state.attached_eye_mm)<1e-6,'Boarded camera follows the absolute cabin state');
    }
    async function exit(surface,selectedPort){
      await surface.waitForFunction(()=>!window.__buildingWalkthrough.elevator.door_phase||window.__buildingWalkthrough.elevator.door_phase==='idle');
      await surface.locator(`[data-lift-exit="${selectedPort.side}"]`).click();
      assert.equal((await liftState(surface)).boarded,false);
      const eye=await surface.evaluate(()=>window.__buildingWalkthrough.camera.eye_mm);
      assert(cameraDistance(eye,selectedPort.exit_eye_mm)<.01,'Exit uses the active source port');
    }
    const corridorGroup=nativeScene.groups.find(group=>group.id===laboratory.level_id+'__Area_C3_020');
    assert(corridorGroup,'Native corridor floor is needed to guide the approach to the lift');
    const corridorX=centre(corridorGroup.bounds_mm)[0],upperPort=port('OG3');assert(upperPort);
    async function approachLift(surface,driver,fromOffice=false){
      const corridorCorner=[corridorX,labOutside[1],upperPort.exit_eye_mm[2]];
      if(fromOffice){
        await surface.locator('#walkthrough-stops button[data-stop="phd"]').click();
        await driver.walkTo(phdOutside);
        const positions=Float32Array.from({length:nativePositions.length/4},(_,i)=>nativePositions.readFloatLE(i*4)/1000);
        const indices=Uint32Array.from({length:nativeIndices.length/4},(_,i)=>nativeIndices.readUInt32LE(i*4));
        const current=await driver.state();
        const doorState=current.objects.find(object=>object.id===nearDoor.id).state;
        const detour=detourOpenDoor({data:model,positions,indices,from:phdOutside,to:corridorCorner,doorId:nearDoor.id,state:doorState});
        assert(detour.evidence.length,'The office-to-lift route goes around the open B leaf');
        for(const point of detour.waypoints)await driver.walkTo(point);
        assert.equal((await driver.state()).objects.find(object=>object.id===nearDoor.id).state,doorState);
        report.elevator.office_approach_detour=detour.evidence;
      }else{
        await driver.walkTo(labOutside);
        await driver.walkTo(corridorCorner);
      }
      await driver.walkTo([corridorX,upperPort.exit_eye_mm[1],upperPort.exit_eye_mm[2]]);
      await driver.walkTo(upperPort.exit_eye_mm);
      return driver.activate(upperPort.id,upperPort.trigger_body_ids,'space');
    }
    await approachLift(page,controls);
    assert.equal((await liftState(page)).state,'OG3');assert.equal((await liftState(page)).boarded,false,'Calling does not board the passenger');
    const upperReferenceMatrix=(await cabinState(page)).model_matrix;
    await enter(page,upperPort);
    const panelTarget=lift.fittings.panel.center_mm.map((v,i)=>v+(i===2?liftObject.states.OG3-lift.reference_z_mm:0));
    await controls.lookAt(panelTarget);
    await page.screenshot({path:path.join(output,'browser-lift-controls.png'),fullPage:true});
    const opposite=lift.ports.find(p=>p.level_id==='OG3'&&p.side==='inward');
    await controls.lookAt([opposite.plane_x_mm,opposite.cabin_entry_mm[1],opposite.z_mm+1100]);
    await page.screenshot({path:path.join(output,'browser-lift-opposite-side.png'),fullPage:true});
    assert(await page.locator('#walkthrough-level').isDisabled());
    assert(await page.locator('#walkthrough-isolate').isDisabled());
    assert((await page.locator('#walkthrough-stops button').evaluateAll(nodes=>nodes.every(node=>node.disabled))));
    await page.locator('[data-lift-floor="EG"]').click();
    assert.equal((await liftState(page)).state,'EG');assert.deepEqual((await cabinState(page)).model_matrix,identityMatrix,'EG is the native cabin reference');
    const egSides=await checkExitButtons(page,'EG');await exit(page,port('EG'));
    await enter(page,port('EG'));await page.locator('[data-lift-floor="OG3"]').click();
    assert.equal((await liftState(page)).state,'OG3');
    assert.deepEqual((await cabinState(page)).model_matrix,upperReferenceMatrix,'Return to OG3 restores its translated cabin pose, not the EG identity');
    const ogSides=await checkExitButtons(page,'OG3');await exit(page,upperPort);
    await enter(page,upperPort);await page.locator('[data-lift-floor="KG"]').click();
    assert.equal((await liftState(page)).state,'KG');const kgSides=await checkExitButtons(page,'KG');
    await page.setViewportSize({width:390,height:844});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Lift controls fit the mobile viewport');
    await page.screenshot({path:path.join(output,'browser-lift-mobile.png'),fullPage:true});
    await exit(page,port('KG','inward'));
    await page.setViewportSize({width:1280,height:950});
    report.elevator={id:lift.object_id,native_cabin_count:1,cabin_attached_bodies:liftObject.moving_body_ids,
      reduced_motion:true,public_frame_call:true,public_boarding:true,eg_identity:true,og3_return_pose:true,
      active_exit_sides:{EG:egSides,OG3:ogSides,KG:kgSides},mobile_overlay:true};
    progress('reduced-motion elevator and exit policies passed');

    // A real timed ride checks the camera/cabin attachment between floors.
    const liftContext=await browser.newContext({viewport:{width:1280,height:950},reducedMotion:'no-preference'});
    try{
      const riding=await liftContext.newPage();riding.on('pageerror',error=>errors.push(error.message));
      await riding.goto(pathToFileURL(target).href,{waitUntil:'load',timeout:120000});
      await riding.waitForFunction(()=>window.__buildingWalkthrough?.ready,null,{timeout:120000});
      const driver=publicControls(riding);await approachLift(riding,driver,true);
      assert.equal((await liftState(riding)).boarded,false);
      await riding.locator('#walkthrough-canvas').focus();await riding.keyboard.press('Space');
      assert.equal((await driver.state()).lastInteraction.status,'rejected_busy','A repeated frame call during motion is rejected');
      const timeout=120000;
      await riding.waitForFunction(()=>window.__buildingWalkthrough.elevator.state==='OG3',null,{timeout});
      await enter(riding,upperPort);
      await riding.locator('[data-lift-floor="EG"]').click();
      await riding.waitForFunction(({lo,hi})=>{const value=window.__buildingWalkthrough.elevator.value_mm;return value>lo+100&&value<hi-100;},
        {lo:liftObject.states.EG,hi:liftObject.states.OG3},{timeout,polling:'raf'});
      const between=await driver.state();
      assert(cameraDistance(between.camera.eye_mm,between.elevator.attached_eye_mm)<1e-6,'The camera is attached in an intermediate rendered frame');
      assert.equal(between.elevator.boarded,true);assert.equal(between.elevator.state,'moving');
      const cabin=between.objects.find(object=>object.id===lift.object_id);
      assert(Math.abs(cabin.model_matrix[14]*1000-(between.elevator.value_mm-between.elevator.reference_value_mm))<.01,'Only the cabin translation follows the shared joint value');
      await riding.locator('[data-lift-floor="OG3"]').click();
      assert.equal((await liftState(riding)).last_command.status,'rejected_busy');
      assert.equal((await liftState(riding)).target_state,'EG');
      await riding.locator('#walkthrough-canvas').focus();await riding.keyboard.down('e');
      try{await riding.waitForTimeout(150);}finally{await riding.keyboard.up('e');}
      const during=(await driver.state());assert(cameraDistance(during.camera.eye_mm,during.elevator.attached_eye_mm)<1e-6,'Q/E cannot detach a passenger during travel');
      await riding.screenshot({path:path.join(output,'browser-lift-travelling.png'),fullPage:true});
      await riding.waitForFunction(()=>window.__buildingWalkthrough.elevator.state==='EG',null,{timeout});
      assert.deepEqual((await cabinState(riding)).model_matrix,identityMatrix);
      await checkExitButtons(riding,'EG');await exit(riding,port('EG'));
      await enter(riding,port('EG'));await riding.locator('[data-lift-floor="OG3"]').click();
      await riding.waitForFunction(()=>window.__buildingWalkthrough.elevator.state==='OG3',null,{timeout});
      assert.deepEqual((await cabinState(riding)).model_matrix,upperReferenceMatrix);
      await checkExitButtons(riding,'OG3');await exit(riding,upperPort);
      report.elevator.animated_round_trip=true;report.elevator.busy_rejected=true;
      report.elevator.intermediate_attachment={camera_mm:between.camera.eye_mm,attached_eye_mm:between.elevator.attached_eye_mm,cabin_value_mm:between.elevator.value_mm};
      progress('animated elevator round trip passed');
    }finally{await liftContext.close();}
    assert.deepEqual(errors,[],'Laboratory and elevator controls produce no browser errors');
    report.interactions.push('walk 3.002 through corridor into equipped 3.003','recipe cabinet door','prismatic stool lift',
      'same-frame lab isolation','native lift frame call','lift boarding and active exits','animated OG3–EG–OG3 ride');

    const microwave = model.objects.find(v=>v.id==='Kitchen1008.Microwave.Door');
    assert(microwave,'The microwave has a source-defined door');
    const fridgeBefore = await objectState();
    await rendered(()=>page.evaluate(id=>window.__buildingWalkthrough.viewObject(id),microwave.id));
    const microwaveState=()=>page.evaluate(id=>window.__buildingWalkthrough.objects.find(v=>v.id===id),microwave.id);
    const windowGroup=scene.groups.find(v=>v.id==='Kitchen1008_Microwave_Window');
    assert(windowGroup&&microwave.moving_body_ids.includes(windowGroup.id),'The native microwave window belongs to its moving door');
    const windowCentre=windowGroup.bounds_mm.min.map((v,i)=>(v+windowGroup.bounds_mm.max[i])/2);
    for(const expected of ['open','closed']) {
      const screen=await page.evaluate(({id,point})=>{
        const v=window.__buildingWalkthrough,o=v.objects.find(v=>v.id===id),m=o.model_matrix,p=point.map(x=>x/1000);
        const world=[0,1,2].map(r=>(m[r]*p[0]+m[4+r]*p[1]+m[8+r]*p[2]+m[12+r])*1000);
        const pixel=v.projectPoint(world),c=document.querySelector('canvas'),rect=c.getBoundingClientRect();
        return {x:rect.left+pixel.x/c.width*rect.width,y:rect.top+pixel.y/c.height*rect.height,visible:pixel.visible};
      },{id:microwave.id,point:windowCentre});
      assert(screen.visible,'The transformed native microwave window is visible before clicking');
      await page.mouse.click(screen.x,screen.y);
      await page.waitForFunction(id=>{const viewer=window.__buildingWalkthrough;return viewer.lastInteraction?.id===id
        &&viewer.lastInteraction.input==='click'&&viewer.frames>viewer.lastInteraction.frame;},microwave.id,{timeout:120000});
      assert.equal((await page.evaluate(()=>window.__buildingWalkthrough.lastInteraction)).status,'accepted');
      assert.equal((await microwaveState()).state,expected,'Microwave native window responds to mouse');
      assert(Object.values((await microwaveState()).body_angles_deg).every(a=>a===(expected==='open'?90:0)));
      await page.screenshot({path:path.join(output,`browser-microwave-${expected}.png`),fullPage:true});
    }
    await page.locator('#walkthrough-canvas').focus();
    for(const expected of ['open','closed']) {
      await page.keyboard.press('Space');
      await page.waitForFunction(id=>{const viewer=window.__buildingWalkthrough;return viewer.lastInteraction?.id===id
        &&viewer.lastInteraction.input==='space'&&viewer.frames>viewer.lastInteraction.frame;},microwave.id,{timeout:120000});
      assert.equal((await page.evaluate(()=>window.__buildingWalkthrough.lastInteraction)).status,'accepted');
      assert.equal((await microwaveState()).state,expected,'Space toggles the microwave at its opening');
    }
    assert.deepEqual(await objectState(),fridgeBefore,'Microwave commands leave the refrigerator unchanged');
    report.microwave={mouse_open_close:true,space_open_close:true,moving_body_ids:microwave.moving_body_ids};
    report.interactions.push('latest-master microwave mouse and Space open/close','pinned office computer and social articulation coverage');

    progress('latest-master microwave regression passed');

    // A corrupt source must produce a useful visible error rather than an empty canvas.
    const defaultStop = model.stops.find(stop => stop.id === (model.default_stop_id || model.default_stop)) || model.stops[0];
    const broken = {stops: [defaultStop], levels: model.levels, settings: model.settings,
      scenes: {[defaultStop.scene]: {...model.scenes[defaultStop.scene], index_count: model.scenes[defaultStop.scene].index_count + 3}}};
    await page.goto('about:blank');
    await page.setContent(html.replace(inline[0], `<script id="walkthrough-data" type="application/json">${JSON.stringify(broken).replace(/</g, '\\u003c')}</script>`),
      {waitUntil: 'load', timeout: 120000});
    await page.waitForSelector('#walkthrough-error:not([hidden])');
    assert.match(await page.locator('#walkthrough-error').textContent(), /could not be displayed/);
    report.interactions.push('visible malformed-scene error');
    report.passed = true;
    fs.writeFileSync(path.join(output, 'browser-check.json'), JSON.stringify(report, null, 2) + '\n');
    console.log(JSON.stringify(report, null, 2));
  } catch(error) {
    const failures=[];
    for(const [index,surface] of browser.contexts().flatMap(context=>context.pages()).entries()){
      const screenshot=`browser-failure-${index}.png`;
      try{
        await surface.screenshot({path:path.join(output,screenshot),fullPage:true,timeout:15000});
        const state=await surface.evaluate(()=>{
          const v=window.__buildingWalkthrough;
          return v?{camera:v.camera,scene:v.sceneId,stop:v.stopId,frames:v.frames,target:v.interactionTarget,
            lastInteraction:v.lastInteraction,elevator:v.elevator,isolated:v.isolated}:null;
        });
        failures.push({screenshot,state});
      }catch(captureError){failures.push({screenshot,capture_error:String(captureError)});}
    }
    fs.writeFileSync(path.join(output,'browser-failure.json'),JSON.stringify({passed:false,error:String(error),failures},null,2)+'\n');
    throw error;
  } finally {await browser.close();}
})().catch(error => {console.error(error); process.exitCode = 1;});
