'use strict';
const assert=require('node:assert/strict');
const {visible}=require('../scripts/monitor_frustum.js');
const identity=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1];
const box=(min,max)=>({min,max});
const centred=(x,y,z,r=10)=>box([x-r,y-r,z-r],[x+r,y+r,z+r]);
function multiply(a,b){
  return Array.from({length:16},(_,i)=>{
    const row=i%4,column=Math.floor(i/4);
    return [0,1,2,3].reduce((sum,k)=>sum+a[k*4+row]*b[column*4+k],0);
  });
}
function perspective(near,far){
  return [1,0,0,0,0,1,0,0,0,0,(far+near)/(near-far),-1,0,0,2*far*near/(near-far),0];
}

assert.equal(visible(identity,centred(0,0,0)),true,'interior');
for(let axis=0;axis<3;axis++)for(const sign of [-1,1]){
  const outside=[0,0,0];outside[axis]=sign*1100;
  assert.equal(visible(identity,centred(...outside)),false,'outside clip plane '+axis+'/'+sign);
  const crossing=[0,0,0];crossing[axis]=sign*1000;
  assert.equal(visible(identity,centred(...crossing,20)),true,'straddling clip plane '+axis+'/'+sign);
  const contact=[0,0,0];contact[axis]=sign*1010;
  assert.equal(visible(identity,centred(...contact)),true,'contact clip plane '+axis+'/'+sign);
}
assert.equal(visible(new Float32Array(identity),box([-100000,-100000,-100000],[100000,100000,100000])),true,'enclosing box retained');
assert.equal(visible(identity,centred(999.99999,0,0,0)),true,'plane rounding remains visible');

const projection=perspective(.025,180);
assert.equal(visible(projection,centred(0,0,-1000)),true,'metre projection receives millimetre bounds');
assert.equal(visible(projection,centred(0,0,-5,1)),false,'entirely before near plane');
assert.equal(visible(projection,centred(0,0,-25,10)),true,'crosses near plane');
assert.equal(visible(projection,centred(0,0,1000)),false,'behind camera');
assert.equal(visible(projection,centred(0,0,-181000)),false,'beyond far plane');
assert.equal(visible(projection,box([-1000000,-1000000,-1000000],[1000000,1000000,1000000])),true,'perspective enclosing box retained');

// MVP is supplied by the caller. This model moves the origin two metres away.
const translated=identity.slice();translated[14]=-2;
assert.equal(visible(multiply(projection,translated),centred(0,0,0)),true,'effective translated MVP');
translated[12]=4;
assert.equal(visible(multiply(projection,translated),centred(0,0,0)),false,'effective translated MVP outside');
// +90 degrees about Y maps model +X to camera -Z without transforming its AABB.
const rotated=[0,0,-1,0,0,1,0,0,1,0,0,0,0,0,0,1];
assert.equal(visible(multiply(projection,rotated),centred(1000,0,0)),true,'rotated effective MVP');
assert.equal(visible(multiply(projection,rotated),centred(-1000,0,0)),false,'rotated box behind camera');
assert.equal(visible(multiply(projection,rotated),box([-100000,-100000,-100000],[100000,100000,100000])),true,'rotated enclosing box retained');

for(const matrix of [null,[],identity.slice(1),identity.map((v,i)=>i===3?NaN:v),identity.map((v,i)=>i===3?Infinity:v)]){
  assert.throws(()=>visible(matrix,centred(0,0,0)),/Finite clip matrix/);
}
for(const bounds of [null,{},box([0,0],[1,1]),box([1,0,0],[0,1,1]),box([NaN,0,0],[1,1,1]),box([0,0,0],[Infinity,1,1])]){
  assert.throws(()=>visible(identity,bounds),/Finite clip matrix/);
}
console.log('Monitor frustum checks passed: six planes, contacts, near/far, metre/mm, MVP translation/rotation, enclosing boxes, invalid inputs.');
