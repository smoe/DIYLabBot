// Run from the repository root. Legacy positional Playwright/Chrome arguments remain supported.
const fs = require('node:fs');
const path = require('node:path');
const zlib = require('node:zlib');
const {pathToFileURL} = require('node:url');
const assert = require('node:assert/strict');

function options(argv, env = process.env) {
  const result = {input: 'docs/media/robot-demo.html', outputBase: 'docs/media/robot-demo',
    playwright: env.SOLIDCRAFTBOT_PLAYWRIGHT || 'playwright', chrome: env.SOLIDCRAFTBOT_CHROME,
    recordSeconds: env.SOLIDCRAFTBOT_VIDEO_DURATION_S || 20,
    screenshotTime: env.SOLIDCRAFTBOT_SCREENSHOT_TIME_S};
  const names = {'--input': 'input', '--output-base': 'outputBase', '--playwright': 'playwright',
    '--chrome': 'chrome', '--record-seconds': 'recordSeconds', '--screenshot-time': 'screenshotTime'};
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
  if (!Number.isFinite(result.recordSeconds) || result.recordSeconds <= 0) throw new Error('Positive recording duration required');
  if (result.screenshotTime !== undefined) {
    result.screenshotTime = Number(result.screenshotTime);
    if (!Number.isFinite(result.screenshotTime) || result.screenshotTime < 0) throw new Error('Nonnegative screenshot time required');
  }
  if (/\.(mp4|webm|png|html)$/i.test(result.outputBase)) throw new Error('--output-base must omit the file extension');
  return result;
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

// Normalize recording time: rendering speed varies with host CPU.
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
    console.log('Usage: node scripts/export_readme_video.cjs [playwright-module] [chrome-executable] [--input HTML] [--output-base PATH] [--playwright MODULE] [--chrome EXECUTABLE] [--record-seconds 20] [--screenshot-time SECONDS]');
    return;
  }
  const input = path.resolve(config.input), output = path.resolve(config.outputBase);
  const source = timing(fs.readFileSync(input, 'utf8'));
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
    const result = await page.evaluate(async ({source, seconds}) => {
      const root = document.querySelector('#cf01-bench-rack'), canvas = root.querySelector('canvas');
      const slider = root.querySelector('[data-time-slider]'), duration = Number(slider.max);
      if (duration !== source.duration) throw new Error('Browser/source duration mismatch');
      function show(time) {slider.value = time; slider.dispatchEvent(new Event('input', {bubbles: true}));}
      const ownership = source.checks.map(([time, owner, sampleId]) => {
        show(time);
        const actual=sampleId?JSON.parse(root.dataset.sampleOwners)[sampleId]:root.dataset.tubeOwner;
        if (Math.abs(Number(root.dataset.currentTime) - time) > 0.001 || actual !== owner) {
          throw new Error('Unexpected tube ownership at source time ' + time);
        }
        return {time_s: time, owner,...(sampleId?{sample_id:sampleId}:{})};
      });
      const mime = ['video/mp4;codecs=avc1.42001E', 'video/mp4'].find(type => MediaRecorder.isTypeSupported(type));
      if (!mime) throw new Error('MP4 MediaRecorder support required; refusing a WebM replacement');
      show(0);
      const fps = 20, frames = Math.max(1, Math.round(seconds * fps));
      const recorder = new MediaRecorder(canvas.captureStream(fps), {mimeType: mime, videoBitsPerSecond: 1000000});
      if (!recorder.mimeType.startsWith('video/mp4')) throw new Error('Recorder did not select MP4');
      const chunks = [], states = [];
      const done = new Promise((resolve, reject) => {
        recorder.ondataavailable = event => chunks.push(event.data);
        recorder.onstop = resolve;
        recorder.onerror = () => reject(new Error('MP4 recording failed'));
      });
      recorder.start();
      for (let i = 0; i <= frames; i++) {
        show(i * duration / frames);
        if (i % Math.max(1, Math.round(frames / 4)) === 0 || i === frames) states.push({...root.dataset,sourceTimeS:i*duration/frames});
        await new Promise(resolve => setTimeout(resolve, 1000 / fps));
      }
      recorder.stop();
      await done;
      const bytes = new Uint8Array(await new Blob(chunks).arrayBuffer());
      let binary = '';
      for (const byte of bytes) binary += String.fromCharCode(byte);
      return {mime: recorder.mimeType, data: btoa(binary), states, ownership, frames: frames + 1};
    }, {source, seconds: config.recordSeconds});
    for (const state of result.states) {
      assertStateOwnership(state,source);
    }
    const video = shortMp4(Buffer.from(result.data, 'base64'), config.recordSeconds);
    await page.locator('[data-time-slider]').evaluate((slider, time) => {
      slider.value = time; slider.dispatchEvent(new Event('input', {bubbles: true}));
    }, screenshotTime);
    const screenshot = await page.locator('#cf01-bench-rack').screenshot();
    assert.deepEqual(errors, []);
    fs.mkdirSync(path.dirname(output), {recursive: true});
    fs.writeFileSync(output + '.mp4', video);
    fs.writeFileSync(output + '.png', screenshot);
    console.log(JSON.stringify({input, video: output + '.mp4', screenshot: output + '.png',
      source_scene_sha256: source.sceneSha256, source_duration_s: source.duration,
      video_target_duration_s: config.recordSeconds, screenshot_time_s: screenshotTime,
      mime: result.mime, frames: result.frames, ownership_checks: result.ownership, states: result.states, errors}));
  } finally {await browser.close();}
}

module.exports = {options, timing, shortMp4, assertStateOwnership};
if (require.main === module) main().catch(error => {console.error(error); process.exitCode = 1;});
