// Set SOLIDCRAFTBOT_PLAYWRIGHT and SOLIDCRAFTBOT_CHROME for the browser checks.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {spawnSync}=require('node:child_process');
const {worldFrame,projection}=require('../scripts/templates/robot_camera_views.js');
const identity={r:[1,0,0,0,1,0,0,0,1],p:[0,0,0]};
const fixture={id:'camera',group:'mount',optical_frame:{...identity,p:[2,0,1]},cone_range_mm:10,cone_far_radius_mm:5};
assert.deepEqual(worldFrame(fixture,{r:[0,-1,0,1,0,0,0,0,1],p:[10,20,30]}).p,[10,22,31]);
const p=projection(fixture,2),z=10,x=5*2/Math.sqrt(5),y=5/Math.sqrt(5);
assert(Math.abs(p[0]*x/z-1)<1e-7); // right corner of the inscribed rectangle
assert(Math.abs(p[5]*y/z+1)<1e-7); // optical +Y goes down in the image
assert(p[11]===1); // positive optical depth, not an OpenGL -Z camera
console.log('PASS: camera mounting and optical projection convention');

async function browserChecks(){
  if(!process.env.SOLIDCRAFTBOT_PLAYWRIGHT){console.log('SKIP: browser camera checks (set SOLIDCRAFTBOT_PLAYWRIGHT)');return;}
  const expected=spawnSync('python3',['-c',`
import json,sys
sys.path.insert(0,'scripts')
import build_cf01_camera_demo as d
import robot_spec as r
from cf01_unload_motion import ProgramEvaluator
m=d.read_mesh(d.DEFAULT)
s=r.load('model/robot.json',m['scene'].get('robot_parameter_overrides_mm'))
evaluate=ProgramEvaluator(m['unload_program']); out=[]
times={0.,5.,25.,31.9,50.,85.,m['unload_program']['duration_s']}
for transfer in m['unload_program']['transfers']:
 for key in ['gripped_s','support_s']:
  times.update([transfer[key]-.001,transfer[key],transfer[key]+.001])
for t in sorted(times):
 state=evaluate(t); frames=r.forward(s,state['joints_deg']); cameras={}
 for c in d.camera_metadata(m):
  f=c['optical_frame']; optical=[f['r'][i*3:i*3+3]+[f['p'][i]] for i in range(3)]+[[0,0,0,1]]
  cameras[c['id']]=r.multiply(r.multiply(m['arm_base'],frames[c['mounted_link']]),optical)
 out.append({'time':t,'cameras':cameras,'owners':state['owners']})
print(json.dumps(out))
`],{cwd:path.resolve(__dirname,'..'),encoding:'utf8'});
  assert.equal(expected.status,0,expected.stderr);
  const references=JSON.parse(expected.stdout),{chromium}=require(process.env.SOLIDCRAFTBOT_PLAYWRIGHT);
  const browser=await chromium.launch({headless:true,executablePath:process.env.SOLIDCRAFTBOT_CHROME,
    args:['--use-gl=angle','--use-angle='+(process.env.SOLIDCRAFTBOT_ANGLE||'swiftshader'),'--enable-unsafe-swiftshader']});
  try{
    const page=await browser.newPage({viewport:{width:960,height:1000},deviceScaleFactor:1,reducedMotion:'reduce'}),errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    await page.goto(require('node:url').pathToFileURL(path.resolve('docs/media/robot-demo-cameras-aligned.html')).href);
    await page.waitForSelector('[data-camera-time]');
    for(const expected of references){
      const actual=await page.evaluate(t=>{
        const root=document.querySelector('#cf01-bench-rack'),slider=root.querySelector('[data-time-slider]');
        slider.value=t;slider.dispatchEvent(new Event('input'));
        return {time:Number(root.dataset.cameraTime),cameras:JSON.parse(root.dataset.cameraFrames),owners:JSON.parse(root.dataset.sampleOwners),tcp:root.motionProbe(t).matrices.Tool.p};
      },expected.time);
      assert(Math.abs(actual.time-expected.time)<1e-9);assert.deepEqual(actual.owners,expected.owners);
      for(const [id,matrix] of Object.entries(expected.cameras)){
        const frame=actual.cameras[id];
        for(let i=0;i<3;i++){
          assert(Math.abs(frame.p[i]-matrix[i][3])<1e-8,`${id} origin at ${expected.time}`);
          for(let j=0;j<3;j++)assert(Math.abs(frame.r[i*3+j]-matrix[i][j])<1e-8,`${id} optical axes`);
        }
      }
      const tip=actual.cameras.C_tip,delta=actual.tcp.map((x,i)=>x-tip.p[i]);
      const optical=[0,1,2].map(j=>delta.reduce((s,x,i)=>s+x*tip.r[i*3+j],0));
      assert(optical[2]>0&&Math.hypot(optical[0],optical[1])<1e-8,'Gripper TCP must lie on the camera optical axis');
      assert(actual.cameras.C_scene.r[7]<-.8,'Overview must remain upright');
    }
    const html=fs.readFileSync('docs/media/robot-demo-cameras-aligned.html','utf8');
    const mesh=JSON.parse(require('node:zlib').gunzipSync(Buffer.from(html.match(/data-mesh>([^<]+)<\/script>/)[1],'base64')));
    const visibility=await page.evaluate(mesh=>{
      const root=document.querySelector('#cf01-bench-rack'),renderer=RobotCameraViews.create(mesh);
      const camera=mesh.camera_views.find(c=>c.id==='C_tip'),overview=mesh.camera_views.find(c=>c.id==='C_scene'),report=[];
      const countPixels=()=>{
        const gl=renderer.canvas.getContext('webgl'),pixels=new Uint8Array(320*180*4),counts=[0,0,0];
        gl.readPixels(0,0,320,180,gl.RGBA,gl.UNSIGNED_BYTE,pixels);
        for(let i=0;i<pixels.length;i+=4)for(let c=0;c<3;c++)if(pixels[i+c]>64&&pixels[i+(c+1)%3]<8&&pixels[i+(c+2)%3]<8)counts[c]++;
        return counts;
      };
      for(const transfer of mesh.unload_program.transfers){
        const tube=mesh.unload_program.samples.find(s=>s.id===transfer.sample_id).tube_body;
        for(const [stage,time] of [['grasp',transfer.gripped_s+.01],['transfer',(transfer.gripped_s+transfer.support_s)/2],['rack_arrival',transfer.support_s-.01]]){
          const state=root.motionProbe(time),matrices=new Map(Object.entries(state.matrices));
          renderer.render(camera,matrices,320,180,b=>b.id==='LeftFingerPad'?[255,0,0]:b.id==='RightFingerPad'?[0,255,0]:b.id===tube?[0,0,255]:[0,0,0]);
          const counts=countPixels();
          renderer.render(overview,matrices,320,180,b=>b.asset==='station'?[255,0,0]:b.asset==='bench'?[0,255,0]:b.asset==='rack'?[0,0,255]:[0,0,0]);
          const wide=countPixels();
          report.push({sample_id:transfer.sample_id,stage,time_s:time,left_finger_pixels:counts[0],right_finger_pixels:counts[1],tube_pixels:counts[2],
            overview_station_pixels:wide[0],overview_bench_pixels:wide[1],overview_rack_pixels:wide[2]});
        }
      }
      return report;
    },mesh);
    for(const sample of visibility)for(const key of ['left_finger_pixels','right_finger_pixels','tube_pixels'])
      assert(sample[key]>8,`${key} must be visible at ${sample.time_s}, ${sample.sample_id}: ${sample[key]}`);
    for(const sample of visibility){
      assert(sample.overview_bench_pixels>8,'Workspace must be visible');
      if(sample.stage==='grasp')assert(sample.overview_station_pixels>8,'CF01 must be visible during pickup');
      if(sample.stage==='rack_arrival')assert(sample.overview_rack_pixels>8,'Rack must be visible on arrival');
    }
    const occlusion=await page.evaluate(()=>{
      const I={r:[1,0,0,0,1,0,0,0,1],p:[0,0,0]},camera={group:'mount',optical_frame:I,cone_range_mm:10,cone_far_radius_mm:5};
      const triangle=(z,color)=>({group:'scene',v:[[-2,-2,z],[2,-2,z],[0,2,z]],f:[[0,1,2]],color});
      // Draw the far blue face last: the near red face must still occlude it.
      const renderer=RobotCameraViews.create({bodies:[triangle(2,[240,0,0]),triangle(4,[0,0,240])]});
      renderer.render(camera,new Map(),64,64,b=>b.color);
      const gl=renderer.canvas.getContext('webgl'),pixel=new Uint8Array(4);gl.readPixels(32,32,1,1,gl.RGBA,gl.UNSIGNED_BYTE,pixel);
      return Array.from(pixel);
    });
    assert(occlusion[0]>100&&occlusion[2]===0,'Near surface must occlude the later far surface');
    const captures=[];fs.mkdirSync('tmp/camera-demo',{recursive:true});
    for(const width of [390,960])for(const language of ['de','en']){
      await page.setViewportSize({width,height:1100});
      await page.selectOption('[data-language]',language);
      const layout=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,text:document.querySelector('[data-phase]').textContent}));
      assert(layout.scroll<=layout.width,'Horizontal overflow');
      const file=`tmp/camera-demo/checked-${width}-${language}.png`;
      await page.locator('[data-scene]').screenshot({path:file});captures.push(file);
    }
    assert.deepEqual(errors,[]);
    const digest=file=>require('node:crypto').createHash('sha256').update(fs.readFileSync(file)).digest('hex');
    const report={passed:true,html_sha256:digest('docs/media/robot-demo-cameras-aligned.html'),test_sha256:digest(__filename),
      angle:process.env.SOLIDCRAFTBOT_ANGLE||'swiftshader',independent_fk_times:references.map(x=>x.time),camera_count:2,
      gripper_visibility:visibility,visibility_scope:'Sampled pixels with opaque occlusion; overview may exclude the rack during CF01 pickup. No all-around hazard coverage.',
      near_surface_occlusion_pixel:occlusion,captures,errors};
    fs.writeFileSync('tmp/camera-demo/browser-validation.json',JSON.stringify(report,null,2)+'\n');
    console.log(`PASS: ${references.length} Python/JS FK and TCP checks, ${visibility.length} finger/tube visibility poses, depth occlusion, DE/EN, desktop/mobile`);
  }finally{await browser.close();}
}
browserChecks().catch(e=>{console.error(e);process.exitCode=1;});
