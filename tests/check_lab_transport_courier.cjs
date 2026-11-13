// Real Chromium UI behavior against a controlled local HTTP fixture.
// TLS, authentication authority and domain correctness are separate Python checks.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const crypto = require('node:crypto');
const {chromium} = require(process.argv[2] || 'playwright');
const chrome = process.argv[3];
const output = process.argv[4];
const root = path.resolve(__dirname, '..');
const PENDING = 'diylabbot.courier.pending.v1';
const password = 'UI.Synthetic.Password.Only';
const run = 'SYN.UI.Run', serverId = 'SYN.UI.Server';
const grants = {
  source: [{id: 'Grant.Source', kind: 'endpoint', resource_id: 'LabA.CF01'}],
  courier: [{id: 'Grant.Courier', kind: 'agent', resource_id: 'AgentHuman'}],
  recipient: [{id: 'Grant.Target', kind: 'endpoint', resource_id: 'LabB.NanoDrop'}],
  owner: [{id: 'Grant.Owner', kind: 'owner', resource_id: run}],
  other: [{id: 'Grant.Other', kind: 'observer', resource_id: run}],
};
const fixture = {sequence: 1, epoch: 1, write: true, held: false, workflowHold: false,
  routeOnly: false, newJob: null, dispatched: false,
  receipts: new Map(), roles: new Set(), posts: [], effects: 0, events: [],
  dropAfterCommit: false, dropBeforeCommit: false};
const info = () => ({format: 'solidcraftbot.lab-transport-network-info/1', server_uuid: serverId,
  boot_id: 'Boot.UI.1', run_id: run, mode: 'synthetic_only', tls_required: true});
const materials = Array.from({length: 12}, (_, index) => ({place_id: `Slot${String(index + 1).padStart(2, '0')}`,
  vessel_id: `Tube${String(index + 1).padStart(2, '0')}`, content_revision: 0,
  materials: [{material_id: `Sample${String(index + 1).padStart(2, '0')}`, origin_id: null}]}));
function snapshot(subject) {
  let allowed = [];
  const add = (operation, role) => ({operation, grant_id: grants[subject][0].id, ...(role ? {role} : {})});
  if (!fixture.held) {
    const roles = {source: ['pickup_release'], courier: ['pickup_accept', 'delivery_release'], recipient: ['delivery_accept']}[subject] || [];
    allowed = roles.filter(role => !fixture.roles.has(role)).map(role => add('attest', role));
  }
  if (subject === 'owner') allowed = [add('hold'), add('cancel'), ...(fixture.held ? [add('reconcile')] : [])];
  if (fixture.routeOnly && !fixture.dispatched) allowed = subject === 'owner' ? [...allowed, add('dispatch')] : [];
  return {...info(), subject, principal: 'SYN.' + subject, grants: grants[subject], revision: fixture.sequence,
    cursor: {server_uuid: serverId, run_id: run, sequence: fixture.sequence, sha256: 'a'.repeat(64)},
    assignment_epoch: fixture.epoch, write_session_available: fixture.write,
    root_status: fixture.workflowHold ? 'held' : 'waiting_transport',
    workflow_reconcile: {allowed: subject === 'owner' && fixture.workflowHold,
      grant_id: 'Grant.Owner', reason: 'Expliziter Arbeitsplatzabgleich nach Sitzungsübernahme.',
      args_template: {scope: 'workflow', boot_id: info().boot_id, assignment_epoch: fixture.epoch,
        observations: materials.map(item => ({sample_id: item.materials[0].material_id, vessel_id: item.vessel_id,
          location: {kind: 'rack', rack_id: 'Rack', place_id: item.place_id}}))}},
    routes: fixture.routeOnly && !fixture.newJob ? [{id: 'CF01ToNanoDrop', source_endpoint: 'LabA.CF01',
      target_endpoint: 'LabB.NanoDrop', agent_id: 'AgentHuman', allowed_actions:
        subject === 'owner' && fixture.write && !fixture.workflowHold ? [add('prepare_route')] : []}] : [],
    jobs: fixture.routeOnly && !fixture.newJob ? [] : [{job_id: fixture.routeOnly ? fixture.newJob : 'CF01.Out', rack_id: 'Rack', source_endpoint: 'LabA.CF01', target_endpoint: 'LabB.NanoDrop',
      agent_id: 'AgentHuman', phase: 'pickup_pending', control: fixture.held ? 'held' : 'active',
      assignment_epoch: 1, manifest_sha256: 'b'.repeat(64), pickup_handover_id: 'Handover.Pickup',
      delivery_handover_id: 'Handover.Delivery', manifest: materials, receipts: {}, allowed_actions: allowed}]};
}
function respond(res, status, value) {
  res.writeHead(status, {'Content-Type': 'application/json', 'Cache-Control': 'no-store'});
  res.end(JSON.stringify(value));
}
const server = http.createServer(async (req, res) => {
  fixture.events.push([req.method, req.url]);
  if (['/', '/courier.js', '/courier.css'].includes(req.url)) {
    const filename = {'/': 'lab_transport_courier.html', '/courier.js': 'lab_transport_courier.js', '/courier.css': 'lab_transport_courier.css'}[req.url];
    res.writeHead(200, {'Content-Type': req.url === '/' ? 'text/html' : req.url.endsWith('.js') ? 'application/javascript' : 'text/css',
      'Content-Security-Policy': "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'"});
    res.end(fs.readFileSync(path.join(root, 'scripts', filename))); return;
  }
  if (req.url === '/api/info') return respond(res, 200, info());
  let raw = ''; for await (const part of req) raw += part;
  if (req.url === '/api/login') {
    const value = JSON.parse(raw);
    if (!grants[value.username] || value.password !== password || value.server_uuid !== serverId) {
      return respond(res, 401, {error: {code: 'unauthorized', message: 'Anmeldung abgewiesen'}});
    }
    return respond(res, 200, {access_token: 'UI.Token.' + value.username, subject: value.username,
      token_type: 'Bearer', expires_in_s: 60, server_uuid: serverId});
  }
  const subject = String(req.headers.authorization || '').replace('Bearer UI.Token.', '');
  if (!grants[subject]) return respond(res, 401, {error: {code: 'unauthorized', message: 'Erneut anmelden'}});
  if (req.url === '/api/logout') return respond(res, 200, {logged_out: true});
  if (req.url === '/api/session') return respond(res, 200, {...info(), subject, principal: 'SYN.' + subject, grants: grants[subject]});
  if (req.url === '/api/snapshot') return respond(res, 200, snapshot(subject));
  if (req.url.startsWith('/api/requests/')) {
    const record = fixture.receipts.get(decodeURIComponent(req.url.split('/').pop()));
    return respond(res, 200, {receipt: record || null, replayed: Boolean(record), snapshot: snapshot(subject)});
  }
  if (req.url === '/api/requests' && req.method === 'POST') {
    const wire = JSON.parse(raw); fixture.posts.push({raw, wire, subject});
    if (fixture.dropBeforeCommit) { fixture.dropBeforeCommit = false; res.destroy(); return; }
    let receipt = fixture.receipts.get(wire.request_id);
    if (!receipt) {
      fixture.sequence++; fixture.effects++;
      if (wire.operation === 'attest') fixture.roles.add(wire.args.role);
      if (wire.operation === 'hold' || wire.operation === 'cancel') fixture.held = true;
      if (wire.operation === 'resume') { fixture.write = true; fixture.workflowHold = true; fixture.epoch++; }
      if (wire.operation === 'reconcile' && wire.args.scope === 'workflow') fixture.workflowHold = false;
      if (wire.operation === 'prepare_route') { fixture.newJob = wire.args.job_id; fixture.dispatched = false; fixture.roles.clear(); }
      if (wire.operation === 'dispatch') fixture.dispatched = true;
      receipt = {request_id: wire.request_id, operation: wire.operation,
        request_context: {subject, grant: {...grants[subject].find(grant => grant.id === wire.grant_id)},
          wire_sha256: crypto.createHash('sha256').update(raw).digest('hex'),
          interface: 'solidcraftbot.lab-transport-network-protocol/1', transport_channel: 'https',
          operation: wire.operation, owner_fence: wire.operation === 'attest' ? null : {
            boot_id: wire.args.boot_id, assignment_epoch: wire.args.assignment_epoch}},
        response: {request_id: wire.request_id, result: {job: {phase: 'completed'}}}};
      fixture.receipts.set(wire.request_id, receipt);
    }
    if (fixture.dropAfterCommit) { fixture.dropAfterCommit = false; res.destroy(); return; }
    return respond(res, 200, {receipt, replayed: false, snapshot: snapshot(subject)});
  }
  respond(res, 404, {error: {code: 'not_found', message: 'Unbekannter Pfad'}});
});

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  const browser = await chromium.launch({headless: true, ...(chrome ? {executablePath: chrome} : {})});
  try {
    const noJs = await browser.newContext({javaScriptEnabled: false});
    const fallback = await noJs.newPage();
    await fallback.goto(origin);
    assert(await fallback.locator('#login').isDisabled());
    assert.equal(await fallback.locator('#login-form').getAttribute('method'), 'post');
    assert.equal(await fallback.locator('#login-form').getAttribute('action'), '/api/login');
    await fallback.locator('#username').fill('source');
    await fallback.locator('#password').fill(password);
    await fallback.locator('#password').press('Enter');
    assert.equal(fallback.url(), `${origin}/`);
    await noJs.close();
    const page = await browser.newPage({viewport: {width: 1100, height: 900}});
    const errors = []; page.on('pageerror', failure => errors.push(failure.message));
    let persistedBeforePost = 0;
    let loseSessionResponse = false;
    await page.route('**/api/session', async route => {
      if (loseSessionResponse) { loseSessionResponse = false; await route.abort('failed'); }
      else await route.continue();
    });
    await page.route('**/api/requests', async route => {
      if (route.request().method() === 'POST') {
        const pending = await page.evaluate(key => JSON.parse(sessionStorage.getItem(key)), PENDING);
        assert.equal(pending.wire_json, route.request().postData());
        assert.equal(pending.server_uuid, serverId); assert.equal(pending.run_id, run);
        assert.equal(pending.subject, {'Grant.Owner': 'owner', 'Grant.Source': 'source',
          'Grant.Courier': 'courier', 'Grant.Target': 'recipient'}[JSON.parse(pending.wire_json).grant_id]);
        persistedBeforePost++;
        if (fixture.dropBeforeCommit) {
          fixture.dropBeforeCommit = false; fixture.failedWire = route.request().postData();
          await route.abort('failed'); return;
        }
        if (fixture.dropAfterCommit) {
          fixture.dropAfterCommit = false;
          await route.fetch(); // The fixture committed, but the UI never sees its reply.
          await route.abort('failed'); return;
        }
      }
      await route.continue();
    });
    async function login(subject) {
      await page.locator('#username').fill(subject); await page.locator('#password').fill(password);
      await page.locator('#login').click(); await page.locator('#session-panel').waitFor({state: 'visible'});
      await page.waitForFunction(() => !document.getElementById('refresh').disabled);
      assert.equal(await page.locator('#password').inputValue(), '');
    }
    async function logout() {
      await page.locator('#logout').click(); await page.locator('#login-panel').waitFor({state: 'visible'});
      await page.waitForFunction(() => !document.getElementById('login').disabled);
    }
    async function checkedRole() {
      const card = page.locator('article[data-job="CF01.Out"]');
      await card.locator('input:not([type="checkbox"])').first().fill('Rack');
      await card.locator('input[type="checkbox"]').first().check();
      return card.getByRole('button', {name: 'Abgabestelle: Abgabe bestätigen'});
    }
    async function ready() { await page.waitForFunction(() => !document.getElementById('refresh').disabled); }
    await page.goto(origin); await page.waitForFunction(() => !document.getElementById('login').disabled);
    assert.equal(fixture.posts.length, 0);
    await login('source'); await page.locator('#refresh').click(); await ready();
    assert.equal(fixture.posts.length, 0, 'Login and reconnect must not attest anything');
    const release = page.getByRole('button', {name: 'Abgabestelle: Abgabe bestätigen'});
    assert(await release.isDisabled());
    assert.equal(await page.getByRole('button', {name: 'Bote: Übernahme bestätigen'}).count(), 0);
    await page.locator('#observed-rack-0').fill('OtherRack');
    await page.locator('article input[type="checkbox"]').first().check();
    assert(await release.isDisabled());
    await page.locator('#observed-rack-0').fill('Rack');
    fixture.dropAfterCommit = true; await release.click(); await ready();
    assert.equal(fixture.posts.length, 1); assert.equal(fixture.effects, 1);
    const original = await page.evaluate(key => JSON.parse(sessionStorage.getItem(key)).wire_json, PENDING);
    assert.equal(original, fixture.posts[0].raw);
    fixture.held = true;
    await page.reload(); await page.waitForFunction(() => !document.getElementById('login').disabled);
    assert.equal(fixture.posts.length, 1, 'Reload must not replay automatically');
    loseSessionResponse = true;
    await page.locator('#username').fill('source'); await page.locator('#password').fill(password);
    await page.locator('#login').click();
    await page.waitForFunction(() => !document.getElementById('login').disabled);
    assert.deepEqual(errors, [], 'A session-fetch failure must not escape through partial login state');
    assert(await page.locator('#login-panel').isVisible());
    assert(await page.locator('#refresh').isDisabled());
    assert(await page.locator('#retry').isDisabled());
    assert.equal(await page.locator('#password').inputValue(), '');
    assert.equal(await page.evaluate(key => JSON.parse(sessionStorage.getItem(key)).wire_json, PENDING), original);
    assert.equal(fixture.posts.length, 1, 'An incomplete login must not repeat pending work');
    await login('other');
    assert(await page.locator('#retry').isDisabled()); assert(await page.locator('#receipt').isDisabled());
    assert.equal(await page.evaluate(key => JSON.parse(sessionStorage.getItem(key)).wire_json, PENDING), original);
    await logout(); await login('source'); await page.locator('#retry').click(); await ready();
    assert.equal(fixture.posts.length, 1, 'Stored receipt must be read before retrying a mutation');
    assert.equal(await page.locator('#pending-panel').isVisible(), false);
    assert((await page.locator('article').innerText()).includes('held'), 'Fresh snapshot must override historical receipt state');

    fixture.held = false; fixture.roles.clear(); fixture.receipts.clear();
    await page.locator('#refresh').click(); await ready();
    fixture.dropBeforeCommit = true; await (await checkedRole()).click(); await ready();
    const missing = fixture.failedWire, beforeRetry = fixture.posts.length;
    await page.locator('#retry').click(); await ready();
    assert.equal(fixture.posts.length, beforeRetry + 1);
    assert.equal(fixture.posts.at(-1).raw, missing, 'An unknown outcome must retry the exact saved JSON');
    assert.equal(fixture.effects, 2, 'Uncommitted loss plus retry has one effect');
    const stored = await page.evaluate(() => JSON.stringify({...sessionStorage}));
    assert(!stored.includes(password) && !stored.includes('UI.Token.'));
    assert.equal(await page.evaluate(() => localStorage.length), 0);

    fixture.roles.clear(); await page.locator('#refresh').click(); await ready();
    fixture.dropBeforeCommit = true; await (await checkedRole()).click(); await ready();
    const unresolved = await page.evaluate(key => JSON.parse(sessionStorage.getItem(key)).wire_json, PENDING);
    const unresolvedRequest = JSON.parse(unresolved);
    const otherIntent = JSON.stringify({...unresolvedRequest, args: {...unresolvedRequest.args,
      observation_id: 'Different.Confirmed.Intent'}});
    const matching = structuredClone(fixture.receipts.get(JSON.parse(missing).request_id));
    matching.request_id = unresolvedRequest.request_id;
    matching.response.request_id = unresolvedRequest.request_id;
    matching.request_context.wire_sha256 = crypto.createHash('sha256').update(unresolved).digest('hex');
    const conflict = structuredClone(matching);
    conflict.request_context.wire_sha256 = crypto.createHash('sha256').update(otherIntent).digest('hex');
    fixture.receipts.set(unresolvedRequest.request_id, conflict);
    const postsBeforeConflict = fixture.posts.length;
    await page.locator('#receipt').click(); await ready();
    assert((await page.locator('#error').innerText()).includes('anderen Meldung'));
    assert.equal(await page.evaluate(key => JSON.parse(sessionStorage.getItem(key)).wire_json, PENDING), unresolved);
    await page.locator('#retry').click(); await ready();
    assert.equal(fixture.posts.length, postsBeforeConflict, 'A conflicting receipt must not authorize another POST');
    assert(await page.locator('#pending-panel').isVisible(), 'Same request ID with different bytes must preserve pending intent');
    for (const wrongContext of [
      {...matching.request_context, subject: 'other'},
      {...matching.request_context, grant: {...matching.request_context.grant, resource_id: 'Other.Endpoint'}},
    ]) {
      fixture.receipts.set(unresolvedRequest.request_id, {...matching, request_context: wrongContext});
      await page.locator('#receipt').click(); await ready();
      assert(await page.locator('#pending-panel').isVisible(), 'Subject and full grant must match before clearing');
    }
    fixture.receipts.set(unresolvedRequest.request_id, matching);
    await page.evaluate(() => { Object.defineProperty(crypto, 'subtle', {configurable: true, value: undefined}); });
    await page.locator('#receipt').click(); await ready();
    assert((await page.locator('#error').innerText()).includes('nicht geprüft'));
    assert.equal(await page.evaluate(key => JSON.parse(sessionStorage.getItem(key)).wire_json, PENDING), unresolved);
    await page.evaluate(() => { delete crypto.subtle; });
    await page.locator('#receipt').click(); await ready();
    assert.equal(await page.locator('#pending-panel').isVisible(), false);
    assert.equal(fixture.posts.length, postsBeforeConflict, 'Matching evidence recovery is read-only');

    await logout(); await login('courier');
    const courierPickup = page.getByRole('button', {name: 'Bote: Übernahme bestätigen'});
    const courierDelivery = page.getByRole('button', {name: 'Bote: Abgabe am Ziel bestätigen'});
    assert(await courierPickup.isDisabled()); assert(await courierDelivery.isDisabled());
    assert.equal(await page.getByRole('button', {name: 'Empfangsstelle: Aufnahme bestätigen'}).count(), 0);
    await page.locator('#observed-rack-0').fill('Rack');
    await page.locator('article input[type="checkbox"]').first().check();
    const postsBeforePickup = fixture.posts.length;
    await courierPickup.click(); await ready();
    assert.equal(fixture.posts.length, postsBeforePickup + 1, 'One courier confirmation must not send both roles');
    assert.equal(fixture.posts.at(-1).wire.args.role, 'pickup_accept');
    assert(await courierDelivery.isDisabled(), 'The second courier role needs a new explicit confirmation');

    await logout(); fixture.write = false; fixture.held = false;
    await login('owner');
    assert(await page.locator('#resume').isDisabled());
    await page.locator('#resume-confirm').check(); await page.locator('#resume').click(); await ready();
    assert.equal(fixture.posts.at(-1).wire.operation, 'resume');
    const reconciliation = page.locator('#workflow-reconciliation');
    assert(await reconciliation.isVisible());
    assert.equal(await reconciliation.locator('input:checked').count(), 0);
    const workflowSubmit = reconciliation.getByRole('button');
    assert(await workflowSubmit.isDisabled());
    for (const input of await reconciliation.locator('input[type="checkbox"]').all()) await input.check();
    await workflowSubmit.click(); await ready();
    const workflowArgs = fixture.posts.at(-1).wire.args;
    assert.equal(workflowArgs.scope, 'workflow'); assert.equal(workflowArgs.observations.length, 12);
    assert.equal(workflowArgs.assignment_epoch, fixture.epoch);
    for (const key of ['manifest_confirmed', 'workspace_clear', 'arm_clear', 'gripper_empty']) assert.equal(workflowArgs[key], true);
    let owner = page.locator('article').locator('details').last();
    await owner.locator('summary').click();
    assert(await owner.getByRole('button', {name: 'Auftrag halten', exact: true}).isDisabled());
    await owner.locator('input[type="text"]').fill('Synthetisch ungewisser Ausgang');
    await owner.getByRole('button', {name: 'Auftrag halten', exact: true}).click(); await ready();
    assert.equal(fixture.posts.at(-1).wire.operation, 'hold');
    owner = page.locator('article').locator('details').last(); await owner.locator('summary').click();
    assert.deepEqual(await owner.locator('select').evaluateAll(items => items.map(item => item.value)), ['', '']);
    assert.equal(await owner.locator('input:checked').count(), 0);
    await owner.locator('input[type="text"]').fill('Ort ausdrücklich weiter unbekannt');
    await owner.locator('select').nth(0).selectOption('unknown');
    await owner.locator('select').nth(1).selectOption('unknown');
    await owner.locator('input[type="checkbox"]').check();
    await owner.getByRole('button', {name: 'Disposition ausdrücklich melden'}).click(); await ready();
    const disposition = fixture.posts.at(-1).wire.args;
    assert.equal(disposition.scope, 'job'); assert.equal(disposition.outcome, 'unknown'); assert.equal(disposition.location, null);
    assert.equal(disposition.manifest.length, 12); assert.equal(disposition.boot_id, info().boot_id);
    assert.equal(fixture.held, true);

    await logout(); fixture.routeOnly = true; fixture.held = false;
    await login('owner');
    const route = page.locator('[data-route="CF01ToNanoDrop"]');
    const prepare = route.getByRole('button', {name: 'Route als neuen Auftrag vorbereiten'});
    assert(await prepare.isDisabled());
    const postsBeforePrepare = fixture.posts.length;
    await route.locator('input[type="checkbox"]').check();
    fixture.dropBeforeCommit = true; await prepare.click(); await ready();
    const prepareWire = await page.evaluate(key => JSON.parse(sessionStorage.getItem(key)).wire_json, PENDING);
    const prepareRequest = JSON.parse(prepareWire);
    assert.equal(prepareRequest.operation, 'prepare_route');
    assert.equal(prepareRequest.args.route_id, 'CF01ToNanoDrop');
    assert.match(prepareRequest.args.job_id, /^UI\.Job\.[a-f0-9]{32}$/);
    assert.equal(prepareRequest.args.boot_id, info().boot_id);
    assert.equal(prepareRequest.args.assignment_epoch, fixture.epoch);
    await page.reload(); await page.waitForFunction(() => !document.getElementById('login').disabled);
    await login('owner');
    assert.equal(fixture.posts.length, postsBeforePrepare, 'Reload/login must not prepare the route');
    assert.equal(await page.evaluate(key => JSON.parse(sessionStorage.getItem(key)).wire_json, PENDING), prepareWire);
    await page.locator('#retry').click(); await ready();
    assert.equal(fixture.posts.at(-1).raw, prepareWire);
    assert.equal(fixture.newJob, prepareRequest.args.job_id);
    const dispatch = page.getByRole('button', {name: 'Botenauftrag ausdrücklich bereitstellen'});
    assert(await dispatch.isDisabled());
    assert.equal(fixture.dispatched, false, 'Preparing a route must not dispatch it');
    await page.locator('article[data-job="' + fixture.newJob + '"] input[type="checkbox"]').first().check();
    fixture.dropBeforeCommit = true; await dispatch.click(); await ready();
    const dispatchWire = await page.evaluate(key => JSON.parse(sessionStorage.getItem(key)).wire_json, PENDING);
    const dispatchRequest = JSON.parse(dispatchWire);
    assert.equal(dispatchRequest.operation, 'dispatch');
    assert.equal(dispatchRequest.args.job_id, prepareRequest.args.job_id);
    assert.equal(dispatchRequest.args.boot_id, info().boot_id);
    assert.equal(dispatchRequest.args.assignment_epoch, fixture.epoch);
    await page.reload(); await page.waitForFunction(() => !document.getElementById('login').disabled);
    await login('owner');
    assert.equal(fixture.dispatched, false, 'Reload/login must not dispatch');
    await page.locator('#retry').click(); await ready();
    assert.equal(fixture.posts.at(-1).raw, dispatchWire);
    assert.equal(fixture.dispatched, true); assert.equal(fixture.roles.size, 0);
    const postsBeforeCourierLogin = fixture.posts.length;
    await logout(); await login('courier');
    assert.equal(fixture.posts.length, postsBeforeCourierLogin, 'Dispatch must not fabricate any courier receipt');
    assert(await page.getByRole('button', {name: 'Bote: Übernahme bestätigen'}).isDisabled());

    await logout();
    await page.evaluate(key => sessionStorage.setItem(key, 'unreadable-confirmed-intent'), PENDING);
    fixture.roles.clear(); fixture.held = false; fixture.routeOnly = false;
    const postsBeforeCorrupt = fixture.posts.length;
    await page.reload(); await page.waitForFunction(() => !document.getElementById('login').disabled);
    await login('source');
    assert(await page.locator('#pending-panel').isVisible());
    assert(await (await checkedRole()).isDisabled(), 'Malformed saved intent cannot be overwritten by a new statement');
    assert.equal(fixture.posts.length, postsBeforeCorrupt);
    await page.locator('#discard').click(); await ready();
    assert.equal(await page.locator('#pending-panel').isVisible(), false);
    assert.equal(fixture.posts.length, postsBeforeCorrupt, 'Discard is local, not a server cancellation');
    assert(persistedBeforePost >= 6);
    assert.deepEqual(errors, []);
    if (output) await page.screenshot({path: output, fullPage: true});
    const hashes = {};
    for (const name of ['lab_transport_courier.html', 'lab_transport_courier.js', 'lab_transport_courier.css']) {
      hashes[name] = crypto.createHash('sha256').update(fs.readFileSync(path.join(root, 'scripts', name))).digest('hex');
    }
    console.log(JSON.stringify({passed: true, browser: await browser.version(), persistedBeforePost,
      noAutomaticAttestations: true, responseLossReceiptRecovery: true, exactRetryAfterUncommittedLoss: true,
      accountBoundPendingIntent: true, noCredentialStorage: true, explicitOwnerReconciliation: true,
      noJavaScriptCredentialUrlLeak: true,
      explicitRoutePreparationAndDispatchWithExactReloadRetry: true,
      receiptIntentSubjectGrantAndDigestVerified: true, missingWebCryptoPreservesPending: true,
      failedSessionFetchClearsPartialLogin: true,
      malformedPendingBlocksNewStatements: true, source_sha256: hashes,
      scope: 'Real Chromium UI behavior with controlled local HTTP fixture; not TLS/auth/domain qualification'}));
  } finally { await browser.close(); }
})().catch(failure => {console.error(failure); process.exitCode = 1;}).finally(() => server.close());
