/* Replay the certified Lab 3.003 planar PVA curve on the covered native body group. */
(function (global) {
  'use strict';

  const fields = ['pose_mm_rad', 'velocity_mm_rad_s', 'acceleration_mm_rad_s2'];
  const identity = () => new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]);
  const stationary = point => fields.slice(1).every(key => point[key].every(v => Math.abs(v) <= 1e-9));

  function create(config, Curve) {
    const curve = new Curve(config.points, fields);
    const first = config.points[0], last = config.points.at(-1);
    const dock = first[fields[0]].slice();
    const duration = config.duration_s;
    const angle = last[fields[0]][2] - dock[2];
    const turn = config.half_turn;
    if (first.time_s !== 0 || duration !== last.time_s || duration <= 0 || dock.length !== 3 ||
        Math.hypot(...last[fields[0]].slice(0, 2).map((v, i) => v - dock[i])) > 1e-7 ||
        Math.abs(Math.sin(angle)) > 1e-9 || Math.abs(Math.cos(angle) - (turn ? -1 : 1)) > 1e-9 ||
        !stationary(first) || !stationary(last)) {
      throw Error('The covered TR01 curve must depart and return at rest to the same dock.');
    }
    const reversal = config.reversal?.time_s;
    if (turn) {
      const {start_s: start, end_s: end, delta_rad: delta} = turn;
      const sections = config.direction_sections || [];
      const knots = config.points.filter(point => point.time_s >= start && point.time_s <= end);
      if (reversal !== undefined || !Number.isFinite(delta) ||
          Math.abs(delta-Math.PI) > 1e-9 || !(0 < start && start < end && end < duration) ||
          sections.length !== 3 || sections.some((section, index) =>
            section.direction !== ['forward', 'pivot', 'forward'][index] ||
            section.start_s !== [0, start, end][index] || section.end_s !== [start, end, duration][index]) ||
          knots.length !== 2 || knots[0].time_s !== start || knots[1].time_s !== end ||
          knots.some(point => !stationary(point)) ||
          Math.hypot(...knots[1][fields[0]].slice(0, 2).map((v, i) => v - knots[0][fields[0]][i])) > 1e-7 ||
          Math.abs(knots[1][fields[0]][2] - knots[0][fields[0]][2] - delta) > 1e-9) {
        throw Error('The half-turn must occur at the two stationary knots of its certified pivot.');
      }
    }
    if (reversal !== undefined) {
      const [forward, reverse] = config.direction_sections;
      const knot = config.points.find(point => point.time_s === reversal);
      if (config.direction_sections.length !== 2 || forward.direction !== 'forward' || reverse.direction !== 'reverse' ||
          forward.start_s !== 0 || forward.end_s !== reversal || reverse.start_s !== reversal ||
          reverse.end_s !== duration || reversal <= 0 || reversal >= duration || !knot ||
          !stationary(knot)) {
        throw Error('The direction change must occur at a certified stationary knot.');
      }
    }
    const world = config.room_to_world;
    const roomPoint = ([x, y, z]) => world.slice(0, 3).map(row => row[0]*x + row[1]*y + row[2]*z + row[3]);
    const origin = roomPoint([dock[0], dock[1], 0]).map(v => v/1000);
    let state = 'ready', time = 0, rate = config.default_playback_rate, anchor = null;
    let pose = dock.slice(), matrix = identity(), arrived = false;

    function setTime(t) {
      time = Math.min(duration, Math.max(0, t));
      pose = (time === 0 ? dock : time === duration ? last[fields[0]] : curve.at(time).p).slice();
      if (time === 0 || time === duration && !turn) {
        matrix = identity();
        return;
      }
      const target = roomPoint([pose[0], pose[1], 0]).map(v => v/1000);
      const delta = pose[2] - dock[2], c = Math.cos(delta), s = Math.sin(delta);
      matrix = new Float32Array([c, s, 0, 0, -s, c, 0, 0, 0, 0, 1, 0,
        target[0] - c*origin[0] + s*origin[1], target[1] - s*origin[0] - c*origin[1], 0, 1]);
    }

    function advance(now) {
      if (state !== 'playing') return false;
      const elapsed = Math.max(0, now - anchor);
      anchor = Math.max(anchor, now);
      setTime(time + elapsed/1000*rate);
      if (time === duration) {
        state = 'docked';
        arrived = true;
        anchor = null;
      }
      return true;
    }

    function play(now) {
      if (state === 'playing') return;
      if (state === 'docked') {
        arrived = false;
        setTime(0);
      }
      state = 'playing';
      anchor = now;
    }

    function pause(now) {
      if (state !== 'playing') return;
      advance(now);
      if (state === 'playing') state = 'paused';
      anchor = null;
    }

    function seek(target) {
      if (!Number.isFinite(target)) throw Error('A finite TR01 model time is required.');
      arrived = false;
      setTime(target);
      state = time === 0 ? 'ready' : time === duration ? 'docked' : 'paused';
      anchor = null;
    }

    function setRate(next, now) {
      if (!config.playback_rates.includes(next)) throw Error('Unsupported TR01 playback factor.');
      advance(now);
      rate = next;
    }

    return {
      advance, play, pause, seek, setRate, roomPoint,
      get matrix() { return matrix; },
      get arrived() { return arrived; },
      get locked() { return state === 'playing' || state === 'paused'; },
      get snapshot() {
        const pivoting = turn && time >= turn.start_s && time < turn.end_s;
        const direction = pivoting ? 'pivot' : reversal !== undefined && time >= reversal ? 'reverse' : 'forward';
        return {state, time_s: time, duration_s: duration, playback_rate: rate, pose_mm_rad: pose.slice(), direction};
      }
    };
  }

  const api = {create};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  global.WalkthroughTR01Lap = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
