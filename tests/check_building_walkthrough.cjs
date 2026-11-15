// Usage: node tests/check_building_walkthrough.cjs <index.html> [playwright-module] [chrome-executable]
// Exercise the derived native scene through the same controls exposed to visitors.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const {pathToFileURL} = require('node:url');
const {chromium} = require(process.argv[3] || 'playwright');

(async () => {
  assert(process.argv[2], 'A generated walk-through HTML file is required.');
  const target = path.resolve(process.argv[2]);
  const html = fs.readFileSync(target, 'utf8');
  const inline = html.match(/<script id="walkthrough-data" type="application\/json">([\s\S]*?)<\/script>/);
  assert(inline, 'A standalone inline scene is required.');
  const model = JSON.parse(inline[1]);
  assert(model.scenes.building && model.scenes.lab, 'Building and separate lab frames are required.');
  for (const id of ['phd', 'lab', 'kitchen', 'atrium', 'seating']) {
    assert(model.stops.some(stop => stop.id === id), `The ${id} viewpoint is required.`);
  }
  assert(!/<script[^>]+src=|<link[^>]+href=["']https?:/i.test(html), 'The viewer must work without external libraries.');
  const output = path.dirname(target);
  const browser = await chromium.launch({headless: true,
    ...(process.argv[4] ? {executablePath: process.argv[4]} : {}),
    args: ['--enable-webgl', '--ignore-gpu-blocklist', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
  });
  try {
    const page = await browser.newPage({viewport: {width: 1280, height: 950}, reducedMotion: 'reduce'});
    const errors = [], network = [];
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
      browser: {engine: 'chromium', version: browser.version()}, viewpoints: [], detail_views: [], interactions: []};
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
      if (stop.scene === 'lab') assert.match(await page.locator('#walkthrough-context').textContent(), /separate local room model/);
      const pixels = await page.evaluate(() => {
        const canvas = document.querySelector('#walkthrough-canvas'), gl = canvas.getContext('webgl2');
        const bytes = new Uint8Array(canvas.width * canvas.height * 4);
        gl.readPixels(0, 0, canvas.width, canvas.height, gl.RGBA, gl.UNSIGNED_BYTE, bytes);
        const colors = new Set(); let samples = 0, geometry = 0;
        for (let i = 0; i < bytes.length; i += 4 * 23) {
          colors.add(`${bytes[i] >> 3},${bytes[i + 1] >> 3},${bytes[i + 2] >> 3}`); samples++;
          if (Math.abs(bytes[i] - 201) + Math.abs(bytes[i + 1] - 217) + Math.abs(bytes[i + 2] - 214) > 12) geometry++;
        }
        return {colors: colors.size, geometry_fraction: geometry / samples, gl_error: gl.getError()};
      });
      assert.equal(pixels.gl_error, 0, `${stop.id}: WebGL error`);
      assert(pixels.colors > 6 && pixels.geometry_fraction > .04, `${stop.id}: blank or featureless image ${JSON.stringify(pixels)}`);
      const screenshot = `browser-${String(stop.id).replace(/[^a-z0-9_-]/gi, '-')}.png`;
      await page.screenshot({path: path.join(output, screenshot), fullPage: true});
      report.viewpoints.push({id: stop.id, scene: stop.scene, stats: state.stats, pixels, screenshot});
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
            .map((value, axis) => value - before[axis])) >= distance, {before, distance}, {timeout: 15000});
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
        .map((value, axis) => value - before[axis])) > 100, initial.camera.eye_mm, {timeout: 15000});
    } finally {await page.keyboard.up('w');}
    const walked = await read();
    assert(cameraDistance(initial.camera.eye_mm, walked.camera.eye_mm) > 100, 'W moves the camera');
    report.interactions.push('keyboard horizontal movement');
    await page.keyboard.down('e');
    try {
      await page.waitForFunction(z => window.__buildingWalkthrough.camera.eye_mm[2] > z + 80,
        walked.camera.eye_mm[2], {timeout: 15000});
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
        .map((value, axis) => value - before[axis])) > 100, looked.camera.eye_mm, {timeout: 15000});
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
    assert.equal(network.length, 0, 'The viewer makes no network requests');
    assert.deepEqual(errors, [], 'No browser or renderer errors');
    assert((await read()).frames > initial.frames, 'Controls request new rendered frames');

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
  } finally {await browser.close();}
})().catch(error => {console.error(error); process.exitCode = 1;});
