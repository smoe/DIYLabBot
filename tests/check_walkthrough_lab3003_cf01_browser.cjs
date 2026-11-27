// Usage: node tests/check_walkthrough_lab3003_cf01_browser.cjs <index.html> <playwright> <chrome>
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {chromium} = require(process.argv[3] || 'playwright');

(async () => {
  const file = path.resolve(process.argv[2]);
  const html = fs.readFileSync(file, 'utf8');
  const model = JSON.parse(html.match(/<script id="walkthrough-data" type="application\/json">([\s\S]*?)<\/script>/)[1]);
  const {tr01_lap: lap, lab3003_cf01_cycle: cf01} = model;
  assert.equal(cf01.synthetic, true);
  assert.equal(cf01.arm_motion_checked, false);
  const expectedTubes = cf01.samples.map(sample => sample.id);
  const browser = await chromium.launch({headless:true, executablePath:process.argv[4],
    args:['--enable-webgl', '--ignore-gpu-blocklist', '--use-angle=swiftshader', '--enable-unsafe-swiftshader']});
  const page = await browser.newPage({viewport:{width:1440, height:1000}});
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', record => { if (record.type() === 'error') errors.push(record.text()); });
  const snapshot = () => page.evaluate(() => {
    const walkthrough = window.__buildingWalkthrough;
    return {lap:walkthrough.tr01Lap, station:walkthrough.lab3003CF01, stopId:walkthrough.stopId};
  });
  const click = id => page.locator('#' + id).click({force:true});
  async function advanceStationTo(target) {
    const {station} = await snapshot();
    await page.clock.fastForward(Math.max(34, Math.ceil((target - station.time_s) * 1000 / station.playback_rate)));
    return (await snapshot()).station;
  }

  try {
    await page.clock.install({time:new Date('2026-11-25T21:00:00Z')});
    await page.goto(pathToFileURL(file).href, {timeout:120000});
    await page.waitForFunction(() => window.__buildingWalkthrough?.ready ||
      !document.getElementById('walkthrough-error').hidden, null, {timeout:120000});
    assert.equal(await page.evaluate(() => window.__buildingWalkthrough?.ready), true,
      await page.locator('#walkthrough-error').textContent());
    await page.clock.pauseAt(new Date(await page.evaluate(() => Date.now() + 100)));
    assert.equal((await snapshot()).station.state, 'ready');

    await page.locator('#walkthrough-lap-time').evaluate((slider, end) => {
      slider.value = String(end);
      slider.dispatchEvent(new Event('input', {bubbles:true}));
    }, lap.duration_s);
    await page.clock.fastForward(1000);
    const scrubbed = await snapshot();
    assert.equal(scrubbed.lap.state, 'docked');
    assert.equal(scrubbed.lap.time_s, lap.duration_s);
    assert.equal(scrubbed.station.state, 'ready');
    assert.equal(scrubbed.station.cover_removed, false);
    assert.deepEqual(scrubbed.station.seated, []);

    await click('walkthrough-lap-reverse');
    await page.clock.fastForward(34);
    const reversing = await snapshot();
    assert.equal(reversing.lap.state, 'playing');
    assert.equal(reversing.lap.direction, 'reverse');
    assert.equal(reversing.station.state, 'ready');
    await page.clock.fastForward(Math.ceil((lap.duration_s - reversing.lap.time_s) * 1000 /
      reversing.lap.playback_rate) + 100);
    const actual = await snapshot();
    assert.equal(actual.lap.state, 'docked');
    assert.equal(actual.station.state, 'playing');
    assert.equal(actual.station.phase, 'docked');
    assert.equal(actual.station.cover_removed, false);

    const guarded = await page.evaluate(() =>
      window.__buildingWalkthrough.command('Lab3003.Freezer01.OuterDoor', 'open'));
    assert.equal(guarded.status, 'rejected_lap_active');
    await click('walkthrough-lap-play');
    const paused = (await snapshot()).station;
    assert.equal(paused.state, 'paused');
    assert.equal(await page.locator('#walkthrough-lap-reset').isDisabled(), true);
    await page.clock.fastForward(1000);
    assert.deepEqual((await snapshot()).station, paused);
    await click('walkthrough-lap-play');
    assert.equal((await snapshot()).station.state, 'playing');

    await click('walkthrough-cf01-view');
    assert.equal((await snapshot()).stopId, cf01.stop_id);
    const cutaway = page.locator('#walkthrough-cf01-cutaway');
    assert.equal(await cutaway.isChecked(), false);
    const beforeSpin = await advanceStationTo(cf01.spin_started_s - 0.13);
    assert.deepEqual(beforeSpin.seated, expectedTubes);
    assert.equal(beforeSpin.rpm, 0);
    assert.equal(beforeSpin.lid_locked, true);
    assert.equal(beforeSpin.brake_held, true);
    await cutaway.check({force:true});
    const spin = await advanceStationTo(cf01.spin_started_s + 0.3);
    assert.equal(spin.phase, 'spinning');
    assert(spin.rpm > 0);
    assert.equal(spin.lid_deg, 0);
    assert.equal(spin.lid_locked, true);
    assert.equal(spin.brake_held, false);
    assert.match(await page.locator('#walkthrough-cf01-phase').textContent(), /CF01 schleudert/);
    assert.match(await page.locator('#walkthrough-cf01-status').textContent(), /2\/2 Tubes.*verriegelt.*Rotorschnitt/);
    const canvas = page.locator('#walkthrough-canvas');
    const frame = await canvas.evaluate(element => element.toDataURL());
    const laterSpin = await advanceStationTo(cf01.spin_started_s + 0.69);
    assert.equal(laterSpin.phase, 'spinning');
    assert.notEqual(laterSpin.rotor_deg, spin.rotor_deg);
    assert.notEqual(await canvas.evaluate(element => element.toDataURL()), frame,
      'The cutaway should show actual WebGL movement with the closed lid in simulation.');

    const braking = await advanceStationTo((cf01.brake_started_s + cf01.stopped_s) / 2);
    assert.equal(braking.phase, 'braking');
    assert(braking.rpm > 0 && braking.rpm < spin.rpm);
    assert.equal(braking.lid_locked, true);
    assert.equal(braking.brake_held, false);
    const stopped = await advanceStationTo(cf01.stopped_s + 0.2);
    assert.equal(stopped.state, 'completed');
    assert.equal(stopped.phase, 'stopped');
    assert.equal(stopped.rpm, 0);
    assert.equal(stopped.lid_locked, true);
    assert.equal(stopped.brake_held, true);
    assert.deepEqual(stopped.seated, expectedTubes);
    assert.match(await page.locator('#walkthrough-cf01-phase').textContent(), /Stillstand bestätigt/);
    await page.clock.fastForward(2000);
    assert.deepEqual((await snapshot()).station, stopped);
    assert.equal((await snapshot()).lap.state, 'docked');
    assert.equal(await page.locator('#walkthrough-lap-play').isDisabled(), true);

    await click('walkthrough-lap-reset');
    await page.clock.fastForward(34);
    const reset = await snapshot();
    assert.equal(reset.lap.state, 'ready');
    assert.equal(reset.station.state, 'ready');
    assert.equal(reset.station.cover_removed, false);
    assert.deepEqual(reset.station.seated, []);
    assert.deepEqual(errors, []);
    console.log('Standalone walkthrough, confirmed TR01 return, visible CF01 spin, held stop and explicit reset passed.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
