const assert=require('node:assert/strict');
const {create}=require('../scripts/walkthrough_robots.js');
const {Curve}=require('../scripts/templates/quintic_motion.js');
const {jointMatrix}=require('../scripts/walkthrough_interaction.js');
const fixture=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const c=fixture.robot;
function session(){const o=new Map(fixture.objects.map(config=>[config.id,{config,value:config.states.reference}]));return {o,r:create(c,o,Curve)};}
const multiply=(a,b)=>Array.from({length:16},(_,n)=>{const r=n%4,k=Math.floor(n/4);return [0,1,2,3].reduce((s,i)=>s+a[i*4+r]*b[k*4+i],0);});
for(const sample of fixture.fk){
 let parent=null;
 fixture.objects.forEach((o,i)=>{
  const m=jointMatrix(o.joint,sample.q[i],o.states.reference);parent=parent?multiply(parent,m):m;
  parent.forEach((v,n)=>assert(Math.abs(v-sample.matrices[i][n])<2e-5,'FK mismatch joint '+i));
 });
}
{
 const {r}=session();assert.equal(r.command('unknown',0).status,'unknown_command');assert.equal(r.command('home',0).status,'already_in_state');
 assert.equal(r.command('demo',0).status,'accepted');assert.equal(r.command('home',10).status,'rejected_busy');
 r.advance(1e6);assert.equal(r.snapshot.state,'idle');r.snapshot.joints_deg.forEach((v,i)=>assert(Math.abs(v-c.demo_deg[i])<1e-8));
 assert.equal(r.command('home',1e6).status,'accepted');r.advance(2e6);r.snapshot.joints_deg.forEach((v,i)=>assert(Math.abs(v-c.reference_deg[i])<1e-8));
}
// Stop at many points, in both directions: position stays on the proven path,
// no jump at command time, the stop completes, and a new home command works.
for(const reverse of [false,true])for(let n=1;n<40;n++){
 const {r}=session();let origin=0;
 if(reverse){r.command('demo',0);r.advance(100000);origin=100000;}
 const result=r.command(reverse?'home':'demo',origin),at=origin+result.duration_s*1000*n/40;
 r.advance(at);const before=r.snapshot.joints_deg;
 assert.equal(r.command('stop',at).status,'accepted');assert.deepEqual(r.snapshot.joints_deg,before);
 for(let t=0;t<=c.stop_ramp_s*1000+10;t+=10){r.advance(at+t);r.snapshot.joints_deg.forEach((v,i)=>assert(v>=Math.min(c.reference_deg[i],c.demo_deg[i])-1e-7&&v<=Math.max(c.reference_deg[i],c.demo_deg[i])+1e-7));}
 assert.equal(r.snapshot.busy,false);const q=r.snapshot.joints_deg;r.advance(at+10000);assert.deepEqual(r.snapshot.joints_deg,q);
 const home=r.command('home',at+10001);assert(['accepted','already_in_state'].includes(home.status));r.advance(at+1e6);
}
console.log('Robot commands, 78 smooth-stop cases and shared-source FK passed.');
