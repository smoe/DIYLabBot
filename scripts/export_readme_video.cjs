// Run from the repository root. Legacy positional Playwright/Chrome arguments remain supported.
const fs = require('node:fs');
const path = require('node:path');
const zlib = require('node:zlib');
const {pathToFileURL} = require('node:url');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const {spawn} = require('node:child_process');

function options(argv, env = process.env) {
  const result = {input: 'docs/media/robot-demo-continuous-cfr.html', outputBase: 'docs/media/robot-demo-continuous-cfr',
    playwright: env.SOLIDCRAFTBOT_PLAYWRIGHT || 'playwright', chrome: env.SOLIDCRAFTBOT_CHROME,
    ffmpeg: env.SOLIDCRAFTBOT_FFMPEG || 'ffmpeg', fps: env.SOLIDCRAFTBOT_VIDEO_FPS || 20,
    recordSeconds: env.SOLIDCRAFTBOT_VIDEO_DURATION_S || 45,
    screenshotTime: env.SOLIDCRAFTBOT_SCREENSHOT_TIME_S};
  const names = {'--input': 'input', '--output-base': 'outputBase', '--playwright': 'playwright',
    '--chrome': 'chrome', '--ffmpeg':'ffmpeg', '--fps':'fps', '--record-seconds': 'recordSeconds', '--screenshot-time': 'screenshotTime'};
  const positional = [];
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--help') {result.help = true; continue;}
    if (!argv[i].startsWith('--')) {positional.push(argv[i]); continue;}
    const [flag, ...inline] = argv[i].split('=');
    if (!names[flag]) throw new Error('Unknown option: ' + flag);
    const value = inline.length ? inline.join('=') : argv[++i];
    if (!value || value.startsWith('--')) throw new Error('Value required for ' + flag);
    result[names[flag]] = value;
  }
  if (positional.length > 2) throw new Error('Expected at most positional Playwright and Chrome paths');
  if (positional[0]) result.playwright = positional[0];
  if (positional[1]) result.chrome = positional[1];
  result.recordSeconds = Number(result.recordSeconds);
  result.fps = Number(result.fps);
  scheduleFrames(1, result.recordSeconds, result.fps);
  if (result.screenshotTime !== undefined) {
    result.screenshotTime = Number(result.screenshotTime);
    if (!Number.isFinite(result.screenshotTime) || result.screenshotTime < 0) throw new Error('Nonnegative screenshot time required');
  }
  if (/\.(mp4|webm|png|html)$/i.test(result.outputBase)) throw new Error('--output-base must omit the file extension');
  return result;
}

function scheduleFrames(duration, seconds=45, fps=20) {
  if (!Number.isFinite(duration) || duration <= 0) throw new Error('Positive finite source duration required');
  if (!Number.isInteger(fps) || fps < 1 || fps > 120) throw new Error('Integer fps in 1..120 required');
  const count=seconds*fps;
  if (!Number.isFinite(seconds) || seconds <= 0 || seconds > 3600 || !Number.isInteger(count) || count < 2 || count > 36000)
    throw new Error('Recording requires an integer frame count in 2..36000 and at most 3600 seconds');
  return Array.from({length:count},(_,index)=>({index,pts_s:index/fps,source_time_s:index/(count-1)*duration}));
}

const digest=data=>crypto.createHash('sha256').update(data).digest('hex');

async function encodePngFrames({ffmpeg='ffmpeg',output,fps,schedule,frame,beforePublish=async()=>{}}) {
  assert.equal(typeof output,'string');
  assert.deepEqual(schedule,scheduleFrames(schedule.at(-1)?.source_time_s,schedule.length/fps,fps),'Canonical CFR schedule required');
  fs.mkdirSync(path.dirname(output),{recursive:true});
  const directory=fs.mkdtempSync(path.join(path.dirname(output),'.readme-video-'));
  const temporary=path.join(directory,'video.mp4');
  const args=['-hide_banner','-loglevel','error','-nostdin','-y','-f','image2pipe','-vcodec','png',
    '-framerate',String(fps),'-i','pipe:0','-an','-c:v','libx264','-preset','medium','-crf','20',
    '-vf','pad=ceil(iw/2)*2:ceil(ih/2)*2','-pix_fmt','yuv420p','-r',String(fps),'-fps_mode','cfr',
    '-frames:v',String(schedule.length),'-video_track_timescale',String(fps*1000),'-movflags','+faststart',temporary];
  let child,completion,closed=false,stderr=Buffer.alloc(0);
  try {
    child=spawn(ffmpeg,args,{stdio:['pipe','ignore','pipe'],shell:false});
    completion=new Promise(resolve=>{
      child.once('error',error=>{closed=true;resolve({error});});
      child.once('close',(code,signal)=>{closed=true;resolve({code,signal});});
    });
    // Keep only bounded diagnostic output; never accumulate frame images.
    child.stderr.on('data',data=>{stderr=Buffer.concat([stderr,data]).subarray(-16384);});
    child.stdin.on('error',()=>{}); // Individual writes and completion report failure.
    for (const point of schedule) {
      const png=await frame(point);
      assert(Buffer.isBuffer(png)&&png.length<=16*1024*1024&&png.subarray(0,8).equals(Buffer.from('89504e470d0a1a0a','hex')),'Bounded PNG frame required');
      // Await each write callback: pipe backpressure bounds queued frame data.
      await Promise.race([new Promise((resolve,reject)=>child.stdin.write(png,error=>error?reject(error):resolve())),
        completion.then(result=>{throw new Error('ffmpeg stopped before all frames: '+(result.error?.message??result.code));})]);
    }
    child.stdin.end();
    const result=await completion;
    if(result.error||result.code!==0)throw new Error('ffmpeg encoding failed: '+(result.error?.message??result.signal??result.code)+' '+stderr.toString('utf8'));
    const header=Buffer.alloc(8),fd=fs.openSync(temporary,'r');
    try {assert.equal(fs.readSync(fd,header,0,8,0),8,'Empty encoder output');} finally {fs.closeSync(fd);}
    assert.equal(header.toString('ascii',4,8),'ftyp','Encoder did not produce MP4');
    await beforePublish();
    fs.renameSync(temporary,output);
    return {codec:'libx264',pixel_format:'yuv420p',fps_mode:'cfr',fps,frames:schedule.length,
      duration_s:schedule.length/fps,first_pts_s:schedule[0].pts_s,last_pts_s:schedule.at(-1).pts_s};
  } finally {
    if(child&&!closed){child.kill('SIGKILL');await completion;}
    fs.rmSync(directory,{recursive:true,force:true});
  }
}

function timing(html) {
  const packed = html.match(/<script type="application\/json" data-mesh>([^<]+)<\/script>/);
  assert(packed, 'Inline source mesh required');
  const mesh = JSON.parse(zlib.gunzipSync(Buffer.from(packed[1], 'base64')));
  if (mesh.unload_program) {
    const program=mesh.unload_program,duration=program.duration_s,checks=[];
    assert(duration>0&&program.transfers.length>=2,'Consecutive unload program required');
    for(const transfer of program.transfers){
      const epsilon=Math.min(.01,(transfer.support_s-transfer.gripped_s)/4);
      checks.push([transfer.gripped_s-epsilon,'rotor',transfer.sample_id],
        [transfer.gripped_s,'gripper',transfer.sample_id],
        [transfer.support_s-epsilon,'gripper',transfer.sample_id],
        [transfer.support_s,'rack',transfer.sample_id],
        [duration,'rack',transfer.sample_id]);
    }
    const shown=program.transfers[1];
    return {duration,checks,screenshot:shown.presented_s+.1,multiSample:true,
      sampleIds:program.samples.map(sample=>sample.id),
      transfers:program.transfers.map(({sample_id,gripped_s,support_s})=>({sample_id,gripped_s,support_s})),
      sceneSha256:mesh.trajectory.scene_sha256};
  }
  const duration = mesh.trajectory.samples.at(-1).time_s;
  const attachment = mesh.scene.checks.attachment_time_s, handoff = mesh.scene.checks.rack_handoff_time_s;
  assert([duration, attachment, handoff].every(Number.isFinite), 'Finite source event times required');
  assert(duration > 0 && attachment > 0 && attachment < handoff && handoff <= duration, 'Ordered source event times required');
  assert.equal(mesh.trajectory.duration_s, duration, 'Trajectory duration disagrees with its final sample');
  const epsilon = Math.min(0.05, attachment / 2, (handoff - attachment) / 4);
  const checks = [[0, 'station'], [attachment - epsilon, 'station'], [attachment, 'gripper'],
    [handoff - epsilon, 'gripper'], [handoff, 'rack'], [duration, 'rack']];
  const clear = mesh.scene.checks.robot_clear_confirmed_s;
  const screenshot = Number.isFinite(clear) && clear + 1 < handoff ? Math.max(attachment, clear + 1) : (attachment + handoff) / 2;
  return {duration, attachment, handoff, checks, screenshot, sceneSha256: mesh.trajectory.scene_sha256};
}

function assertStateOwnership(state,source) {
  const time=state.sourceTimeS??Number(state.currentTime);
  if(!source.multiSample){
    assert.equal(state.tubeOwner,time>=source.handoff?'rack':time>=source.attachment?'gripper':'station');
    return;
  }
  const owners=JSON.parse(state.sampleOwners);
  assert.deepEqual(Object.keys(owners).sort(),[...source.sampleIds].sort());
  for(const id of source.sampleIds){
    const transfer=source.transfers.find(item=>item.sample_id===id);
    const expected=transfer&&time>=transfer.support_s?'rack':transfer&&time>=transfer.gripped_s?'gripper':'rotor';
    assert.equal(owners[id],expected,id+' ownership at '+time);
  }
}

// Legacy metadata helper for historical callers; unused by the CFR exporter.
function shortMp4(data, seconds = 20) {
  assert.equal(data.toString('ascii', 4, 8), 'ftyp', 'Recorder did not produce an MP4 container');
  const clocks = [];
  function boxes(start, end) {
    for (let pos = start; pos + 8 <= end;) {
      const size = data.readUInt32BE(pos), type = data.toString('ascii', pos + 4, pos + 8);
      if (size < 8 || pos + size > end) throw new Error('Unsupported MP4 box');
      if (['moov', 'trak', 'mdia'].includes(type)) boxes(pos + 8, pos + size);
      if (['mvhd', 'mdhd'].includes(type)) {
        const version = data[pos + 8], offset = pos + 8 + (version === 1 ? 20 : 12);
        const scale = data.readUInt32BE(offset);
        const duration = version === 1 ? Number(data.readBigUInt64BE(offset + 4)) : data.readUInt32BE(offset + 4);
        clocks.push({type, offset, scale, duration});
      }
      pos += size;
    }
  }
  boxes(0, data.length);
  const movie = clocks.find(c => c.type === 'mvhd');
  if (!movie || movie.scale <= 0 || movie.duration <= 0) throw new Error('No positive MP4 movie clock');
  const factor = movie.duration / movie.scale / seconds;
  for (const clock of clocks) data.writeUInt32BE(Math.max(1, Math.round(clock.scale * factor)), clock.offset);
  return data;
}

async function main(argv = process.argv.slice(2)) {
  const config = options(argv);
  if (config.help) {
    console.log('Usage: node scripts/export_readme_video.cjs [playwright-module] [chrome-executable] [--input HTML] [--output-base PATH] [--playwright MODULE] [--chrome EXECUTABLE] [--ffmpeg EXECUTABLE] [--fps 20] [--record-seconds 45] [--screenshot-time SECONDS]');
    return;
  }
  const input = path.resolve(config.input), output = path.resolve(config.outputBase);
  const inputBytes=fs.readFileSync(input),source = timing(inputBytes.toString('utf8'));
  const schedule=scheduleFrames(source.duration,config.recordSeconds,config.fps);
  const screenshotTime = config.screenshotTime ?? source.screenshot;
  assert(screenshotTime <= source.duration, 'Screenshot time exceeds the source duration');
  const {chromium} = require(config.playwright);
  const browser = await chromium.launch({headless: true, ...(config.chrome ? {executablePath: config.chrome} : {})});
  try {
    const page = await browser.newPage({viewport: {width: 960, height: 820}, deviceScaleFactor: 1, reducedMotion: 'reduce'});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => {if (message.type() === 'error') errors.push(message.text());});
    await page.goto(pathToFileURL(input).href);
    await page.waitForSelector('[data-current-time]');
    const ownership=await page.evaluate(source=>{
      const root=document.querySelector('#cf01-bench-rack'),slider=root.querySelector('[data-time-slider]');
      if(Number(slider.max)!==source.duration)throw new Error('Browser/source duration mismatch');
      slider.step='any'; // Preserve exact frame and event times, independent of UI stepping.
      return source.checks.map(([time,owner,sampleId])=>{
        slider.value=time;slider.dispatchEvent(new Event('input',{bubbles:true}));
        const actual=sampleId?JSON.parse(root.dataset.sampleOwners)[sampleId]:root.dataset.tubeOwner;
        if(Math.abs(Number(root.dataset.currentTime)-time)>.001||actual!==owner)throw new Error('Unexpected tube ownership at source time '+time);
        return {time_s:time,owner,...(sampleId?{sample_id:sampleId}:{})};
      });
    },source);
    const frames=[],states=[];
    let screenshot,manifestPath,manifestSha256;
    const encoding=await encodePngFrames({ffmpeg:config.ffmpeg,output:output+'.mp4',fps:config.fps,schedule,
      frame:async point=>{
        const captured=await page.evaluate(time=>{
          const root=document.querySelector('#cf01-bench-rack'),slider=root.querySelector('[data-time-slider]');
          slider.value=time;slider.dispatchEvent(new Event('input',{bubbles:true}));
          // The source input handler draws synchronously; no wall-clock wait.
          return {png:root.querySelector('canvas').toDataURL('image/png'),state:{...root.dataset,sourceTimeS:time}};
        },point.source_time_s);
        assert.deepEqual(errors,[]);
        assert(Math.abs(Number(captured.state.currentTime)-point.source_time_s)<=.001,'Rendered source clock mismatch');
        assertStateOwnership(captured.state,source);
        assert(captured.png.startsWith('data:image/png;base64,'),'Canvas PNG required');
        const png=Buffer.from(captured.png.slice('data:image/png;base64,'.length),'base64');
        frames.push({...point,png_sha256:digest(png),
          ...(source.multiSample?{owners:JSON.parse(captured.state.sampleOwners)}:{tube_owner:captured.state.tubeOwner})});
        if(point.index%Math.max(1,Math.round((schedule.length-1)/4))===0||point.index===schedule.length-1)states.push(captured.state);
        return png;
      },
      beforePublish:async()=>{
        await page.locator('[data-time-slider]').evaluate((slider,time)=>{
          slider.value=time;slider.dispatchEvent(new Event('input',{bubbles:true}));
        },screenshotTime);
        screenshot=await page.locator('#cf01-bench-rack').screenshot();
        assert.deepEqual(errors,[]);
        const manifest={format:'solidcraftbot.readme-video-frames/1',input,input_sha256:digest(inputBytes),
          source_scene_sha256:source.sceneSha256,source_duration_s:source.duration,
          video_duration_s:config.recordSeconds,fps:config.fps,frames};
        const directory=path.resolve('tmp/readme-video');fs.mkdirSync(directory,{recursive:true});
        manifestPath=path.join(directory,path.basename(output)+'.frames.json');
        const bytes=Buffer.from(JSON.stringify(manifest,null,2)+'\n');
        fs.writeFileSync(manifestPath,bytes);manifestSha256=digest(bytes);
      }});
    const posterTemporary=output+'.png.tmp';
    try {fs.writeFileSync(posterTemporary,screenshot);fs.renameSync(posterTemporary,output+'.png');}
    finally {fs.rmSync(posterTemporary,{force:true});}
    console.log(JSON.stringify({input,video:output+'.mp4',screenshot:output+'.png',
      source_scene_sha256:source.sceneSha256,source_duration_s:source.duration,
      video_target_duration_s:config.recordSeconds,screenshot_time_s:screenshotTime,
      mime:'video/mp4',frames:frames.length,encoding,frame_manifest:manifestPath,frame_manifest_sha256:manifestSha256,
      ownership_checks:ownership,states,errors}));
  } finally {await browser.close();}
}

module.exports = {options,timing,shortMp4,assertStateOwnership,scheduleFrames,encodePngFrames};
if (require.main === module) main().catch(error => {console.error(error); process.exitCode = 1;});
