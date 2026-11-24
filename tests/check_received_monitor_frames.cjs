// Received recording and live monitor adapter contracts without a GPU.
const assert=require('node:assert/strict');
const paintedText=[];
class Element{
 constructor(tag){this.tagName=tag;this.children=[];this.width=320;this.height=180;this.hidden=false;this.context=null;this.handlers={};}
 append(...children){this.children.push(...children);}setAttribute(){}addEventListener(event,handler){this.handlers[event]=handler;}focus(){}remove(){}
 getContext(){if(!this.context){let bytes=new Uint8ClampedArray(this.width*this.height*4);this.context={
  fillRect:()=>bytes.fill(255),fillText:text=>paintedText.push(text),clearRect:()=>bytes.fill(0),save(){},restore(){},translate(){},scale(){},
  drawImage:canvas=>{bytes=new Uint8ClampedArray(canvas.getContext('2d').getImageData().data);},
  getImageData:()=>({data:new Uint8ClampedArray(bytes)}),putImageData:image=>{bytes=new Uint8ClampedArray(image.data);}
 };}return this.context;}
}
global.document={hidden:false,createElement:tag=>new Element(tag)};
global.window={addEventListener(){}};
global.ImageData=class{constructor(w,h){this.data=new Uint8ClampedArray(w*h*4);}};
const schedule=global.setTimeout;global.setTimeout=()=>0;
const {create}=require('../scripts/camera_monitor_wall.js');
let uploads=0,staticCaptures=0;
const gl=new Proxy({canvas:new Element('canvas'),createTexture:()=>({}),createFramebuffer:()=>({}),createRenderbuffer:()=>({}),
 checkFramebufferStatus:()=>1,FRAMEBUFFER_COMPLETE:1,getError:()=>0,NO_ERROR:0,texImage2D:()=>uploads++},
 {get:(target,key)=>key in target?target[key]:()=>{}});
const ids=Array.from({length:20},(_,i)=>'BF01.BF'+String(i+1).padStart(2,'0')+'.Overview');
const cameras=ids.map(id=>({id,category:'transporter',kind:'modeled_camera',availability:'not_connected',label:id}));
cameras.push({id:'arm',category:'robot',kind:'modeled_camera',availability:'available',label:'Arm'});
const config={cameras,default_assignments:Array(20).fill('arm'),settings:{resolution_px:[320,180],mosaic_rate_hz:1,selected_rate_hz:5,stale_after_s:5}};
const wall={grid_rows:4,grid_columns:5,monitors:ids.map((_,i)=>({id:'M'+i,label:'Monitor '+i,screen_body_id:'Screen'+i}))};
const host=new Element('section');
const value=create({config,wall,gl,host,capture:()=>{staticCaptures++;return{model_time_s:0};},visible:()=>true,requestRender(){},focusMain(){}});
assert.equal(value.snapshot.source_connected,false);
let now=10,delivered=true,future=false;
const image=new Element('canvas');image.getContext('2d').fillRect();
value.connectReceivedSource({camera_ids:ids,clock:()=>now,frameAt:id=>!delivered?null:{canvas:image,
 camera_ref:'capture-'+id,captured_s:future?11:8,received_s:future?12:9,program_time_s:now,vehicle_id:id,level_id:'EG'}});
assert.equal(value.snapshot.source_kind,'received_fleet_recording');
assert.deepEqual(value.snapshot.slots.map(s=>s.camera_id),ids);
assert(cameras.slice(0,20).every(c=>c.availability==='not_connected'),'Source registry records remain unchanged');
for(let i=0;i<20;i++)assert.equal(value.captureSlot(i).status,'captured');
assert.equal(staticCaptures,0,'Received frames never use the static-camera renderer');
assert(value.snapshot.slots.every(s=>s.frame.captured_s===8&&s.frame.received_s===9&&s.frame.model_time_s===8&&s.pixel_alpha_min===255));
now=20;assert(value.snapshot.slots.every(s=>s.status==='Aufnahme veraltet'),'Age follows the recording clock, not re-render time');
now=0;value.synchronizeReceivedSource();assert(value.snapshot.slots.every(s=>s.frame===null&&s.image_hash===null),'Backward seek clears future texture images immediately');
delivered=false;assert.equal(value.captureSlot(0).status,'awaiting_received_capture');assert.equal(value.snapshot.slots[0].frame,null);
now=10;delivered=true;future=true;assert.equal(value.captureSlot(0).status,'error','Undelivered future images fail closed');
value.assign(0,'arm');assert.equal(value.captureSlot(0).status,'captured');assert.equal(staticCaptures,1);
future=false;value.assign(0,ids[0]);assert.equal(value.captureSlot(0).status,'captured');
assert.equal(value.snapshot.slots[0].frame.camera_ref,'capture-'+ids[0]);
const previousPerformance=global.performance;
let browserMs=1000;
global.performance={now:()=>browserMs};
let session='one',revision=0,position='2. OG · Flur',followed=null;
const liveFrame={canvas:image,camera_ref:'capture-live',captured_s:8,received_s:9,level_id:'EG',location:'EG · Foyer'};
value.connectReceivedSource({kind:'received_fleet_live',camera_ids:ids,clock:()=>now,
 frameAt:()=>delivered?{...liveFrame,session_id:session,geometry_revision:revision,program_time_s:now}:null,
 locationAt:()=>position,followVehicle:id=>{followed=id;}});
assert.equal(value.snapshot.source_kind,'received_fleet_live');
assert(value.snapshot.slots.every(s=>s.frame===null),'Changing received source resets historical screen images');
const [panel]=host.children;
const liveInfo=panel.children.find(e=>e.tagName==='div');
const [captureLocation,currentLocation,followButton]=liveInfo.children;
const details=panel.children.find(e=>e.tagName==='p');
value.open(0);
assert.equal(liveInfo.hidden,false);
assert.equal(captureLocation.textContent,'Aufnahmeort · Noch keine Aufnahme');
assert.equal(currentLocation.textContent,'Fahrzeug jetzt · 2. OG · Flur');
assert.equal(value.captureSlot(0).status,'captured');
assert.equal(captureLocation.textContent,'Aufnahmeort · EG · Foyer');
assert(paintedText.includes(ids[0]+' · EG · Foyer'),'The monitor bitmap labels the captured pose');
assert(!paintedText.includes(ids[0]+' · 2. OG · Flur'),'The live location never labels the captured image');
const initialUploads=uploads;
position='3. OG · Labor 3.003';
browserMs=3500;
assert.equal(value.captureSlot(0).status,'captured');
assert.equal(value.snapshot.slots[0].frames,1);
assert.equal(value.snapshot.slots[0].captured_browser_ms,1000);
assert.equal(uploads,initialUploads,'An unchanged live frame does not upload again');
assert.equal(captureLocation.textContent,'Aufnahmeort · EG · Foyer');
assert.equal(currentLocation.textContent,'Fahrzeug jetzt · 3. OG · Labor 3.003');
assert.match(details.textContent,/2\.0 s Modellzeit.*2\.5 s Browserzeit/);
revision++;
assert.equal(value.captureSlot(0).status,'captured');
assert.equal(uploads,initialUploads+1,'Changed visual geometry redraws an existing capture');
assert.match(details.textContent,/2\.5 s Browserzeit/,'Geometry redraw does not refresh the age of the source image');
session='two';
assert.equal(value.captureSlot(0).status,'captured');
assert.equal(uploads,initialUploads+2,'Different sessions can reuse capture references');
assert.match(details.textContent,/0\.0 s Browserzeit/);
delivered=false;
assert.equal(value.captureSlot(0).status,'awaiting_received_capture');
assert.equal(captureLocation.textContent,'Aufnahmeort · Noch keine Aufnahme');
assert.equal(value.snapshot.slots[0].frame,null);
followButton.handlers.click();
assert.equal(followed,ids[0]);
assert.equal(panel.hidden,true);
value.assign(0,'arm');
value.open(0);
assert.equal(liveInfo.hidden,true);
global.performance=previousPerformance;
assert.throws(()=>value.connectReceivedSource({kind:'unqualified_source',camera_ids:ids,clock:()=>now,frameAt:()=>null}));
assert(uploads>20);value.dispose();global.setTimeout=schedule;
console.log('Passed received-monitor assignments, seek and source isolation, live capture and vehicle locations, browser and model ages, duplicate suppression, and following.');
