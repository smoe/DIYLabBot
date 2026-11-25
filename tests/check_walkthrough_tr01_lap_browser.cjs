// Usage: node tests/check_walkthrough_tr01_lap_browser.cjs <index.html> <playwright> <chrome>
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {chromium} = require(process.argv[3] || 'playwright');

(async () => {
  const file = path.resolve(process.argv[2]);
  const html = fs.readFileSync(file, 'utf8');
  const model = JSON.parse(html.match(/<script id="walkthrough-data" type="application\/json">([\s\S]*?)<\/script>/)[1]);
  const lap = model.tr01_lap;
  assert.equal(lap.autoplay, true);
  assert.equal(model.default_stop, lap.stop_id);
  const lab = model.stops.find(stop => stop.id === model.default_stop);
  assert.equal(lab.anchor.opening, 'D3_003B');
  const labLevel = model.levels.find(level => level.id === lab.level_id);
  const dock = lap.points[0].pose_mm_rad;
  const dockMatrix = [1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1];
  const groups = model.scenes.building.groups.filter(group => lap.body_ids.includes(group.id));
  assert.equal(groups.length, 57);
  assert(groups.some(group => group.id === lap.cover_body_id && group.index_count > 0));
  const browser = await chromium.launch({headless:true, executablePath:process.argv[4],
    args:['--enable-webgl','--ignore-gpu-blocklist','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  const page = await browser.newPage({viewport:{width:1440,height:1000}});
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const snapshot = () => page.evaluate(() => window.__buildingWalkthrough.tr01Lap);
  const view = () => page.evaluate(() => {
    const walkthrough = window.__buildingWalkthrough;
    return {camera: walkthrough.camera, isolated: walkthrough.isolated, stopId: walkthrough.stopId};
  });
  async function hold(key, ms) {
    await page.keyboard.down(key);
    await page.clock.runFor(ms);
    await page.keyboard.up(key);
  }
  try {
    await page.clock.install({time:new Date('2026-11-25T21:00:00Z')});
    await page.goto(pathToFileURL(file).href, {timeout:120000});
    await page.waitForFunction(() => window.__buildingWalkthrough?.tr01Lap?.state === 'playing', null, {timeout:120000});
    await page.clock.pauseAt(new Date(await page.evaluate(() => Date.now()+1000)));
    const panel = page.locator('#walkthrough-lap');
    await panel.waitFor({state:'visible'});
    assert.match(await panel.innerText(), /mit Haube.*15 mm/);
    const entrance = await view();
    assert.equal(entrance.stopId, lab.id);
    assert.equal(entrance.isolated, false);
    assert(Math.abs(entrance.camera.eye_mm[2] - labLevel.z_mm - model.settings.eye_height_mm) < 1);
    await page.screenshot({path:path.join(path.dirname(file),'tr01-lab-entry.png')});

    await hold('q', 100);
    assert((await view()).camera.eye_mm[2] < entrance.camera.eye_mm[2] - 40);
    await page.locator('#walkthrough-return').click({force:true});
    await page.clock.fastForward(34);
    await page.keyboard.down('Shift');
    await hold('s', 450);
    await page.keyboard.up('Shift');
    const corridor = await view();
    assert(corridor.camera.eye_mm[1] > entrance.camera.eye_mm[1] + 1100);
    assert.equal(corridor.camera.eye_mm[2], entrance.camera.eye_mm[2]);
    assert.equal(await panel.isVisible(), false);
    assert.equal((await snapshot()).state, 'playing');
    await page.locator('#walkthrough-return').click({force:true});
    await page.clock.fastForward(34);
    assert.deepEqual(await view(), entrance);

    const play = page.locator('#walkthrough-lap-play');
    const initial = await snapshot();
    await page.clock.fastForward(12000);
    const inFlight = await snapshot();
    assert.equal(inFlight.state, 'playing');
    assert(Math.abs(inFlight.time_s - initial.time_s - 96) < 1);
    assert.notDeepEqual(inFlight.matrix, initial.matrix);
    await play.click({force:true});
    const paused = await snapshot();
    assert.equal(paused.state, 'paused');
    await page.clock.fastForward(2000);
    assert.deepEqual(await snapshot(), paused);

    const ordinaryLab = page.locator('[data-stop="lab"]');
    const adjacentRoom = page.locator('[data-stop="phd"]');
    await adjacentRoom.click({force:true});
    await page.clock.fastForward(34);
    assert.equal(await panel.isVisible(), false);
    await ordinaryLab.click({force:true});
    await page.clock.fastForward(34);
    assert.equal(await panel.isVisible(), true);
    assert.deepEqual(await snapshot(), paused);

    const freezer = await page.evaluate(() => window.__buildingWalkthrough.command('Lab3003.Freezer01.OuterDoor','open'));
    assert.equal(freezer.status, 'rejected_lap_active');
    const cam = (await view()).camera;
    await page.locator('#walkthrough-lap-follow').check({force:true});
    await page.clock.fastForward(34);
    const tracking = await view();
    assert.deepEqual(tracking.camera.eye_mm, cam.eye_mm);
    assert.notEqual(tracking.camera.yaw_rad, cam.yaw_rad);
    assert.equal(tracking.isolated, false);
    await page.screenshot({path:path.join(path.dirname(file),'tr01-lap-follow.png')});

    await page.locator('#walkthrough-lap-rate').selectOption('16');
    await play.click({force:true});
    await adjacentRoom.click({force:true});
    await page.clock.fastForward(34);
    const away = await snapshot();
    assert.equal(away.state, 'playing');
    assert.equal(await panel.isVisible(), false);
    await page.clock.fastForward(12000);
    const playedAway = await snapshot();
    assert.equal(playedAway.state, 'playing');
    assert(playedAway.time_s > away.time_s + 180);
    await ordinaryLab.click({force:true});
    await page.clock.fastForward(34);
    assert.equal((await snapshot()).state, 'playing');
    await page.clock.fastForward(Math.ceil((lap.duration_s-playedAway.time_s)*1000/16 + 250));
    const arrived = await snapshot();
    assert.equal(arrived.state, 'docked');
    assert.equal(arrived.time_s, lap.duration_s);
    assert.deepEqual(arrived.pose_mm_rad.slice(0, 2), dock.slice(0, 2));
    assert.deepEqual(arrived.matrix, dockMatrix);
    assert.equal(await page.locator('#walkthrough-lap-status').innerText(), 'Wieder angedockt');
    await page.clock.fastForward(34);
    const nextLap = await snapshot();
    assert.equal(nextLap.state, 'playing');
    assert(nextLap.time_s < 1);
    await page.clock.fastForward(12000);
    assert((await snapshot()).time_s > 180);
    await page.locator('#walkthrough-lap-reset').click({force:true});
    await page.clock.fastForward(1000);
    assert.equal((await snapshot()).state, 'ready');
    await page.locator('#walkthrough-lap-reverse').click({force:true});
    const shift = await snapshot();
    assert.equal(shift.time_s, lap.reversal.time_s);
    assert.equal(shift.direction, 'reverse');
    assert.equal(shift.playback_rate, 1);
    await page.clock.fastForward(3000);
    const backing = await snapshot();
    assert(backing.pose_mm_rad[1] > shift.pose_mm_rad[1]);
    assert(Math.abs(backing.pose_mm_rad[2] - shift.pose_mm_rad[2]) < .1);
    assert.equal(await page.locator('#walkthrough-lap-status').innerText(), 'Rückwärts zum Dock');
    const reverseView = await view();
    assert.equal(reverseView.stopId, lab.id);
    assert.equal(reverseView.isolated, false);
    assert.deepEqual(reverseView.camera.eye_mm, entrance.camera.eye_mm);
    await page.screenshot({path:path.join(path.dirname(file),'tr01-reverse-docking.png')});
    await page.clock.fastForward(Math.ceil((lap.duration_s-backing.time_s)*1000 + 250));
    await page.clock.fastForward(1000);
    assert.equal((await snapshot()).state, 'docked');
    assert.deepEqual(errors, []);
    console.log('Eye-level startup, physical exit into the corridor, automatic repeat during navigation, fixture interlock and exact redocking passed.');
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
