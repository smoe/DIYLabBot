/* Local synthetic views. This module neither receives fleet telemetry nor commands equipment. */
(function(scope){
  'use strict';
  const finite3=v=>Array.isArray(v)&&v.length===3&&v.every(Number.isFinite);
  const dot=(a,b)=>a.reduce((s,v,i)=>s+v*b[i],0);
  const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
  function unit(v){const n=Math.hypot(...v);if(!(n>1e-12))throw Error('Degenerate camera axis');return v.map(x=>x/n);}
  function pose(camera,delta){
    if(!finite3(camera.eye_mm)||!finite3(camera.target_mm)||!finite3(camera.up))throw Error('Missing camera frame');
    const point=p=>!delta?p.slice():[0,1,2].map(i=>(delta[i]*p[0]/1000+delta[i+4]*p[1]/1000+delta[i+8]*p[2]/1000+delta[i+12])*1000);
    const up=!delta?camera.up.slice():[0,1,2].map(i=>delta[i]*camera.up[0]+delta[i+4]*camera.up[1]+delta[i+8]*camera.up[2]);
    return {eye_mm:point(camera.eye_mm),target_mm:point(camera.target_mm),up:unit(up)};
  }
  function projection(camera,frame,aspect){
    const near=camera.near_mm/1000,far=camera.far_mm/1000,fov=camera.fov_y_deg*Math.PI/180;
    if(!(near>0&&far>near&&fov>0&&fov<Math.PI&&aspect>0))throw Error('Invalid camera optics');
    const eye=frame.eye_mm.map(v=>v/1000),z=unit(eye.map((v,i)=>v-frame.target_mm[i]/1000)),x=unit(cross(frame.up,z)),y=cross(z,x);
    const view=[x[0],y[0],z[0],0,x[1],y[1],z[1],0,x[2],y[2],z[2],0,-dot(x,eye),-dot(y,eye),-dot(z,eye),1];
    const f=1/Math.tan(fov/2),p=[f/aspect,0,0,0,0,f,0,0,0,0,(far+near)/(near-far),-1,0,0,2*far*near/(near-far),0],out=new Float32Array(16);
    for(let c=0;c<4;c++)for(let r=0;r<4;r++)for(let k=0;k<4;k++)out[c*4+r]+=p[k*4+r]*view[c*4+k];
    return out;
  }
  function digest(bytes){let h=2166136261;for(const b of bytes)h=Math.imul(h^b,16777619);return (h>>>0).toString(16).padStart(8,'0');}
  function imageSize(value){if(!Array.isArray(value)||value.length!==2||value.some(v=>!Number.isInteger(v)||v<16||v>1920))throw Error('Invalid monitor image size');return value.slice();}
  const unavailable={no_camera:'Keine Kamera modelliert',not_connected:'Flotte nicht angebunden',missing_viewpoint:'Kein Blickpunkt vorhanden'};
  const groupLabels={transporter:'Transporter',robot:'Roboterkameras',device:'Geräte'};
  function create({config,wall,gl,host,capture,visible,requestRender,focusMain}){
    const rows=wall?.grid_rows,columns=wall?.grid_columns;
    if(!Number.isInteger(rows)||rows<1||!Number.isInteger(columns)||columns<1||
      !Array.isArray(wall.monitors)||wall.monitors.length!==rows*columns||!Array.isArray(config.cameras))throw Error('Source-bound monitor grid required');
    const [width,height]=imageSize(config.settings.resolution_px);
    const mosaicMs=1000/config.settings.mosaic_rate_hz,selectedMs=1000/config.settings.selected_rate_hz;
    if(!(mosaicMs>=1000/30&&selectedMs>=1000/30))throw Error('Invalid monitor refresh rate');
    const mosaicSpacingMs=mosaicMs/wall.monitors.length;
    const cameras=new Map(config.cameras.map(c=>[c.id,c]));
    if(cameras.size!==config.cameras.length)throw Error('Duplicate monitor camera');
    const defaults=config.default_assignments;
    if(!Array.isArray(defaults)||defaults.length!==wall.monitors.length||
      defaults.some(id=>id!==null&&cameras.get(id)?.availability!=='available'))throw Error('Invalid default monitor assignments');
    let selected=null,timer=null,disposed=false,nextCapture=0,cursor=0,lastCaptureWasSelected=false;
    const panel=document.createElement('section');panel.className='camera-wall-panel';panel.hidden=true;panel.setAttribute('aria-label','Kameraansicht');
    const close=document.createElement('button');close.type='button';close.className='quiet-button';close.textContent='Schließen';
    const title=document.createElement('h2'),select=document.createElement('select'),label=document.createElement('label');
    label.textContent='Kamera für diesen Monitor';select.id='camera-wall-select';label.htmlFor=select.id;
    const image=document.createElement('canvas');image.width=width;image.height=height;image.setAttribute('aria-label','Synthetisches Kamerabild');
    const details=document.createElement('p'),notice=document.createElement('p');details.setAttribute('role','status');notice.className='notice';
    notice.textContent='Modellansichten · keine Aufzeichnung · keine Meldungsquelle angebunden';
    const options=new Map();
    if(defaults.includes(null)){
      const option=document.createElement('option');option.value='';option.textContent='Keine Bildquelle';option.disabled=true;select.append(option);
    }
    for(const c of cameras.values()){
      const group=c.category;
      if(!options.has(group)){const node=document.createElement('optgroup');node.label=groupLabels[group];options.set(group,node);select.append(node);}
      const option=document.createElement('option');option.value=c.id;
      const status=c.availability==='available'?'Ansicht verfügbar':unavailable[c.availability],location=c.location||c.level_id;
      option.textContent=[c.label,location===status?null:location,c.id,status].filter(Boolean).join(' · ');
      options.get(group).append(option);
    }
    panel.append(close,title,label,select,image,details,notice);host.append(panel);
    const large=image.getContext('2d'),scratch=document.createElement('canvas');scratch.width=width;scratch.height=height;
    const scratchContext=scratch.getContext('2d');
    const bitmap=new ImageData(width,height),pixels=new Uint8Array(bitmap.data.buffer);
    function texture(){const t=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,t);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);return t;}
    const startedAt=performance.now();
    const slots=wall.monitors.map((monitor,i)=>{const canvas=document.createElement('canvas');canvas.width=width;canvas.height=height;return {monitor,camera_id:defaults[i],canvas,context:canvas.getContext('2d'),texture:texture(),frames:0,last_capture:null,first_capture:null,last_status:0,duration_ms:0,next_due:startedAt+i*mosaicSpacingMs,error:null,hash:null,frame:null};});
    const framebuffer=gl.createFramebuffer(),color=texture(),depth=gl.createRenderbuffer();
    gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,width,height,0,gl.RGBA,gl.UNSIGNED_BYTE,null);
    gl.bindRenderbuffer(gl.RENDERBUFFER,depth);gl.renderbufferStorage(gl.RENDERBUFFER,gl.DEPTH_COMPONENT24,width,height);
    gl.bindFramebuffer(gl.FRAMEBUFFER,framebuffer);gl.framebufferTexture2D(gl.FRAMEBUFFER,gl.COLOR_ATTACHMENT0,gl.TEXTURE_2D,color,0);gl.framebufferRenderbuffer(gl.FRAMEBUFFER,gl.DEPTH_ATTACHMENT,gl.RENDERBUFFER,depth);
    if(gl.checkFramebufferStatus(gl.FRAMEBUFFER)!==gl.FRAMEBUFFER_COMPLETE)throw Error('Monitor framebuffer incomplete');gl.bindFramebuffer(gl.FRAMEBUFFER,null);
    function state(slot){
      if(slot.error)return 'Darstellungsfehler';
      if(slot.camera_id===null)return 'Keine Bildquelle';
      const missing=unavailable[cameras.get(slot.camera_id)?.availability];if(missing)return missing;
      if(document.hidden)return 'Anzeige pausiert';
      if(slot.last_capture===null)return 'Bild wird vorbereitet';
      return performance.now()-slot.last_capture>config.settings.stale_after_s*1000?'Bild veraltet':'Bild verfügbar';
    }
    function caption(slot,now){
      const camera=cameras.get(slot.camera_id),age=slot.last_capture===null?null:Math.max(0,now-slot.last_capture)/1000;
      const status=state(slot)+(age===null?'':' · Bildalter '+age.toFixed(1)+' s Browserzeit');
      return camera?[camera.label,camera.id+' · '+(camera.location||camera.level_id||'Nicht angebunden'),status,camera.origin_label]:[status];
    }
    function decorate(slot,now){
      const camera=cameras.get(slot.camera_id),ctx=slot.context;
      ctx.fillStyle='#102225';ctx.fillRect(0,0,width,31);ctx.fillRect(0,height-28,width,28);ctx.fillStyle='#fffbed';ctx.font='11px sans-serif';
      ctx.fillText(camera.label+' · '+(camera.location||camera.level_id||'Nicht angebunden'),6,12,width-12);ctx.fillText(camera.id,6,25,width-12);
      ctx.fillText(camera.kind==='modeled_camera'?'Modellkamera · synthetisches Livebild':'Virtuelle Übersicht · keine Kamera',6,height-15,width-12);
      ctx.fillText(caption(slot,now)[2],6,height-3,width-12);slot.last_status=now;
    }
    function upload(slot){gl.bindTexture(gl.TEXTURE_2D,slot.texture);gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,true);gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,slot.canvas);gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,false);}
    function placeholder(slot){const ctx=slot.context;ctx.fillStyle='#142526';ctx.fillRect(0,0,width,height);ctx.fillStyle='#f1eee2';ctx.font='12px sans-serif';caption(slot,performance.now()).forEach((text,i)=>ctx.fillText(text,10,35+i*25,width-20));upload(slot);}
    slots.forEach(placeholder);
    function refreshUI(){if(selected===null)return;const slot=slots[selected];title.textContent=slot.monitor.label;select.value=slot.camera_id??'';large.drawImage(slot.canvas,0,0);details.textContent=caption(slot,performance.now()).join(' · ')+(slot.frame?.model_time_s===null||slot.frame?.model_time_s===undefined?'':' · Arm-Modellzeit '+slot.frame.model_time_s.toFixed(2)+' s')+(slot.error?' · '+slot.error:'');}
    function assign(index,id){const slot=slots[index];if(!slot||!cameras.has(id))return {status:'unknown_target'};slot.camera_id=id;slot.error=null;slot.frames=0;slot.hash=null;slot.frame=null;slot.last_capture=null;slot.first_capture=null;slot.next_due=0;placeholder(slot);refreshUI();requestRender();return {status:'accepted'};}
    function open(index){if(!slots[index])return {status:'unknown_target'};selected=index;panel.hidden=false;refreshUI();select.focus();slots[index].next_due=0;return {status:'accepted',id:slots[index].monitor.id};}
    function shut(){panel.hidden=true;selected=null;focusMain();requestRender();}
    close.addEventListener('click',shut);panel.addEventListener('keydown',e=>{if(e.key==='Escape'){e.stopPropagation();shut();}});
    select.addEventListener('change',()=>assign(selected,select.value));
    function captureSlot(index,wallVisible=visible()){
      const slot=slots[index];if(!slot)return {status:'unknown_target'};
      const camera=cameras.get(slot.camera_id);if(!camera)return {status:'unassigned'};
      if(camera.availability!=='available')return {status:camera.availability};
      const started=performance.now();
      try{
        gl.bindFramebuffer(gl.FRAMEBUFFER,framebuffer);gl.viewport(0,0,width,height);
        const frame=capture(camera,width,height);gl.readPixels(0,0,width,height,gl.RGBA,gl.UNSIGNED_BYTE,pixels);
        const code=gl.getError();if(code!==gl.NO_ERROR)throw Error('Camera drawing error '+code);
        // RGB already includes glass blended over the opaque scene background.
        // Copying residual GL alpha would blend older placeholder text into a frame.
        for(let i=3;i<pixels.length;i+=4)pixels[i]=255;
        slot.hash=digest(pixels);slot.frame=frame;
        scratchContext.putImageData(bitmap,0,0);
        const ctx=slot.context;ctx.save();ctx.translate(0,height);ctx.scale(1,-1);ctx.drawImage(scratch,0,0);ctx.restore();
        slot.last_capture=performance.now();if(slot.first_capture===null)slot.first_capture=slot.last_capture;slot.frames++;slot.error=null;slot.duration_ms=performance.now()-started;decorate(slot,slot.last_capture);upload(slot);
      }catch(error){slot.error=error.message||String(error);placeholder(slot);}
      finally{gl.bindFramebuffer(gl.FRAMEBUFFER,null);gl.viewport(0,0,gl.canvas.width,gl.canvas.height);}
      if(index===selected)refreshUI();if(wallVisible)requestRender();return {status:slot.error?'error':'captured'};
    }
    const due=(slot,now)=>slot.next_due<=now&&cameras.get(slot.camera_id)?.availability==='available';
    function tick(){
      if(disposed)return;const now=performance.now(),wallVisible=!document.hidden&&visible();
      if(!document.hidden&&(selected!==null||wallVisible)){
        // Use one pass per turn. Alternate when a selected and a mosaic view are both due.
        if(now>=nextCapture){
          const selectedDue=selected!==null&&due(slots[selected],now);
          let index=selectedDue&&!lastCaptureWasSelected?selected:null;
          if(index===null&&wallVisible)for(let n=0;n<slots.length;n++){
            const i=(cursor+n)%slots.length;
            if(i!==selected&&due(slots[i],now)){index=i;cursor=(i+1)%slots.length;break;}
          }
          if(index===null&&selectedDue)index=selected;
          if(index!==null){
            captureSlot(index,wallVisible);const completed=performance.now();lastCaptureWasSelected=index===selected;
            slots[index].next_due=completed+(lastCaptureWasSelected?selectedMs:mosaicMs);
            nextCapture=completed+Math.min(30,mosaicSpacingMs);
          }
        }
        for(const [i,slot] of slots.entries())if((wallVisible||i===selected)&&!slot.error&&slot.last_capture!==null&&now-slot.last_status>1000){
          decorate(slot,now);upload(slot);if(i===selected)refreshUI();if(wallVisible)requestRender();
        }
      }
      timer=setTimeout(tick,30);
    }
    timer=setTimeout(tick,30);
    function dispose(){if(disposed)return;disposed=true;clearTimeout(timer);slots.forEach(s=>gl.deleteTexture(s.texture));gl.deleteTexture(color);gl.deleteFramebuffer(framebuffer);gl.deleteRenderbuffer(depth);panel.remove();}
    window.addEventListener('pagehide',event=>{if(event.persisted){clearTimeout(timer);timer=null;}else dispose();});
    window.addEventListener('pageshow',()=>{if(!disposed&&timer===null)tick();});
    gl.canvas.addEventListener('webglcontextlost',dispose,{once:true});
    return {open,assign,captureSlot,dispose,get selected(){return selected;},get textures(){return disposed?new Map():new Map(slots.map(s=>[s.monitor.screen_body_id,s.texture]));},
      get snapshot(){const now=performance.now();return {selected,texture_count:disposed?0:slots.length+1,framebuffer_count:disposed?0:1,renderbuffer_count:disposed?0:1,resolution_px:[width,height],slots:slots.map(s=>({id:s.monitor.id,camera_id:s.camera_id,status:state(s),error:s.error,frames:s.frames,image_hash:s.hash,frame:s.frame,captured_browser_ms:s.last_capture,age_s:s.last_capture===null?null:(now-s.last_capture)/1000,render_duration_ms:s.duration_ms,measured_rate_hz:s.frames<2?null:(s.frames-1)*1000/(s.last_capture-s.first_capture)}))};}};
  }
  const api={pose,projection,digest,imageSize,create};if(typeof module!=='undefined'&&module.exports)module.exports=api;scope.CameraMonitorWall=api;
})(typeof globalThis!=='undefined'?globalThis:this);
