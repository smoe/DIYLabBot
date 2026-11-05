// Local browser QA of the generated conversation animation.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require(path.join(process.argv[2],'playwright'));
(async()=>{
  const directory=path.resolve(process.argv[3]),errors=[],checks=[];
  const options={headless:true};
  const edge='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
  if(fs.existsSync(edge))options.executablePath=edge;
  const browser=await chromium.launch(options),page=await browser.newPage({viewport:{width:820,height:1100},reducedMotion:'reduce'});
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto('file:///'+path.join(directory,'preview.html').replaceAll('\\','/'));
  const frame=page.frameLocator('iframe'),root=frame.locator('#h03-transfer-reset'),slider=root.locator('[data-time-slider]');
  await root.locator('canvas').waitFor({state:'visible'});
  async function seek(t){await slider.evaluate((input,value)=>{input.value=value;input.dispatchEvent(new Event('input',{bubbles:true}))},t);return root.evaluate(el=>({...el.dataset}))}
  for(const [t,expected] of [[0,{cam:0,tubeLift:0,pull:4.2,turn:0}],[6,{cam:130,tubeLift:28}],[12,{cam:220,pull:0}],[16,{cam:360,tubeLift:28}],[18,{cam:360,tubeLift:48,pull:0}],[25,{cam:210,tubeLift:28}],[27,{pull:4.5,turn:0}],[28.5,{pull:4.5,turn:45}],[30,{pull:4.5,turn:90}],[36,{cam:0,tubeLift:0,turn:90}],[40,{cam:0,tubeLift:0,pull:4.2,turn:0}]]){
    const actual=await seek(t);for(const [k,v] of Object.entries(expected))assert(Math.abs(Number(actual[k])-v)<1e-5,`${t}s ${k}: ${actual[k]} != ${v}`);
    checks.push({time_s:t,passed:true,values:actual});
    if([0,6,18,27,28.5,30,40].includes(t))await root.screenshot({path:path.join(directory,`review-${String(t).replace('.','-')}.png`)});
  }
  await seek(27);await root.locator('[data-play]').click();await page.waitForTimeout(600);assert(Number(await root.getAttribute('data-current-time'))>27.2);await root.locator('[data-play]').click();
  checks.push({id:'play_button_advances_cycle',passed:true});
  for(const width of [320,600,820]){
    await page.setViewportSize({width,height:1200});await seek(28.5);
    const layout=await root.evaluate(el=>({width:el.clientWidth,scroll:el.scrollWidth,canvasHeight:el.querySelector('canvas').getBoundingClientRect().height}));
    assert(layout.scroll<=layout.width+1,`Overflow at ${width}px`);
    await root.screenshot({path:path.join(directory,`review-width-${width}.png`)});checks.push({id:`width_${width}`,passed:true,...layout});
  }
  await page.emulateMedia({colorScheme:'dark'});await page.setViewportSize({width:820,height:1100});await seek(28.5);
  await root.screenshot({path:path.join(directory,'review-dark.png')});
  assert.deepEqual(errors,[]);
  const result={passed:true,checks,console_errors:errors,scope:'Browser runtime, playback, exact key states and responsive layout. PNGs require separate visual inspection.'};
  fs.writeFileSync(path.join(directory,'browser-checks.json'),JSON.stringify(result,null,2)+'\n');
  console.log(JSON.stringify({passed:true,checks:checks.length,console_errors:errors}));await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
