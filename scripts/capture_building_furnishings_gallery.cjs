// Usage: node scripts/capture_building_furnishings_gallery.cjs <index.html> <output-directory>
//          <viewpoints.json> [playwright-module] [chrome-executable]
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const {pathToFileURL} = require('node:url');

const width = 1280;
const height = 960;
const [input, destination, fixture, playwright = 'playwright', executablePath] = process.argv.slice(2);
const digest = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const centre = ({min, max}) => min.map((value, axis) => (value + max[axis]) / 2);
const distance = (a, b) => Math.hypot(...a.map((value, axis) => value - b[axis]));

async function main() {
  assert(input && destination && fixture, 'Pass checked index.html, an output directory and a PhD1002 viewpoint file.');
  const html = fs.readFileSync(input);
  const buildPath = path.join(path.dirname(input), 'build-report.json');
  const buildBytes = fs.readFileSync(buildPath);
  const build = JSON.parse(buildBytes);
  const fixtureBytes = fs.readFileSync(fixture);
  const {phd1002} = JSON.parse(fixtureBytes);
  assert.equal(build.format, 'solidcraftbot.building-walkthrough-build/1');
  assert.equal(build.passed, true);
  assert.equal(build.artifact_sha256.html, digest(html), 'Native HTML must match its checked build report.');
  const text = html.toString('utf8');
  const inline = /(<script id="walkthrough-data" type="application\/json">)([\s\S]*?)(<\/script>)/.exec(text);
  assert(inline, 'Missing inline native walkway data.');
  const model = JSON.parse(inline[2]);
  assert.deepEqual(model.source_files_sha256, build.source_files_sha256);
  assert.equal(model.qualification.metric_scale_known, false);

  assert(phd1002?.id === 'phd1002' && phd1002.scene === 'building' && phd1002.level_id === 'OG1',
    'Expected a source-derived PhD1002 viewing fixture on OG1.');
  for (const point of [phd1002.eye_mm, phd1002.target_mm]) {
    assert(Array.isArray(point) && point.length === 3 && point.every(Number.isFinite));
  }
  const kitchen = model.stops.find(stop => stop.id === 'kitchen');
  const phd3002 = model.stops.find(stop => stop.id === 'phd');
  assert.equal(kitchen?.level_id, 'OG1');
  assert.equal(phd3002?.level_id, 'OG3');
  assert(!model.stops.some(stop => stop.id === phd1002.id), 'The fixture may not replace a source viewpoint.');

  const groups = model.scenes.building.groups;
  const fridge = model.objects.find(row => row.id === 'Kitchen1008.Fridge.Door');
  const shell = groups.find(group => group.id === 'Kitchen1008_Fridge_Shell');
  const penguin = groups.find(group => group.id === 'Kitchen1008_Penguin_Body');
  const door = groups.find(group => group.id === 'Kitchen1008_Fridge_Door');
  assert(fridge && shell && penguin && door && fridge.moving_body_ids.includes(door.id));
  const target = centre(shell.bounds_mm);
  const cabinetHeight = shell.bounds_mm.max[2] - shell.bounds_mm.min[2];
  const detail = {
    id: 'gallery-fridge-detail', label: 'Kühlschrank 1.008', scene: fridge.scene, level_id: fridge.level_id,
    eye_mm: target.map((value, axis) => value + fridge.front[axis] * cabinetHeight * 1.35),
    target_mm: target,
  };
  detail.eye_mm[2] += .22 * cabinetHeight;
  assert(!model.stops.some(stop => stop.id === detail.id));
  model.stops.push(phd1002, detail);
  const data = JSON.stringify(model).replace(/</g, '\\u003c').replace(/\u2028/g, '\\u2028').replace(/\u2029/g, '\\u2029');
  const derived = text.slice(0, inline.index) + inline[1] + data + inline[3] + text.slice(inline.index + inline[0].length);
  const output = path.resolve(destination);
  fs.mkdirSync(output, {recursive: true});
  const temporary = fs.mkdtempSync(path.join(output, 'capture-'));
  const pagePath = path.join(temporary, 'index.html');
  fs.writeFileSync(pagePath, derived);
  const report = {
    format: 'solidcraftbot.building-furnishings-browser-gallery/1', passed: false,
    html_sha256: digest(html), build_report_sha256: digest(buildBytes), fixture_sha256: digest(fixtureBytes),
    native_builds: build.native_builds, qualification: model.qualification,
    scope: 'Rendered native presentation geometry and browser refrigerator articulation.',
    images: [], browser_errors: [],
  };

  const mac = process.platform === 'darwin';
  const args = ['--enable-gpu', '--enable-webgl', '--ignore-gpu-blocklist', '--use-gl=angle',
    mac ? '--use-angle=metal' : '--use-angle=swiftshader'];
  if (!mac) args.push('--enable-unsafe-swiftshader');
  let browser;
  try {
    const {chromium} = require(playwright);
    browser = await chromium.launch({headless: true, executablePath, args});
    report.browser = {version: browser.version(), profile: mac ? 'metal' : 'swiftshader'};
    const page = await browser.newPage({viewport: {width: 1440, height: 1200}, deviceScaleFactor: 1, reducedMotion: 'reduce'});
    page.on('pageerror', error => report.browser_errors.push(error.message));
    await page.goto(pathToFileURL(pagePath).href, {waitUntil: 'load', timeout: 120000});
    await page.waitForFunction(() => window.__buildingWalkthrough?.ready || document.querySelector('#building-walkthrough').dataset.error,
      null, {timeout: 120000});
    assert.equal(await page.locator('#building-walkthrough').getAttribute('data-error'), null,
      await page.locator('#walkthrough-error').textContent());
    const canvas = page.locator('#walkthrough-canvas');
    await page.addStyleTag({content: `
      #walkthrough-stage { width: ${width}px; height: ${height}px; border-radius: 0; box-shadow: none; }
      #walkthrough-stage > :not(#walkthrough-canvas) { visibility: hidden !important; }
      #walkthrough-canvas { outline: none !important; }
    `});
    const camera = () => page.evaluate(() => window.__buildingWalkthrough.camera);
    const frames = () => page.evaluate(() => window.__buildingWalkthrough.frames);
    const fridgeState = () => page.evaluate(id => window.__buildingWalkthrough.objects.find(object => object.id === id), fridge.id);
    const redraw = async action => {
      const before = await frames();
      const result = await action();
      await page.waitForFunction(previous => window.__buildingWalkthrough.frames > previous, before);
      return result;
    };
    const select = async stop => {
      await redraw(() => page.locator(`#walkthrough-stops [data-stop="${stop.id}"]`).click());
      assert.equal(await page.evaluate(() => window.__buildingWalkthrough.stopId), stop.id);
      const actual = await camera();
      assert.equal(actual.level_id, stop.level_id);
      assert(distance(actual.eye_mm, stop.eye_mm) < .01, `${stop.id}: the captured pose must match the source camera.`);
      const target = await page.evaluate(point => window.__buildingWalkthrough.projectPoint(point), stop.target_mm);
      assert(target.visible && Math.hypot(target.x - width/2, target.y - height/2) < 1,
        `${stop.id}: the camera must aim at the source target.`);
    };
    const capture = async (id, viewpoint, groupIds) => {
      assert(groupIds.length > 0);
      const observed = await canvas.evaluate(element => {
        const gl = element.getContext('webgl2');
        const pixels = new Uint8Array(element.width * element.height * 4);
        gl.readPixels(0, 0, element.width, element.height, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
        const colors = new Set();
        for (let i = 0; i < pixels.length; i += 4 * 23) {
          colors.add(`${pixels[i] >> 3},${pixels[i + 1] >> 3},${pixels[i + 2] >> 3}`);
        }
        const debug = gl.getExtension('WEBGL_debug_renderer_info');
        return {colors: colors.size, error: gl.getError(), pixels: [element.width, element.height],
          renderer: gl.getParameter(debug ? debug.UNMASKED_RENDERER_WEBGL : gl.RENDERER)};
      });
      assert.equal(observed.error, 0);
      assert(observed.colors > 8, `${id}: expected visible rendered surfaces.`);
      assert.deepEqual(observed.pixels, [width, height]);
      const file = `${id}.png`;
      const bytes = await canvas.screenshot({path: path.join(output, file), animations: 'disabled'});
      assert.equal(bytes.subarray(1, 4).toString(), 'PNG');
      assert.deepEqual([bytes.readUInt32BE(16), bytes.readUInt32BE(20)], [width, height]);
      report.images.push({id, file, sha256: digest(bytes), bytes: bytes.length, pixels: observed.pixels,
        source_body_ids: groupIds, viewpoint, camera: await camera(), renderer: observed.renderer, sampled_colors: observed.colors});
    };
    for (const [id, stop] of [['Kitchen1008', kitchen], ['PhD1002', phd1002], ['PhD3002', phd3002]]) {
      await select(stop);
      await capture(id, stop, groups.filter(group => group.id.startsWith(id + '_')).map(group => group.id));
    }

    assert.equal((await redraw(() => page.evaluate(id => window.__buildingWalkthrough.viewObject(id), fridge.id))).status, 'accepted');
    assert.equal((await fridgeState()).state, 'closed');
    assert(distance((await camera()).eye_mm, fridge.viewpoint.eye_mm) < .01);
    // Sample the lower dark penguin flank, away from the white belly and the shelf.
    const sample = centre(penguin.bounds_mm);
    sample[0] += .36 * (penguin.bounds_mm.max[0] - penguin.bounds_mm.min[0]);
    sample[2] = penguin.bounds_mm.min[2] + .16 * (penguin.bounds_mm.max[2] - penguin.bounds_mm.min[2]);
    const readPixel = point => canvas.evaluate((element, world) => {
      const pixel = window.__buildingWalkthrough.projectPoint(world);
      if (!pixel.visible) throw Error('The source penguin sample must lie within the image.');
      const gl = element.getContext('webgl2'), rgba = new Uint8Array(4);
      gl.readPixels(Math.floor(pixel.x), element.height - 1 - Math.floor(pixel.y), 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, rgba);
      return [...rgba];
    }, point);
    const closed = await readPixel(sample);
    const doorPosition = await canvas.evaluate((element, point) => {
      const pixel = window.__buildingWalkthrough.projectPoint(point);
      if (!pixel.visible) throw Error('The closed native door must be visible for the mouse click.');
      const box = element.getBoundingClientRect();
      return [box.left + pixel.x / element.width * box.width, box.top + pixel.y / element.height * box.height];
    }, centre(door.bounds_mm));
    await redraw(() => page.mouse.click(...doorPosition));
    const interaction = await page.evaluate(() => window.__buildingWalkthrough.lastInteraction);
    assert(interaction?.id === fridge.id && interaction.input === 'click' && interaction.status === 'accepted');
    const opened = await fridgeState();
    assert.equal(opened.state, 'open');
    assert.equal(opened.angle_deg, fridge.states.open);
    assert.deepEqual(opened.body_angles_deg, Object.fromEntries(fridge.moving_body_ids.map(id => [id, opened.angle_deg])));
    const open = await readPixel(sample);
    const brightness = rgba => (rgba[0] + rgba[1] + rgba[2]) / 3;
    assert(brightness(closed) > 140 && brightness(closed) - brightness(open) > 50,
      'Opening the fridge must expose the dark native penguin body.');
    await select(detail);
    assert.equal((await fridgeState()).state, 'open', 'The modeled door state persists in the close-up.');
    await capture('Kitchen1008_EasterEgg', detail, groups.filter(group =>
      /^(Kitchen1008_Fridge_|Kitchen1008_Penguin)/.test(group.id)).map(group => group.id));
    report.fridge = {interaction, angle_deg: opened.angle_deg, body_angles_deg: opened.body_angles_deg,
      sampled_point_mm: sample, closed_rgba: closed, open_rgba: open,
      detail_body: shell.id, detail_front: fridge.front};
    assert.deepEqual(report.browser_errors, []);
    report.passed = true;
  } catch (error) {
    report.error = error.message;
    throw error;
  } finally {
    await browser?.close();
    fs.writeFileSync(path.join(output, 'browser-gallery-report.json'), JSON.stringify(report, null, 2) + '\n');
    fs.rmSync(temporary, {recursive: true});
  }
  console.log(JSON.stringify({passed: true, images: report.images.map(image => image.file), output}));
}

main().catch(error => { console.error(error); process.exitCode = 1; });
