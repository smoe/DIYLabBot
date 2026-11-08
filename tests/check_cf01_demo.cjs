// Usage: node tests/check_cf01_demo.cjs <generated.html> [playwright-module] [chrome-executable] [failed-batch-report ...]
// Exercise the current template with real meshes, and optional-panel failures.
const fs = require('node:fs');
const path = require('node:path');
const zlib = require('node:zlib');
const assert = require('node:assert/strict');
const { chromium } = require(process.argv[3] || 'playwright');

(async () => {
  const target = path.resolve(process.argv[2]);
  const html = fs.readFileSync(target, 'utf8');
  const packed = html.match(/(<script type="application\/json" data-mesh>)([^<]+)(<\/script>)/);
  assert(packed, 'Inline mesh required');
  const mesh = JSON.parse(zlib.gunzipSync(Buffer.from(packed[2], 'base64')));
  assert(!('_workspace' in mesh.scene), 'Internal workspace leaked into HTML');
  const labels = JSON.parse(html.match(/const labels=(\{[\s\S]*?\});/)[1]);
  for (const key of [...mesh.trajectory.samples.map(record => record.phase), ...mesh.rack_batch.trace.map(record => record.stage)]) {
    assert(labels[key]?.length === 2 && labels[key].every(text => typeof text === 'string' && text.length), `Missing bilingual description: ${key}`);
  }
  const browser = await chromium.launch({headless: true, ...(process.argv[4] ? {executablePath: process.argv[4]} : {})});
  try {
    const page = await browser.newPage({viewport: {width: 960, height: 820}, reducedMotion: 'reduce'});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => {if (message.type() === 'error') errors.push(message.text());});
    await page.goto('file://' + target);
    await page.waitForSelector('[data-current-time]');
    assert.equal(await page.locator('html').getAttribute('lang'), 'de');
    assert(!mesh.rack_batch.trace.some(record => record.ownership === 'unresolved'), 'Successful trace contains unresolved ownership');
    assert.match(await page.locator('[data-play]').textContent(), /Bewegung/);
    const ownership = [];
    for (const [time, owner] of [[0, 'station'], [15, 'station'], [30, 'gripper'], [45, 'gripper'], [60, 'rack']]) {
      await page.locator('[data-time-slider]').fill(String(time));
      assert.equal(await page.locator('#cf01-bench-rack').getAttribute('data-tube-owner'), owner);
      ownership.push(owner);
    }
    await page.locator('[data-batch-panel]').evaluate(el => {el.open = true;});
    const pendingIndex = mesh.rack_batch.trace.findIndex(record => record.ownership === 'pending');
    assert(pendingIndex >= 0);
    await page.locator('[data-batch-slider]').fill(String(pendingIndex));
    assert.equal(await page.locator('#cf01-bench-rack').getAttribute('data-batch-ownership'), 'pending');
    assert.match(await page.locator('[data-batch-handoff]').textContent(), /Übergabe läuft/);
    assert(!/Zuordnung ungeklärt/.test(await page.locator('[data-batch-handoff]').textContent()));

    await page.locator('[data-batch-slider]').fill(String(mesh.rack_batch.trace.length - 1));
    assert.equal(await page.locator('#cf01-bench-rack').getAttribute('data-batch-order-restored'), 'true');
    assert.match(await page.locator('[data-batch-gripper]').textContent(), /wiederhergestellt: ja/);
    assert.match(await page.locator('[data-phase]').textContent(), /Leeren Greifer/);
    await page.screenshot({path: path.join(path.dirname(target), 'browser-check-de.png'), fullPage: true});
    await page.locator('[data-language]').selectOption('en');
    assert.match(await page.locator('[data-i18n="batch_description"]').textContent(), /Recorded local mock protocol/);
    assert.match(await page.locator('[data-batch-gripper]').textContent(), /restored: yes/);
    assert.match(await page.locator('[data-phase]').textContent(), /Withdraw empty gripper/);
    assert.match(await page.locator('[data-play]').textContent(), /Play cycle/);
    await page.screenshot({path: path.join(path.dirname(target), 'browser-check-en.png'), fullPage: true});
    // A language change must preserve a running batch timer, its position and pause control.
    await page.locator('[data-batch-play]').click();
    await page.waitForFunction(() => Number(document.querySelector('[data-batch-slider]').value) > 0);
    const before = Number(await page.locator('[data-batch-slider]').inputValue());
    await page.locator('[data-language]').selectOption('de');
    assert.equal(await page.locator('[data-batch-play]').textContent(), 'Pause');
    await page.waitForFunction(value => Number(document.querySelector('[data-batch-slider]').value) > value, before);
    await page.locator('[data-batch-play]').click();
    for (const language of ['de', 'en']) {
      await page.locator('[data-language]').selectOption(language);
      for (const width of [320, 600, 960]) {
        await page.setViewportSize({width, height: 820});
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${language}: overflow at ${width}px`);
      }
    }
    const variants = {
      absent: data => {delete data.rack_batch;},
      malformed: data => {data.rack_batch.trace[5].inventory = null;},
    };
    for (const [name, mutate] of Object.entries(variants)) {
      const data = structuredClone(mesh); mutate(data);
      const replacement = zlib.gzipSync(JSON.stringify(data)).toString('base64');
      await page.setContent(html.replace(packed[0], packed[1] + replacement + packed[3]));
      await page.waitForSelector('[data-current-time]');
      await page.locator('[data-time-slider]').fill('30');
      assert.equal(await page.locator('#cf01-bench-rack').getAttribute('data-tube-owner'), 'gripper', name);
      if (name === 'absent') assert(await page.locator('[data-batch-panel]').isHidden());
      else {
        assert.match(await page.locator('[data-batch-panel]').textContent(), /Chargenanzeige nicht verfügbar/);
        await page.locator('[data-language]').selectOption('en');
        assert.equal(await page.locator('[data-batch-panel]').textContent(), 'Batch panel unavailable');
      }
      // Actual playback must also survive an optional-panel failure.
      await page.locator('[data-play]').click();
      await page.waitForFunction(() => Number(document.querySelector('#cf01-bench-rack').dataset.currentTime) > 30, null, {timeout: 10000});
    }
    const failedReports = process.argv.slice(5);
    for (const reportPath of failedReports) {
      const report = JSON.parse(fs.readFileSync(reportPath, 'utf8'));
      assert.equal(report.ownership, 'unresolved');
      assert.equal(report.pending_handoff.robot_confirmation, true);
      assert.equal(report.pending_handoff.station_confirmation, false);
      const data = structuredClone(mesh); data.rack_batch = report;
      const replacement = zlib.gzipSync(JSON.stringify(data)).toString('base64');
      await page.goto('about:blank');
      await page.setContent(html.replace(packed[0], packed[1] + replacement + packed[3]));
      await page.waitForSelector('[data-current-time]');
      await page.locator('[data-batch-panel]').evaluate(el => {el.open = true;});
      await page.locator('[data-batch-slider]').fill(String(report.trace.length - 1));
      assert.equal(await page.locator('#cf01-bench-rack').getAttribute('data-batch-ownership'), 'unresolved');
      assert.equal(await page.locator('#cf01-bench-rack').getAttribute('data-batch-order-restored'), 'false');
      assert.match(await page.locator('[data-batch-handoff]').textContent(), /Zuordnung ungeklärt.*Sample01.*Stationsquittung fehlt/);
      assert.match(await page.locator('[data-batch-handoff]').textContent(), /keine gesicherte Ortsangabe/);
      await page.screenshot({path: path.join(path.dirname(target), 'browser-check-unresolved-'+report.failure.operation+'-de.png'), fullPage: true});
      await page.locator('[data-language]').selectOption('en');
      assert.match(await page.locator('[data-batch-handoff]').textContent(), /Ownership unresolved.*Sample01.*Station acknowledgement missing/);
      assert.match(await page.locator('[data-batch-handoff]').textContent(), /not an assured physical location/);
    }
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({passed: true, languages: ['de','en'], ownership_at_0_15_30_45_60_s: ownership,
      batch_order_restored: true, unresolved_handoff_reports: failedReports.length, optional_panel_failures: Object.keys(variants), widths: [320,600,960], console_errors: errors}, null, 2));
  } finally {await browser.close();}
})().catch(error => {console.error(error); process.exitCode = 1;});
