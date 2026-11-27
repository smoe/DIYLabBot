/* Play the checked synthetic Lab 3.003 CF01 station trace once after docking. */
(function (global) {
  'use strict';

  const EPSILON = 1e-7;
  const FLAGS = ['arm_clear', 'lid_locked', 'brake_held', 'cover_removed'];
  const near = (a, b) => Math.abs(a - b) <= EPSILON;
  const finiteVector = (value, length) => Array.isArray(value) &&
    value.length === length && value.every(Number.isFinite);
  const identifier = value => typeof value === 'string' && value.length > 0;
  const bodyIds = values => Array.isArray(values) && values.every(identifier) &&
    new Set(values).size === values.length;
  const closed = step => step.lid_locked && near(step.lid_deg, 0) &&
    step.latch_mm.every(value => near(value, 0));

  function requireCondition(condition, message) {
    if (!condition) throw Error(message);
  }

  function indexSamples(config) {
    requireCondition(Array.isArray(config.samples) && config.samples.length &&
      identifier(config.cover_body_id) && bodyIds(config.empty_rotor_body_ids),
      'A CF01 cycle requires a cover, CF01 placeholders and identified tubes.');
    const samples = new Set();
    const slots = new Set();
    const carrier = new Map();
    const rotor = new Map();
    const emptyRotor = new Set(config.empty_rotor_body_ids);
    for (const sample of config.samples) {
      requireCondition(identifier(sample.id) && !samples.has(sample.id) &&
        Number.isInteger(sample.slot) && sample.slot > 0 && !slots.has(sample.slot) &&
        identifier(sample.carrier_body_id) && sample.carrier_body_id !== config.cover_body_id &&
        !emptyRotor.has(sample.carrier_body_id) && !carrier.has(sample.carrier_body_id) &&
        bodyIds(sample.rotor_body_ids) && sample.rotor_body_ids.length,
        'Each CF01 tube requires one distinct carrier location and rotor slot.');
      for (const id of sample.rotor_body_ids) {
        requireCondition(emptyRotor.has(id) && !rotor.has(id),
          'CF01 rotor bodies must map to distinct masked placeholders.');
        rotor.set(id, sample.id);
      }
      samples.add(sample.id);
      slots.add(sample.slot);
      carrier.set(sample.carrier_body_id, sample.id);
    }
    requireCondition(!emptyRotor.has(config.cover_body_id), 'The TR01 cover cannot be a CF01 placeholder.');
    return {samples, carrier, rotor, emptyRotor};
  }

  function checkedTimeline(config, samples) {
    const {duration_s: duration, spin_started_s: spinTime, brake_started_s: brakeTime,
      stopped_s: stopTime, steps} = config;
    requireCondition([duration, spinTime, brakeTime, stopTime].every(Number.isFinite) &&
      0 < spinTime && spinTime < brakeTime && brakeTime < stopTime && stopTime === duration &&
      Array.isArray(steps) && steps.length >= 5,
      'CF01 requires ordered spin, braking and stationary completion times.');

    let previousTime = -1;
    let previousSeated = [];
    let removed = false;
    let held = null;
    let supported = null;
    const pusher = Boolean(config.arm_motion);
    const pickupTimes = new Map();
    for (const step of steps) {
      requireCondition(Number.isFinite(step.time_s) && step.time_s > previousTime &&
        identifier(step.phase) && Number.isFinite(step.lid_deg) && Number.isFinite(step.rotor_deg) &&
        Number.isFinite(step.rpm) && step.rpm >= 0 && finiteVector(step.latch_mm, 2) &&
        FLAGS.every(key => typeof step[key] === 'boolean') && bodyIds(step.seated) &&
        step.seated.every(id => samples.has(id)),
        'CF01 trace contains an invalid or out-of-order station record.');
      requireCondition((!removed || step.cover_removed) &&
        previousSeated.every(id => step.seated.includes(id)),
        'CF01 inventory and cover state must progress without repeating a transfer.');
      const handling = step.cover_removed && step.brake_held && step.lid_deg > 0 &&
        !step.lid_locked && step.rpm === 0;
      if (pusher) requireCondition(Number.isFinite(step.pusher_mm) && step.pusher_mm >= 0 &&
        Number.isFinite(step.lift_mm) && step.lift_mm >= 0 && step.lift_mm <= step.pusher_mm &&
        (step.pusher_mm === 0 || handling), 'An extended pusher requires a held, open lid and stopped rotor.');
      if (step.phase === 'arm_transfer') {
        requireCondition(held === null && supported === null && samples.has(step.tube_id) && !pickupTimes.has(step.tube_id) &&
          handling && !step.arm_clear && step.seated.length === previousSeated.length,
          'CF01 requires a unique confirmed pickup before seating.');
        held = step.tube_id;
        pickupTimes.set(held, step.time_s);
      }
      if (pusher && step.phase === 'pusher_transfer') {
        requireCondition(held !== null && step.tube_id === held && step.pusher_sample_id === held &&
          supported === null && handling && step.lift_mm > 0 && !step.arm_clear,
          'Tube release must be confirmed onto the held, extended pusher.');
        supported = held;
        held = null;
      }
      if (step.seated.length > previousSeated.length) {
        const owner = pusher ? supported : held;
        requireCondition(step.seated.length === previousSeated.length + 1 && step.phase === 'seated' &&
          handling && owner !== null && step.tube_id === owner && step.seated.includes(owner) &&
          !previousSeated.includes(owner) && (!pusher || (step.arm_clear && step.pusher_mm === 0 && step.lift_mm === 0)),
          'A tube can change ownership only on a seated confirmation with access secured.');
        held = null;
        supported = null;
      }
      if (pusher) requireCondition(step.pusher_sample_id === supported &&
        (!['lowering', 'pocket_reached'].includes(step.phase) || (step.arm_clear && supported !== null)),
        'CF01 must keep the same supported tube until its seating is confirmed.');
      if (step.time_s < spinTime) {
        requireCondition(step.rpm === 0, 'CF01 cannot spin during docking, access or loading.');
      } else {
        requireCondition(step.arm_clear && closed(step) && step.cover_removed &&
          step.seated.length === samples.size && step.brake_held === (step.time_s === stopTime) &&
          (step.time_s === stopTime ? step.rpm === 0 : step.rpm > 0),
          'CF01 spin requires a clear workspace, a closed and locked lid and all tubes seated.');
      }
      previousTime = step.time_s;
      previousSeated = step.seated;
      removed = step.cover_removed;
    }

    const first = steps[0];
    const startIndex = steps.findIndex(step => step.time_s === spinTime);
    const start = steps[startIndex];
    const brake = steps.find(step => step.time_s === brakeTime);
    const stop = steps.at(-1);
    const prior = steps[startIndex - 1];
    requireCondition(first.time_s === 0 && first.phase === 'docked' &&
      !first.cover_removed && !first.seated.length && first.brake_held && first.arm_clear && closed(first) &&
      start?.phase === 'spinning' && brake?.phase === 'braking' &&
      stop.time_s === stopTime && stop.phase === 'stopped' &&
      prior?.arm_clear && prior.brake_held && closed(prior) && prior.seated.length === samples.size &&
      near(prior.rotor_deg, start.rotor_deg) && near(start.rpm, brake.rpm),
      'CF01 must start at a covered dock and finish with the seated load and brake held.');
    requireCondition(near(brake.rotor_deg, start.rotor_deg + 6 * start.rpm * (brakeTime - spinTime)) &&
      near(stop.rotor_deg, brake.rotor_deg + 3 * brake.rpm * (stopTime - brakeTime)),
      'CF01 rotor angles must agree with the unwrapped spin and braking profile.');
    return {steps: steps.map(step => ({...step, seated: step.seated.slice(), latch_mm: step.latch_mm.slice()})),
      duration, spin: {...start}, brake: {...brake}, stop: {...stop}, pickupTimes};
  }

  function indexJoints(config, samples) {
    const {lid, rotor, latches} = config.joints || {};
    requireCondition(Array.isArray(latches) && latches.length === 2,
      'CF01 requires two separate latch joints.');
    const groups = [
      {...lid, type: 'revolute'}, {...rotor, type: 'revolute'},
      ...latches.map(latch => ({...latch, type: 'prismatic'}))
    ];
    if (config.arm_motion) groups.push({...config.joints.pusher, type: 'prismatic'});
    const owners = new Map();
    groups.forEach((joint, index) => {
      requireCondition(bodyIds(joint.body_ids) && joint.body_ids.length &&
        finiteVector(joint.origin_mm, 3) && finiteVector(joint.axis, 3) &&
        near(Math.hypot(...joint.axis), 1) && Number.isFinite(joint.reference_value),
        'Every CF01 joint requires its native body group and a finite world frame.');
      for (const id of joint.body_ids) {
        requireCondition(!owners.has(id) && id !== config.cover_body_id && !samples.carrier.has(id) &&
          (index === 1 || !samples.emptyRotor.has(id)),
          'A CF01 moving body can have only one native joint.');
        owners.set(id, index);
      }
    });
    for (const id of samples.rotor.keys()) {
      requireCondition(!owners.has(id) || owners.get(id) === 1, 'A seated tube must rotate with the CF01 rotor.');
      owners.set(id, 1);
    }
    return {groups, owners};
  }

  function inverseRigid(matrix) {
    const inverse = new Float32Array([matrix[0], matrix[4], matrix[8], 0,
      matrix[1], matrix[5], matrix[9], 0, matrix[2], matrix[6], matrix[10], 0, 0, 0, 0, 1]);
    for (let axis = 0; axis < 3; axis++) {
      inverse[12 + axis] = -(inverse[axis] * matrix[12] + inverse[4 + axis] * matrix[13] + inverse[8 + axis] * matrix[14]);
    }
    return inverse;
  }

  function checkedArm(config, steps, rotor, pusher, jointMatrix, motion) {
    const arm = config.arm_motion;
    if (!arm) return null;
    const {Curve, multiply, identity} = motion || {};
    requireCondition(config.arm_motion_checked === true && [Curve, multiply, identity].every(value => typeof value === 'function') &&
      ['program_sha256', 'collision_report_sha256', 'native_report_sha256'].every(key =>
        typeof arm[key] === 'string' && /^[0-9a-f]{64}$/.test(arm[key])) &&
      arm.samples?.length === config.samples.length && finiteVector(arm.reference_deg, 6) &&
      arm.joints?.length === 6 && Number.isFinite(arm.tool?.reference_gap_mm) &&
      arm.tool.reference_gap_mm > 0 && Array.isArray(arm.tool.bodies) && arm.tool.bodies.length,
      'True ArmC playback requires a native, collision-checked motion program.');
    const moving = new Map();
    for (const [index, joint] of arm.joints.entries()) {
      requireCondition(finiteVector(joint.origin_mm, 3) && finiteVector(joint.axis, 3) &&
        near(Math.hypot(...joint.axis), 1) && bodyIds(joint.body_ids) && joint.body_ids.length,
        'An ArmC joint has no native body group or valid park reference.');
      for (const id of joint.body_ids) {
        requireCondition(!moving.has(id), 'An ArmC body can belong to only one joint.');
        moving.set(id, index);
      }
    }
    const tool = new Map();
    for (const body of arm.tool.bodies) {
      requireCondition(identifier(body.id) && !moving.has(body.id) && !tool.has(body.id) &&
        finiteVector(body.gap_axis, 3) && (near(Math.hypot(...body.gap_axis), .5) ||
          near(Math.hypot(...body.gap_axis), 0)),
        'Tool body motion must follow one native flange or finger group.');
      tool.set(body.id, body.gap_axis);
    }

    function forward(q) {
      let parent = identity();
      return q.map((rad, i) => (parent = multiply(parent, jointMatrix(
        {...arm.joints[i], type: 'revolute'}, rad * 180 / Math.PI, arm.reference_deg[i]))));
    }

    const jawFields = ['positions_mm', 'velocities_mm_s', 'accelerations_mm_s2'];
    const phase = (id, name) => {
      const matches = steps.filter(step => step.tube_id === id && step.phase === name);
      requireCondition(matches.length === 1, 'A native arm track requires one '+name+' event.');
      return matches[0];
    };
    const tracks = arm.samples.map((track, index) => {
      const sample = config.samples[index];
      requireCondition(track.id === sample.id && track.slot === sample.slot &&
        !moving.has(sample.carrier_body_id) && !tool.has(sample.carrier_body_id),
        'ArmC track identities must match the confirmed dock loading order.');
      const start = phase(track.id, 'pusher_raised');
      const grip = phase(track.id, 'arm_transfer');
      const release = phase(track.id, 'pusher_transfer');
      const clear = phase(track.id, 'arm_clear');
      const seat = phase(track.id, 'seated');
      const curve = new Curve(track.points);
      const jaw = new Curve(track.jaw_points, jawFields);
      const end = track.points.at(-1).time_s;
      requireCondition(track.points[0].time_s === 0 && track.jaw_points[0].time_s === 0 &&
        near(end, track.jaw_points.at(-1).time_s) && 0 < track.grip_s && track.grip_s < track.seat_s && track.seat_s < end &&
        near(grip.time_s - start.time_s, track.grip_s) && near(release.time_s - start.time_s, track.seat_s) &&
        near(clear.time_s - start.time_s, end) && release.lift_mm > 0 && seat.time_s > clear.time_s && clear.arm_clear &&
        steps.filter(step => step.time_s >= start.time_s && step.time_s <= clear.time_s).every(step =>
          step.cover_removed && step.brake_held && !step.lid_locked && step.rpm === 0 &&
          near(step.pusher_mm, start.pusher_mm) &&
          near(step.lid_deg, start.lid_deg) && near(step.rotor_deg, start.rotor_deg)),
        'ArmC may move only at the stationary dock with the held lid, rotor and raised pusher.');
      for (const t of [0, end]) {
        const q = curve.at(t);
        const gap = jaw.at(t);
        requireCondition(finiteVector(q.p, 6) && q.p.every((rad, i) => near(rad * 180 / Math.PI, arm.reference_deg[i])) &&
          q.v.every(v => near(v, 0)) && q.a.every(a => near(a, 0)) && finiteVector(gap.p, 1) &&
          near(gap.p[0], arm.tool.reference_gap_mm) && near(gap.v[0], 0) && near(gap.a[0], 0),
          'ArmC and both gripper fingers must match the native stationary park endpoints.');
      }
      const dockInverse = inverseRigid(forward(curve.at(track.grip_s).p).at(-1));
      const raisedMatrix = multiply(forward(curve.at(track.seat_s).p).at(-1), dockInverse);
      return {curve, jaw, start, grip, release, seat, clear, dockInverse, raisedMatrix, body: sample.carrier_body_id};
    });
    let matrices;
    let attached;
    let snapshot;

    function update(time, angle, lift) {
      const active = tracks.find(track => time >= track.start.time_s && time < track.clear.time_s);
      const t = active ? time - active.start.time_s : 0;
      const q = active ? active.curve.at(t).p : arm.reference_deg.map(deg => deg * Math.PI / 180);
      const gap = active ? active.jaw.at(t).p[0] : arm.tool.reference_gap_mm;
      matrices = forward(q);
      const flange = matrices.at(-1);
      const held = active && time >= active.grip.time_s && time < active.release.time_s ? active.grip.tube_id : null;
      attached = new Map();
      for (const track of tracks) {
        if (time >= track.release.time_s) {
          const seated = time >= track.seat.time_s;
          const lowered = multiply(jointMatrix(pusher, seated ? 0 : lift, track.release.lift_mm), track.raisedMatrix);
          attached.set(track.body, seated ? multiply(jointMatrix(rotor, angle, track.seat.rotor_deg), lowered) : lowered);
        } else if (time >= track.grip.time_s) {
          attached.set(track.body, multiply(flange, track.dockInverse));
        }
      }
      for (const [id, axis] of tool) {
        const local = identity();
        axis.forEach((value, i) => { local[12 + i] = value * (gap - arm.tool.reference_gap_mm) / 1000; });
        attached.set(id, multiply(flange, local));
      }
      snapshot = {arm_joints_deg: q.map(rad => rad * 180 / Math.PI), jaw_gap_mm: gap, held_tube: held};
    }

    return {update, bodyIds: [...moving.keys(), ...tool.keys()],
      matrix: id => moving.has(id) ? matrices[moving.get(id)] : attached.get(id),
      get snapshot() { return snapshot; }};
  }

  function create(config, jointMatrix, motion) {
    requireCondition(config && typeof jointMatrix === 'function', 'The CF01 trace requires native joint transforms.');
    const inventory = indexSamples(config);
    const {steps, duration, spin, brake, stop, pickupTimes} = checkedTimeline(config, inventory.samples);
    const {groups, owners} = indexJoints(config, inventory);
    const arm = checkedArm(config, steps, groups[1], groups[4], jointMatrix, motion);
    const rate = config.playback_rate ?? 1;
    requireCondition(Number.isFinite(rate) && rate > 0, 'CF01 playback rate must be positive.');

    let state = 'ready';
    let anchor = null;
    let time = 0;
    let current;
    let seated;
    let matrices;
    let index = 0;

    function update() {
      while (index + 1 < steps.length && steps[index + 1].time_s <= time) index++;
      const step = steps[index];
      const next = steps[index + 1] || step;
      const interval = next.time_s - step.time_s;
      const t = interval ? (time - step.time_s) / interval : 0;
      const smooth = t * t * t * (10 + t * (-15 + 6 * t));
      const geometry = (a, b) => a + (b - a) * smooth;
      let rotor = geometry(step.rotor_deg, next.rotor_deg);
      let rpm = step.rpm;
      if (time >= spin.time_s && time < brake.time_s) {
        rotor = spin.rotor_deg + 6 * spin.rpm * (time - spin.time_s);
        rpm = spin.rpm;
      } else if (time >= brake.time_s && time < stop.time_s) {
        const elapsed = time - brake.time_s;
        const brakeDuration = stop.time_s - brake.time_s;
        rpm = brake.rpm * (1 - elapsed / brakeDuration);
        rotor = brake.rotor_deg + 3 * (brake.rpm + rpm) * elapsed;
      }
      const lid = geometry(step.lid_deg, next.lid_deg);
      const latches = step.latch_mm.map((value, i) => geometry(value, next.latch_mm[i]));
      seated = new Set(step.seated);
      current = {...step, time_s: time, lid_deg: lid, latch_mm: latches, rotor_deg: rotor, rpm};
      const values = [lid, rotor, ...latches];
      if (arm) {
        current.lift_mm = step.pusher_sample_id === next.pusher_sample_id ? geometry(step.lift_mm, next.lift_mm) : step.lift_mm;
        current.pusher_mm = geometry(step.pusher_mm, next.pusher_mm);
        values.push(current.pusher_mm);
        arm.update(time, rotor, current.lift_mm);
      }
      matrices = groups.map((joint, i) => jointMatrix(joint, values[i], joint.reference_value));
    }

    function start(now, docked) {
      if (state !== 'ready' || docked !== true || !Number.isFinite(now)) return false;
      state = 'playing';
      anchor = now;
      return true;
    }

    function advance(now) {
      if (state !== 'playing' || !Number.isFinite(now) || now <= anchor) return false;
      time = Math.min(duration, time + (now - anchor) / 1000 * rate);
      anchor = now;
      update();
      if (time === duration) {
        state = 'completed';
        anchor = null;
      }
      return true;
    }

    function pause(now) {
      if (state !== 'playing' || !Number.isFinite(now)) return false;
      advance(now);
      if (state === 'playing') {
        state = 'paused';
        anchor = null;
      }
      return true;
    }

    function resume(now) {
      if (state !== 'paused' || !Number.isFinite(now)) return false;
      state = 'playing';
      anchor = now;
      return true;
    }

    function hidden(id) {
      if (id === config.cover_body_id) return current.cover_removed;
      if (inventory.carrier.has(id)) return !arm && time >= pickupTimes.get(inventory.carrier.get(id));
      if (arm && inventory.emptyRotor.has(id)) return true;
      return inventory.emptyRotor.has(id) && !seated.has(inventory.rotor.get(id));
    }

    update();
    return {
      start, advance, pause, resume, hidden,
      armBodyIds: arm?.bodyIds || [],
      modelMatrix: id => arm?.matrix(id) || matrices[owners.get(id)] || null,
      get active() { return state === 'playing' || state === 'paused'; },
      get snapshot() {
        return {...current, state, duration_s: duration, playback_rate: rate,
          seated: current.seated.slice(), latch_mm: current.latch_mm.slice(), ...(arm?.snapshot || {})};
      }
    };
  }

  const api = {create};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  global.WalkthroughLab3003CF01 = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
