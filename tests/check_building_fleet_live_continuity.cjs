// Measure a fresh live browser session. Serve the exact bundle with an untouched worker.
// Usage: node check_building_fleet_live_continuity.cjs <build-dir> <new-report.json> <playwright> <chrome> [wall-seconds] [first-continuation|verified-extensions|verified-goal]
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const zlib = require('node:zlib');
const {createHash} = require('node:crypto');
const digest = value => createHash('sha256').update(value).digest('hex');

function observe() {
    const audit = window.__continuity = {snapshots: [], frames: [], progress: [], errors: []};
    const bounded = vector => vector.every(component => Math.abs(component) <= 1e-6);
    function motionRecord(trajectory, start, end) {
        const moving = [];
        let tail;
        for (const episode of trajectory.episodes) {
            const points = episode.points;
            for (let i = 1; i < points.length; i++) {
                const a = points[i-1], b = points[i];
                if (b.time_s <= start || a.time_s >= end) continue;
                tail = b;
                // A quintic with equal endpoint poses and zero endpoint V and A is constant.
                if (bounded(a.velocity_mm_rad_s) && bounded(b.velocity_mm_rad_s) &&
                        bounded(a.acceleration_mm_rad_s2) && bounded(b.acceleration_mm_rad_s2) &&
                        a.pose_mm_rad.every((p, j) => Math.abs(p-b.pose_mm_rad[j]) <= 1e-8)) continue;
                const from = Math.max(start, a.time_s), to = Math.min(end, b.time_s);
                if (moving.length && moving.at(-1)[1] === from) moving.at(-1)[1] = to;
                else moving.push([from, to]);
            }
        }
        return {moving, v_end: tail?.velocity_mm_rad_s, a_end: tail?.acceleration_mm_rad_s2};
    }
    const Original = window.Worker;
    window.Worker = class extends Original {
        constructor(...args) {
            super(...args);
            if (!new URL(args[0], location.href).pathname.endsWith('/building_fleet_browser_worker.mjs')) return;
            this.addEventListener('message', ({data}) => {
                const wall = performance.now()/1000;
                if (data.type === 'progress') audit.progress.push({wall, ...data.progress});
                if (data.type === 'error') audit.errors.push(data.error);
                if (data.type !== 'state') return;
                const s = data.state, w = s.executed_window;
                const curves = new Map((w?.trajectories ?? []).map(t => [
                    t.vehicle_id, motionRecord(t, w.start_s, w.end_s)]));
                audit.snapshots.push({wall, model: s.model_time_s, step: s.integration_step_s,
                    window: w ? [w.start_s, w.end_s] : null, preparation: s.background_preparation,
                    worker_timing: s.worker_timing, cameras: s.camera_frames.length,
                    vehicles: s.states.map(row => ({...row, pva: curves.get(row.id)}))});
            });
        }
    };
    function frame(now) {
        const f = window.__buildingFleet;
        if (f?.ready) audit.frames.push({wall: now/1000, received: audit.snapshots.length, resync_count: f.display_resync_count ?? null, model: f.time_s, display: f.display_time_s,
            frozen: f.frozen, factor: f.playback_factor ?? null, buffer_underrun: f.buffer_underrun ?? null});
        requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
}

function horizonChanges(snapshots) {
    const history = [], latest = new Map();
    for (const s of snapshots) {
        for (const v of s.vehicles) {
            if (!Number.isFinite(v.own_route_horizon_mm)) continue;
            if (latest.get(v.id) === v.own_route_horizon_mm) continue;
            history.push({vehicle:v.id, model_s:s.model, wall_s:s.wall, progress_mm:v.progress_mm,
                horizon_mm:v.own_route_horizon_mm, v:v.pva?.v_end, a:v.pva?.a_end, pose:v.pose_xyz_mm,
                joined:s.preparation?.continuations ?? 0, receipt:s.preparation?.checked_intervals?.[v.id] ?? null});
            latest.set(v.id,v.own_route_horizon_mm);
        }
    }
    return history;
}

function summarize(audit) {
    const snapshots = audit.snapshots;
    const byTime = new Map();
    for (const [index, s] of snapshots.entries()) {
        if (!byTime.has(s.model)) byTime.set(s.model, []);
        byTime.get(s.model).push(index);
    }
    const first = snapshots[0], last = snapshots.at(-1);
    const starts = new Map(first.vehicles.map(v => [v.id, v.pose_xyz_mm]));
    const moved = new Set(), stops = [], waits = new Map();
    let activeStops = new Map();
    const groups = {};
    let firstMotion = null;
    for (const s of snapshots) {
        s.real_stop = []; s.resource_wait = [];
        const currentStops = new Map();
        for (const v of s.vehicles) {
            const start = starts.get(v.id);
            if (Math.hypot(...v.pose_xyz_mm.slice(0, 2).map((p, i) => p-start[i])) >= 1) {
                moved.add(v.id);
                firstMotion ??= {vehicle: v.id, wall_s: s.wall, model_s: s.model};
            }
            const still = v.pva && s.window[1]-s.window[0] >= s.step-1e-8 &&
                !v.pva.moving.some(([, end]) => end > s.model-s.step+1e-8);
            if (!still) continue;
            if (v.requested_resource && v.hold_reason === 'resource_wait') {
                s.resource_wait.push(v.id);
                waits.set(v.id, {id: v.id, resource: v.requested_resource, holder: v.resource_holder,
                    queue_position: v.queue_position, pose: v.pose_xyz_mm, condition: v.hold_condition, model_s: s.model});
            }
            if ('controller_mode' in v ? !v.controller_mode : v.mode !== 'driving') continue;
            const reason = v.controller_reason ?? v.hold_reason ?? 'unreported';
            s.real_stop.push([v.id, reason]);
            const key = v.id+' '+reason;
            let stop = activeStops.get(key);
            if (!stop) {
                stop = {vehicle: v.id, reason, first_model_s: s.model,
                first_wall_s: s.wall, first_progress_mm: v.progress_mm ?? null, horizon_mm: v.own_route_horizon_mm,
                pending_full_route: s.preparation?.requests?.some(r => r.vehicle_id === v.id && r.kind === 'full_route') ?? false};
                stops.push(stop);
            }
            stop.last_model_s = s.model;
            stop.last_wall_s = s.wall;
            currentStops.set(key,stop);
        }
        activeStops = currentStops;
    }
    let previous, group, comparables = 0;
    for (const f of audit.frames) {
        const index = byTime.get(f.model)?.findLast(i => i < (f.received ?? Infinity));
        assert(index !== undefined, 'Displayed model clock must have an executed worker snapshot');
        const s = snapshots[index], w = s.window;
        f.snapshot = index;
        let firstBuffered = index;
        while (w && f.display < snapshots[firstBuffered].window[0]-1e-7) {
            const older = snapshots[firstBuffered-1]?.window;
            assert(older && older[1] >= snapshots[firstBuffered].window[0]-1e-7,
                'Displayed pose must have contiguous overlapping executed history');
            firstBuffered--;
        }
        assert(!w || f.display <= w[1]+1e-7, 'Display cannot extrapolate beyond execution');
        f.presentation = f.frozen ? 'paused_or_disconnected' : !w ? 'snapshot_only' : 'advancing';
        const resync = previous && Number.isInteger(f.resync_count) && f.resync_count > previous.resync_count;
        if (resync) f.presentation = 'explicit_resync';
        else if (previous && !f.frozen && w && Math.abs(f.display-previous.display) <= 1e-9) {
            const laterPVA = snapshots.slice(firstBuffered,index+1).some(snapshot =>
                snapshot.vehicles.some(v => v.pva.moving.some(([, end]) => end > f.display+1e-9)));
            f.presentation = f.display >= w[1]-1e-9 ? 'buffer_underrun' : laterPVA ? 'display_freeze' : 'stationary_buffer';
        }
        const prevSample = snapshots[index-1];
        const rate = s.worker_timing?.last_cycle?.realtime_factor ?? (prevSample && s.wall > prevSample.wall ?
            (s.model-prevSample.model)/(s.wall-prevSample.wall) : null);
        f.compute_slowdown = Number.isFinite(rate) ? rate < 1 : null;
        if (previous) {
            comparables++;
            const seconds = f.wall-previous.wall;
            const bucket = groups[f.presentation] ??= {frames: 0, wall_s: 0, episodes: 0, longest_s: 0};
            if (group?.name !== f.presentation) { group = {name: f.presentation, seconds: 0}; bucket.episodes++; }
            group.seconds += seconds;
            bucket.frames++;
            bucket.wall_s += seconds;
            bucket.longest_s = Math.max(bucket.longest_s, group.seconds);
        }
        previous = f;
    }
    const firstPositive = snapshots.find(s => s.model > 0);
    const finiteFactors = audit.frames.map(f => f.factor).filter(Number.isFinite);
    return {first_motion: firstMotion, moved: [...moved], model_s: last.model, wall_s: last.wall,
        model_per_wall: (last.model-firstPositive.model)/(last.wall-firstPositive.wall),
        display_s: previous.display,
        displayed_model_s_per_wall_s: (previous.display-audit.frames[0].display)/(previous.wall-audit.frames[0].wall),
        playback_factor_range: finiteFactors.length ? [Math.min(...finiteFactors), Math.max(...finiteFactors)] : null,
        classified_frame_intervals: comparables, presentation: groups,
        controller_stops: stops, resource_wait: [...waits.values()], horizon_changes:horizonChanges(snapshots),
        resync_count: previous.resync_count ?? null, worker_timing: last.worker_timing ?? null, preparation: last.preparation,
        qualification: 'Per-frame presentation and concurrent controller/resource observations in one foreground live session. Baseline snapshots do not expose controller or resource reasons.'};
}

async function run() {
    const [directory, reportPath, playwright, chrome, duration = '50', finish] = process.argv.slice(2);
    const root = path.resolve(directory), output = path.resolve(reportPath), seconds = Number(duration);
    assert(seconds > 0 && Number.isFinite(seconds));
    const checkIntervals = finish === 'verified-extensions' || finish === 'verified-goal';
    const tracePath = output+'.trace.json.gz';
    assert(!fs.existsSync(output) && !fs.existsSync(tracePath), 'Supply new evidence paths');
    const build = JSON.parse(fs.readFileSync(path.join(root,'browser-build-report.json')));
    assert(build.passed && !build.bundle_only);
    for (const [name, pin] of Object.entries(build.files)) {
        const bytes = fs.readFileSync(path.join(root, name));
        assert.equal(digest(bytes), pin.sha256, name); assert.equal(bytes.byteLength, pin.bytes, name);
    }
    const manifest = JSON.parse(fs.readFileSync(path.join(root,'runtime-manifest.json')));
    assert.equal(digest(fs.readFileSync(path.join(root,'runtime-manifest.json'))),build.runtime_manifest.sha256);
    assert.equal(manifest.archive.sha256,build.files['runtime.zip'].sha256);
    const mime = {'.html':'text/html','.js':'text/javascript','.mjs':'text/javascript','.json':'application/json',
        '.wasm':'application/wasm','.zip':'application/zip','.gz':'application/gzip'};
    const server = http.createServer((req, res) => {
        const url = new URL(req.url, 'http://localhost');
        if (url.pathname === '/favicon.ico') return res.writeHead(204).end();
        const name = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
        if (!Object.hasOwn(build.files,name)) return res.writeHead(404).end();
        res.setHeader('Content-Type', mime[path.extname(name)] ?? 'application/octet-stream');
        res.setHeader('Content-Length',build.files[name].bytes);
        res.setHeader('Cache-Control','public,max-age=600');
        fs.createReadStream(path.join(root,name)).pipe(res);
    });
    const receipt = {passed:false, manifest_sha256:build.runtime_manifest.sha256,
        html_sha256:build.files['index.html'].sha256, archive_sha256:build.files['runtime.zip'].sha256,
        checker_sha256:digest(fs.readFileSync(__filename)), requested_wall_s:seconds, stop_condition:finish ?? 'wall_time',
        host_platform:process.platform, transfer:'identity', viewport:{width:1440,height:1000}, errors:[]};
    let browser;
    try {
        await new Promise((resolve, reject) => server.once('error',reject).listen(0,'127.0.0.1',resolve));
        browser = await require(playwright).chromium.launch({headless:true,executablePath:chrome,
            args:['--enable-gpu','--enable-webgl','--ignore-gpu-blocklist','--use-gl=angle',
                ...(process.platform === 'darwin' ? ['--use-angle=metal'] : [])]});
        receipt.chromium = browser.version();
        const page = await browser.newPage({viewport:receipt.viewport});
        page.on('pageerror', err => receipt.errors.push(err.message));
        const origin = 'http://127.0.0.1:'+server.address().port;
        page.on('request', req => {
            if (/^https?:/.test(req.url()) && new URL(req.url()).origin !== origin) receipt.errors.push('external '+req.url());
        });
        page.on('requestfailed', req => receipt.errors.push(req.url()+' '+req.failure()?.errorText));
        await page.addInitScript(observe);
        const response = await page.goto(origin);
        assert.equal(digest(await response.body()),receipt.html_sha256);
        const started = Date.now();
        for (;;) {
            const status = await page.evaluate(() => {
                const states = window.__continuity.snapshots, s = states.at(-1);
                const initial = states.find(x => x.vehicles.some(v => v.own_route_horizon_mm > 0));
                const first = initial?.vehicles.find(v => v.own_route_horizon_mm > 0);
                const current = s?.vehicles.find(v => v.id === first?.id);
                const knotEnds = current && new Set(states.filter(x => x.preparation?.continuations > 0)
                    .map(x => x.vehicles.find(v => v.id === current.id).own_route_horizon_mm).filter(Number.isFinite));
                return {wall: performance.now()/1000, model: s?.model, preparation: s?.preparation,
                    full: s?.worker_timing?.planner_jobs?.full_route, starter:s?.worker_timing?.last_starter,
                    observed_extensions: knotEnds?.size ?? 0,
                    full_horizon: current && current.own_route_horizon_mm === current.goal_mm,
                    past_first_horizon: current && current.progress_mm > first.own_route_horizon_mm+1,
                    planner_ready:s?.worker_timing?.planner_ready_wall_ms, errors:window.__continuity.errors};
            });
            if (status.errors.length) break;
            console.log(JSON.stringify(status));
            const joined = status.preparation?.continuations > 0;
            const completed = (finish === 'first-continuation' && joined) ||
                (checkIntervals && joined && status.past_first_horizon && status.observed_extensions >= 3 &&
                    (finish !== 'verified-goal' || status.full_horizon));
            if (status.wall >= seconds || (completed && status.wall >= 55)) break;
            if (checkIntervals && Object.keys(status.preparation?.failures ?? {}).length) break;
            assert(Date.now()-started < (seconds+30)*1000, 'Real browser deadline exceeded');
            await page.waitForTimeout(Math.min(10000, (seconds-status.wall)*1000));
        }
        const audit = await page.evaluate(() => window.__continuity);
        receipt.errors.push(...audit.errors);
        try {
            assert(!receipt.errors.length, receipt.errors.join('\n'));
            receipt.latest = await page.evaluate(pins => {
                const f = window.__buildingFleet, s = f.snapshot;
                return {host:s.execution_host, fallback:s.recording_fallback, vehicles:f.instance_count,
                    cameras:s.camera_frames.length, rendered:f.renderer_stats.last_instance_count, session:s.session_id,
                    sources_match: Object.keys(s.source_files_sha256).length === Object.keys(pins).length &&
                        Object.entries(pins).every(([name,ref]) => s.source_files_sha256[name] === ref.sha256)};
            },manifest.files);
            assert.equal(receipt.latest.sources_match,true);
            assert.equal(receipt.latest.host,'browser_wasm_worker'); assert.equal(receipt.latest.fallback,false);
            assert.equal(receipt.latest.vehicles,20); assert.equal(receipt.latest.rendered,20); assert.equal(receipt.latest.cameras,20);
            receipt.summary = summarize(audit);
            // Cut all comparison runs at identical wall time; the long gate run may continue independently.
            const frames = audit.frames.filter(frame => frame.wall <= 55);
            const received = frames.at(-1)?.received;
            if (frames.length && received && audit.snapshots[received-1].model > 0) receipt.first_55_wall_s = summarize({
                frames, snapshots: audit.snapshots.slice(0,received)});

            assert(receipt.summary.first_motion && receipt.summary.classified_frame_intervals);
            if (checkIntervals) {
                const latest = audit.snapshots.at(-1), first = receipt.summary.horizon_changes[0];
                assert.deepEqual(latest.preparation.failures, {});
                assert(latest.preparation.continuations > 0, 'An executed C2 continuation is required');
                assert(receipt.summary.horizon_changes.filter(h => h.vehicle === first.vehicle && h.receipt && h.joined).length >= 3,
                    'Observe the partial join and two further checked horizons on the same physical leg');
                const last = latest.vehicles.find(v => v.id === first.vehicle);
                if (finish === 'verified-goal') assert.equal(last.own_route_horizon_mm,last.goal_mm);
                assert(last.progress_mm > first.horizon_mm+1,
                    'The transporter must move beyond its original checked starter');
            }
        } finally {
            const bytes = zlib.gzipSync(JSON.stringify(audit));
            fs.writeFileSync(tracePath,bytes,{flag:'wx'});
            receipt.trace = {file:path.basename(tracePath),sha256:digest(bytes)};
        }
        receipt.passed = true;
    } catch (err) {
        receipt.error = err.stack; throw err;
    } finally {
        await browser?.close();
        server.closeAllConnections(); server.close();
        fs.writeFileSync(output,JSON.stringify(receipt,null,2)+'\n',{flag:'wx'});
    }
    console.log(JSON.stringify(receipt.summary));
}
module.exports = {summarize};
if (require.main === module) run().catch(err => { console.error(err); process.exitCode=1; });
