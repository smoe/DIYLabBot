/* Native meshes; sampled source FK at true model time. No playback speed-up. */
(async()=>{
 const raw=Uint8Array.from(atob(document.getElementById('packed').textContent.trim()),c=>c.charCodeAt(0));
 const data=JSON.parse(await new Response(new Blob([raw]).stream().pipeThrough(new DecompressionStream('gzip'))).text());
 const canvas=document.querySelector('canvas'),gl=canvas.getContext('webgl',{antialias:true,preserveDrawingBuffer:true});
 if(!gl)throw Error('WebGL ist nicht verfügbar.');
 function shader(type,source){const s=gl.createShader(type);gl.shaderSource(s,source);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(s));return s}
 const gpu=gl.createProgram();gl.attachShader(gpu,shader(gl.VERTEX_SHADER,'attribute vec3 p,n;uniform mat4 model,view;varying vec3 normal;void main(){normal=mat3(model)*n;gl_Position=view*model*vec4(p,1.0);}'));
 gl.attachShader(gpu,shader(gl.FRAGMENT_SHADER,'precision mediump float;varying vec3 normal;uniform vec4 color;void main(){float light=.42+.58*abs(dot(normalize(normal),normalize(vec3(-.4,-.6,1.))));gl_FragColor=vec4(color.rgb*light,color.a);}'));
 gl.linkProgram(gpu);if(!gl.getProgramParameter(gpu,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(gpu));gl.useProgram(gpu);
 const position=gl.getAttribLocation(gpu,'p'),normal=gl.getAttribLocation(gpu,'n'),model=gl.getUniformLocation(gpu,'model'),view=gl.getUniformLocation(gpu,'view'),color=gl.getUniformLocation(gpu,'color');
 gl.enableVertexAttribArray(position);gl.enableVertexAttribArray(normal);gl.enable(gl.DEPTH_TEST);
 const meshes=data.meshes.map(mesh=>{const array=[];for(const face of mesh.f){const p=face.map(i=>mesh.v[i]),x=p[1].map((v,i)=>v-p[0][i]),y=p[2].map((v,i)=>v-p[0][i]),n=[x[1]*y[2]-x[2]*y[1],x[2]*y[0]-x[0]*y[2],x[0]*y[1]-x[1]*y[0]],length=Math.hypot(...n)||1;for(const q of p)array.push(...q,...n.map(v=>v/length))}const buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(array),gl.STATIC_DRAW);return{buffer,count:array.length/6}});
 const column=m=>new Float32Array(m.map((_,i)=>m[i%4*4+Math.floor(i/4)]));
 const slider=document.getElementById('time'),play=document.getElementById('play'),camera=document.getElementById('view');slider.max=data.duration_s;
 let t=0,playing=false,last=0,yaw=-1.05,pitch=.65,zoom=1,drag=null;
 const captions={'load.approach':'Anfahrt an das Rack','load.close':'Greifen · Rack bleibt abgestützt','load.carried':'Durchgehende Übernahme auf TR01','load.release':'Freigeben · Träger in der Aufnahme','load.withdraw':'Arm zieht sich zurück','travel':'TR01 fährt · Haube und Rückhaltung manuell bestätigt','unload.approach':'Zielarm fährt an','unload.close':'Zielarm greift · Träger bleibt abgestützt','unload.carried':'Durchgehende Ablage an RF02','unload.release':'Freigeben am Ziel','unload.withdraw':'Zielarm zieht sich zurück'};
 function draw(){
  let lo=0,hi=data.frames.length-1;while(lo<hi){const mid=Math.ceil((lo+hi)/2);if(data.frames[mid].t<=t)lo=mid;else hi=mid-1}const frame=data.frames[lo];
  const ratio=Math.min(2,devicePixelRatio||1),w=Math.round(canvas.clientWidth*ratio),h=Math.round(canvas.clientHeight*ratio);canvas.width=w;canvas.height=h;gl.viewport(0,0,w,h);gl.clearColor(.967,.98,.985,1);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
  const vehicle=frame.poses[data.bodies.find(b=>b.id==='TR01.LT01ReceiverBase').pose],cx=vehicle?vehicle[3]:200;
  const center=camera.value==='source'?[70,-220,960]:camera.value==='target'?[1470,-220,960]:camera.value==='vehicle'?[cx,-650,700]:[700,-100,750];
  const scale=(camera.value==='all'?1050:520)/zoom,aspect=w/h,right=[Math.cos(yaw),Math.sin(yaw),0],up=[-Math.sin(yaw)*Math.sin(pitch),Math.cos(yaw)*Math.sin(pitch),Math.cos(pitch)],depth=[Math.sin(yaw)*Math.cos(pitch),-Math.cos(yaw)*Math.cos(pitch),Math.sin(pitch)],v=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1];
  [right,up,depth].forEach((axis,i)=>{const k=i===0?1/(scale*aspect):i===1?1/scale:-1/5000;for(let j=0;j<3;j++)v[i*4+j]=axis[j]*k;v[i*4+3]=-axis.reduce((sum,x,j)=>sum+x*center[j],0)*k});gl.uniformMatrix4fv(view,false,column(v));
  for(const transparent of [false,true]){gl.depthMask(!transparent);if(transparent){gl.enable(gl.BLEND);gl.blendFunc(gl.SRC_ALPHA,gl.ONE_MINUS_SRC_ALPHA)}else gl.disable(gl.BLEND);
   for(const body of data.bodies){if(body.cover&&frame.phase!=='travel'||(body.opacity<.5)!==transparent)continue;const mesh=meshes[body.mesh],matrix=frame.poses[body.pose]||data.static[body.pose];gl.uniformMatrix4fv(model,false,column(matrix));gl.uniform4fv(color,[...body.color.slice(1).match(/../g).map(v=>parseInt(v,16)/255),transparent?body.opacity:1]);gl.bindBuffer(gl.ARRAY_BUFFER,mesh.buffer);gl.vertexAttribPointer(position,3,gl.FLOAT,false,24,0);gl.vertexAttribPointer(normal,3,gl.FLOAT,false,24,12);gl.drawArrays(gl.TRIANGLES,0,mesh.count)}
  }gl.depthMask(true);slider.value=t;document.getElementById('clock').textContent=t.toFixed(2)+' / '+data.duration_s.toFixed(2)+' s';document.getElementById('phase').textContent=captions[frame.phase];canvas.dataset.ready='true';canvas.dataset.phase=frame.phase;
 }
 function pause(){playing=false;play.textContent=t>=data.duration_s?'Erneut abspielen':'Abspielen'}
 play.onclick=()=>{if(playing)pause();else{if(t>=data.duration_s)t=0;playing=true;last=performance.now();play.textContent='Pause'}};
 slider.oninput=()=>{t=Number(slider.value);pause();draw()};camera.onchange=()=>{zoom=1;draw()};
 canvas.onpointerdown=e=>{drag=[e.clientX,e.clientY];canvas.setPointerCapture(e.pointerId)};canvas.onpointerup=()=>{drag=null};canvas.onpointercancel=()=>{drag=null};canvas.onpointermove=e=>{if(drag){yaw-=(e.clientX-drag[0])*.007;pitch=Math.max(-.25,Math.min(1.45,pitch+(e.clientY-drag[1])*.007));drag=[e.clientX,e.clientY];draw()}};
 canvas.onwheel=e=>{e.preventDefault();zoom=Math.max(.4,Math.min(5,zoom*Math.exp(-e.deltaY*.001)));draw()};new ResizeObserver(draw).observe(canvas);
 function tick(now){if(playing){t=Math.min(data.duration_s,t+(now-last)/1000);draw();if(t>=data.duration_s)pause()}last=now;requestAnimationFrame(tick)}requestAnimationFrame(tick);
 window.logisticsReplay={drawAt(value){t=Math.max(0,Math.min(data.duration_s,value));pause();draw()},duration:data.duration_s};draw();
})().catch(error=>{document.getElementById('error').textContent=error.message;console.error(error)});
