/* Exact source-bound H02 replay. Rendering is separate from CAD qualification. */
(function(global){
'use strict';
const identity=()=>[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1];
const flat=m=>m.flat();
function multiply(a,b){const r=Array(16).fill(0);for(let i=0;i<4;i++)for(let j=0;j<4;j++)for(let k=0;k<4;k++)r[i*4+j]+=a[i*4+k]*b[k*4+j];return r}
function inverse(a){const r=identity();for(let i=0;i<3;i++)for(let j=0;j<3;j++)r[i*4+j]=a[j*4+i];for(let i=0;i<3;i++)r[i*4+3]=-r.slice(i*4,i*4+3).reduce((s,v,j)=>s+v*a[j*4+3],0);return r}
const translate=(x,y,z)=>[1,0,0,x,0,1,0,y,0,0,1,z,0,0,0,1];
const column=a=>new Float32Array(a.map((_,i)=>a[(i%4)*4+Math.floor(i/4)]));
function state(data,t){
 t=Math.max(0,Math.min(data.total_duration,t));let start=0,phase='extraction';
 for(const name of Object.keys(data.durations)){if(t<start+data.durations[name]||name===Object.keys(data.durations).at(-1)){phase=name;break}start+=data.durations[name]}
 const curve=data.curves[phase],local=t-start,index=Math.min(curve.segments.length-1,Math.max(0,curve.times.findIndex((v,i)=>i>0&&local<v)-1));
 // At the final endpoint use the last segment; at joins choose the right side.
 const segment=local>=curve.times.at(-1)?curve.segments.length-1:index,h=curve.times[segment+1]-curve.times[segment],u=(local-curve.times[segment])/h;
 let coeff=curve.segments[segment].slice();const scalar=[];
 for(let n=0;n<4;n++){scalar.push(coeff.reduceRight((sum,c)=>sum*u+c,0)/h**n);coeff=coeff.slice(1).map((c,i)=>c*(i+1))}
 const value=scalar[0];let z=phase==='closure'?data.z0:value,y=0,yaw=0,tubeYaw=0,toolPva=[[0,0,z],[0,0,scalar[1]],[0,0,scalar[2]]];
 if(data.transfer){
  const r=data.transfer;
  if(phase==='extraction'){
   let lo=0,hi=r.length;
   for(let i=0;i<48;i++){const x=(lo+hi)/2,m=x+r.weight*(x/2-r.length*Math.sin(2*Math.PI*x/r.length)/(4*Math.PI));if(m<value)lo=x;else hi=x}
   const x=(lo+hi)/2,angle=Math.PI*x/r.length,w=1+r.weight*Math.sin(angle)**2,wp=2*r.weight*Math.PI/r.length*Math.sin(angle)*Math.cos(angle),dx=scalar[1]/w,ddx=scalar[2]/w-wp*scalar[1]**2/w**3;
   const piece=r.pieces.find(p=>x<=p[1])||r.pieces.at(-1),[a,b,points]=piece,u=(x-a)/(b-a);
   function bezier(v){while(v.length>1)v=v.slice(0,-1).map((v0,i)=>v0+(v[i+1]-v0)*u);return v[0]}
   const jets=[1,2].map(k=>{let v=points.map(p=>p[k]),f=[];for(let n=0;n<3;n++){f.push(bezier(v)/(b-a)**n);v=v.length>1?v.slice(0,-1).map((v0,i)=>(v.length-1)*(v[i+1]-v0)):[0]}return [f[0],f[1]*dx,f[1]*ddx+f[2]*dx*dx]});
   y=jets[0][0];z=jets[1][0];toolPva=[0,1,2].map(n=>[0,jets[0][n],jets[1][n]]);
   const uYaw=Math.max(0,Math.min(1,(x-r.pieces[1][0])/(r.pieces.at(-1)[0]-r.pieces[1][0])));yaw=r.yaw*uYaw**4*(35+uYaw*(-84+uYaw*(70-20*uYaw)));
  }else if(phase==='approach'){z=data.z0+data.travel+value;toolPva=[[0,0,z],[0,0,scalar[1]],[0,0,scalar[2]]];}
  else if(phase==='closure'){z=data.z0;toolPva=[[0,0,z],[0,0,0],[0,0,0]];}
  else{y=r.seat[1];z=r.seat[2]+(phase==='withdraw'?value:0);yaw=r.yaw;toolPva=[[0,y,z],[0,0,phase==='withdraw'?scalar[1]:0],[0,0,phase==='withdraw'?scalar[2]:0]];}
  tubeYaw=phase==='extraction'?yaw:['release','withdraw'].includes(phase)?r.yaw:0;
 }
 const radial=data.transfer?y-data.transfer.base_y:data.radial;
 const w=z-data.shoulder+data.end,c=(radial**2+w*w-data.upper**2-data.fore**2)/(2*data.upper*data.fore),elbow=Math.acos(c);
 const shoulder=Math.atan(radial/w)-Math.atan(data.fore*Math.sqrt(1-c*c)/(data.upper+data.fore*c));
 const q=[Math.PI/2,shoulder,elbow,0,Math.PI-shoulder-elbow,-Math.PI/2-yaw*Math.PI/180];
 let m=identity();const matrices={[data.links[0]]:flat(data.base)};
 q.forEach((angle,i)=>{const f=flat(data.frames[i]),r=identity();r[0]=r[5]=Math.cos(angle);r[1]=-Math.sin(angle);r[4]=Math.sin(angle);m=multiply(multiply(multiply(m,f),r),inverse(f));matrices[data.links[i+1]]=multiply(flat(data.base),m)});
 const gap=data.transfer?(phase==='closure'?data.jaw_travel+value:phase==='release'?value:phase==='extraction'?0:data.jaw_travel):(phase==='closure'?value:phase==='approach'?data.jaw_travel:0),dz=z-data.z0,tube=phase==='extraction'?dz:data.transfer&&['release','withdraw'].includes(phase)?data.transfer.seat[2]-data.z0:0;
 const tubeY=phase==='extraction'?y:data.transfer&&['release','withdraw'].includes(phase)?data.transfer.seat[1]:0;
 function rotate(a){const m=identity(),v=a*Math.PI/180;m[0]=m[5]=Math.cos(v);m[1]=-Math.sin(v);m[4]=Math.sin(v);return m}
 const tool=multiply(translate(0,y,dz),rotate(yaw));
 Object.assign(matrices,{Tool:tool,FingerLeft:multiply(tool,translate(-gap,0,0)),FingerRight:multiply(tool,translate(gap,0,0)),Tube:multiply(translate(0,tubeY,tube),rotate(tubeYaw))});
 return {phase,scalar,toolPva,y,yaw,tubeY,tubeYaw,q:q.map(v=>v*180/Math.PI),z,gap,tube,matrices};
}
const api={state,multiply,inverse};if(typeof module!=='undefined')module.exports=api;global.H02Animation=api;
if(typeof document==='undefined')return;
(async()=>{
 const root=document.getElementById('h02-arm-motion');if(!root)return;
 const bytes=Uint8Array.from(atob(root.querySelector('[data-packed]').textContent.trim()),c=>c.charCodeAt(0));
 const data=JSON.parse(await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))).text());
 const canvas=root.querySelector('canvas'),gl=canvas.getContext('webgl',{antialias:true,preserveDrawingBuffer:true});
 if(!gl)throw Error('WebGL is unavailable');
 function shader(type,text){const s=gl.createShader(type);gl.shaderSource(s,text);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(s));return s}
 const gpu=gl.createProgram();gl.attachShader(gpu,shader(gl.VERTEX_SHADER,'attribute vec3 a; attribute vec3 n; uniform mat4 model; uniform mat4 view; varying vec3 normal; void main(){normal=mat3(model)*n;gl_Position=view*model*vec4(a,1.0);}'));
 gl.attachShader(gpu,shader(gl.FRAGMENT_SHADER,'precision mediump float; varying vec3 normal; uniform vec3 color; void main(){float light=0.45+0.55*abs(dot(normalize(normal),normalize(vec3(-0.4,-0.6,1.0))));gl_FragColor=vec4(color*light,1.0);}'));
 gl.linkProgram(gpu);if(!gl.getProgramParameter(gpu,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(gpu));gl.useProgram(gpu);
 const a=gl.getAttribLocation(gpu,'a'),n=gl.getAttribLocation(gpu,'n'),model=gl.getUniformLocation(gpu,'model'),view=gl.getUniformLocation(gpu,'view'),color=gl.getUniformLocation(gpu,'color');
 gl.enableVertexAttribArray(a);gl.enableVertexAttribArray(n);gl.enable(gl.DEPTH_TEST);
 const bodies=data.bodies.map(b=>{const vertices=[];for(const f of b.f){const p=f.map(i=>b.v[i]),x=p[1].map((v,i)=>v-p[0][i]),y=p[2].map((v,i)=>v-p[0][i]);const norm=[x[1]*y[2]-x[2]*y[1],x[2]*y[0]-x[0]*y[2],x[0]*y[1]-x[1]*y[0]],length=Math.hypot(...norm)||1;for(const point of p)vertices.push(...point,...norm.map(v=>v/length))}const buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(vertices),gl.STATIC_DRAW);return {...b,buffer,count:vertices.length/6}});
 let t=0,playing=false,last=0,yaw=-.7,pitch=.48,zoom=1,drag=null,currentPhase='',lastRemembered='';
 root.querySelector('[data-time]').max=data.total_duration;
 const play=root.querySelector('[data-play]'),slider=root.querySelector('[data-time]'),speed=root.querySelector('[data-speed]'),camera=root.querySelector('[data-view]');
 function theme(name){const s=document.createElement('span');s.style.color='var('+name+')';root.append(s);const rgb=getComputedStyle(s).color.match(/[\d.]+/g).slice(0,3).map(Number);s.remove();return rgb.map(v=>v/255)}
 function draw(){
  const s=state(data,t),ratio=Math.min(2,devicePixelRatio||1),w=Math.round(canvas.clientWidth*ratio),h=Math.round(canvas.clientHeight*ratio);if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h}gl.viewport(0,0,w,h);gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
  const close=camera.value==='detail',center=close?[0,s.y,s.z-8]:[0,-120,110],scale=(close?105:270)/zoom,aspect=w/h;
  const right=[Math.cos(yaw),Math.sin(yaw),0],up=[-Math.sin(yaw)*Math.sin(pitch),Math.cos(yaw)*Math.sin(pitch),Math.cos(pitch)],depth=[Math.sin(yaw)*Math.cos(pitch),-Math.cos(yaw)*Math.cos(pitch),Math.sin(pitch)];
  const v=identity();[right,up,depth].forEach((axis,i)=>{const k=i===0?1/(scale*aspect):i===1?1/scale:-1/2000;for(let j=0;j<3;j++)v[i*4+j]=axis[j]*k;v[i*4+3]=-axis.reduce((sum,x,j)=>sum+x*center[j],0)*k});gl.uniformMatrix4fv(view,false,column(v));
  const fg=theme('--foreground'),bg=theme('--background'),accent=theme('--viz-series-1');
  for(const b of bodies){if(close&&b.id==='SupportPlane')continue;gl.uniformMatrix4fv(model,false,column(s.matrices[b.group]||identity()));const highlight=b.group==='Tube',mix=b.id==='SupportPlane'?.13:b.group.startsWith('L')?.66:.43;const c=highlight?accent:fg.map((v,i)=>v*mix+bg[i]*(1-mix));gl.uniform3fv(color,c);gl.bindBuffer(gl.ARRAY_BUFFER,b.buffer);gl.vertexAttribPointer(a,3,gl.FLOAT,false,24,0);gl.vertexAttribPointer(n,3,gl.FLOAT,false,24,12);gl.drawArrays(gl.TRIANGLES,0,b.count)}
  slider.value=t;root.querySelector('[data-clock]').textContent=t.toFixed(2)+' / '+data.total_duration.toFixed(2)+' s';
  if(s.phase!==currentPhase){currentPhase=s.phase;root.querySelector('[data-phase]').textContent={approach:'Approach · tube supported by H02',closure:'Grasp · jaws closing; tube remains seated',extraction:data.transfer?'Continuous transfer · tube held by gripper':'Extraction · tube moves with gripper',release:'Release · tube supported by rack',withdraw:'Withdraw · tube remains in rack'}[s.phase]}
  root.querySelector('[data-values]').textContent='Jaw gap '+(data.closed_gap+2*s.gap).toFixed(1)+' mm · tube lift '+s.tube.toFixed(1)+' mm · '+(['closure','release'].includes(s.phase)?'Jaw':'TCP')+' speed '+(['closure','release'].includes(s.phase)?Math.abs(s.scalar[1]):Math.hypot(...s.toolPva[1])).toFixed(1)+' mm/s · a '+(['closure','release'].includes(s.phase)?Math.abs(s.scalar[2]):Math.hypot(...s.toolPva[2])).toFixed(1)+' mm/s²';
  Object.assign(root.dataset,{time:String(t),phase:s.phase,tubeLift:String(s.tube),jawTravel:String(s.gap),ready:'true'});
  root.replayState=s;
 }
 function pause(){playing=false;play.textContent=t>=data.total_duration?'Replay':'Play';}
 function signature(snapshot){return JSON.stringify([snapshot?.modelContent?.time_s,snapshot?.privateContent])}
 function remember(){const snapshot={modelContent:{motion_sha256:data.motion_sha256,time_s:t,phase:state(data,t).phase},privateContent:{yaw,pitch,zoom,view:camera.value,speed:speed.value}};lastRemembered=signature(snapshot);if(global.openai?.setWidgetState)global.openai.setWidgetState(snapshot).catch(()=>{})}
 play.onclick=()=>{if(playing)pause();else{if(t>=data.total_duration)t=0;playing=true;last=performance.now();play.textContent='Pause'}remember()};
 slider.oninput=()=>{t=Number(slider.value);pause();draw()};slider.onchange=remember;
 camera.onchange=()=>{zoom=1;draw();remember()};speed.onchange=remember;
 canvas.onpointerdown=e=>{drag=[e.clientX,e.clientY];canvas.setPointerCapture(e.pointerId)};
 canvas.onpointermove=e=>{if(!drag)return;yaw-=(e.clientX-drag[0])*.008;pitch=Math.max(-.3,Math.min(1.4,pitch+(e.clientY-drag[1])*.008));drag=[e.clientX,e.clientY];draw()};canvas.onpointerup=()=>{drag=null;remember()};canvas.onpointercancel=()=>{drag=null};
 canvas.onwheel=e=>{e.preventDefault();zoom=Math.max(.4,Math.min(4,zoom*Math.exp(-e.deltaY*.001)));draw()};
 new ResizeObserver(draw).observe(canvas);new MutationObserver(draw).observe(document.documentElement,{attributes:true,attributeFilter:['class','style','data-theme']});matchMedia('(prefers-color-scheme: dark)').addEventListener('change',draw);
 function restore(snapshot){const m=snapshot?.modelContent,p=snapshot?.privateContent;if(m?.motion_sha256===data.motion_sha256&&Number.isFinite(m.time_s))t=Math.max(0,Math.min(data.total_duration,m.time_s));if(p){yaw=p.yaw??yaw;pitch=p.pitch??pitch;zoom=p.zoom??zoom;if(['full','detail'].includes(p.view))camera.value=p.view;if(['.5','1','2'].includes(p.speed))speed.value=p.speed}pause();draw()}
 restore(global.openai?.widgetState);global.addEventListener('openai:set_globals',e=>{const snapshot=e.detail?.globals?.widgetState;if(signature(snapshot)!==lastRemembered)restore(snapshot)});
 function tick(now){if(playing){t=Math.min(data.total_duration,t+(now-last)/1000*Number(speed.value));draw();if(t>=data.total_duration){pause();remember()}}last=now;requestAnimationFrame(tick)}requestAnimationFrame(tick);
 root.animationData=data;root.drawAt=value=>{t=Math.max(0,Math.min(data.total_duration,value));pause();draw();return root.replayState};draw();
})().catch(error=>{const root=document.getElementById('h02-arm-motion');root.querySelector('[data-phase]').textContent=error.message;root.querySelector('[data-phase]').setAttribute('role','alert');console.error(error)});
})(typeof window==='undefined'?globalThis:window);
