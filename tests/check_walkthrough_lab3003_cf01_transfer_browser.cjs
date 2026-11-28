// Usage: node tests/check_walkthrough_lab3003_cf01_transfer_browser.cjs <index.html> <playwright> <chrome>
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {chromium} = require(process.argv[3] || 'playwright');

function near(a, b, tolerance = 1e-6) {
  assert(Math.abs(a-b) <= tolerance, `Expected ${a} within ${tolerance} of ${b}`);
}

async function main() {
  assert(process.argv[2], 'A completed native ArmC preview is required.');
  const file = path.resolve(process.argv[2]);
  const folder = path.dirname(file);
  const html = fs.readFileSync(file, 'utf8');
  const report = JSON.parse(fs.readFileSync(path.join(folder, 'preview-report.json'), 'utf8'));
  const htmlHash = crypto.createHash('sha256').update(html).digest('hex');
  assert.equal(report.passed, true);
  assert.equal(report.html_sha256, htmlHash);
  const inline = html.match(/<script id="walkthrough-data" type="application\/json">([\s\S]*?)<\/script>/);
  assert(inline, 'A standalone preview with embedded native scene data is required.');
  const model = JSON.parse(inline[1]);
  const {lab3003_cf01_cycle: cycle} = model;
  const departure = model.tr01_lap;
  const hasReturns = Array.isArray(cycle.return_samples);
  assert(!departure || hasReturns && departure.half_turn && !departure.autoplay,
    'The docked arm may release only a checked, non-repeating departure lap.');
  assert.equal(cycle.arm_motion_checked, true);
  assert.equal(cycle.synthetic, true);
  assert(cycle.docked_start);
  assert.equal(cycle.arm_motion.program_sha256, report.arm_program_sha256);
  assert.equal(cycle.arm_motion.collision_report_sha256, report.collision_report_sha256);
  const groups = model.scenes[cycle.scene].groups;
  const armBodies = cycle.arm_motion.joints.map(joint => joint.body_ids[0]);
  const vesselBodies = cycle.samples.map(sample => sample.carrier_body_id);
  const pusherBody = cycle.joints.pusher.body_ids[0];
  const requested = [...armBodies, ...vesselBodies, pusherBody, cycle.cover_body_id, ...cycle.empty_rotor_body_ids];
  assert.equal(new Set(requested).size, requested.length);
  for (const id of requested) assert.equal(groups.filter(group => group.id === id).length, 1, id);

  const gpu = process.env.SOLIDCRAFTBOT_WALKTHROUGH_GPU === 'metal' ? ['--use-angle=metal'] :
    ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'];
  const browser = await chromium.launch({headless: true, executablePath: process.argv[4],
    args: ['--enable-webgl', '--ignore-gpu-blocklist', ...gpu]});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', record => { if (record.type() === 'error') errors.push(record.text()); });
    // Pass through the viewer's real transforms and visibility decisions while
    // observing which native IDs the scene actually asks the runtime to draw.
    await page.addInitScript(bodyIds => {
      const wanted = new Set(bodyIds);
      window.__cf01Rendered = {matrices: {}, hidden: {}};
      let api;
      Object.defineProperty(window, 'WalkthroughLab3003CF01', {
        get: () => api,
        set: original => {
          api = {...original, create(...args) {
            const runtime = original.create(...args);
            const renderer = Object.create(runtime);
            renderer.hidden = id => {
              const hidden = runtime.hidden(id);
              if (wanted.has(id)) window.__cf01Rendered.hidden[id] = hidden;
              return hidden;
            };
            renderer.modelMatrix = id => {
              const matrix = runtime.modelMatrix(id);
              if (wanted.has(id)) window.__cf01Rendered.matrices[id] = matrix ? Array.from(matrix) : null;
              return matrix;
            };
            return renderer;
          }};
        },
      });
    }, requested);
    await page.clock.install({time: new Date('2026-11-25T21:00:00Z')});
    await page.goto(pathToFileURL(file).href, {timeout: 120000});
    await page.waitForFunction(() => window.__buildingWalkthrough?.ready ||
      !document.getElementById('walkthrough-error').hidden, null, {timeout: 120000});
    assert.equal(await page.evaluate(() => window.__buildingWalkthrough?.ready), true,
      await page.locator('#walkthrough-error').textContent());
    await page.clock.pauseAt(new Date(await page.evaluate(() => Date.now() + 100)));
    const snapshot = () => page.evaluate(() => {
      const view = window.__buildingWalkthrough;
      return {station: view.lab3003CF01, lap: view.tr01Lap, stop: view.stopId, frames: view.frames,
        renderer: view.renderer, rendered: window.__cf01Rendered};
    });
    const play = page.locator('#walkthrough-cf01-play');
    const stationView = page.locator('#walkthrough-cf01-view');
    const phase = page.locator('#walkthrough-cf01-phase');
    const canvas = page.locator('#walkthrough-canvas');
    const image = () => canvas.evaluate(element => element.toDataURL());
    const fixture = 'Lab3003.Freezer01.OuterDoor';
    const freezer = model.objects.find(item => item.id === fixture);
    assert(freezer?.commands.open && freezer?.commands.close);
    const changeFixture = name => page.evaluate(({id, name}) => window.__buildingWalkthrough.command(id, name),
      {id: fixture, name});
    async function at(target) {
      const before = await snapshot();
      assert(target >= before.station.time_s, 'Browser test witnesses stay ordered.');
      await page.evaluate(() => { window.__cf01Rendered = {matrices: {}, hidden: {}}; });
      const elapsed = (target-before.station.time_s) * 1000 / before.station.playback_rate;
      await page.clock.fastForward(Math.max(18, Math.ceil(elapsed)+1));
      const after = await snapshot();
      assert(after.frames > before.frames, 'A new WebGL frame should reflect the current motion time.');
      assert(after.station.time_s + 1e-6 >= Math.min(target, cycle.duration_s));
      return after;
    }
    const openIndices = [];
    async function checkOpenIndex(prefix) {
      const before = cycle.steps.find(step => step.phase === prefix+'open_indexing');
      const after = cycle.steps.find(step => step.phase === prefix+'open_indexed');
      const lidId = cycle.joints.lid.body_ids[0];
      const start = await at(before.time_s+0.02);
      assert.equal(start.station.phase, before.phase);
      assert.deepEqual(start.station.seated, before.seated);
      const carried = cycle.samples.find(sample => sample.id === before.seated[0]).carrier_body_id;
      const lid = await page.evaluate(id => window.__buildingWalkthrough.bodyMatrix(id), lidId);
      const mid = await at((before.time_s+after.time_s)/2);
      assert.equal(mid.station.phase, before.phase);
      assert.equal(mid.station.lid_deg, before.lid_deg);
      assert.equal(mid.station.rpm, 0);
      assert.equal(mid.station.pusher_mm, 0);
      assert.equal(mid.station.held_tube, null);
      assert.equal(mid.station.arm_clear, true);
      assert.equal(mid.station.brake_held, false);
      assert.deepEqual(await page.evaluate(id => window.__buildingWalkthrough.bodyMatrix(id), lidId), lid);
      assert.notDeepEqual(mid.rendered.matrices[carried], start.rendered.matrices[carried]);
      for (const id of armBodies) assert.deepEqual(mid.rendered.matrices[id], start.rendered.matrices[id]);
      if (departure) assert.equal(mid.lap.time_s, 0);
      const done = await at(after.time_s+0.01);
      assert.equal(done.station.phase, after.phase);
      assert.equal(done.station.brake_held, true);
      assert.equal(done.station.lid_deg, before.lid_deg);
      openIndices.push({phase: before.phase, tube_id: before.tube_id, start_s: before.time_s,
        end_s: after.time_s, lid_deg: before.lid_deg, rotation_deg: after.rotor_deg-before.rotor_deg});
    }

    const initial = await snapshot();
    assert.equal(initial.renderer, 'webgl2');
    if (departure) assert.equal(initial.lap.time_s, 0);
    else assert.equal(initial.lap, null);
    assert.equal(initial.station.state, 'ready');
    assert.equal(initial.station.playback_rate, 4);
    assert.match(await page.locator('#walkthrough-cf01-status').textContent(), /4× · Modellzeit 0:00 \/ /);
    assert.equal(initial.station.cover_removed, false);
    assert.equal(initial.rendered.hidden[cycle.cover_body_id], false);
    assert.deepEqual(initial.station.seated, []);
    for (const id of armBodies) assert.equal(initial.rendered.matrices[id]?.length, 16, id);
    assert.equal(await changeFixture('open').then(reply => reply.status), 'accepted');
    await page.clock.fastForward(Math.ceil(freezer.duration_s*1000)+100);
    await play.click({force: true});
    await page.clock.fastForward(34);
    assert.equal((await snapshot()).station.time_s, 0);
    assert.match(await phase.textContent(), /Prüfstellung wiederherstellen/);
    assert.equal(await changeFixture('close').then(reply => reply.status), 'accepted');
    await page.clock.fastForward(Math.ceil(freezer.duration_s*1000)+100);
    await play.click({force: true});
    const coverRemoval = cycle.steps.find(step => step.phase === 'cover_removed').time_s;
    assert.equal((await at(coverRemoval/2)).station.cover_removed, false);
    const covered = await at(coverRemoval+0.1);
    assert.equal(covered.stop, cycle.docked_start.stop_id);
    assert.equal(covered.station.cover_removed, true);
    assert.equal(covered.rendered.hidden[cycle.cover_body_id], true);
    assert.equal((await changeFixture('open')).status, 'rejected_lap_active');

    const witnesses = [];
    let seated = [];
    for (const [index, sample] of cycle.samples.entries()) {
      const active = await at((sample.grip_s+sample.support_release_s)/2);
      const beforeTransferImage = await image();
      assert.equal(active.station.held_tube, sample.id);
      assert.equal(active.station.pusher_sample_id, null);
      assert.equal(active.station.arm_clear, false);
      assert.deepEqual(active.station.seated, seated);
      assert(active.station.arm_joints_deg.some((q, i) =>
        Math.abs(q-(cycle.arm_motion.home_deg ?? cycle.arm_motion.reference_deg)[i]) > 1e-3));
      assert(armBodies.some(id => active.rendered.matrices[id]?.some((value, entry) =>
        Math.abs(value-initial.rendered.matrices[id][entry]) > 1e-4)));
      assert.equal(active.rendered.hidden[sample.carrier_body_id], false);
      assert(active.rendered.matrices[sample.carrier_body_id]);

      const raised = await at((sample.support_release_s+sample.arm_clear_s)/2);
      assert.notEqual(await image(), beforeTransferImage, 'ArmC changes the actual WebGL scene.');
      assert.equal(raised.station.held_tube, null);
      assert.equal(raised.station.pusher_sample_id, sample.id);
      assert(raised.station.lift_mm > 0);
      assert(raised.station.pusher_mm > raised.station.lift_mm);
      assert.equal(raised.station.brake_held, true);
      assert.equal(raised.station.rpm, 0);
      assert.equal(raised.rendered.hidden[sample.carrier_body_id], false);
      assert(raised.rendered.matrices[sample.carrier_body_id]);
      assert.deepEqual(raised.station.seated, seated);
      for (const id of cycle.empty_rotor_body_ids) assert.equal(raised.rendered.hidden[id], true);
      if (index === 0) {
        await play.click({force: true});
        await page.clock.fastForward(34);
        const paused = (await snapshot()).station;
        assert.equal(paused.state, 'paused');
        assert.equal(paused.pusher_sample_id, sample.id);
        await stationView.click({force: true});
        await page.clock.fastForward(34);
        assert.equal((await snapshot()).stop, cycle.stop_id);
        const still = await image();
        assert(still.startsWith('data:image/png;base64,'));
        fs.writeFileSync(path.join(folder, 'pusher-handoff.png'), Buffer.from(still.split(',')[1], 'base64'));
        await page.locator(`#walkthrough-stops [data-stop="${cycle.docked_start.stop_id}"]`).click({force: true});
        await page.clock.fastForward(34);
        await page.clock.fastForward(1000);
        assert.deepEqual((await snapshot()).station, paused, 'A partial handoff stays owned while paused.');
        assert.match(await play.textContent(), /fortsetzen/);
        await play.click({force: true});
      }

      const event = name => cycle.steps.find(step => step.tube_id === sample.id && step.phase === name).time_s;
      const lowering = await at((event('lowering')+event('pocket_reached'))/2);
      assert.equal(lowering.station.arm_clear, true);
      assert.equal(lowering.station.pusher_sample_id, sample.id);
      assert(lowering.station.lift_mm > 0 && lowering.station.lift_mm < raised.station.lift_mm);
      const axis = cycle.joints.pusher.axis;
      const descent = axis.reduce((sum, value, i) => sum + value*1000*
        (raised.rendered.matrices[sample.carrier_body_id][12+i]-lowering.rendered.matrices[sample.carrier_body_id][12+i]), 0);
      near(descent, raised.station.lift_mm-lowering.station.lift_mm, 0.02);
      assert.notDeepEqual(lowering.rendered.matrices[pusherBody], raised.rendered.matrices[pusherBody]);
      const parked = await at(sample.pusher_lowered_s+0.03);
      seated = [...seated, sample.id];
      assert.deepEqual(parked.station.seated, seated);
      assert.equal(parked.station.pusher_sample_id, null);
      assert.equal(parked.station.pusher_mm, 0);
      assert.equal(parked.station.lift_mm, 0);
      assert.equal(parked.rendered.hidden[sample.carrier_body_id], false);
      assert(parked.rendered.matrices[sample.carrier_body_id]);
      for (const id of cycle.empty_rotor_body_ids) assert.equal(parked.rendered.hidden[id], true);
      witnesses.push({id: sample.id, native_body_id: sample.carrier_body_id, carried_s: active.station.time_s,
        supported_s: raised.station.time_s, lowering_s: lowering.station.time_s, seated_s: parked.station.time_s,
        measured_lowering_mm: descent});
      if (index === 0 && cycle.open_lid_indexing) await checkOpenIndex('');
    }

    const spinStart = await at(cycle.spin_started_s-0.08);
    assert.equal(spinStart.station.lid_locked, true);
    assert.equal(spinStart.station.brake_held, true);
    assert.equal(spinStart.station.rpm, 0);
    assert.equal(spinStart.station.pusher_mm, 0);
    assert.deepEqual(spinStart.station.seated, seated);
    const spinning = await at((cycle.spin_started_s+cycle.brake_started_s)/2);
    assert.equal(spinning.station.phase, 'spinning');
    assert.equal(spinning.station.lid_locked, true);
    assert.equal(spinning.station.brake_held, false);
    assert(spinning.station.rpm > 0);
    for (const id of vesselBodies) assert.notDeepEqual(spinning.rendered.matrices[id], spinStart.rendered.matrices[id]);
    const braking = await at((cycle.brake_started_s+cycle.stopped_s)/2);
    assert.equal(braking.station.phase, 'braking');
    assert(braking.station.rpm > 0 && braking.station.rpm < spinning.station.rpm);
    assert.equal(braking.station.brake_held, false);
    const stopped = await at(cycle.stopped_s+0.15);
    assert.equal(stopped.station.state, hasReturns ? 'playing' : 'completed');
    assert.equal(stopped.station.brake_held, true);
    assert.equal(stopped.station.rpm, 0);
    assert.deepEqual(stopped.station.seated, seated);
    const returned = [];
    if (hasReturns) for (const sample of cycle.return_samples) {
      const body = cycle.samples.find(item => item.id === sample.id).carrier_body_id;
      const contact = cycle.steps.find(step => step.tube_id === sample.id && step.phase === 'pickup_contact').time_s;
      const base = await at(contact+0.02);
      assert.equal(base.station.pusher_sample_id, sample.id);
      assert(!base.station.seated.includes(sample.id));
      const lifted = await at((contact+sample.arm_start_s)/2);
      assert.equal(lifted.station.pusher_sample_id, sample.id);
      assert(lifted.station.lift_mm > base.station.lift_mm);
      const rise = cycle.joints.pusher.axis.reduce((sum, value, i) => sum + value*1000*
        (lifted.rendered.matrices[body][12+i]-base.rendered.matrices[body][12+i]), 0);
      near(rise, lifted.station.lift_mm-base.station.lift_mm, 0.02);
      const grasp = await at((sample.grip_s+sample.cassette_release_s)/2);
      assert.equal(grasp.station.held_tube, sample.id);
      assert.equal(grasp.station.transport_ready, false);
      assert.notDeepEqual(grasp.rendered.matrices[body], lifted.rendered.matrices[body]);
      const cassette = await at(sample.cassette_release_s+0.03);
      assert.equal(cassette.station.held_tube, null);
      assert.equal(cassette.rendered.hidden[body], false);
      assert.equal(cassette.rendered.matrices[body], null, 'The original body is now mounted back in TR01.');
      assert.equal(cassette.station.transport_ready, false);
      assert.equal(cassette.station.cover_removed, true);
      const clear = await at(sample.pusher_parked_s+0.03);
      assert.equal(clear.station.arm_clear, true);
      assert.equal(clear.station.pusher_mm, 0);
      if (departure) assert.equal(clear.lap.time_s, 0, 'TR01 remains docked during unloading.');
      returned.push({id: sample.id, native_body_id: body, lifted_s: lifted.station.time_s,
        carried_s: grasp.station.time_s, cassette_s: cassette.station.time_s, measured_rise_mm: rise});
      assert.deepEqual(clear.station.returned, returned.map(item => item.id));
      if (returned.length === 1 && cycle.open_lid_indexing) await checkOpenIndex('return_');
    }
    const ready = hasReturns ? await at(cycle.duration_s) : stopped;
    if (hasReturns) {
      assert.equal(ready.station.state, 'completed');
      assert.equal(ready.station.transport_ready, true);
      assert.equal(ready.station.cover_removed, false);
      assert.equal(ready.rendered.hidden[cycle.cover_body_id], false);
      assert.equal(ready.station.lid_locked, true);
      assert.deepEqual(ready.station.seated, []);
      assert.deepEqual(ready.station.returned, returned.map(item => item.id));
    }
    let lap = null;
    if (departure) {
      await page.clock.fastForward(34);
      assert.equal((await snapshot()).lap.state, 'playing', 'TR01 starts by itself after the station releases it.');
      async function lapAt(t) {
        const {lap: before} = await snapshot();
        const elapsed = (t-before.time_s)*1000/before.playback_rate;
        await page.clock.fastForward(Math.max(18, Math.ceil(elapsed)+1));
        const after = await snapshot();
        assert(after.lap.time_s + 1e-6 >= Math.min(t, departure.duration_s));
        return after;
      }
      async function assertMounted(lapState) {
        const bodies = await page.evaluate(ids => ids.map(id => window.__buildingWalkthrough.bodyMatrix(id)),
          [...vesselBodies, cycle.cover_body_id]);
        assert(bodies.every(matrix => matrix?.length === 16 && matrix.every((value, i) =>
          Math.abs(value-lapState.matrix[i]) < 1e-6)), 'The WebGL body owners keep both tubes and the cover on TR01.');
      }
      const turn = departure.half_turn;
      const [turnStart, turnEnd] = [turn.start_s, turn.end_s].map(time =>
        departure.points.find(point => point.time_s === time).pose_mm_rad);
      for (const i of [0, 1]) near(turnEnd[i], turnStart[i]);
      near(turnEnd[2]-turnStart[2], Math.PI);
      const pivot = await lapAt((turn.start_s+turn.end_s)/2);
      assert.equal(pivot.lap.direction, 'pivot');
      assert(pivot.station.transport_ready && !pivot.station.cover_removed);
      await assertMounted(pivot.lap);
      assert.equal((await changeFixture('open')).status, 'rejected_lap_active');
      assert(await page.locator('#walkthrough-lap-reset').isDisabled());
      const docked = await lapAt(departure.duration_s);
      assert.equal(docked.lap.state, 'docked');
      for (const i of [0, 1]) near(docked.lap.pose_mm_rad[i], initial.lap.pose_mm_rad[i]);
      const delta = docked.lap.pose_mm_rad[2]-initial.lap.pose_mm_rad[2];
      near(Math.cos(delta), -1);
      near(Math.sin(delta), 0);
      await assertMounted(docked.lap);
      await page.clock.fastForward(1000);
      assert.deepEqual((await snapshot()).lap, docked.lap, 'TR01 remains in the opposite orientation without replay.');
      lap = {pivot_s: pivot.lap.time_s, docked_s: docked.lap.time_s, pose_mm_rad: docked.lap.pose_mm_rad};
    } else {
      await page.clock.fastForward(1000);
    }
    assert.deepEqual((await snapshot()).station, ready.station);
    const reset = departure ? page.locator('#walkthrough-lap-reset') : play;
    assert(!(await reset.isDisabled()));
    assert.match(await reset.textContent(), /neu starten|zurücksetzen/);
    await reset.click({force: true});
    const afterReset = await snapshot();
    const replay = afterReset.station;
    assert.equal(replay.time_s, 0);
    assert.equal(replay.cover_removed, false);
    assert.deepEqual(replay.seated, []);
    if (departure) assert.equal(afterReset.lap.time_s, 0);
    assert.deepEqual(errors, []);

    const result = {passed: true, html_sha256: htmlHash, renderer: initial.renderer, handoffs: witnesses,
      returned, lap, open_lid_indices: openIndices,
      spin_s: spinning.station.time_s, confirmed_stillstand_s: stopped.station.time_s, console_errors: errors};
    fs.writeFileSync(path.join(folder, 'transfer-browser-check.json'), JSON.stringify(result, null, 2)+'\n');
    console.log(JSON.stringify(result));
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
