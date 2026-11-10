// Source-current Python/Node/browser comparison of the smooth multi-tube view.
const fs=require('node:fs'),path=require('node:path'),zlib=require('node:zlib');
const assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const {pathToFileURL}=require('node:url');
const target=path.resolve(process.argv[2]),modulePath=process.argv[3]||'playwright';
const chrome=process.argv[4],programPath=path.resolve(process.argv[5]);
const html=fs.readFileSync(target,'utf8');
const packed=html.match(/<script type="application\/json" data-mesh>([^<]+)<\/script>/);
const mesh=JSON.parse(zlib.gunzipSync(Buffer.from(packed[1],'base64'))),program=mesh.unload_program;
assert(program&&program.transfers.length===3);
const {preview_samples,...embeddedProgram}=program;
assert.deepEqual(embeddedProgram,JSON.parse(fs.readFileSync(programPath,'utf8')),'Browser payload differs from the checked program');
const reference=JSON.parse(execFileSync(process.env.SOLIDCRAFTBOT_PYTHON||'python3',['-c',String.raw`
import json,sys
from pathlib import Path
sys.path.insert(0,'scripts')
import cf01_unload_motion as m
p=json.loads(Path(sys.argv[1]).read_text());ev=m.ProgramEvaluator(p);scene=m.SceneEvaluator(p['scene'],p)
times={0.,p['duration_s'],*[p['duration_s']*i/29 for i in range(30)]}
for x in p['transfers']:
 assert x['gripped_s']<x['removed_confirmed_s']<x['clear_s']<x['seated_s']<=x['support_s']
 for key in ['docked_s','presented_s','gripped_s','extracted_s','removed_confirmed_s','clear_s','seated_s','support_s','released_s']:
  times.update([max(0,x[key]-1e-7),x[key],min(p['duration_s'],x[key]+1e-7)])
 for fraction in [.25,.5,.75]:
  times.add(x['gripped_s']+(x['seated_s']-x['gripped_s'])*fraction)
checks=[]
for t in sorted(times):
 s=ev(t);matrices=scene(s)
 checks.append({'time_s':t,'owners':s['owners'],'active_sample_id':s['active_sample_id'],'joints_deg':s['joints_deg'],
  'joint_velocities_rad_s':s['joint_state']['velocities_rad_s'],'station':s['station'],
  'matrices':{key:{'r':[v[i][j] for i in range(3) for j in range(3)],'p':[v[i][3] for i in range(3)]} for key,v in matrices.items() if key.startswith('Tube') or key in ['Tool','RotorGroup']}})
print(json.dumps({'checks':checks}))
`,programPath],{cwd:path.resolve(__dirname,'..'),encoding:'utf8',maxBuffer:5_000_000}));
function close(a,b,tolerance=2e-7){assert(Number.isFinite(a)&&Math.abs(a-b)<=tolerance,`${a} != ${b}`);}
(async()=>{
 const {chromium}=require(modulePath),browser=await chromium.launch({headless:true,...(chrome?{executablePath:chrome}:{})});
 try{
  const page=await browser.newPage({viewport:{width:1000,height:900},reducedMotion:'reduce'}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
  await page.goto(pathToFileURL(target).href);await page.waitForSelector('[data-current-time]');
  const root=page.locator('#cf01-bench-rack');
  close(Number(await page.locator('[data-time-slider]').getAttribute('max')),program.duration_s);
  assert(await page.locator('[data-batch-panel]').isHidden());
  for(const expected of reference.checks){
   const actual=await root.evaluate((el,t)=>el.motionProbe(t),expected.time_s);
   assert.deepEqual(actual.frame.owners,expected.owners);
   assert.equal(actual.frame.active_sample_id,expected.active_sample_id);
   actual.frame.joints_deg.forEach((v,i)=>close(v,expected.joints_deg[i]));
   assert.equal(actual.frame.joint_state.v.length,expected.joint_velocities_rad_s.length);
   actual.frame.joint_state.v.forEach((v,i)=>close(v,expected.joint_velocities_rad_s[i]));
   for(const [key,value]of Object.entries(expected.station))close(actual.frame.values[key],value);
   for(const [key,value]of Object.entries(expected.matrices)){
    actual.matrices[key].r.forEach((v,i)=>close(v,value.r[i]));
    actual.matrices[key].p.forEach((v,i)=>close(v,value.p[i]));
   }
  }
  const liftChecks=[];
  for(const transfer of program.transfers){
   const sample=program.samples.find(x=>x.id===transfer.sample_id),local=mesh.tube_grip_references[sample.tube_body];
   const before=await root.evaluate((el,t)=>el.motionProbe(t),transfer.docked_s);
   const after=await root.evaluate((el,t)=>el.motionProbe(t),transfer.presented_s);
   function transform(m){return m.p.map((x,i)=>x+m.r.slice(i*3,i*3+3).reduce((s,v,j)=>s+v*local[j],0));}
   const a=transform(before.matrices[sample.tube_body]),b=transform(after.matrices[sample.tube_body]);
   const distance=Math.hypot(...b.map((v,i)=>v-a[i]));close(distance,16);close(b[2]-a[2],16*mesh.pickup_axis[2]);
   liftChecks.push({sample_id:sample.id,axial_lift_mm:distance,vertical_lift_mm:b[2]-a[2]});
   for(const time of [transfer.gripped_s,transfer.support_s]){
    await page.locator('[data-time-slider]').evaluate((s,t)=>{s.value=t;s.dispatchEvent(new Event('input',{bubbles:true}));},time);
    assert.equal(JSON.parse(await root.getAttribute('data-sample-owners'))[sample.id],time===transfer.gripped_s?'gripper':'rack');
   }
  }
  const second=program.transfers[1];await page.locator('[data-view]').selectOption('tube');
  for(const [label,time]of [['before',second.docked_s],['raised',second.presented_s+.1]]){
   await page.locator('[data-time-slider]').evaluate((s,t)=>{s.value=t;s.dispatchEvent(new Event('input',{bubbles:true}));},time);
   await root.screenshot({path:path.join(path.dirname(target),'lift-sample02-'+label+'.png')});
  }
  for(const language of ['de','en']){
   await page.locator('[data-language]').selectOption(language);
   assert.match(await page.locator('[data-i18n="motion_description"]').textContent(),language==='en'?/consecutive unloads/:/aufeinanderfolgende Entnahmen/);
   for(const width of [320,600,1000]){await page.setViewportSize({width,height:900});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));}
  }
  await page.setViewportSize({width:1000,height:900});await page.locator('[data-view]').selectOption('assembly');
  await page.locator('[data-time-slider]').evaluate((s,t)=>{s.value=t;s.dispatchEvent(new Event('input',{bubbles:true}));},program.duration_s);
  await root.screenshot({path:path.join(path.dirname(target),'three-samples-final.png')});
  const owners=JSON.parse(await root.getAttribute('data-sample-owners'));
  assert.equal(Object.values(owners).filter(x=>x==='rack').length,3);assert.equal(Object.values(owners).filter(x=>x==='rotor').length,9);
  assert.deepEqual(errors,[]);
  const report={passed:true,python_browser_transform_checks:reference.checks.length,
   python_browser_joint_velocity_checks:reference.checks.length,loaded_interior_times_per_transfer:3,
   sample_count:12,rack_count:3,rotor_count:9,lift_checks:liftChecks,languages:['de','en'],widths:[320,600,1000],console_errors:errors};
  fs.writeFileSync(path.join(path.dirname(target),'browser-validation.json'),JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify(report));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
