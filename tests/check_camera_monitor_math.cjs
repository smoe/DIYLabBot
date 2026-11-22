// Unit and frame conventions independent of the browser and CAD runtimes.
const assert=require('node:assert/strict');
const {pose,projection,imageSize}=require('../scripts/camera_monitor_wall.js');
assert.deepEqual(imageSize([320,1200]),[320,1200],'Browser accepts the same dimensions as the source schema');
assert.deepEqual(imageSize([1920,1920]),[1920,1920]);
for(const size of [[15,180],[320,1921],[320,NaN],[320,180,1]])assert.throws(()=>imageSize(size));
const camera={eye_mm:[1000,0,0],target_mm:[1000,0,100],up:[0,1,0],near_mm:.5,far_mm:180000,fov_y_deg:60};
const delta=[0,1,0,0,-1,0,0,0,0,0,1,0,1,2,0,1];
const frame=pose(camera,delta);
assert.deepEqual(frame.eye_mm,[1000,3000,0]);assert.deepEqual(frame.target_mm,[1000,3000,100]);assert.deepEqual(frame.up,[-1,0,0]);
assert.deepEqual(pose(camera,null).eye_mm,camera.eye_mm);
const m=projection(camera,pose(camera),16/9);
function project(point){const out=[0,0,0,0],p=[...point,1];for(let i=0;i<4;i++)for(let j=0;j<4;j++)out[i]+=m[j*4+i]*p[j];return out.map(v=>v/out[3]);}
assert.ok(Math.abs(project([1,0,.0005])[2]+1)<1e-5,'Near plane is 0.5 mm, not 0.5 metres');
assert.ok(project([1,0,.01])[2]<1,'A lens-near object remains visible');
assert.ok(Math.abs(project([1,0,180])[2]-1)<1e-5);
assert.throws(()=>projection({...camera,near_mm:0},pose(camera),16/9));
assert.throws(()=>pose({...camera,up:[0,0,0]},delta));
console.log('Camera monitor frame/projection checks passed');
