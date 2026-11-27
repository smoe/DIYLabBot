const assert = require('node:assert/strict');
const test = require('node:test');
const {readFileSync} = require('node:fs');
const {Curve} = require('../scripts/templates/quintic_motion.js');
const {create} = require('../scripts/walkthrough_tr01_lap.js');

const point = (t, pose) => ({time_s:t,pose_mm_rad:pose,velocity_mm_rad_s:[0,0,0],acceleration_mm_rad_s2:[0,0,0]});
const room = [[-1,0,0,13000],[0,-1,0,8000],[0,0,1,12750],[0,0,0,1]];
const config = {
  room_to_world:room,
  points:[point(0,[930,5615,0]),point(4,[2000,4000,Math.PI]),point(8,[930,5615,2*Math.PI])],
  duration_s:8, default_playback_rate:4, playback_rates:[1,4,8],
};
const identity=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1];
const transform = (matrix, xyz) => xyz.map((_,i)=>matrix[i]*xyz[0]+matrix[i+4]*xyz[1]+matrix[i+8]*xyz[2]+matrix[i+12]);

test('uses the certified mixed-unit quintic curve and moves around the original world dock', () => {
  const player=create(config,Curve);
  const origin=player.roomPoint([930,5615,0]).map(v=>v/1000);
  player.seek(4);
  const centre=transform(player.matrix,origin);
  player.roomPoint([2000,4000,0]).map(v=>v/1000).forEach((v,i)=>assert(Math.abs(v-centre[i])<2e-6));
  assert.deepEqual(player.snapshot.pose_mm_rad,config.points[1].pose_mm_rad);
  player.seek(8);
  assert.equal(player.snapshot.state,'docked');
  assert.equal(player.arrived,false,'A slider jump does not confirm a delivery.');
  assert.deepEqual(Array.from(player.matrix),identity);
  assert.equal(player.locked,false);
});

test('separates wall-clock playback speed from model time and resume', () => {
  const player=create(config,Curve);
  player.play(0);
  player.advance(500);
  assert.equal(player.snapshot.time_s,2);
  player.pause(750);
  assert.equal(player.snapshot.time_s,3);
  player.advance(5000);
  assert.equal(player.snapshot.time_s,3);
  assert.equal(player.locked,true);
  player.setRate(1,5000);
  player.play(5000);
  player.advance(10000);
  assert.equal(player.snapshot.state,'docked');
  assert.equal(player.arrived,true,'Playback must finish at the dock to confirm a delivery.');
  assert.equal(player.snapshot.time_s,8);
  player.play(10000);
  assert.equal(player.snapshot.time_s,0);
  assert.equal(player.arrived,false);
  player.seek(0);
  assert.equal(player.snapshot.state,'ready');
});

test('rejects a curve whose arrival differs from the certified dock', () => {
  assert.throws(()=>create({...config,points:[...config.points.slice(0,2),point(8,[931,5615,2*Math.PI])]},Curve),/same dock/);
});

test('reports the reverse phase only at and after the stationary gear-change knot', () => {
  const mixed={...config,reversal:{time_s:4},direction_sections:[
    {direction:'forward',start_s:0,end_s:4},{direction:'reverse',start_s:4,end_s:8}
  ]};
  const player=create(mixed,Curve);
  player.seek(3.999);
  assert.equal(player.snapshot.direction,'forward');
  player.seek(4);
  assert.equal(player.snapshot.direction,'reverse');
  assert.throws(()=>create({...mixed,reversal:{time_s:4.1}},Curve),/stationary knot/);
});

if(process.env.TR01_PROGRAM) test('replays the actual model knots and exact dock endpoints',()=>{
  const {routes:[route]}=JSON.parse(readFileSync(process.env.TR01_PROGRAM,'utf8'));
  const player=create({...config,points:route.points,duration_s:route.duration_s,
    reversal:route.reversal,direction_sections:route.direction_sections},Curve);
  for(const knot of route.points.filter((_,i)=>i%31===0)){
    player.seek(knot.time_s);
    player.snapshot.pose_mm_rad.forEach((v,i)=>assert(Math.abs(v-knot.pose_mm_rad[i])<1e-7));
  }
  player.seek(route.duration_s);
  assert.deepEqual(Array.from(player.matrix),identity);
});
