// Usage: node tests/check_walkthrough_ice_maker_browser.cjs <index.html> [playwright-module] [chrome-executable] [evidence-directory]
// Real inputs exercise the complete native scene. Animation time is controlled;
// the isolated distance check uses the same picker and actual flap triangles.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const {pathToFileURL} = require('node:url');
const {chromium} = require(process.argv[3] || 'playwright');
const picking = require('../scripts/walkthrough_interaction.js');

(async () => {
  assert(process.argv[2], 'A generated standalone walkthrough HTML file is required.');
  const target = path.resolve(process.argv[2]), bytes = fs.readFileSync(target), html = bytes.toString('utf8');
  const inline = html.match(/<script id="walkthrough-data" type="application\/json">([\s\S]*?)<\/script>/);
  assert(inline, 'The checked scene must be embedded in the page.');
  const model = JSON.parse(inline[1]), id = 'Lab3016.IceMakerIM01.Flap', body = 'Lab3016_IceMakerIM01_HopperFlap';
  const object = model.objects.find(row => row.id === id), scene = model.scenes.building;
  assert(object, 'The placed IM01 needs its source-derived flap articulation.');
  assert.equal(object.reference_state, 'closed');
  assert.equal(object.initial_state || object.reference_state, 'closed');
  assert.deepEqual(object.states, {closed: 0, open: 85});
  assert(object.moving_body_ids.includes(body));
  assert.equal(model.objects.filter(row => row.moving_body_ids.includes(body)).length, 1);
  const group = scene.groups.find(row => row.id === body);
  assert(group && group.index_count > 0 && group.level_id === 'OG3', 'The moving flap must have native triangles on OG3.');
  assert(html.includes(fs.readFileSync(path.join(__dirname, '../scripts/walkthrough_interaction.js'), 'utf8')),
    'The numerical range check must use the exact picker embedded in this page.');
  const reach = model.interaction.reach_mm;
  assert(Number.isFinite(reach) && reach > 0);
  const output = path.resolve(process.argv[5] || path.dirname(target));
  assert(/(^|[/\\])exports([/\\]|$)/.test(output), 'Write QA artifacts beneath ignored exports/.');
  fs.mkdirSync(output, {recursive: true});
  const report = {
    passed: false, html_sha256: crypto.createHash('sha256').update(bytes).digest('hex'), html_bytes: bytes.length,
    object_id: id, native_body_id: body, reach_mm: reach, browser_profile: 'software', inputs: [], errors: [],
  };
  const browser = await chromium.launch({headless: true,
    ...(process.argv[4] ? {executablePath: process.argv[4]} : {}),
    args: ['--enable-webgl', '--ignore-gpu-blocklist', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
  });
  let page;
  try {
    page = await browser.newPage({viewport: {width: 1280, height: 950}, reducedMotion: 'reduce'});
    page.setDefaultTimeout(120000);
    page.on('pageerror', error => report.errors.push(error.message));
    // Installing before navigation preserves every animation-frame callback.
    await page.clock.install({time: new Date('2026-11-22T12:00:00Z')});
    await page.goto(pathToFileURL(target).href, {timeout: 120000});
    await page.waitForFunction(() => window.__buildingWalkthrough?.ready);
    assert.equal(await page.locator('[data-object-action]').count(), 0, 'Object-specific command buttons are not used.');
    const read = () => page.evaluate(id => window.__buildingWalkthrough.objects.find(row => row.id === id), id);
    const otherStates = () => page.evaluate(id => window.__buildingWalkthrough.objects
      .filter(row => row.id !== id).map(row => [row.id, row.state, row.target_state, row.joint_value]), id);
    async function rendered(action) {
      const before = await page.evaluate(() => window.__buildingWalkthrough.frames);
      await action();
      await page.waitForFunction(before => window.__buildingWalkthrough.frames > before, before);
    }
    await rendered(() => page.evaluate(id => {
      const result = window.__buildingWalkthrough.viewObject(id);
      if (result.status !== 'accepted') throw Error('Cannot reach the source-derived flap viewpoint: ' + result.status);
    }, id));
    assert.equal((await read()).state, 'closed');
    const unchanged = await otherStates();
    const referencePoint = group.bounds_mm.min.map((value, axis) => (value + group.bounds_mm.max[axis]) / 2);
    for (const state of ['open', 'closed']) {
      const pixel = await page.evaluate(({id, point}) => {
        const v = window.__buildingWalkthrough, m = v.objects.find(row => row.id === id).model_matrix;
        const local = point.map(x => x / 1000);
        const world = [0, 1, 2].map(r => 1000 * (m[r] * local[0] + m[4+r] * local[1] + m[8+r] * local[2] + m[12+r]));
        const projected = v.projectPoint(world), canvas = document.getElementById('walkthrough-canvas'), box = canvas.getBoundingClientRect();
        return {x: box.x + projected.x * box.width / canvas.width,
                y: box.y + projected.y * box.height / canvas.height, visible: projected.visible};
      }, {id, point: referencePoint});
      assert(pixel.visible, `The native flap remains visible for mouse ${state}.`);
      await rendered(() => page.mouse.click(pixel.x, pixel.y));
      const live = await read(), interaction = await page.evaluate(() => window.__buildingWalkthrough.lastInteraction);
      assert.equal(interaction.id, id, JSON.stringify(interaction));
      assert.equal(interaction.input, 'click'); assert.equal(interaction.status, 'accepted');
      assert(Number.isFinite(interaction.distance_mm) && interaction.distance_mm <= reach);
      assert.equal(live.state, state); assert.equal(live.joint_value, object.states[state]);
      report.inputs.push({input: 'mouse', target_state: state, hit_distance_mm: interaction.distance_mm, angle_deg: live.angle_deg});
      await page.screenshot({path: path.join(output, `ice-maker-flap-${state}.png`)});
    }
    await rendered(() => page.evaluate(id => window.__buildingWalkthrough.viewObject(id), id));
    await page.locator('#walkthrough-canvas').focus();
    for (const state of ['open', 'closed']) {
      const hint = await page.evaluate(() => window.__buildingWalkthrough.interactionTarget);
      assert.equal(hint?.target_id, id, 'The real centre ray must offer this nearby flap.');
      await rendered(() => page.keyboard.press('Space'));
      const live = await read(), interaction = await page.evaluate(() => window.__buildingWalkthrough.lastInteraction);
      assert.equal(interaction.id, id, JSON.stringify(interaction));
      assert.equal(interaction.input, 'space'); assert.equal(interaction.status, 'accepted');
      assert(Number.isFinite(interaction.distance_mm) && interaction.distance_mm <= reach);
      assert.equal(live.state, state); assert.equal(live.joint_value, object.states[state]);
      report.inputs.push({input: 'space', target_state: state, hit_distance_mm: interaction.distance_mm, angle_deg: live.angle_deg});
    }
    assert.deepEqual(await otherStates(), unchanged, 'Flap inputs do not operate other joints.');
    report.mouse_open_close = report.space_open_close = true;

    function decode(encoded, Type) {
      const buffer = Buffer.from(encoded, 'base64');
      return new Type(buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength));
    }
    const positions = decode(scene.positions_base64, Float32Array), indices = decode(scene.indices_base64, Uint32Array);
    for (let i = 0; i < positions.length; i++) positions[i] /= 1000;
    const picker = picking.createPicker({positions, indices, groups: [group]});
    const normalize = v => {const length = Math.hypot(...v); return v.map(x => x / length);};
    const centre = referencePoint.map(x => x / 1000), eye = (await page.evaluate(() => window.__buildingWalkthrough.camera.eye_mm)).map(x => x / 1000);
    const outward = normalize(eye.map((value, axis) => value - centre[axis]));
    const radius = Math.hypot(...group.bounds_mm.max.map((value, axis) => value - group.bounds_mm.min[axis])) / 2000;
    const farDistance = reach / 1000 + radius + 0.5, far = centre.map((value, axis) => value + outward[axis] * farDistance);
    const direction = outward.map(value => -value), matrix = picking.jointMatrix(object.joint, object.states.closed, object.states[object.reference_state]);
    const options = {targetForBody: () => id, transformForBody: () => matrix, referenceTransformForBody: () => matrix};
    const near = picker.pick(eye, normalize(centre.map((value, axis) => value - eye[axis])), {reach: reach / 1000, ...options});
    assert.equal(near?.target_id, id, 'The isolated actual native triangles must also be eligible nearby.');
    const unrestricted = picker.pick(far, direction, {reach: farDistance + radius + 1, ...options});
    assert.equal(unrestricted?.target_id, id, 'The distant ray must still geometrically intersect the flap.');
    assert(unrestricted.distance_m * 1000 > reach);
    for (const includeReference of [false, true]) {
      assert.equal(picker.pick(far, direction, {reach: reach / 1000, includeReference, ...options}), null,
        'A geometrically aligned flap beyond reach is ineligible for mouse and Space.');
    }
    assert.equal((await read()).state, 'closed');
    report.range = {near_distance_mm: near.distance_m * 1000, aligned_far_distance_mm: unrestricted.distance_m * 1000,
      mouse_rejected: true, space_reference_rejected: true,
      scope: 'Isolated common picker on the actual native flap triangles; full-scene occlusion is covered by near real inputs.'};

    await page.emulateMedia({reducedMotion: 'no-preference'});
    const now = await page.evaluate(() => Date.now());
    await page.clock.pauseAt(new Date(now + 200));
    const started = await page.evaluate(id => {
      const v = window.__buildingWalkthrough;
      return {opening: v.command(id, 'open'), contradictory: v.command(id, 'close')};
    }, id);
    assert.equal(started.opening.status, 'accepted'); assert.equal(started.contradictory.status, 'rejected_busy');
    await page.clock.fastForward(object.duration_s * 350);
    const opening = await read(); assert.equal(opening.state, 'opening'); assert(opening.angle_deg > 0 && opening.angle_deg < 85);
    const hinge = object.joint.origin_mm.map(x => x / 1000), m = opening.model_matrix;
    const transformed = [0, 1, 2].map(r => m[r] * hinge[0] + m[4+r] * hinge[1] + m[8+r] * hinge[2] + m[12+r]);
    const hingeError = Math.hypot(...transformed.map((value, axis) => 1000 * (value - hinge[axis])));
    assert(hingeError < 0.02, 'The animated flap rotates about its source hinge.');
    await page.clock.fastForward(object.duration_s * 1000 + 50); assert.equal((await read()).state, 'open');
    assert.equal((await page.evaluate(id => window.__buildingWalkthrough.command(id, 'close'), id)).status, 'accepted');
    await page.clock.fastForward(object.duration_s * 350);
    const closing = await read(); assert.equal(closing.state, 'closing'); assert(closing.angle_deg > 0 && closing.angle_deg < 85);
    await page.clock.fastForward(object.duration_s * 1000 + 50); assert.equal((await read()).state, 'closed');
    assert.deepEqual(await otherStates(), unchanged); assert.deepEqual(report.errors, []);
    report.animation = {opening_intermediate_angle_deg: opening.angle_deg, closing_intermediate_angle_deg: closing.angle_deg,
      hinge_error_mm: hingeError, busy_rejected: true, timing: 'Playwright-controlled time; no rendering-performance claim.'};
    report.other_objects_unchanged = true; report.passed = true;
    console.log(JSON.stringify(report, null, 2));
  } catch (error) {
    report.failure = error.stack || String(error);
    if (page && !page.isClosed()) {
      try {report.last_interaction = await page.evaluate(() => window.__buildingWalkthrough?.lastInteraction);
        await page.screenshot({path: path.join(output, 'ice-maker-flap-failure.png')});} catch (_) {}
    }
    throw error;
  } finally {
    fs.writeFileSync(path.join(output, 'ice-maker-flap-browser-report.json'), JSON.stringify(report, null, 2) + '\n');
    await browser.close();
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
