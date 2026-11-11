const assert=require('node:assert/strict');
const {assertStateOwnership}=require('../scripts/export_readme_video.cjs');
const source={multiSample:true,sampleIds:['one','two','three','waiting'],transfers:[
  {sample_id:'one',gripped_s:1,support_s:2},{sample_id:'two',gripped_s:3,support_s:4},
  {sample_id:'three',gripped_s:5,support_s:6}]};
for(const time of [0,1,2,3,4,5,6,7]){
  const owners=Object.fromEntries(source.sampleIds.map(id=>{
    const transfer=source.transfers.find(x=>x.sample_id===id);
    return [id,transfer&&time>=transfer.support_s?'rack':transfer&&time>=transfer.gripped_s?'gripper':'rotor'];
  }));
  const state={sourceTimeS:time,sampleOwners:JSON.stringify(owners)};
  assertStateOwnership(state,source);
  assert.throws(()=>assertStateOwnership({...state,sampleOwners:JSON.stringify({...owners,waiting:'rack'})},source));
}
for(const [time,tubeOwner]of [[0,'station'],[1,'gripper'],[2,'rack']])
  assertStateOwnership({sourceTimeS:time,tubeOwner},{attachment:1,handoff:2});
console.log('PASS: all sample identities and legacy single-tube recording states');

const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const {options,scheduleFrames,encodePngFrames}=require('../scripts/export_readme_video.cjs');

async function checkCfr(){
  const defaults=options([],{});
  assert.equal(defaults.input,'docs/media/robot-demo-continuous-cfr.html');
  assert.equal(defaults.outputBase,'docs/media/robot-demo-continuous-cfr');
  assert.equal(defaults.recordSeconds,45);assert.equal(defaults.fps,20);
  const configured=options(['legacy-playwright','legacy-chrome','--input','old.html','--output-base','new',
    '--ffmpeg','/a path/ffmpeg','--fps=24','--record-seconds','3'],{});
  assert.equal(configured.playwright,'legacy-playwright');assert.equal(configured.chrome,'legacy-chrome');
  assert.equal(configured.ffmpeg,'/a path/ffmpeg');assert.equal(configured.fps,24);
  for(const argv of [['--fps','0'],['--fps','121'],['--fps','2.5'],['--record-seconds','0'],
    ['--record-seconds','0.001'],['--record-seconds','3601'],['--output-base','bad.mp4'],['--ffmpeg']])assert.throws(()=>options(argv,{}));
  const duration=80.7591568724187,schedule=scheduleFrames(duration);
  assert.equal(schedule.length,900);assert.deepEqual(schedule,scheduleFrames(duration));
  assert.deepEqual(schedule[0],{index:0,pts_s:0,source_time_s:0});
  assert.deepEqual(schedule.at(-1),{index:899,pts_s:44.95,source_time_s:duration});
  for(let i=1;i<schedule.length;i++){
    assert(Math.abs(schedule[i].pts_s-schedule[i-1].pts_s-.05)<1e-12);
    assert(schedule[i].source_time_s>schedule[i-1].source_time_s);
    assert.equal(schedule[i].source_time_s,i/899*duration);
  }
  for(const args of [[0],[Infinity],[NaN],[-1],[1,45,1.5],[1,.001,20],[1,3600,120]])assert.throws(()=>scheduleFrames(...args));
  const folder=fs.mkdtempSync(path.join(os.tmpdir(),'readme-cfr-tests-'));
  const executable=path.join(folder,'fake encoder with spaces'),output=path.join(folder,'output.mp4');
  // Fake processes test pipe/atomicity semantics, without requiring ffmpeg or a browser.
  const fake=body=>{fs.writeFileSync(executable,'#!'+process.execPath+'\n'+body+'\n');fs.chmodSync(executable,0o755);};
  const png=Buffer.concat([Buffer.from('89504e470d0a1a0a','hex'),Buffer.alloc(64)]);
  const short=scheduleFrames(2,.1,20),parameters={ffmpeg:executable,output,fps:20,schedule:short,frame:async()=>png};
  try{
    fs.writeFileSync(output,'previous video');
    fake('process.stderr.write("x".repeat(100000)); process.exit(7);');
    await assert.rejects(encodePngFrames(parameters));
    assert.equal(fs.readFileSync(output,'utf8'),'previous video');
    assert(!fs.readdirSync(folder).some(name=>name.startsWith('.readme-video-')));
    fake('process.stdin.resume(); process.stdin.on("end",()=>require("node:fs").writeFileSync(process.argv.at(-1),Buffer.from("000000186674797069736f6d0000000069736f6d6d703432", "hex")));');
    await assert.rejects(encodePngFrames({...parameters,beforePublish:async()=>{throw new Error('Browser validation failed');}}),/Browser validation/);
    assert.equal(fs.readFileSync(output,'utf8'),'previous video');
    await assert.rejects(encodePngFrames({...parameters,frame:async()=>Buffer.from('not a PNG')}),/PNG/);
    await assert.rejects(encodePngFrames({...parameters,schedule:[{...short[0],pts_s:.1},short[1]]}),/Canonical/);
    await assert.rejects(encodePngFrames({...parameters,ffmpeg:path.join(folder,'missing encoder')}));
    const seen=[];
    const result=await encodePngFrames({...parameters,frame:async point=>{seen.push(point);return png;}});
    assert.deepEqual(seen,short);assert.equal(result.fps_mode,'cfr');assert.equal(result.codec,'libx264');
    assert.equal(result.frames,2);assert.equal(result.duration_s,.1);
    assert.equal(fs.readFileSync(output).toString('ascii',4,8),'ftyp');
    assert(!fs.readdirSync(folder).some(name=>name.startsWith('.readme-video-')));
  }finally{fs.rmSync(folder,{recursive:true,force:true});}
  console.log('PASS: deterministic CFR schedule, option guards, streaming encoder failures and atomic publication');
}
checkCfr().catch(error=>{console.error(error);process.exitCode=1;});
