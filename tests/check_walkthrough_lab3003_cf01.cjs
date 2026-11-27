const assert = require('node:assert/strict');
const test = require('node:test');
const {execFileSync} = require('node:child_process');
const path = require('node:path');
const {create} = require('../scripts/walkthrough_lab3003_cf01.js');
const {jointMatrix} = require('../scripts/walkthrough_interaction.js');
const {Curve} = require('../scripts/templates/quintic_motion.js');

const point = (time_s, phase, overrides = {}) => ({
  time_s, phase, lid_deg: 0, latch_mm: [0, 0], rotor_deg: 0, rpm: 0,
  seated: [], arm_clear: true, lid_locked: true, brake_held: true, cover_removed: false,
  ...overrides,
});
const joint = (body_ids, axis, origin_mm = [0, 0, 0]) => ({
  body_ids, axis, origin_mm, reference_value: 0,
});

function config() {
  const removed = {cover_removed: true};
  const open = {...removed, lid_deg: 105, lid_locked: false, latch_mm: [6, 6]};
  const one = {seated: ['TubeA']};
  const both = {seated: ['TubeA', 'TubeB']};
  const ready = {...removed, ...both};
  return {
    duration_s: 19,
    spin_started_s: 12,
    brake_started_s: 14,
    stopped_s: 19,
    playback_rate: 1,
    cover_body_id: 'Cover',
    empty_rotor_body_ids: ['RotorTube01', 'RotorCap01', 'RotorTube07', 'RotorTube02'],
    samples: [
      {id: 'TubeA', slot: 1, carrier_body_id: 'CarrierA', rotor_body_ids: ['RotorTube01', 'RotorCap01']},
      {id: 'TubeB', slot: 7, carrier_body_id: 'CarrierB', rotor_body_ids: ['RotorTube07']},
    ],
    joints: {
      lid: joint(['Lid'], [-1, 0, 0], [10, 20, 30]),
      rotor: joint(['Rotor', 'RotorTube07'], [0, 0, 1]),
      latches: [joint(['PinA'], [0, 1, 0]), joint(['PinB'], [0, -1, 0])],
    },
    steps: [
      point(0, 'docked'),
      point(1, 'cover_removed', removed),
      point(2, 'unlocking', removed),
      point(3, 'opening', {...open, lid_deg: 0}),
      point(4, 'open', open),
      point(4.8, 'arm_transfer', {...open, arm_clear: false, tube_id: 'TubeA'}),
      point(5, 'seated', {...open, ...one, tube_id: 'TubeA'}),
      point(6, 'arm_clear', {...open, ...one}),
      point(7, 'arm_transfer', {...open, ...one, arm_clear: false, tube_id: 'TubeB'}),
      point(8, 'seated', {...open, ...both, tube_id: 'TubeB'}),
      point(9, 'closing', {...open, ...both}),
      point(10, 'locking', {...open, ...both, lid_deg: 0}),
      point(11, 'locked', ready),
      point(12, 'spinning', {...ready, rpm: 100, brake_held: false}),
      point(14, 'braking', {...ready, rpm: 100, rotor_deg: 1200, brake_held: false}),
      point(19, 'stopped', {...ready, rotor_deg: 2700}),
    ],
  };
}

function supportedFixture(returning = false) {
  // Synthetic channels test custody and transforms, not the native arm path.
  const python = `
import json, math, sys
sys.path.insert(0, 'scripts')
from lab3003_cf01_cycle import compile_cycle
returning = sys.argv[1] == 'true'
home = .1 if returning else 0
points = [{'time_s': t, 'positions_rad': [angle]+[0]*5, 'velocities_rad_s': [0]*6,
           'accelerations_rad_s2': [0]*6} for t, angle in enumerate((home, .3, .6, home))]
jaw = [{'time_s': t, 'positions_mm': [gap], 'velocities_mm_s': [0], 'accelerations_mm_s2': [0]}
       for t, gap in enumerate((12, 9, 12, 12))]
samples = [{'id': label, 'slot': slot, 'points': points, 'jaw_points': jaw, 'grip_s': 1, 'seat_s': 2}
           for label, slot in (('B2_Tube01', 1), ('B2_Tube07', 7))]
returns = [dict(sample, direction='unload',
                points=[dict(point, time_s=3-point['time_s']) for point in reversed(points)],
                jaw_points=[dict(point, time_s=3-point['time_s']) for point in reversed(jaw)])
           for sample in reversed(samples)] if returning else None
print(json.dumps({'cycle': compile_cycle(arm_paths=samples, return_paths=returns),
                  'tracks': samples, 'returns': returns, 'home': math.degrees(home)}))
`;
  const {cycle, tracks, returns, home} = JSON.parse(execFileSync('python3', ['-B', '-c', python, String(returning)], {
    cwd: path.resolve(__dirname, '..'), encoding: 'utf8',
  }));
  const identity = () => Float32Array.from([1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]);
  function multiply(a, b) {
    const result = new Float32Array(16);
    for (let c=0;c<4;c++) for (let r=0;r<4;r++) for (let k=0;k<4;k++) result[4*c+r] += a[4*k+r]*b[4*c+k];
    return result;
  }
  cycle.joints = {...config().joints, pusher: joint(['Pusher'], [0,0,1])};
  cycle.cover_body_id = 'Cover';
  cycle.empty_rotor_body_ids = ['RotorTube01', 'RotorTube07'];
  for (const sample of cycle.samples) {
    sample.carrier_body_id = 'Carrier' + sample.slot;
    sample.rotor_body_ids = ['RotorTube' + String(sample.slot).padStart(2, '0')];
  }
  cycle.arm_motion_checked = true;
  cycle.arm_motion = {samples: tracks, joints: Array.from({length:6}, (_, i) => joint(['Arm'+i], [0,0,1])),
    reference_deg: [0,0,0,0,0,0], tool: {bodies:[{id:'Finger',gap_axis:[.5,0,0]}], reference_gap_mm:12},
    program_sha256:'a'.repeat(64), collision_report_sha256:'b'.repeat(64), native_report_sha256:'c'.repeat(64)};
  if (returning) {
    cycle.arm_motion.home_deg = [home,0,0,0,0,0];
    cycle.arm_motion.return_samples = returns;
  }
  return {cycle, motion: {Curve, multiply, identity}};
}

test('lowering preserves the same cassette body from arm to pusher to rotor', () => {
  const {cycle, motion} = supportedFixture();
  const runtime = create(cycle, jointMatrix, motion);
  assert(runtime.start(0, true));
  const sample = cycle.samples[0];
  const at = t => { runtime.advance(t*1000+.001); return runtime.snapshot; };
  assert.equal(at(sample.grip_s+.5).held_tube, sample.id);
  assert.equal(at(sample.support_release_s).pusher_sample_id, sample.id);
  assert.equal(runtime.snapshot.held_tube, null);
  const released = runtime.modelMatrix(sample.carrier_body_id);
  const lower = cycle.steps.find(step => step.phase === 'lowering' && step.tube_id === sample.id);
  const pocket = cycle.steps.find(step => step.phase === 'pocket_reached' && step.tube_id === sample.id);
  const halfway = at((lower.time_s+pocket.time_s)/2);
  assert.equal(halfway.pusher_sample_id, sample.id);
  assert(halfway.lift_mm > 0 && halfway.lift_mm < lower.lift_mm);
  assert(runtime.modelMatrix(sample.carrier_body_id)[14] < released[14]);
  assert(at(sample.pusher_lowered_s+.01).seated.includes(sample.id));
  assert.equal(runtime.hidden(sample.rotor_body_ids[0]), true);
  assert.equal(runtime.hidden(sample.carrier_body_id), false);
  assert.equal(at(cycle.duration_s).state, 'completed');
  assert.equal(runtime.snapshot.brake_held, true);

  const unsafe = structuredClone(cycle);
  unsafe.steps.find(step => step.phase === 'lowering').arm_clear = false;
  assert.throws(() => create(unsafe, jointMatrix, motion), /same supported tube/);
});

test('returned tubes rejoin the covered TR01 cassette only after confirmed standstill and individual handoffs', () => {
  const {cycle, motion} = supportedFixture(true);
  const runtime = create(cycle, jointMatrix, motion);
  const at = t => { runtime.advance(t*1000+.001); return runtime.snapshot; };
  const originalBody = id => cycle.samples.find(sample => sample.id === id).carrier_body_id;
  const close = (a, b) => a.every((value, i) => Math.abs(value - b[i]) < 1e-6);
  assert(runtime.start(0, true));
  assert(Math.abs(runtime.snapshot.arm_joints_deg[0] - cycle.arm_motion.home_deg[0]) < 1e-6);
  assert.equal(at(cycle.stopped_s).phase, 'stopped');
  assert.deepEqual(runtime.snapshot.seated, cycle.samples.map(sample => sample.id));
  assert.equal(runtime.snapshot.transport_ready, false);
  for (const sample of cycle.return_samples) {
    const body = originalBody(sample.id);
    const contact = cycle.steps.find(step => step.tube_id === sample.id && step.phase === 'pickup_contact').time_s;
    at(contact-.0001);
    const seated = Array.from(runtime.modelMatrix(body));
    assert.equal(at(contact).pusher_sample_id, sample.id);
    assert(close(seated, Array.from(runtime.modelMatrix(body))));
    const rising = at((contact+sample.arm_start_s)/2);
    assert(rising.lift_mm > 0);
    assert(runtime.modelMatrix(body)[14] > seated[14]);
    at(sample.grip_s-.0001);
    const supported = Array.from(runtime.modelMatrix(body));
    assert.equal(at(sample.grip_s).held_tube, sample.id);
    assert(close(supported, Array.from(runtime.modelMatrix(body))));
    assert.notEqual(runtime.modelMatrix(body), null);
    assert.equal(at(sample.cassette_release_s).held_tube, null);
    assert.equal(runtime.modelMatrix(body), null);
    assert.equal(runtime.hidden(body), false);
    assert(runtime.snapshot.returned.includes(sample.id));
    assert.equal(runtime.snapshot.transport_ready, false);
    assert.equal(runtime.hidden('Cover'), true);
    assert.equal(at(sample.pusher_parked_s).pusher_mm, 0);
  }
  assert.equal(at(cycle.duration_s).state, 'completed');
  assert.equal(runtime.snapshot.transport_ready, true);
  assert.equal(runtime.hidden('Cover'), false);
  assert.deepEqual(runtime.snapshot.seated, []);
  assert.deepEqual(runtime.snapshot.returned, cycle.samples.map(sample => sample.id).reverse());

  const unsafe = structuredClone(cycle);
  unsafe.steps.at(-1).cover_removed = true;
  assert.throws(() => create(unsafe, jointMatrix, motion), /cover fitted/);
  const displaced = structuredClone(cycle);
  displaced.arm_motion.return_samples[0].points[1].positions_rad[0] += .1;
  assert.throws(() => create(displaced, jointMatrix, motion), /same raised tube/);
});

test('requires actual docking, plays once and preserves custody through completion', () => {
  const cycle = create(config(), jointMatrix);
  assert.equal(cycle.start(0, false), false);
  assert.equal(cycle.start(0, {state: 'docked'}), false);
  assert.equal(cycle.snapshot.state, 'ready');
  assert.equal(cycle.hidden('Cover'), false);
  assert.equal(cycle.hidden('CarrierA'), false);
  assert.equal(cycle.hidden('RotorTube01'), true);
  assert.equal(cycle.hidden('RotorCap01'), true);
  assert.equal(cycle.hidden('Unsupported'), false);

  assert.equal(cycle.start(0, true), true);
  cycle.advance(4700);
  assert.equal(cycle.hidden('Cover'), true);
  assert.equal(cycle.hidden('CarrierA'), false);
  assert.equal(cycle.hidden('RotorTube01'), true);
  cycle.advance(4900);
  assert.equal(cycle.snapshot.phase, 'arm_transfer');
  assert.equal(cycle.hidden('CarrierA'), true);
  assert.equal(cycle.hidden('RotorTube01'), true);
  cycle.advance(5000);
  assert.deepEqual(cycle.snapshot.seated, ['TubeA']);
  assert.equal(cycle.hidden('CarrierA'), true);
  assert.equal(cycle.hidden('RotorTube01'), false);
  assert.equal(cycle.hidden('RotorCap01'), false);
  assert.equal(cycle.hidden('CarrierB'), false);
  assert.equal(cycle.hidden('RotorTube07'), true);

  cycle.advance(19000);
  assert.deepEqual(cycle.snapshot.seated, ['TubeA', 'TubeB']);
  assert.equal(cycle.hidden('RotorTube02'), true);
  assert.equal(cycle.hidden('CarrierB'), true);
  assert.equal(cycle.hidden('RotorTube07'), false);
  assert.equal(cycle.active, false);
  assert.equal(cycle.start(20000, true), false);
  assert.equal(cycle.resume(20000), false);
  assert.equal(cycle.snapshot.state, 'completed');
});

test('renders native joints and continuous rotor rotation with a locked lid and held brake after stopping', () => {
  const cycle = create(config(), jointMatrix);
  const fixedLid = Array.from(cycle.modelMatrix('Lid'));
  assert.equal(cycle.modelMatrix('Cover'), null);
  assert.equal(cycle.modelMatrix('Unrelated'), null);
  cycle.start(0, true);
  cycle.advance(3500);
  assert.notDeepEqual(Array.from(cycle.modelMatrix('Lid')), fixedLid);
  assert.equal(cycle.snapshot.lid_locked, false);
  assert(Math.abs(cycle.modelMatrix('PinA')[13] - 0.006) < 1e-8);
  assert(Math.abs(cycle.modelMatrix('PinB')[13] + 0.006) < 1e-8);

  cycle.advance(12500);
  assert.equal(cycle.snapshot.phase, 'spinning');
  assert.equal(cycle.snapshot.lid_locked, true);
  assert.equal(cycle.snapshot.brake_held, false);
  assert.equal(cycle.snapshot.rpm, 100);
  assert.equal(cycle.snapshot.rotor_deg, 300);
  assert.deepEqual(Array.from(cycle.modelMatrix('Lid')), fixedLid);
  assert.equal(cycle.hidden('Lid'), false);
  assert.deepEqual(cycle.modelMatrix('RotorTube01'), cycle.modelMatrix('Rotor'));
  assert.deepEqual(cycle.modelMatrix('RotorTube07'), cycle.modelMatrix('Rotor'));

  cycle.advance(16500);
  assert.equal(cycle.snapshot.phase, 'braking');
  assert.equal(cycle.snapshot.rpm, 50);
  assert.equal(cycle.snapshot.rotor_deg, 2325);
  cycle.advance(19000);
  assert.equal(cycle.snapshot.phase, 'stopped');
  assert.equal(cycle.snapshot.rotor_deg, 2700);
  assert.equal(cycle.snapshot.rpm, 0);
  assert.equal(cycle.snapshot.brake_held, true);
  assert.equal(cycle.snapshot.lid_locked, true);
});

test('pauses model time without losing ownership and resumes without replaying', () => {
  const cycle = create(config(), jointMatrix);
  cycle.start(100, true);
  cycle.pause(5100);
  const snapshot = cycle.snapshot;
  assert.equal(snapshot.state, 'paused');
  assert.equal(cycle.active, true);
  assert.deepEqual(snapshot.seated, ['TubeA']);
  assert.equal(cycle.advance(20000), false);
  assert.equal(cycle.start(20000, true), false);
  assert.deepEqual(cycle.snapshot, snapshot);
  assert.equal(cycle.resume(20000), true);
  cycle.advance(23000);
  assert.deepEqual(cycle.snapshot.seated, ['TubeA', 'TubeB']);
  assert.equal(cycle.snapshot.time_s, 8);
});

test('rejects invalid custody, unlocked spin, inconsistent angles and shared CAD owners', () => {
  const edit = (find, override) => {
    const data = config();
    Object.assign(data.steps.find(step => step.phase === find), override);
    return data;
  };
  assert.throws(() => create(edit('arm_transfer', {phase: 'open'}), jointMatrix), /seated confirmation/);
  assert.throws(() => create(edit('arm_transfer', {tube_id: 'Unknown'}), jointMatrix), /confirmed pickup/);
  assert.throws(() => create(edit('seated', {seated: ['Unknown']}), jointMatrix), /station record/);
  assert.throws(() => create(edit('spinning', {lid_locked: false}), jointMatrix), /closed and locked/);
  assert.throws(() => create(edit('spinning', {arm_clear: false}), jointMatrix), /clear workspace/);
  assert.throws(() => create(edit('stopped', {brake_held: false}), jointMatrix), /spin requires/);
  assert.throws(() => create(edit('braking', {rotor_deg: 1}), jointMatrix), /unwrapped spin/);
  const duplicate = config();
  duplicate.samples[1].rotor_body_ids = duplicate.samples[0].rotor_body_ids;
  assert.throws(() => create(duplicate, jointMatrix), /distinct masked placeholders/);
  const shared = config();
  shared.joints.lid.body_ids.push('Rotor');
  assert.throws(() => create(shared, jointMatrix), /only one native joint/);
});
