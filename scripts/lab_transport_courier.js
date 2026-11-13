/* Explicit synthetic courier statements. No credentials are persisted. */
(() => {
  'use strict';
  const PENDING_KEY = 'diylabbot.courier.pending.v1';
  const CURSOR_KEY = 'diylabbot.courier.cursor.v1';
  const roles = {
    pickup_release: 'Abgabestelle: Abgabe bestätigen',
    pickup_accept: 'Bote: Übernahme bestätigen',
    delivery_release: 'Bote: Abgabe am Ziel bestätigen',
    delivery_accept: 'Empfangsstelle: Aufnahme bestätigen',
  };
  const terminal = new Set(['completed', 'cancelled', 'cancelled_reconciled']);
  const $ = id => document.getElementById(id);
  const state = {info: null, token: null, subject: null, session: null,
                 snapshot: null, cursor: null, pending: null, invalidPending: false, busy: false};

  function node(tag, value, className) {
    const item = document.createElement(tag);
    if (value !== undefined) item.textContent = value;
    if (className) item.className = className;
    return item;
  }
  function error(message) { $('error').textContent = message; $('error').hidden = !message; }
  function message(value) { $('message').textContent = value; }
  function sameContext(value) {
    return Boolean(state.info && state.subject && value && value.server_uuid === state.info.server_uuid &&
      value.run_id === state.info.run_id && value.subject === state.subject);
  }
  function wire() { return state.pending ? JSON.parse(state.pending.wire_json) : null; }
  function canUsePending() {
    return sameContext(state.pending) && Boolean(state.token) && Boolean(state.session) &&
      Array.isArray(state.session.grants) &&
      state.session.grants.some(grant => grant.id === wire().grant_id);
  }
  function controls() {
    $('login').disabled = state.busy || !state.info;
    $('refresh').disabled = state.busy || !state.token;
    $('logout').disabled = state.busy || !state.token;
    $('receipt').disabled = state.busy || !canUsePending();
    $('retry').disabled = state.busy || !canUsePending();
    $('discard').disabled = state.busy;
    $('resume').disabled = state.busy || Boolean(state.pending) || state.invalidPending || !$('resume-confirm').checked;
    for (const button of document.querySelectorAll('[data-mutation]')) {
      button.disabled = state.busy || Boolean(state.pending) || state.invalidPending ||
        !state.snapshot || !state.snapshot.write_session_available || button.dataset.ready !== 'true';
    }
  }
  function busy(value) { state.busy = value; controls(); }
  function renderPending() {
    $('pending-panel').hidden = !state.pending && !state.invalidPending;
    if (state.pending) {
      $('pending-wire').textContent = state.pending.wire_json;
      $('pending-identity').textContent = `Konto: ${state.pending.subject} · Lauf: ${state.pending.run_id}`;
      $('pending-status').textContent = sameContext(state.pending) ?
        'Der Ausgang ist noch nicht bestätigt. Zuerst den gespeicherten Beleg abrufen.' :
        'Diese Meldung gehört zu einem anderen Konto, Lauf oder Dienst. Mit dem passenden Konto anmelden; die Meldung wird nicht übernommen.';
    }
    controls();
  }
  function loadPending() {
    let raw;
    try {
      raw = sessionStorage.getItem(PENDING_KEY);
      if (!raw) return;
      const pending = JSON.parse(raw), request = JSON.parse(pending.wire_json);
      const keys = Object.keys(request).sort().join(',');
      if (pending.format !== 'solidcraftbot.courier-pending/1' ||
          !['server_uuid', 'run_id', 'subject', 'wire_json'].every(key => typeof pending[key] === 'string' && pending[key]) ||
          keys !== 'args,grant_id,operation,request_id' || typeof request.args !== 'object' || request.args === null ||
          !['attest', 'resume', 'prepare_route', 'dispatch', 'hold', 'cancel', 'reconcile'].includes(request.operation)) {
        throw Error('Ungültiges lokales Meldungsformat');
      }
      state.pending = pending;
    } catch (_) {
      state.invalidPending = true;
      error('Die gespeicherte Meldung ist nicht lesbar. Es wurde nichts gesendet. Den lokalen Entwurf erst nach Klärung verwerfen.');
      $('pending-panel').hidden = false;
      $('pending-wire').textContent = raw || '';
      $('pending-identity').textContent = 'Unlesbarer lokaler Entwurf';
    }
  }
  function clearPending() {
    sessionStorage.removeItem(PENDING_KEY);
    state.pending = null; state.invalidPending = false;
    renderPending();
  }
  function cursorHeader(cursor) {
    const bytes = new TextEncoder().encode(JSON.stringify(cursor));
    let encoded = '';
    for (const value of bytes) encoded += String.fromCharCode(value);
    return btoa(encoded).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, '');
  }
  function clearLogin() {
    state.token = null; state.subject = null; state.session = null; state.snapshot = null; state.cursor = null;
    $('login-panel').hidden = false; $('session-panel').hidden = true;
    $('password').value = ''; $('jobs').replaceChildren();
    $('route-preparation').replaceChildren(); $('route-preparation').hidden = true;
    renderPending();
  }
  async function api(path, {method = 'GET', body = undefined, authenticated = true} = {}) {
    const headers = {Accept: 'application/json'};
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (authenticated) {
      if (!state.token) throw Error('Zuerst anmelden.');
      headers.Authorization = `Bearer ${state.token}`;
      if (state.cursor) headers['X-Lab-Cursor'] = cursorHeader(state.cursor);
    }
    const response = await fetch(path, {method, headers, body, credentials: 'omit', cache: 'no-store', redirect: 'error'});
    const value = await response.json();
    if (!response.ok) {
      if (response.status === 401) clearLogin();
      const failure = Error(value.error && value.error.message || 'Die Anfrage wurde abgewiesen.');
      failure.status = response.status; failure.code = value.error && value.error.code;
      throw failure;
    }
    return value;
  }
  function useSnapshot(snapshot) {
    if (!sameContext(snapshot)) throw Error('Dienst, Lauf oder Konto der Antwort stimmen nicht überein.');
    if (!snapshot.cursor || !Array.isArray(snapshot.jobs)) throw Error('Unvollständiger Serverstatus.');
    state.snapshot = snapshot; state.cursor = snapshot.cursor;
    sessionStorage.setItem(CURSOR_KEY, JSON.stringify({server_uuid: state.info.server_uuid,
      run_id: state.info.run_id, subject: state.subject, cursor: snapshot.cursor}));
    $('write-state').textContent = `Laufstatus: ${snapshot.root_status} · Revision: ${snapshot.revision} · Epoche: ${snapshot.assignment_epoch}` +
      (snapshot.write_session_available ? '' : ' · Keine aktive Schreibsitzung. Eine berechtigte Owner-Übernahme ist erforderlich.');
    $('resume-confirm').checked = false;
    const owner = state.session.grants.find(grant => grant.kind === 'owner' && grant.resource_id === snapshot.run_id);
    $('owner-panel').hidden = snapshot.write_session_available || !owner;
    renderWorkflowReconciliation(snapshot.workflow_reconcile, Boolean(owner));
    renderRoutes(snapshot.routes || [], Boolean(owner));
    renderJobs(snapshot.jobs); renderPending();
  }
  async function refresh() {
    useSnapshot(await api('/api/snapshot'));
  }
  async function handle(action) {
    if (state.busy) return;
    error(''); busy(true);
    try { await action(); }
    catch (failure) { error(failure.message || 'Verbindung unterbrochen. Eine gespeicherte Meldung bleibt erhalten.'); }
    finally { busy(false); }
  }
  async function acknowledge(value) {
    const pending = state.pending;
    const request = wire();
    if (!request || !value.receipt || value.receipt.request_id !== request.request_id) {
      throw Error('Kein passender dauerhafter Beleg. Die gespeicherte Meldung bleibt erhalten.');
    }
    const context = value.receipt.request_context;
    const grant = state.session.grants.find(item => item.id === request.grant_id);
    if (!context || context.subject !== pending.subject || !grant || !context.grant ||
        Object.keys(context.grant).sort().join(',') !== 'id,kind,resource_id' ||
        ['id', 'kind', 'resource_id'].some(key => context.grant[key] !== grant[key])) {
      throw Error('Der Beleg gehört nicht zum bestätigten Konto und Grant. Die gespeicherte Meldung bleibt erhalten.');
    }
    if (!globalThis.crypto || !crypto.subtle || typeof crypto.subtle.digest !== 'function') {
      throw Error('Die Belegprüfsumme kann in diesem Browser nicht geprüft werden. Die gespeicherte Meldung bleibt erhalten.');
    }
    const checksum = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',
      new TextEncoder().encode(pending.wire_json))), byte => byte.toString(16).padStart(2, '0')).join('');
    if (context.wire_sha256 !== checksum) {
      throw Error('Die Belegprüfsumme gehört zu einer anderen Meldung mit derselben Kennung. Die gespeicherte Meldung bleibt erhalten.');
    }
    useSnapshot(value.snapshot);
    const identity = request.request_id;
    clearPending();
    message(`Beleg gespeichert: ${identity}. Der angezeigte Zustand stammt aus dem aktuellen Serverstatus.`);
  }
  async function lookup() {
    if (!canUsePending()) throw Error('Die gespeicherte Meldung gehört nicht zur aktuellen Anmeldung.');
    const request = wire();
    const value = await api('/api/requests/' + encodeURIComponent(request.request_id));
    if (value.receipt) { await acknowledge(value); return true; }
    if (value.snapshot) useSnapshot(value.snapshot);
    message('Noch kein gespeicherter Beleg vorhanden. Eine erneute Übermittlung verwendet dieselbe Meldung.');
    return false;
  }
  async function sendPending(retry) {
    if (!canUsePending()) throw Error('Mit dem Konto der gespeicherten Meldung anmelden.');
    if (retry && await lookup()) return;
    await acknowledge(await api('/api/requests', {method: 'POST', body: state.pending.wire_json}));
  }
  async function confirm(operation, args, grantId) {
    if (state.pending || state.invalidPending) throw Error('Zuerst den Ausgang der gespeicherten Meldung klären.');
    const request = {request_id: 'UI.Request.' + crypto.randomUUID().replaceAll('-', ''),
                     grant_id: grantId, operation, args};
    const pending = {format: 'solidcraftbot.courier-pending/1', server_uuid: state.info.server_uuid,
                     run_id: state.info.run_id, subject: state.subject,
                     cursor: state.cursor, wire_json: JSON.stringify(request)};
    // Persistence must succeed before an explicitly confirmed effect is sent.
    sessionStorage.setItem(PENDING_KEY, JSON.stringify(pending));
    state.pending = pending; renderPending();
    await sendPending(false);
  }
  function check(label, parent) {
    const row = node('label', undefined, 'check'), input = document.createElement('input');
    input.type = 'checkbox'; row.append(input, node('span', label)); parent.append(row); return input;
  }
  function select(label, choices, parent) {
    const row = node('label', label), input = document.createElement('select');
    input.append(new Option('Bitte ausdrücklich auswählen', ''));
    for (const [value, text] of choices) input.append(new Option(text, value));
    row.append(input); parent.append(row); return input;
  }
  function mutationButton(label, parent, ready, action) {
    const button = node('button', label); button.type = 'button'; button.dataset.mutation = 'true';
    const update = () => { button.dataset.ready = String(Boolean(ready())); controls(); };
    button.addEventListener('click', () => handle(action)); parent.append(button); update(); return update;
  }
  function renderWorkflowReconciliation(hint, owner) {
    const area = $('workflow-reconciliation'); area.replaceChildren();
    area.hidden = !owner || !hint;
    if (!owner || !hint) return;
    area.append(node('h3', 'Arbeitsplatz nach Wiederaufnahme abgleichen'));
    if (hint.reason) area.append(node('p', hint.reason));
    if (!hint.allowed) return;
    const observations = hint.args_template.observations;
    const details = node('details'); details.append(node('summary', 'Vollständige erwartete Gefäßliste anzeigen'));
    const list = node('ul');
    for (const item of observations) list.append(node('li',
      `${item.sample_id || 'Abgeleitetes Gefäß'} · ${item.vessel_id} · ${JSON.stringify(item.location)}`));
    details.append(list); area.append(details);
    const manifest = check('Ich habe die vollständige gezeigte Gefäßliste und ihre Orte ausdrücklich abgeglichen (synthetische Angabe).', area);
    const workspace = check('Der Arbeitsbereich ist ausdrücklich frei bestätigt.', area);
    const arm = check('Der Arm ist ausdrücklich außerhalb des Arbeitsbereichs bestätigt.', area);
    const gripper = check('Der Greifer ist ausdrücklich leer bestätigt.', area);
    const update = mutationButton('Arbeitsplatzabgleich ausdrücklich melden', area,
      () => [manifest, workspace, arm, gripper].every(input => input.checked),
      () => confirm('reconcile', {...hint.args_template, scope: 'workflow',
        manifest_confirmed: true, workspace_clear: true, arm_clear: true, gripper_empty: true}, hint.grant_id));
    for (const input of [manifest, workspace, arm, gripper]) input.addEventListener('change', update);
  }
  function renderRoutes(routes, owner) {
    const area = $('route-preparation'); area.replaceChildren(); area.hidden = !owner;
    if (!owner) return;
    area.append(node('h3', 'Botenauftrag vorbereiten'));
    const offered = routes.flatMap(route => (route.allowed_actions || [])
      .filter(action => action.operation === 'prepare_route').map(action => ({route, action})));
    if (!offered.length) {
      area.append(node('p', 'Derzeit ist keine weitere Route zur Vorbereitung freigegeben. Erforderliche Arbeitsplatzabgleiche zuerst ausdrücklich abschließen.', 'muted'));
      return;
    }
    for (const {route, action} of offered) {
      const card = node('div'); card.dataset.route = route.id;
      const jobId = 'UI.Job.' + crypto.randomUUID().replaceAll('-', '');
      const authority = {boot_id: state.snapshot.boot_id, assignment_epoch: state.snapshot.assignment_epoch};
      card.append(node('p', `Route: ${route.id} · ${route.source_endpoint} → ${route.target_endpoint} · Agent: ${route.agent_id}`),
        node('p', `Neue Auftragskennung: ${jobId}`, 'job-state'));
      const agreed = check('Ich möchte diese Route unter der gezeigten neuen Kennung vorbereiten. Noch keine Übergabe bestätigen.', card);
      const update = mutationButton('Route als neuen Auftrag vorbereiten', card, () => agreed.checked,
        () => confirm('prepare_route', {...authority, route_id: route.id, job_id: jobId}, action.grant_id));
      agreed.addEventListener('change', update); area.append(card);
    }
  }
  function ownerActions(job, article) {
    const authority = {boot_id: state.snapshot.boot_id, assignment_epoch: state.snapshot.assignment_epoch};
    const actions = job.allowed_actions || [];
    const hold = actions.find(action => action.operation === 'hold');
    const cancel = actions.find(action => action.operation === 'cancel');
    const reconcile = actions.find(action => action.operation === 'reconcile');
    const dispatch = actions.find(action => action.operation === 'dispatch');
    if (dispatch) {
      const area = node('div');
      const agreed = check('Ich stelle diesen vorbereiteten Auftrag ausdrücklich dem zuständigen Agenten bereit. Dies bestätigt keine Übernahme oder Ablieferung.', area);
      const update = mutationButton('Botenauftrag ausdrücklich bereitstellen', area, () => agreed.checked,
        () => confirm('dispatch', {...authority, job_id: job.job_id}, dispatch.grant_id));
      agreed.addEventListener('change', update); article.append(area);
    }
    if (!hold && !cancel && !reconcile) return;
    const area = node('details'); area.append(node('summary', 'Owner: Problem oder Disposition melden'));
    const reasonLabel = node('label', 'Begründung (Pflichtfeld)'), reason = document.createElement('input');
    reason.type = 'text'; reason.maxLength = 2048; reason.required = true;
    reasonLabel.append(reason); area.append(reasonLabel);
    const buttons = node('div', undefined, 'actions'), updates = [];
    const hasReason = () => Boolean(reason.value.trim());
    if (hold) updates.push(mutationButton('Auftrag halten', buttons, hasReason,
      () => confirm('hold', {...authority, job_id: job.job_id, reason: reason.value.trim()}, hold.grant_id)));
    if (cancel) updates.push(mutationButton('Abbruch anfordern', buttons, hasReason,
      () => confirm('cancel', {...authority, job_id: job.job_id, reason: reason.value.trim()}, cancel.grant_id)));
    area.append(buttons);
    if (reconcile) {
      const outcome = select('Ergebnis des Abgleichs', [['unknown', 'Ausgang unbekannt'],
        ['not_performed', 'Nicht durchgeführt'], ['performed', 'Durchführung ausdrücklich beobachtet']], area);
      const location = select('Aktuell bestätigter Ort', [['unknown', 'Unbekannt'],
        ['source', `Quelle: ${job.source_endpoint}`], ['target', `Ziel: ${job.target_endpoint}`],
        ['agent', `Beim Agenten: ${job.agent_id}`]], area);
      const manifest = check('Das oben gezeigte Auftragsmanifest wurde ausdrücklich abgeglichen (synthetische Angabe).', area);
      const valid = () => hasReason() && manifest.checked && outcome.value && location.value &&
        (outcome.value === 'unknown' ? location.value === 'unknown' :
          outcome.value === 'not_performed' ? location.value === 'source' : location.value !== 'unknown');
      const update = mutationButton('Disposition ausdrücklich melden', area, valid, () => {
        let place = null;
        if (location.value === 'source' || location.value === 'target') place = {kind: 'endpoint',
          endpoint_id: location.value === 'source' ? job.source_endpoint : job.target_endpoint};
        else if (location.value === 'agent') place = {kind: 'agent', agent_id: job.agent_id};
        return confirm('reconcile', {...authority, scope: 'job', job_id: job.job_id, outcome: outcome.value, location: place,
          manifest: job.manifest, reason: reason.value.trim()}, reconcile.grant_id);
      });
      outcome.addEventListener('change', update); location.addEventListener('change', update);
      manifest.addEventListener('change', update); updates.push(update);
      area.append(node('p', 'Ein Abgleich erfindet keine fehlenden Übergabebelege. Terminale Konflikte besitzen keine Freigabe; eine abgeglichene Abbruchdisposition ist kein normaler Transporterfolg.', 'muted'));
    }
    reason.addEventListener('input', () => updates.forEach(update => update()));
    article.append(area);
  }
  function renderJobs(jobs) {
    const cards = [];
    for (const [index, job] of jobs.entries()) {
      const article = node('article', undefined, job.control === 'held' ? 'held' : undefined);
      article.dataset.job = job.job_id;
      article.append(node('h3', `Auftrag ${job.job_id}`),
        node('p', `${job.source_endpoint} → ${job.target_endpoint}`, 'job-location'),
        node('p', `Rack: ${job.rack_id} · Agent: ${job.agent_id} · ${job.phase} / ${job.control}`, 'job-state'));
      if (job.control === 'held') article.append(node('p', 'Auftrag gehalten – eine ausdrückliche Klärung ist erforderlich.'));
      const details = node('details'); details.append(node('summary', 'Erwartete Rackplätze, Gefäße und Proben'));
      const table = document.createElement('table'), head = document.createElement('thead'), row = document.createElement('tr');
      for (const label of ['Rackplatz', 'Gefäß', 'Probe / Material', 'Inhaltsrevision']) row.append(node('th', label));
      head.append(row); table.append(head);
      const body = document.createElement('tbody');
      for (const item of job.manifest) {
        const tr = document.createElement('tr');
        for (const value of [item.place_id, item.vessel_id,
          item.materials.map(material => material.material_id).join(', '), item.content_revision]) tr.append(node('td', String(value)));
        body.append(tr);
      }
      table.append(body); const wrap = node('div', undefined, 'table-wrap'); wrap.append(table); details.append(wrap); article.append(details);
      const actions = (job.allowed_actions || []).filter(action => action.operation === 'attest' && roles[action.role]);
      if (actions.length) {
        const label = node('label', 'Beobachtete Rackkennung'), input = document.createElement('input');
        input.id = 'observed-rack-' + index; input.autocomplete = 'off'; label.htmlFor = input.id;
        article.append(label, input);
        const agreed = check('Ich bestätige diese einzelne Rollenangabe und den gezeigten Rackinhalt ausdrücklich für den synthetischen Test.', article);
        const buttons = node('div', undefined, 'actions'), updates = [];
        for (const action of actions) {
          const ready = () => agreed.checked && input.value.trim() === job.rack_id;
          updates.push(mutationButton(roles[action.role], buttons, ready, () => confirm('attest', {
            job_id: job.job_id, role: action.role,
            observation_id: 'UI.Observation.' + crypto.randomUUID().replaceAll('-', ''),
            assignment_epoch: job.assignment_epoch,
            handover_id: action.role.startsWith('pickup') ? job.pickup_handover_id : job.delivery_handover_id,
            manifest_sha256: job.manifest_sha256, observed_rack_id: input.value.trim(), confirmed: true,
          }, action.grant_id)));
        }
        agreed.addEventListener('change', () => updates.forEach(update => update()));
        input.addEventListener('input', () => updates.forEach(update => update()));
        article.append(buttons);
      } else if (!terminal.has(job.phase)) article.append(node('p', 'Für dieses Konto ist derzeit keine Übergabebestätigung verfügbar.', 'muted'));
      ownerActions(job, article); cards.push(article);
    }
    $('jobs').replaceChildren(...(cards.length ? cards : [node('p', 'Für dieses Konto sind noch keine Transportaufträge sichtbar.')]));
    controls();
  }

  $('login-form').addEventListener('submit', event => {
    event.preventDefault();
    handle(async () => {
      const username = $('username').value, password = $('password').value;
      $('password').value = '';
      try {
        const login = await api('/api/login', {method: 'POST', authenticated: false,
          body: JSON.stringify({username, password, server_uuid: state.info.server_uuid})});
        state.token = login.access_token; state.subject = login.subject;
        state.session = await api('/api/session');
        if (state.session.subject !== state.subject || state.session.server_uuid !== state.info.server_uuid) {
          throw Error('Anmeldung und Dienstkontext stimmen nicht überein.');
        }
        let remembered = null;
        try { remembered = JSON.parse(sessionStorage.getItem(CURSOR_KEY)); } catch (_) { /* no remembered prefix */ }
        state.cursor = sameContext(remembered) ? remembered.cursor : sameContext(state.pending) ? state.pending.cursor : null;
        $('identity').textContent = `Konto: ${state.subject} · Principal: ${state.session.principal}`;
        $('login-panel').hidden = true; $('session-panel').hidden = false;
        await refresh(); message('Angemeldet. Abrufen bestätigt keine Übergabe.');
      } catch (failure) {
        clearLogin();
        throw failure;
      }
    });
  });
  $('refresh').addEventListener('click', () => handle(async () => { await refresh(); message('Aktueller Zustand abgerufen; keine Übergabe bestätigt.'); }));
  $('logout').addEventListener('click', () => handle(async () => {
    try { await api('/api/logout', {method: 'POST', body: '{}'}); }
    finally { clearLogin(); }
    message('Abgemeldet. Eine gespeicherte Meldung und Serverreservierungen bleiben erhalten.');
  }));
  $('receipt').addEventListener('click', () => handle(lookup));
  $('retry').addEventListener('click', () => handle(() => sendPending(true)));
  $('discard').addEventListener('click', () => handle(async () => {
    clearPending(); message('Nur der lokale Entwurf wurde verworfen. Der Serverauftrag wurde nicht abgebrochen.');
  }));
  $('resume-confirm').addEventListener('change', controls);
  $('resume').addEventListener('click', () => handle(async () => {
    const snapshot = state.snapshot;
    const grant = state.session.grants.find(item => item.kind === 'owner' && item.resource_id === snapshot.run_id);
    if (!grant || !$('resume-confirm').checked) throw Error('Owner-Bestätigung erforderlich.');
    await confirm('resume', {boot_id: snapshot.boot_id, assignment_epoch: snapshot.assignment_epoch}, grant.id);
  }));
  window.addEventListener('online', () => { if (state.token) handle(refresh); });
  loadPending(); renderPending();
  handle(async () => {
    state.info = await api('/api/info', {authenticated: false});
    $('service').textContent = `Dienst: ${state.info.server_uuid} · Lauf: ${state.info.run_id}`;
    renderPending();
  });
})();
