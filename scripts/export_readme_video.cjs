// Run from repository root with Node and Playwright. Optional arguments: Playwright module path, Chromium executable.
const {chromium}=require(process.argv[2] || 'playwright');
const fs=require('fs');
// Normalize recording time: rendering speed varies with host CPU.
function shortMp4(data, seconds=20) {
  const clocks=[];
  function boxes(start,end) {
    for(let pos=start;pos+8<=end;) {
      const size=data.readUInt32BE(pos),type=data.toString('ascii',pos+4,pos+8);
      if(size<8 || pos+size>end) throw new Error('Unsupported MP4 box');
      if(['moov','trak','mdia'].includes(type)) boxes(pos+8,pos+size);
      if(['mvhd','mdhd'].includes(type)) {
        const version=data[pos+8],offset=pos+8+(version===1?20:12);
        const scale=data.readUInt32BE(offset);
        const duration=version===1?Number(data.readBigUInt64BE(offset+4)):data.readUInt32BE(offset+4);
        clocks.push({type,offset,scale,duration});
      }
      pos+=size;
    }
  }
  boxes(0,data.length);
  const movie=clocks.find(c=>c.type==='mvhd');
  if(!movie) throw new Error('No MP4 movie clock');
  const factor=movie.duration/movie.scale/seconds;
  for(const c of clocks) data.writeUInt32BE(Math.max(1,Math.round(c.scale*factor)),c.offset);
  return data;
}
(async()=>{
const browser=await chromium.launch({headless:true,...(process.argv[3] ? {executablePath:process.argv[3]} : {})});
const page=await browser.newPage({viewport:{width:960,height:820},deviceScaleFactor:1});
const errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.goto(require('node:url').pathToFileURL(require('node:path').resolve('docs/media/robot-demo.html')).href);
await page.waitForFunction(()=>document.querySelector('[data-current-time]'));
const result=await page.evaluate(async()=>{
const root=document.querySelector('#cf01-bench-rack'),canvas=root.querySelector('canvas'),slider=root.querySelector('[data-time-slider]');
const mime=['video/mp4;codecs=avc1.42001E','video/webm;codecs=vp9','video/webm'].find(t=>MediaRecorder.isTypeSupported(t));
const recorder=new MediaRecorder(canvas.captureStream(20),{mimeType:mime,videoBitsPerSecond:1000000});const chunks=[];
const done=new Promise(resolve=>{recorder.ondataavailable=e=>chunks.push(e.data);recorder.onstop=resolve});recorder.start();
const states=[];
for(let i=0;i<=400;i++){slider.value=i*60/400;slider.dispatchEvent(new Event('input',{bubbles:true}));if(i%100===0)states.push({...root.dataset});await new Promise(r=>setTimeout(r,50));}
recorder.stop();await done;const bytes=new Uint8Array(await new Blob(chunks).arrayBuffer());let binary='';for(const b of bytes)binary+=String.fromCharCode(b);return {mime,data:btoa(binary),states};
});
if(result.states.map(s=>s.tubeOwner).join(',')!=='station,station,gripper,gripper,rack') throw new Error('Unexpected tube ownership');
const ext=result.mime.startsWith('video/mp4')?'mp4':'webm';const bytes=Buffer.from(result.data,'base64');
fs.writeFileSync('docs/media/robot-demo.'+ext,ext==='mp4'?shortMp4(bytes):bytes);
await page.locator('[data-time-slider]').evaluate(e=>{e.value=30.5;e.dispatchEvent(new Event('input',{bubbles:true}))});
await page.locator('#cf01-bench-rack').screenshot({path:'docs/media/robot-demo.png'});
if(errors.length) throw new Error(errors.join('\n'));
console.log(JSON.stringify({mime:result.mime,states:result.states,errors}));await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
