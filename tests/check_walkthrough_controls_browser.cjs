// Usage: node tests/check_walkthrough_controls_browser.cjs <index.html> [playwright-module] [chrome-executable] [output-directory] [https-url]
// SOLIDCRAFTBOT_WALKTHROUGH_GPU=metal uses the same native GPU profile as the full walkthrough check.
// The full native scene is driven only by public controls. Clock-controlled cases
// prove input semantics, not real-time rendering or movement performance.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const {pathToFileURL} = require('node:url');
const {chromium} = require(process.argv[3] || 'playwright');

(async () => {
  assert(process.argv[2], 'A generated standalone walkthrough HTML file is required.');
  const target = path.resolve(process.argv[2]), htmlBytes = fs.readFileSync(target), html = htmlBytes.toString('utf8');
  const liveURL = process.argv[6] ? new URL(process.argv[6]) : null;
  if (liveURL) assert.equal(liveURL.protocol, 'https:', 'A live deployment must use HTTPS.');
  const faviconURL = liveURL ? new URL('/favicon.ico', liveURL).href : null;
  const inline = html.match(/<script id="walkthrough-data" type="application\/json">([\s\S]*?)<\/script>/);
  assert(inline, 'The regression requires a standalone inline native scene.');
  const model = JSON.parse(inline[1]);
  assert(model.scenes?.building?.groups?.length, 'The complete native building scene is required.');
  const output = path.resolve(process.argv[5] || path.dirname(target));
  assert(/(^|[/\\])exports([/\\]|$)/.test(output), 'Write browser evidence beneath an ignored exports directory.');
  fs.mkdirSync(output, {recursive: true});
  const gpuProfile = process.env.SOLIDCRAFTBOT_WALKTHROUGH_GPU || 'software';
  assert(['software', 'metal'].includes(gpuProfile), 'Supported GPU profiles are software and metal.');
  const browser = await chromium.launch({headless: true,
    ...(process.argv[4] ? {executablePath: process.argv[4]} : {}),
    args: gpuProfile === 'metal'
      ? ['--enable-gpu', '--enable-webgl', '--ignore-gpu-blocklist', '--use-gl=angle', '--use-angle=metal']
      : ['--enable-webgl', '--ignore-gpu-blocklist', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
  });
  const report = {target, html_sha256: crypto.createHash('sha256').update(htmlBytes).digest('hex'), html_bytes: htmlBytes.length,
    browser: {engine: 'chromium', version: browser.version(), launch_profile: gpuProfile},
    timing: 'A real requestAnimationFrame smoke precedes Playwright-controlled frame time; no real-time performance claim.',
    checks: [], hidden_cleanup: {proven: false}};
  const progress = stage => console.log(JSON.stringify({stage, time: new Date().toISOString()}));
  let page;
  try {
    page = await browser.newPage({viewport: {width: 1280, height: 950}, reducedMotion: 'no-preference'});
    page.setDefaultTimeout(120000);
    const errors = [], network = [];
    let bodySession;
    const liveDocuments = [];
    if (liveURL) report.live = {url: liveURL.href, main_requests: [], ignored_favicon: [], unexpected_requests: network};
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => {
      if (message.type() !== 'error') return;
      if (liveURL && message.location().url === faviconURL)
        report.live.ignored_favicon.push({event: 'console', url: faviconURL, message: message.text()});
      else errors.push(message.text());
    });
    page.on('request', request => {
      if (!/^https?:/.test(request.url())) return;
      if (liveURL && request.url() === liveURL.href && request.isNavigationRequest()
          && request.frame() === page.mainFrame() && request.method() === 'GET' && !report.live.main_requests.length)
        report.live.main_requests.push({url: request.url(), method: request.method(), resource_type: request.resourceType()});
      else if (liveURL && request.url() === faviconURL && request.method() === 'GET')
        report.live.ignored_favicon.push({event: 'request', url: request.url(), resource_type: request.resourceType()});
      else network.push(request.url());
    });
    if (liveURL) {
      page.on('requestfailed', request => {
        if (request.url() === faviconURL)
          report.live.ignored_favicon.push({event: 'requestfailed', url: request.url(), failure: request.failure()});
        else errors.push(`Network request failed: ${request.url()}: ${request.failure()?.errorText}`);
      });
      page.on('response', response => {
        if (response.url() === faviconURL)
          report.live.ignored_favicon.push({event: 'response', url: response.url(), status: response.status()});
      });
      // The standalone native scene exceeds Chrome's default inspector cache.
      // Read the actual main response through the same bounded, buffered session.
      bodySession = await page.context().newCDPSession(page);
      const resourceBuffer = htmlBytes.length * 2 + 1024 * 1024;
      report.live.inspector_buffer_bytes = {resource: resourceBuffer, total: resourceBuffer * 2};
      bodySession.on('Network.responseReceived', event => {
        if (event.type === 'Document' && event.response.url === liveURL.href)
          liveDocuments.push({request_id: event.requestId, url: event.response.url, status: event.response.status});
      });
      await bodySession.send('Network.enable', {maxResourceBufferSize: resourceBuffer, maxTotalBufferSize: resourceBuffer * 2});
    }
    const mainResponse = await page.goto(liveURL?.href || pathToFileURL(target).href, {waitUntil: 'load', timeout: 120000});
    if (liveURL) {
      assert(mainResponse, 'The deployed main document must have an HTTP response.');
      assert.equal(liveDocuments.length, 1, 'The buffered session observes exactly the deployed main document.');
      const document = liveDocuments[0];
      assert.equal(document.status, mainResponse.status(), 'Both browser sessions observe the same main response status.');
      const captured = await bodySession.send('Network.getResponseBody', {requestId: document.request_id});
      const body = Buffer.from(captured.body, captured.base64Encoded ? 'base64' : 'utf8');
      await bodySession.detach();
      Object.assign(report.live, {response_url: mainResponse.url(), status: mainResponse.status(),
        body_sha256: crypto.createHash('sha256').update(body).digest('hex'), body_bytes: body.length,
        body_source: 'Network.getResponseBody from the same buffered actual HTTPS document session'});
      assert.equal(mainResponse.url(), liveURL.href, 'The browser reaches the exact requested deployment URL.');
      assert.equal(mainResponse.status(), 200, 'The deployed main document returns HTTP 200.');
      assert.equal(body.length, htmlBytes.length, 'The deployed response has the exact checked local byte length.');
      assert.equal(report.live.body_sha256, report.html_sha256, 'The deployed response has the exact checked local SHA-256.');
      assert.equal(report.live.main_requests.length, 1, 'The browser made exactly the expected main document request.');
      progress('deployed HTTPS response matches checked local HTML bytes');
    }
    await page.waitForFunction(() => window.__buildingWalkthrough?.ready
      || document.querySelector('#building-walkthrough')?.dataset.error, null, {timeout: 120000});
    assert.equal(await page.locator('#building-walkthrough').getAttribute('data-error'), null,
      await page.locator('#walkthrough-error').textContent());
    const read = () => page.evaluate(() => {
      const viewer = window.__buildingWalkthrough;
      return {camera: viewer.camera, elevator: viewer.elevator, frames: viewer.frames};
    });
    const distance = (a, b) => Math.hypot(...a.map((value, axis) => value - b[axis]));
    const yawDelta = (a, b) => Math.atan2(Math.sin(b.camera.yaw_rad - a.camera.yaw_rad),
      Math.cos(b.camera.yaw_rad - a.camera.yaw_rad));
    const delta = (a, b) => b.camera.eye_mm.map((value, axis) => value - a.camera.eye_mm[axis]);
    function stationary(a, b, label) {
      assert(distance(a.camera.eye_mm, b.camera.eye_mm) < 1e-6, `${label}: camera position is unchanged`);
      assert(Math.abs(yawDelta(a, b)) < 1e-10, `${label}: camera yaw is unchanged`);
    }
    function turned(a, b, sign, label) {
      assert(distance(a.camera.eye_mm, b.camera.eye_mm) < 1e-6, `${label}: turning never translates`);
      assert(sign * yawDelta(a, b) > .025, `${label}: yaw has the expected direction`);
      assert.equal(b.camera.pitch_rad, a.camera.pitch_rad, `${label}: pitch is unchanged`);
    }
    function strafed(a, b, sign, label) {
      const movement = delta(a, b), yaw = a.camera.yaw_rad;
      const right = movement[0] * Math.sin(yaw) - movement[1] * Math.cos(yaw);
      const forward = movement[0] * Math.cos(yaw) + movement[1] * Math.sin(yaw);
      assert(sign * right > 30, `${label}: sideways translation has the expected direction`);
      assert(Math.abs(forward) < 1e-6 && Math.abs(movement[2]) < 1e-6, `${label}: translation is horizontal and sideways`);
      assert(Math.abs(yawDelta(a, b)) < 1e-10, `${label}: strafing never changes yaw`);
    }
    const canvas = page.locator('#walkthrough-canvas');
    // This first case uses the browser's real clock and real animation frames.
    await canvas.focus();
    const realBefore = await read();
    await page.keyboard.down('ArrowLeft');
    try {
      await page.waitForFunction(yaw => window.__buildingWalkthrough.camera.yaw_rad > yaw + .04,
        realBefore.camera.yaw_rad, {timeout: 120000, polling: 'raf'});
    } finally {await page.keyboard.up('ArrowLeft');}
    const realAfter = await read();
    turned(realBefore, realAfter, 1, 'Real-frame ArrowLeft smoke');
    report.real_frame_smoke = {before: realBefore, after: realAfter};
    report.checks.push('real-frame arrow yaw with stationary eye');
    progress('real-frame smoke passed; starting clock-controlled input checks');
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const epoch = new Date('2026-11-19T12:00:00Z');
    await page.clock.install({time: epoch});
    await page.clock.pauseAt(new Date(epoch.getTime() + 1000));
    const advance = (milliseconds = 160) => page.clock.runFor(milliseconds);
    const segment = async () => {const before = await read(); await advance(); return [before, await read()];};
    const stop = model.stops.find(value => value.id === (model.default_stop_id || model.default_stop)) || model.stops[0];
    const reset = async () => {
      await page.locator(`#walkthrough-stops button[data-stop="${stop.id}"]`).click();
      await canvas.focus(); await advance(32);
    };
    const held = new Set();
    const down = async key => {await page.keyboard.down(key); held.add(key);};
    const up = async key => {await page.keyboard.up(key); held.delete(key);};
    const release = async () => {for (const key of [...held]) await up(key); await page.mouse.up(); await advance(32);};
    const settled = async label => {const [a, b] = await segment(); stationary(a, b, label);};

    for (const [key, sign] of [['ArrowLeft', 1], ['ArrowRight', -1]]) {
      await reset(); await down(key); const [a, b] = await segment(); turned(a, b, sign, key); await release();
    }
    for (const [key, sign] of [['ArrowLeft', -1], ['ArrowRight', 1], ['a', -1], ['d', 1]]) {
      await reset(); if (key.startsWith('Arrow')) await down('AltLeft');
      await down(key); const [a, b] = await segment(); strafed(a, b, sign, `Strafe ${key}`); await release();
    }
    report.checks.push('both arrow yaw directions', 'both Alt+arrow strafe directions', 'A/D strafing retained');
    progress('arrow and strafe directions passed');

    await reset(); await down('ArrowRight');
    {const [a, b] = await segment(); turned(a, b, -1, 'Held right arrow initially turns');}
    await down('AltLeft');
    {const [a, b] = await segment(); strafed(a, b, 1, 'Alt pressed during held right arrow');}
    await up('AltLeft');
    {const [a, b] = await segment(); turned(a, b, -1, 'Alt released during held right arrow');}
    await release(); await settled('Arrow released after Alt');
    await reset(); await down('AltLeft'); await down('ArrowLeft'); await advance();
    await up('ArrowLeft'); await settled('Arrow released before Alt'); await up('AltLeft'); await settled('Alt released last');
    await down('AltLeft'); await down('AltRight'); await down('ArrowLeft'); await advance();
    await up('AltLeft');
    {const [a, b] = await segment(); strafed(a, b, -1, 'Right Alt remains held after Left Alt release');}
    await up('AltRight');
    {const [a, b] = await segment(); turned(a, b, 1, 'Both Alts released while left arrow remains held');}
    await release();
    report.checks.push('live Alt transitions without arrow repeat', 'both modifier release orders', 'independent physical Alt keys');
    progress('live Alt transitions and physical modifier releases passed');

    await reset(); await down('w'); await down('ArrowUp'); await advance(); await up('w');
    {const [a, b] = await segment(); assert(distance(a.camera.eye_mm, b.camera.eye_mm) > 30, 'ArrowUp survives release of its W alias');}
    await up('ArrowUp'); await settled('Both forward aliases released');
    await down('w'); await down('ArrowUp'); await advance(); await up('ArrowUp');
    {const [a, b] = await segment(); assert(distance(a.camera.eye_mm, b.camera.eye_mm) > 30, 'W survives release of its ArrowUp alias');}
    await release();
    await reset(); await down('w'); await advance(32);
    let pair = await segment(); const normal = distance(pair[0].camera.eye_mm, pair[1].camera.eye_mm); await release();
    await reset(); await down('ShiftLeft'); await down('ShiftRight'); await down('w'); await advance(32);
    pair = await segment(); const bothShifts = distance(pair[0].camera.eye_mm, pair[1].camera.eye_mm);
    await up('ShiftLeft'); pair = await segment(); const rightShift = distance(pair[0].camera.eye_mm, pair[1].camera.eye_mm);
    await up('ShiftRight'); pair = await segment(); const noShift = distance(pair[0].camera.eye_mm, pair[1].camera.eye_mm); await release();
    for (const fast of [bothShifts, rightShift]) assert(fast / normal > 2.1 && fast / normal < 2.7, 'Shift speeds translation by the configured 2.4 multiplier');
    assert(Math.abs(noShift / normal - 1) < .1, 'Releasing the final physical Shift restores normal speed');
    report.shift_distances_mm = {normal, bothShifts, rightShift, noShift};
    report.checks.push('independent W/Up release in both orders', 'independent physical Shift keys', 'Shift accelerates translation');
    progress('alias independence and Shift speed passed');

    // DOM fixtures only observe ordinary keyboard events and native editing.
    await page.evaluate(() => {
      const fixture = document.createElement('div'); fixture.id = 'controls-browser-fixture';
      fixture.innerHTML = '<input id="controls-input" value="sample"><textarea id="controls-textarea">sample</textarea>'
        + '<select id="controls-select"><option>one</option><option>two</option></select>'
        + '<div contenteditable=""><span id="controls-editable" tabindex="0">sample</span></div><output id="controls-events" hidden></output>';
      document.body.append(fixture);
      const output = fixture.querySelector('output'), events = [];
      window.addEventListener('keydown', event => {
        events.push({code: event.code, ctrl: event.ctrlKey, meta: event.metaKey, alt: event.altKey,
          target: event.target.id, prevented: event.defaultPrevented});
        output.textContent = JSON.stringify(events);
      });
    });
    for (const modifier of ['ControlLeft', 'MetaLeft']) {
      await reset(); await down('w'); await advance(); await down(modifier);
      await settled(`${modifier} clears held movement`); await page.keyboard.press('a'); await advance();
      await settled(`${modifier}+A stays a browser shortcut`); await up(modifier);
      await down('w'); await settled(`${modifier} cleanup survives held-key repeats`); await up('w');
      await down('w');
      {const [a, b] = await segment(); assert(distance(a.camera.eye_mm, b.camera.eye_mm) > 30, 'A fresh W press resumes navigation after shortcut cleanup');}
      await release();
    }
    for (const selector of ['#controls-input', '#controls-textarea', '#controls-select', '#controls-editable']) {
      await reset(); await down('w'); await advance(); await page.locator(selector).focus();
      await settled(`${selector} focus clears held movement`); await up('w');
      const a = await read(); await page.keyboard.press('ArrowLeft'); await page.keyboard.press('w'); await advance();
      stationary(a, await read(), `${selector} preserves editing keys`);
    }
    await page.locator('#controls-input').fill('sample'); await page.keyboard.press('End'); await page.keyboard.press('ArrowLeft');
    assert.equal(await page.locator('#controls-input').evaluate(node => node.selectionStart), 5, 'Native input ArrowLeft moves the caret');
    await page.keyboard.press('w'); assert.equal(await page.locator('#controls-input').inputValue(), 'samplwe', 'Native typing reaches the input');
    const observed = JSON.parse(await page.locator('#controls-events').textContent());
    const preserved = observed.filter(event => event.ctrl || event.meta || event.target.startsWith('controls-'));
    assert(preserved.some(event => event.ctrl && event.code === 'KeyA'), 'Observed a real Control+A key event');
    assert(preserved.some(event => event.meta && event.code === 'KeyA'), 'Observed a real Meta+A key event');
    assert(preserved.length > 10 && preserved.every(event => !event.prevented), 'Editing and browser shortcuts retain native default behavior');
    report.checks.push('Ctrl/Meta shortcuts clear movement and preserve default behavior', 'held-key repeat cannot revive cleared movement', 'editable focus clears movement', 'input/textarea/select/inherited contenteditable preserve editing');
    progress('browser shortcuts and editable focus passed');

    const pointerDown = async action => {
      const box = await page.locator(`[data-move="${action}"]`).boundingBox();
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2); await page.mouse.down();
    };
    await reset(); await pointerDown('left');
    {const [a, b] = await segment(); strafed(a, b, -1, 'On-screen left button');}
    await page.mouse.up(); await settled('On-screen pointer release');
    await reset(); await pointerDown('forward'); await down('w'); await advance(); await up('w');
    {const [a, b] = await segment(); assert(distance(a.camera.eye_mm, b.camera.eye_mm) > 30, 'Keyboard release preserves held pointer movement');}
    await page.mouse.up(); await settled('Pointer then keyboard release');
    await reset(); await down('w'); await pointerDown('forward'); await advance(); await page.mouse.up();
    {const [a, b] = await segment(); assert(distance(a.camera.eye_mm, b.camera.eye_mm) > 30, 'Pointer release preserves held keyboard movement');}
    await release();
    await reset(); await down('w'); await pointerDown('forward'); await advance();
    await page.evaluate(() => window.dispatchEvent(new Event('blur'))); await settled('Window blur clears keyboard and pointer movement');
    await release(); report.checks.push('on-screen strafing retained', 'pointer/keyboard ownership in both release orders', 'blur clears held inputs');
    progress('pointer ownership and blur cleanup passed');

    // Try a genuine Chrome visibility transition; never replace document.hidden.
    let cdp, windowId, actuallyHidden = false, hiddenReason;
    try {
      cdp = await page.context().newCDPSession(page);
      ({windowId} = await cdp.send('Browser.getWindowForTarget'));
      await reset(); await down('w'); await advance();
      await cdp.send('Browser.setWindowBounds', {windowId, bounds: {windowState: 'minimized'}});
      actuallyHidden = await page.evaluate(() => document.hidden);
      await cdp.send('Browser.setWindowBounds', {windowId, bounds: {windowState: 'normal'}}); await page.bringToFront();
      hiddenReason = 'Headless Chrome did not mark the minimized page hidden.';
    } catch (error) {
      hiddenReason = String(error.message);
      if (cdp && windowId) await cdp.send('Browser.setWindowBounds', {windowId, bounds: {windowState: 'normal'}}).catch(() => {});
      await page.bringToFront();
    } finally {if (cdp) await cdp.detach();}
    if (actuallyHidden) {
      assert.equal(await page.evaluate(() => document.hidden), false, 'The visibility check restores a visible browser page');
      await settled('Real hidden/show transition clears held movement');
      report.hidden_cleanup = {proven: true, mechanism: 'Chrome window minimize/restore (may also deliver blur)'};
    } else report.hidden_cleanup = {proven: false, reason: hiddenReason};
    await release();
    progress('visibility mechanism checked; starting public lift controls');

    const lift = model.elevator, liftObject = model.objects.find(object => object.id === lift?.object_id);
    assert(liftObject, 'The full scene must retain its public lift controls.');
    const jump = Math.ceil(liftObject.duration_s * 1000) + 2000;
    const settleLift = async () => {
      for (let attempt = 0; attempt < 8; attempt++) {
        const state = (await read()).elevator;
        if (state.state !== 'moving' && (!state.door_phase || state.door_phase === 'idle')) return;
        await page.clock.fastForward(jump);
      }
      assert.fail('Lift did not reach an idle source-derived floor.');
    };
    const attached = state => assert(distance(state.camera.eye_mm, state.elevator.attached_eye_mm) < 1e-6,
      'Passenger eye remains exactly attached to the absolute cabin pose');
    await reset(); await settleLift();
    const result = await page.evaluate(id => window.__buildingWalkthrough.viewObject(id), liftObject.id);
    assert.equal(result.status, 'accepted'); await advance(32);
    await page.locator('[data-lift-call]').click(); await settleLift();
    // Queued inputs acquired outside the cabin must be cleared at boarding.
    await canvas.focus(); await down('w'); await down('ArrowLeft');
    await page.locator('[data-lift-enter]').click();
    assert.equal((await read()).elevator.boarded, true); await settled('Boarding clears outside keyboard inputs');
    await release(); attached(await read());
    await canvas.focus(); await down('ArrowRight');
    {const [a, b] = await segment(); turned(a, b, -1, 'Arrow yaw aboard the stationary lift'); attached(b);}
    await down('AltLeft'); await down('w'); await down('e'); await down('ShiftLeft');
    {const [a, b] = await segment(); stationary(a, b, 'All translation remains locked aboard'); attached(b);}
    await release();
    const origin = (await read()).elevator.state;
    const destination = Object.keys(liftObject.states).filter(level => level !== origin)
      .sort((a, b) => Math.abs(liftObject.states[a] - liftObject.states[origin]) - Math.abs(liftObject.states[b] - liftObject.states[origin]))[0];
    await page.locator(`[data-lift-floor="${destination}"]`).click();
    for (let attempt = 0; attempt < 8 && (await read()).elevator.state !== 'moving'; attempt++) await page.clock.fastForward(500);
    assert.equal((await read()).elevator.state, 'moving', 'A public floor button begins an animated ride');
    await canvas.focus(); await down('ArrowLeft'); await down('w'); await down('e');
    const rideBefore = await read(); await advance(160); const rideAfter = await read();
    attached(rideBefore); attached(rideAfter);
    assert(yawDelta(rideBefore, rideAfter) > .025, 'Arrow yaw remains available during the ride');
    assert.equal(rideBefore.camera.eye_mm[0], rideAfter.camera.eye_mm[0]);
    assert.equal(rideBefore.camera.eye_mm[1], rideAfter.camera.eye_mm[1]);
    assert.notEqual(rideBefore.elevator.value_mm, rideAfter.elevator.value_mm, 'The actual cabin moves during the attachment check');
    await release(); await settleLift(); attached(await read());
    await down('w'); await down('ArrowLeft');
    const exitPort = lift.ports.find(port => port.active && port.level_id === destination);
    await page.locator(`[data-lift-exit="${exitPort.side}"]`).click();
    const exited = await read(); assert.equal(exited.elevator.boarded, false);
    assert(distance(exited.camera.eye_mm, exitPort.exit_eye_mm) < .01, 'Exit uses the source-derived port');
    await settled('Exiting clears queued translation and yaw'); await release();
    report.lift = {from: origin, to: destination, ride_before: rideBefore, ride_after: rideAfter};
    report.checks.push('boarding/exit clear queued inputs', 'stationary and travelling lift attachment', 'lift yaw allowed and translation locked');
    progress('stationary and travelling lift controls passed');

    await reset(); await page.locator('#controls-browser-fixture').evaluate(node => node.remove());
    await page.screenshot({path: path.join(output, 'browser-controls-full-scene.png'), fullPage: true});
    report.help = {visible: await page.locator('#walkthrough-help').textContent(), aria: await canvas.getAttribute('aria-label')};
    assert.deepEqual(errors, [], 'Control interactions produce no browser errors');
    assert.deepEqual(network, [], liveURL ? 'Live controls request only the checked main document and optional browser favicon'
      : 'Standalone controls do not request external resources');
    report.passed = true;
    fs.writeFileSync(path.join(output, 'browser-controls-report.json'), JSON.stringify(report, null, 2) + '\n');
    console.log(JSON.stringify({passed: true, checks: report.checks, hidden_cleanup: report.hidden_cleanup,
      report: path.join(output, 'browser-controls-report.json')}));
  } catch (error) {
    report.passed = false; report.failure = error.stack || String(error);
    if (page) {
      report.last_state = await page.evaluate(() => ({camera: window.__buildingWalkthrough?.camera,
        elevator: window.__buildingWalkthrough?.elevator, error: document.querySelector('#building-walkthrough')?.dataset.error})).catch(() => null);
      await page.screenshot({path: path.join(output, 'browser-controls-failure.png'), fullPage: true, timeout: 15000}).catch(() => {});
    }
    fs.writeFileSync(path.join(output, 'browser-controls-report.json'), JSON.stringify(report, null, 2) + '\n');
    throw error;
  } finally {await browser.close();}
})().catch(error => {console.error(error); process.exitCode = 1;});
