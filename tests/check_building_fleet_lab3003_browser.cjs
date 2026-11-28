// Usage: node tests/check_building_fleet_lab3003_browser.cjs <walkthrough URL> <playwright> <chrome> [report.json]
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require(process.argv[3] || 'playwright');
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:process.argv[4],
    args:['--enable-webgl','--ignore-gpu-blocklist','--use-gl=angle','--use-angle=metal']});
  try{
    const page=await browser.newPage({viewport:{width:1440,height:1000}});
    await page.clock.install();
    const errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    page.on('console',e=>{if(e.type()==='error')errors.push(e.text());});
    const collect=()=>page.evaluate(()=>{
      const view=window.__buildingWalkthrough, fleet=window.__buildingFleet, snap=fleet?.snapshot;
      const station=view?.lab3003CF01, lap=view?.tr01Lap;
      return {ready:view?.ready===true,renderer:view?.renderer,station,lap,model:snap?.model_time_s,display:fleet?.display_time_s,
        states:snap?.states.map(row=>({id:row.id,pose:row.pose_xyz_mm,goal:row.own_route_horizon_mm,phase:row.mode})),
        reserved:snap?.lab3003_reserved,release:document.getElementById('building-walkthrough')?.dataset.lab3003Release,host:snap?.execution_host,fallback:snap?.recording_fallback,
        command_errors:snap?.command_errors,frames:view?.frames,stop:view?.stopId,drawn:fleet?.renderer_stats.last_instance_count,
        error:document.getElementById('walkthrough-error')?.textContent,wall:performance.now()/1000};
    });
    await page.goto(process.argv[2],{timeout:120000});
    await page.waitForFunction(()=>window.__buildingWalkthrough?.ready||document.querySelector('#walkthrough-error:not([hidden])'),null,{timeout:110000});
    const first=await collect();
    assert(first.ready, first.error);
    assert.equal(first.renderer,'webgl2'); assert.equal(first.stop,'camera-wall');
    await page.locator('button[data-stop="cf01-zyklus"]').click();
    await page.waitForFunction(()=>window.__buildingWalkthrough?.stopId==='cf01-zyklus'&&
       window.__buildingFleet?.snapshot?.states?.some(row=>row.progress_mm>1)&&
       window.__buildingWalkthrough?.lab3003CF01?.arm_joints_deg?.length===6,null,{timeout:100000});
    const changed=(a,b)=>a&&b&&a.some((x,i)=>Math.abs(x-b[i])>1e-5);
    const moving=(a,b)=>a.states&&b.states&&a.states.some((v,i)=>changed(v.pose,b.states[i].pose));
    let last=await collect(), overlap, lapOverlap;
    for(let i=0;i<180;i++){
      await page.waitForTimeout(1100);
      const current=await collect();
      if(!overlap&&changed(last.station?.arm_joints_deg,current.station?.arm_joints_deg)&&moving(last,current)){
        assert.equal(current.host,'browser_wasm_worker');
        assert.equal(current.fallback,false); assert.equal(current.drawn,6); assert.equal(current.reserved,true);
        assert(current.frames>last.frames&&current.model>last.model);
        overlap=[last,current]; console.log('ArmC and fleet moved in the same rendered interval',last.wall,current.wall);
      }
      if(overlap&&current.lap?.state==='playing'&&changed(last.lap?.pose_mm_rad,current.lap?.pose_mm_rad)&&moving(last,current)){
        assert.equal(current.reserved,true);assert(current.frames>last.frames&&current.model>last.model);
        lapOverlap=[last,current]; console.log('TR01 and fleet moved in the same rendered interval',last.wall,current.wall);
        break;
      }
      if(errors.length)throw Error(errors.join('\n'));
      last=current;
    }
    assert(overlap&&lapOverlap,'Need simultaneous simulated movement in the ArmC and TR01 stages');
    // Test the remainder of the certified lab sequence without waiting for its entire presentation time.
    const finishing=await collect();
    const rate=finishing.lap.playback_rate;
    await page.clock.fastForward(Math.ceil((finishing.lap.duration_s-finishing.lap.time_s)*1000/rate)+1000);
    const docked=await collect();
    assert.equal(docked.lap.state,'docked',JSON.stringify({lap:docked.lap,error:docked.error}));
    await page.waitForFunction(()=>window.__buildingWalkthrough?.tr01Lap?.state==='docked'&&
        window.__buildingFleet?.snapshot?.lab3003_reserved===false&&
        document.getElementById('building-walkthrough')?.dataset.lab3003Release==='confirmed',null,{timeout:40000});
    const end=await collect();
    assert.equal(end.lap.state,'docked'); assert.equal(end.reserved,false); assert.equal(end.release,'confirmed');
    assert.equal(end.station.returned.length,2);
    assert.deepEqual(errors,[]);assert.deepEqual(end.command_errors??[],[]);
    if(process.argv[5])fs.writeFileSync(process.argv[5],JSON.stringify({passed:true,start:first,overlap,lapOverlap,end},null,2)+'\n',{flag:'wx'});
    console.log('Bay reservation released after confirmed laboratory lap and returned tubes',end.model,end.lap.pose_mm_rad);
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
