/* Local synthetic views and optional received model images; no equipment commands. */
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
    const cameras=new Map(config.cameras.map(c=>[c.id,{...c}]));
    if(cameras.size!==config.cameras.length)throw Error('Duplicate monitor camera');
    const defaults=config.default_assignments;
    if(!Array.isArray(defaults)||defaults.length!==wall.monitors.length||
      defaults.some(id=>id!==null&&cameras.get(id)?.availability!=='available'))throw Error('Invalid default monitor assignments');
    let selected=null,timer=null,disposed=false,nextCapture=0,cursor=0,lastCaptureWasSelected=false,receivedSource=null;
    const panel=document.createElement('section');panel.className='camera-wall-panel';panel.hidden=true;panel.setAttribute('aria-label','Kameraansicht');
    const close=document.createElement('button');close.type='button';close.className='quiet-button';close.textContent='Schließen';
    const title=document.createElement('h2'),select=document.createElement('select'),label=document.createElement('label');
    label.textContent='Kamera für diesen Monitor';select.id='camera-wall-select';label.htmlFor=select.id;
    const liveInfo=document.createElement('div'),captureLocation=document.createElement('p'),currentLocation=document.createElement('p');
    const followVehicle=document.createElement('button');followVehicle.type='button';followVehicle.className='quiet-button';followVehicle.textContent='Fahrzeug folgen';
    const freshness=document.createElement('p');
    liveInfo.hidden=true;liveInfo.append(captureLocation,currentLocation,followVehicle,freshness);
    const image=document.createElement('canvas');image.width=width;image.height=height;image.setAttribute('aria-label','Synthetisches Kamerabild');
    const details=document.createElement('p'),notice=document.createElement('p');details.setAttribute('role','status');notice.className='notice';
    notice.textContent='Modellansichten · keine Aufzeichnung · keine Meldungsquelle angebunden';
    const options=new Map(),cameraOptions=new Map();
    if(defaults.includes(null)){
      const option=document.createElement('option');option.value='';option.textContent='Keine Bildquelle';option.disabled=true;select.append(option);
    }
    for(const c of cameras.values()){
      const group=c.category;
      if(!options.has(group)){const node=document.createElement('optgroup');node.label=groupLabels[group];options.set(group,node);select.append(node);}
      const option=document.createElement('option');option.value=c.id;
      const status=c.availability==='available'?'Ansicht verfügbar':unavailable[c.availability],location=c.location||c.level_id;
      option.textContent=[c.label,location===status?null:location,c.id,status].filter(Boolean).join(' · ');
      options.get(group).append(option);cameraOptions.set(c.id,option);
    }
    panel.append(close,title,label,select,liveInfo,image,details,notice);host.append(panel);
    const large=image.getContext('2d'),scratch=document.createElement('canvas');scratch.width=width;scratch.height=height;
    const scratchContext=scratch.getContext('2d');
    const bitmap=new ImageData(width,height),pixels=new Uint8Array(bitmap.data.buffer);
    function texture(){const t=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,t);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);return t;}
    const startedAt=performance.now();
    const slots=wall.monitors.map((monitor,i)=>{const canvas=document.createElement('canvas');canvas.width=width;canvas.height=height;return {monitor,camera_id:defaults[i],canvas,context:canvas.getContext('2d'),texture:texture(),frames:0,last_capture:null,first_capture:null,last_received_capture:null,last_status:0,duration_ms:0,next_due:startedAt+i*mosaicSpacingMs,error:null,hash:null,frame:null,pixel_alpha_min:null};});
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
      if(slot.last_capture===null)return receivedSource?.ids.has(slot.camera_id)?'Noch keine empfangene Aufnahme':'Bild wird vorbereitet';
      if(receivedSource?.ids.has(slot.camera_id))return receivedSource.clock()-slot.frame.captured_s>config.settings.stale_after_s?'Aufnahme veraltet':'Aufnahme empfangen';
      return performance.now()-slot.last_capture>config.settings.stale_after_s*1000?'Bild veraltet':'Bild verfügbar';
    }
    const isLive=slot=>receivedSource?.kind==='received_fleet_live'&&receivedSource.ids.has(slot.camera_id);
    const capturePlace=slot=>slot.frame?.location||slot.frame?.level_id||null;
    const cameraPlace=(slot,camera)=>isLive(slot)&&slot.frame?capturePlace(slot)||'Aufnahmeort unbekannt':camera.location||camera.level_id||'Nicht angebunden';
    function ageLabel(slot,now){
      const external=receivedSource?.ids.has(slot.camera_id),age=slot.last_capture===null?null:external?Math.max(0,receivedSource.clock()-slot.frame.captured_s):Math.max(0,now-slot.last_capture)/1000;
      return state(slot)+(age===null?'':' · Bildalter '+age.toFixed(1)+(external?' s Modellzeit':' s Browserzeit'));
    }
    function browserAgeLabel(slot,now){
      if(!isLive(slot)||!slot.frame||!slot.last_received_capture)return null;
      const elapsed=Math.max(0,now-slot.last_received_capture.browser_ms)/1000;
      return 'Letzte neue Aufnahme vor '+elapsed.toFixed(1)+' s Browserzeit';
    }
    function caption(slot,now){
      const camera=cameras.get(slot.camera_id),status=ageLabel(slot,now);
      return camera?[camera.label,camera.id+' · '+cameraPlace(slot,camera),status,camera.origin_label,browserAgeLabel(slot,now)].filter(Boolean):[status];
    }
    function decorate(slot,now){
      const camera=cameras.get(slot.camera_id),ctx=slot.context;
      ctx.fillStyle='#102225';ctx.fillRect(0,0,width,31);ctx.fillRect(0,height-28,width,28);ctx.fillStyle='#fffbed';ctx.font='11px sans-serif';
      ctx.fillText(camera.label+' · '+cameraPlace(slot,camera),6,12,width-12);ctx.fillText(camera.id,6,25,width-12);
      const browserAge=browserAgeLabel(slot,now);
      const origin=receivedSource?.ids.has(slot.camera_id)?'Empfangene Modellpose · synthetische Ansicht':camera.kind==='modeled_camera'?'Modellkamera · synthetisches Livebild':'Virtuelle Übersicht · keine Kamera';
      const age=ageLabel(slot,now);
      ctx.fillText(browserAge?age:origin,6,height-15,width-12);
      ctx.fillText(browserAge||age,6,height-3,width-12);slot.last_status=now;
    }
    function upload(slot){gl.bindTexture(gl.TEXTURE_2D,slot.texture);gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,true);gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,slot.canvas);gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,false);}
    function placeholder(slot){const ctx=slot.context;ctx.fillStyle='#142526';ctx.fillRect(0,0,width,height);ctx.fillStyle='#f1eee2';ctx.font='12px sans-serif';caption(slot,performance.now()).forEach((text,i)=>ctx.fillText(text,10,35+i*25,width-20));upload(slot);}
    slots.forEach(placeholder);
    function refreshUI(redraw=true){
      if(selected===null)return;
      const slot=slots[selected];title.textContent=slot.monitor.label;select.value=slot.camera_id??'';
      liveInfo.hidden=!isLive(slot);
      if(!liveInfo.hidden){
        const position=receivedSource.locationAt?.(slot.camera_id);
        captureLocation.textContent='Aufnahmeort · '+(capturePlace(slot)||(slot.frame?'Unbekannt':'Noch keine Aufnahme'));
        currentLocation.textContent='Fahrzeug jetzt · '+(position||'Position noch unbekannt');
        followVehicle.hidden=typeof receivedSource.followVehicle!=='function';
        followVehicle.disabled=!position;
        freshness.textContent=browserAgeLabel(slot,performance.now())||state(slot);
      }
      if(redraw)large.drawImage(slot.canvas,0,0);
      details.textContent=caption(slot,performance.now()).join(' · ')+(slot.frame?.model_time_s==null?'':(receivedSource?.ids.has(slot.camera_id)?' · Aufnahme-Modellzeit ':' · Arm-Modellzeit ')+slot.frame.model_time_s.toFixed(2)+' s')+(slot.error?' · '+slot.error:'');
    }
    function clearFrame(slot){
      slot.hash=null;slot.frame=null;slot.pixel_alpha_min=null;slot.last_capture=null;slot.last_received_capture=null;
    }
    function assign(index,id){const slot=slots[index];if(!slot||!cameras.has(id))return {status:'unknown_target'};slot.camera_id=id;slot.error=null;slot.frames=0;clearFrame(slot);slot.first_capture=null;slot.next_due=0;placeholder(slot);refreshUI();requestRender();return {status:'accepted'};}
    function open(index){if(!slots[index])return {status:'unknown_target'};selected=index;panel.hidden=false;refreshUI();select.focus();slots[index].next_due=0;return {status:'accepted',id:slots[index].monitor.id};}
    function shut(){panel.hidden=true;selected=null;focusMain();requestRender();}
    close.addEventListener('click',shut);panel.addEventListener('keydown',e=>{if(e.key==='Escape'){e.stopPropagation();shut();}});
    select.addEventListener('change',()=>assign(selected,select.value));
    followVehicle.addEventListener('click',()=>{
      const slot=slots[selected],source=receivedSource;
      if(!slot||!isLive(slot)||followVehicle.hidden||followVehicle.disabled)return;
      shut();source.followVehicle(slot.camera_id);
    });
    function synchronizeReceivedSource(){
      if(!receivedSource)return;const now=receivedSource.clock();
      if(!Number.isFinite(now)||now<0)throw Error('Finite recording clock required');
      let redactSelected=false;
      for(const slot of slots)if(receivedSource.ids.has(slot.camera_id)&&slot.frame&&(slot.frame.captured_s>now||slot.frame.received_s>now)){
        clearFrame(slot);placeholder(slot);redactSelected||=slot===slots[selected];
      }
      refreshUI(redactSelected);
    }
    function connectReceivedSource(source){
      if(!source||!Array.isArray(source.camera_ids)||source.camera_ids.length!==slots.length||new Set(source.camera_ids).size!==slots.length||source.camera_ids.some(id=>!cameras.has(id)||cameras.get(id).category!=='transporter')||typeof source.frameAt!=='function'||typeof source.clock!=='function')throw Error('Known complete received-camera source required');
      const kind=source.kind??'received_fleet_recording';if(!['received_fleet_recording','received_fleet_live'].includes(kind))throw Error('Unknown received-camera source kind');
      receivedSource={...source,kind,ids:new Set(source.camera_ids)};
      const live=kind==='received_fleet_live';
      for(const id of source.camera_ids){const camera=cameras.get(id);camera.availability='available';camera.location=live?'BF01-Patrouille':'BF01-Aufzeichnung';camera.origin_label=live?'Empfangene Modellpose · aktive synthetische Simulation':'Empfangene Modellpose · synthetische Teilaufzeichnung';cameraOptions.get(id).textContent=camera.label+' · '+id+' · empfangene Modellansicht';}
      notice.textContent=live?'Experimentelle BF01-Patrouille · empfangene Modellposen · synthetische Ansichten, keine realen Kamerabilder':'Experimentelle BF01-Teilaufzeichnung · empfangene Modellposen · synthetische Ansichten, keine realen Kamerabilder';
      source.camera_ids.forEach((id,index)=>assign(index,id));synchronizeReceivedSource();return{status:'accepted',camera_count:source.camera_ids.length};
    }
    function captureReceivedSlot(slot){
      synchronizeReceivedSource();const now=receivedSource.clock(),frame=receivedSource.frameAt(slot.camera_id,width,height);
      if(frame===null){
        if(!isLive(slot)||slot.frame||slot.error){clearFrame(slot);slot.error=null;placeholder(slot);}
        return 'awaiting_received_capture';
      }
      if(!frame||!frame.canvas||frame.canvas.width!==width||frame.canvas.height!==height||typeof frame.camera_ref!=='string'||!frame.camera_ref||![frame.captured_s,frame.received_s,frame.program_time_s].every(Number.isFinite)||frame.captured_s<0||frame.received_s<frame.captured_s||frame.received_s>now||frame.program_time_s!==now)throw Error('Received frame must bind the current recording clock and an already delivered capture');
      const {canvas,...metadata}=frame;
      const last=slot.last_received_capture;
      const live=isLive(slot),sameCapture=live&&last&&last.session_id===frame.session_id&&last.camera_ref===frame.camera_ref;
      if(sameCapture&&frame.session_id&&Number.isInteger(frame.geometry_revision)&&frame.geometry_revision===slot.frame?.geometry_revision&&!slot.error){
        slot.frame={...metadata,model_time_s:frame.captured_s};
        return 'unchanged';
      }
      slot.context.clearRect(0,0,width,height);slot.context.drawImage(frame.canvas,0,0);
      const bitmap=slot.context.getImageData(0,0,width,height);for(let i=3;i<bitmap.data.length;i+=4)bitmap.data[i]=255;slot.context.putImageData(bitmap,0,0);
      slot.hash=digest(bitmap.data);slot.frame={...metadata,model_time_s:frame.captured_s};slot.pixel_alpha_min=255;
      if(live&&!sameCapture)slot.last_received_capture={session_id:frame.session_id,camera_ref:frame.camera_ref,browser_ms:performance.now()};
      return 'new';
    }
    function captureSlot(index,wallVisible=visible()){
      const slot=slots[index];if(!slot)return {status:'unknown_target'};
      const camera=cameras.get(slot.camera_id);if(!camera)return {status:'unassigned'};
      if(camera.availability!=='available')return {status:camera.availability};
      const started=performance.now();
      try{
        if(receivedSource?.ids.has(slot.camera_id)){
          const result=captureReceivedSlot(slot);
          if(result==='unchanged'){if(index===selected)refreshUI(false);return {status:'captured'};}
          if(result==='awaiting_received_capture'){if(index===selected)refreshUI();if(wallVisible)requestRender();return {status:result};}
        }else{
        gl.bindFramebuffer(gl.FRAMEBUFFER,framebuffer);gl.viewport(0,0,width,height);
        const frame=capture(camera,width,height);gl.readPixels(0,0,width,height,gl.RGBA,gl.UNSIGNED_BYTE,pixels);
        const code=gl.getError();if(code!==gl.NO_ERROR)throw Error('Camera drawing error '+code);
        // RGB already includes glass blended over the opaque scene background.
        // Copying residual GL alpha would blend older placeholder text into a frame.
        for(let i=3;i<pixels.length;i+=4)pixels[i]=255;
        slot.hash=digest(pixels);slot.frame=frame;
        scratchContext.putImageData(bitmap,0,0);
        const ctx=slot.context;ctx.save();ctx.translate(0,height);ctx.scale(1,-1);ctx.drawImage(scratch,0,0);ctx.restore();slot.pixel_alpha_min=255;
        }
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
    return {open,assign,captureSlot,connectReceivedSource,synchronizeReceivedSource,dispose,get selected(){return selected;},get textures(){return disposed?new Map():new Map(slots.map(s=>[s.monitor.screen_body_id,s.texture]));},
      get snapshot(){const now=performance.now();return {selected,source_connected:Boolean(receivedSource),source_kind:receivedSource?.kind??null,model_time_s:receivedSource?receivedSource.clock():null,texture_count:disposed?0:slots.length+1,framebuffer_count:disposed?0:1,renderbuffer_count:disposed?0:1,resolution_px:[width,height],slots:slots.map(s=>({id:s.monitor.id,screen_body_id:s.monitor.screen_body_id,camera_id:s.camera_id,pixel_alpha_min:s.pixel_alpha_min,status:state(s),error:s.error,frames:s.frames,image_hash:s.hash,frame:s.frame,captured_browser_ms:s.last_capture,age_s:s.last_capture===null?null:(now-s.last_capture)/1000,render_duration_ms:s.duration_ms,measured_rate_hz:s.frames<2?null:(s.frames-1)*1000/(s.last_capture-s.first_capture)}))};}};
  }
  const api={pose,projection,digest,imageSize,create};if(typeof module!=='undefined'&&module.exports)module.exports=api;scope.CameraMonitorWall=api;
})(typeof globalThis!=='undefined'?globalThis:this);
