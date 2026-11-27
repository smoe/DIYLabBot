// Usage: node tests/check_walkthrough_stairs.cjs <generated index.html>
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {createCameraCollider, createPicker, createStairWalker, jointMatrix} = require('../scripts/walkthrough_interaction.js');

assert(process.argv[2], 'Pass the generated walkthrough HTML to check its native stair routes.');
const html = readFileSync(process.argv[2], 'utf8');
const inline = html.match(/<script id="walkthrough-data" type="application\/json">([\s\S]*?)<\/script>/);
assert(inline, 'Expected a standalone walkthrough with inline native geometry.');
const program = JSON.parse(inline[1]);
const scene = program.scenes.building;
function decode(encoded, count, Kind) {
  const buffer = Buffer.from(encoded, 'base64');
  assert.equal(buffer.byteLength, count * 4);
  return new Kind(buffer.buffer, buffer.byteOffset, count);
}
const positions = decode(scene.positions_base64, scene.vertex_count * 3, Float32Array).map(mm => mm / 1000);
const indices = decode(scene.indices_base64, scene.index_count, Uint32Array);
const groups = scene.groups.filter(group => group.index_count);
const eyeHeight = program.settings.eye_height_mm / 1000;
const nav = program.navigation;
const collider = createCameraCollider({positions, indices, groups, radius: nav.camera_radius_mm / 1000,
  margin: nav.contact_margin_mm / 1000, iterations: nav.max_contact_iterations, slides: nav.max_slides});
const walker = createStairWalker({positions, indices, groups, eyeHeight});
const picker = createPicker({positions, indices, groups});
const groupsById = new Map(groups.map(group => [group.id, group]));
const floorHeights = Object.fromEntries(program.levels.map(level => [level.id, level.z_mm / 1000]));
const center = (lo, hi) => (lo + hi) / 2;
const low = (group, axis) => group.bounds_mm.min[axis] / 1000;
const high = (group, axis) => group.bounds_mm.max[axis] / 1000;
const near = (value, expected, label) => assert(Math.abs(value - expected) < .002,
  `${label}: expected ${expected}, got ${value}`);

// Use the finished native surfaces to find the travel lanes. The expected
// route never depends on the walker or on a second set of stair dimensions.
function treadBounds(group, height) {
  const result = [Infinity, Infinity, -Infinity, -Infinity];
  for (let index = group.index_start; index < group.index_start + group.index_count; index += 3) {
    const [a, b, c] = [indices[index], indices[index + 1], indices[index + 2]]
      .map(vertex => positions.subarray(3 * vertex, 3 * vertex + 3));
    if ([a, b, c].some(point => Math.abs(point[2] - height) > 1e-5)) continue;
    const area = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
    if (area <= 0) continue;
    for (const point of [a, b, c]) {
      result[0] = Math.min(result[0], point[0]);
      result[1] = Math.min(result[1], point[1]);
      result[2] = Math.max(result[2], point[0]);
      result[3] = Math.max(result[3], point[1]);
    }
  }
  assert(result.every(Number.isFinite), `${group.id}: native top surface at ${height} m`);
  return result;
}

const roofDeck = groups.find(group => group.role === 'concept_roof_access_deck');
assert(roofDeck, 'Expected the native roof access deck.');
floorHeights.ROOF = high(roofDeck, 2);

function route(role, levels, landingForLevel) {
  const all = groups.filter(group => group.role === role);
  assert.equal(all.length, levels.length - 1);
  const legs = [];
  for (let index = 1; index < levels.length; index++) {
    const from = levels[index - 1], to = levels[index];
    const group = all.find(group => group.id.endsWith(`_${from}_${to}`));
    assert(group, `${role} must connect ${from} to ${to}`);
    const startHeight = floorHeights[from], endHeight = floorHeights[to];
    const midHeight = center(startHeight, endHeight);
    const firstTread = treadBounds(group, center(startHeight, midHeight));
    const lastTread = treadBounds(group, center(midHeight, endHeight));
    const midLanding = treadBounds(group, midHeight);
    const firstLane = center(firstTread[1], firstTread[3]), secondLane = center(lastTread[1], lastTread[3]);
    assert(firstLane < secondLane);
    // Turn at the far end of each landing with room for the camera near the
    // guard. At each level both directions use the same route.
    const turnX = midLanding[0] + (midLanding[2] - midLanding[0]) / 4;
    const stairEdge = high(group, 0);
    const entryX = level => center(stairEdge, high(landingForLevel(level), 0));
    const a = [entryX(from), firstLane, startHeight];
    const b = [turnX, firstLane, midHeight];
    const c = [turnX, secondLane, midHeight];
    const d = [entryX(to), secondLane, endHeight];
    if (legs.length) {
      near(legs.at(-1)[0], a[0], 'Shared level landing X');
      near(legs.at(-1)[2], a[2], 'Shared level landing height');
    }
    legs.push(a, b, c, d);
  }
  return legs;
}

function roomDoorPose(ids, state) {
  const transforms = new Map();
  for (const id of ids) {
    const door = program.objects.find(object => object.id === id);
    assert(door?.mechanism === 'room_door', `${id}: expected an operable native landing door`);
    const matrix = jointMatrix(door.joint, door.states[state], door.states[door.reference_state]);
    for (const part of door.moving_body_ids) transforms.set(part, matrix);
  }
  return {transformsForBody: id => [transforms.get(id) || null]};
}

function walk(waypoints, options = {}, step = .08) {
  let eye = [...waypoints[0]];
  eye[2] += eyeHeight;
  for (let index = 1; index < waypoints.length; index++) {
    const [x, y, height] = waypoints[index];
    const expectedRise = height - waypoints[index - 1][2];
    let distance = Math.hypot(x - eye[0], y - eye[1]);
    let movedUp = false, movedDown = false;
    for (let remaining = Math.ceil(distance / step) + 4; distance > 1e-5 && remaining > 0; remaining--) {
      const factor = Math.min(1, step / distance);
      const delta = [(x - eye[0]) * factor, (y - eye[1]) * factor, 0];
      const result = walker.move(eye, delta, collider, options);
      const next = result.eye;
      const rise = next[2] - eye[2];
      movedUp ||= rise > .001;
      movedDown ||= rise < -.001;
      assert(Math.abs(rise) < .251, `Walking jumped more than a tread from ${eye} to ${next}.`);
      const nextDistance = Math.hypot(x - next[0], y - next[1]);
      assert(nextDistance < distance - 1e-6,
        `Stuck at ${eye} on route to ${[x, y, height]}, contacts: ${result.contacts}`);
      distance = nextDistance;
      eye = next;
    }
    near(eye[0], x, 'Waypoint X');
    near(eye[1], y, 'Waypoint Y');
    near(eye[2] - eyeHeight, height, 'Waypoint foot height');
    assert.equal(movedUp, expectedRise > 0, 'Every ascending span gains height without a vertical key.');
    assert.equal(movedDown, expectedRise < 0, 'Every descending span loses height without a vertical key.');
  }
}

const internal = route('concept_continuous_stair', ['KG', 'EG', 'OG1', 'OG2', 'OG3'],
  level => groupsById.get(`${level}__Area_R3_028`));
// The open leaves swing over the model's turn between flights. Close the
// four operable doors for through travel and keep their native leaves in
// collision, as the browser does after commanding the doors.
const stairDoors = ['EG.D0_020.Door', ...['OG1', 'OG2', 'OG3'].map(level => `${level}.D3_028.Door`)];
const closedStairDoors = roomDoorPose(stairDoors, 'closed');
const [openApproach, openDestination] = internal.slice(3, 5);
const doorBlocked = collider.move(
  [openApproach[0], openApproach[1], openApproach[2] + eyeHeight],
  [openDestination[0] - openApproach[0], openDestination[1] - openApproach[1], 0],
  roomDoorPose([stairDoors[0]], 'open'));
assert(doorBlocked.contacts.includes('EG__DoorLeaf_D0_020'), 'An open landing door still blocks the crossing.');

function roomDoorPoints(id) {
  const door = program.objects.find(object => object.id === id);
  return [door.viewpoint.eye_mm, door.viewpoint.target_mm]
    .map(point => point.map(value => value / 1000));
}

const basementDoor = 'KG.DK013.Door';
const [[basementX, basementY]] = roomDoorPoints(basementDoor);
const [wellX, , basementHeight] = internal[0];
const basementReturnY = internal[2][1];
internal.unshift([basementX, basementY, basementHeight], [basementX, basementReturnY, basementHeight],
  [wellX, basementReturnY, basementHeight]);

const topDoor = stairDoors.at(-1);
const [[corridorX], [, doorwayY]] = roomDoorPoints(topDoor);
const [topX, , topHeight] = internal.at(-1);
const upperExit = [topX, doorwayY, topHeight];
internal.push(upperExit);
const exit = [upperExit, [corridorX, doorwayY, topHeight]];
const openTop = roomDoorPose([topDoor], 'open');
walk(internal, closedStairDoors);
walk(exit, openTop);
walk(exit.toReversed(), openTop);
walk(internal.toReversed(), closedStairDoors, .2);

const external = route('concept_external_metal_stair', ['EG', 'OG1', 'OG2', 'OG3', 'ROOF'],
  level => groupsById.get(`ExternalFireStair_Entry_${level}`));
const groundStair = groupsById.get('ExternalFireStair_EG_OG1');
const [groundEntryX, , groundZ] = external[0];
const beneathReturnY = external[2][1];
const groundPoint = low(groundStair, 0) + 2 * nav.camera_radius_mm / 1000;
external.unshift([groundPoint, beneathReturnY, groundZ], [groundEntryX, beneathReturnY, groundZ]);
const roofLanding = external.at(-1);
const roofY = center(low(roofDeck, 1), high(roofDeck, 1));
external.push([roofLanding[0], roofY, floorHeights.ROOF],
  [center(low(roofDeck, 0), high(roofDeck, 0)), roofY, floorHeights.ROOF]);
const fireDoors = ['OG1', 'OG2', 'OG3'].map(level => `${level}.D3_017.Door`);
const closedFireDoors = roomDoorPose(fireDoors, 'closed');
walk(external, closedFireDoors);
walk(external.toReversed(), closedFireDoors, .2);

// Access the outer stair from the building through its actual OG1 door.
// The current EG facade encloses the base. Both directions include the
// native EG floor inside this enclosure.
const firstFireDoor = fireDoors[0];
const [[fireViewX], [fireDoorX, fireDoorY]] = roomDoorPoints(firstFireDoor);
const fireCorridorX = fireDoorX + Math.abs(fireViewX - fireDoorX);
const fireArrival = external.find(point => point[2] === floorHeights.OG1);
const fireEntry = [[fireArrival[0], fireDoorY, floorHeights.OG1],
  [fireCorridorX, fireDoorY, floorHeights.OG1]];
const openFireEntry = roomDoorPose([firstFireDoor], 'open');
walk([fireArrival, fireEntry[0]], closedFireDoors);
walk(fireEntry, openFireEntry);
walk(fireEntry.toReversed(), openFireEntry);
walk([fireEntry[0], fireArrival], closedFireDoors);

// The existing Space interaction ray must be able to reach each door
// from inside the stair, in both authored poses.
function assertDoorPickable(id, viewpoint, state) {
  const door = program.objects.find(object => object.id === id);
  const bodyId = door.moving_body_ids[0];
  const leaf = groupsById.get(bodyId);
  const transform = roomDoorPose([id], state).transformsForBody(bodyId)[0];
  const middle = [0, 1, 2].map(axis => center(low(leaf, axis), high(leaf, axis)));
  const target = middle.map((_, axis) => transform[12 + axis]
    + middle.reduce((sum, value, i) => sum + value * transform[axis + i * 4], 0));
  const eye = [viewpoint[0], viewpoint[1], viewpoint[2] + eyeHeight];
  const ray = target.map((value, axis) => value - eye[axis]);
  const length = Math.hypot(...ray);
  const projection = picker.pick(eye, ray.map(value => value / length), {
    reach: program.interaction.reach_mm / 1000,
    targetForBody: id => door.moving_body_ids.includes(id) ? door.id : null,
    transformForBody: id => door.moving_body_ids.includes(id) ? transform : null,
    includeReference: true,
  });
  assert.equal(projection?.target_id, id, `${id} is operable from the stair side in pose ${state}.`);
}

for (const state of ['open', 'closed']) {
  assertDoorPickable(topDoor, upperExit, state);
  assertDoorPickable(firstFireDoor, fireEntry[0], state);
}

console.log('Native walkthrough stairs: KG–OG3 and EG–roof in both directions, including the roof deck.');
