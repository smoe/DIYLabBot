/* Room-triggered archival-film playback; video bytes remain at the source URL. */
(function(scope){
  'use strict';
  const finite3=value=>Array.isArray(value)&&value.length===3&&value.every(Number.isFinite);
  function insidePolygon(polygon,[x,y]){
    let inside=false;
    for(let i=0,j=polygon.length-1;i<polygon.length;j=i++){
      const a=polygon[j],b=polygon[i],dx=b[0]-a[0],dy=b[1]-a[1],length=Math.hypot(dx,dy);
      const projection=length?((x-a[0])*dx+(y-a[1])*dy)/(length*length):-1;
      if(projection>=0&&projection<=1&&Math.abs((x-a[0])*dy-(y-a[1])*dx)<=1e-7*length)return true;
      if((a[1]>y)!==(b[1]>y)&&x<dx*(y-a[1])/dy+a[0])inside=!inside;
    }
    return inside;
  }
  function insideRoom(config,eye){
    return finite3(eye)&&eye[2]>=config.floor_z_mm&&eye[2]<config.ceiling_z_mm&&
      insidePolygon(config.room_interior_polygon_mm,eye);
  }
  function create({config,gl,host,requestRender}){
    if(!config||!Array.isArray(config.room_interior_polygon_mm)||config.room_interior_polygon_mm.length<3||
      config.room_interior_polygon_mm.some(p=>!Array.isArray(p)||p.length!==2||!p.every(Number.isFinite))||
      !Number.isFinite(config.floor_z_mm)||!Number.isFinite(config.ceiling_z_mm)||config.floor_z_mm>=config.ceiling_z_mm||
      typeof config.film?.title!=='string'||!config.film.title)throw Error('Source-bound seminar room and film required');
    for(const key of ['source_url','video_url'])if(new URL(config.film[key]).protocol!=='https:')throw Error('HTTPS archival film source required');
    const video=document.createElement('video');
    video.id='seminar-projection-video';video.hidden=true;video.setAttribute('aria-hidden','true');
    video.crossOrigin='anonymous';video.preload='none';video.muted=true;video.defaultMuted=true;video.loop=true;video.playsInline=true;
    video.setAttribute('muted','');video.setAttribute('playsinline','');
    const panel=document.createElement('section');panel.id='seminar-projection';panel.className='seminar-projection';panel.hidden=true;panel.setAttribute('aria-label','Filmprojektion im Seminarraum');
    const title=document.createElement('strong');title.textContent=config.film.title;
    const status=document.createElement('p');status.id='seminar-projection-status';status.setAttribute('role','status');status.setAttribute('aria-live','polite');
    const actions=document.createElement('div');actions.className='seminar-projection-actions';
    const playButton=document.createElement('button');playButton.type='button';playButton.id='seminar-projection-play';playButton.className='quiet-button';
    const soundButton=document.createElement('button');soundButton.type='button';soundButton.id='seminar-projection-sound';soundButton.className='quiet-button';
    const source=document.createElement('a');source.href=config.film.source_url;source.target='_blank';source.rel='noopener noreferrer';source.textContent='Filmquelle';
    actions.append(playButton,soundButton);panel.append(title,status,actions,source);host.append(video,panel);
    const texture=gl.createTexture(),previous=gl.getParameter(gl.TEXTURE_BINDING_2D);
    gl.bindTexture(gl.TEXTURE_2D,texture);
    gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
    gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,1,1,0,gl.RGBA,gl.UNSIGNED_BYTE,new Uint8Array([8,12,14,255]));gl.bindTexture(gl.TEXTURE_2D,previous);
    let inRoom=false,userPaused=false,suspended=false,disposed=false,loaded=false,pending=false,blocked=false,error=null;
    let videoFrame=null,fallbackTimer=null,uploaded=0,lastTime=-1,uiKey=null;
    const wanted=()=>inRoom&&!document.hidden&&!suspended&&!userPaused&&!disposed&&!blocked&&!error;
    function state(){
      if(disposed)return 'disposed';if(!inRoom)return 'outside';if(document.hidden||suspended)return 'hidden';
      if(error)return 'error';if(blocked)return 'blocked';if(userPaused)return 'paused';
      return !video.paused&&video.readyState>=2?'playing':'loading';
    }
    function refresh(){
      const phase=state(),key=[phase,video.muted].join(':');if(key===uiKey)return;uiKey=key;
      panel.hidden=!inRoom||disposed;
      status.textContent=({outside:'',hidden:'Wiedergabe pausiert.',paused:'Film pausiert.',playing:video.muted?'Stumm · Endlosschleife':'Mit Ton · Endlosschleife',
        loading:'Film wird geladen …',blocked:'Zum Starten „Abspielen“ wählen.',error:'Film nicht verfügbar. Der Rundgang bleibt benutzbar.'})[phase]||'';
      playButton.textContent=phase==='error'?'Erneut versuchen':userPaused||blocked?'Abspielen':'Pausieren';
      playButton.setAttribute('aria-label',playButton.textContent+' · '+config.film.title);
      soundButton.textContent=video.muted?'Ton einschalten':'Ton ausschalten';soundButton.setAttribute('aria-pressed',String(!video.muted));
    }
    function cancelFrame(){
      if(videoFrame!==null){video.cancelVideoFrameCallback(videoFrame);videoFrame=null;}
      if(fallbackTimer!==null){clearTimeout(fallbackTimer);fallbackTimer=null;}
    }
    function fail(message){error=message;pending=false;video.pause();cancelFrame();refresh();if(!document.hidden)requestRender();}
    function upload(){
      if(!wanted()||video.paused||video.readyState<2||!video.videoWidth||lastTime===video.currentTime)return;
      const previousTexture=gl.getParameter(gl.TEXTURE_BINDING_2D),previousFlip=gl.getParameter(gl.UNPACK_FLIP_Y_WEBGL);
      try{
        gl.bindTexture(gl.TEXTURE_2D,texture);gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,true);
        gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,video);
        lastTime=video.currentTime;uploaded++;requestRender();
      }catch(_){fail('video_texture_unavailable');}
      finally{gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,previousFlip);gl.bindTexture(gl.TEXTURE_2D,previousTexture);}
    }
    function scheduleFrame(){
      if(!wanted()||video.paused||videoFrame!==null||fallbackTimer!==null)return;
      if(typeof video.requestVideoFrameCallback==='function'){
        videoFrame=video.requestVideoFrameCallback(()=>{videoFrame=null;upload();refresh();scheduleFrame();});
      }else{
        fallbackTimer=setTimeout(()=>{fallbackTimer=null;upload();refresh();scheduleFrame();},1000/24);
      }
    }
    function sync(){
      if(disposed)return;
      if(!wanted()){video.pause();cancelFrame();refresh();return;}
      if(!loaded){loaded=true;video.src=config.film.video_url;}
      if(video.paused&&!pending){
        pending=true;
        try{
          Promise.resolve(video.play()).then(()=>{
            pending=false;if(!wanted()){video.pause();cancelFrame();}else scheduleFrame();refresh();
          }).catch(reason=>{
            pending=false;if(!wanted())return;
            if(reason?.name==='NotAllowedError'){blocked=true;cancelFrame();refresh();requestRender();}
            else if(reason?.name!=='AbortError')fail('video_playback_unavailable');
          });
        }catch(_){fail('video_playback_unavailable');}
      }
      refresh();scheduleFrame();
    }
    function update({sceneId,eye_mm,isolated=false}){
      if(disposed)return;
      const next=sceneId==='building'&&!isolated&&insideRoom(config,eye_mm);
      if(next!==inRoom){inRoom=next;if(!next)pending=false;}
      sync();
    }
    function play(){
      if(disposed||!inRoom)return {status:'outside'};
      userPaused=false;blocked=false;
      if(error){error=null;video.load();}
      sync();return {status:'accepted'};
    }
    function pause(){userPaused=true;sync();return {status:'accepted'};}
    playButton.addEventListener('click',()=>{if(userPaused||blocked||error)play();else pause();});
    soundButton.addEventListener('click',()=>{video.muted=!video.muted;refresh();if(wanted())sync();});
    video.addEventListener('playing',()=>{if(!wanted()){video.pause();return;}refresh();scheduleFrame();});
    video.addEventListener('loadeddata',()=>{refresh();if(wanted()){upload();scheduleFrame();}});
    video.addEventListener('error',()=>fail('media_error_'+(video.error?.code||'unknown')));
    const visibility=()=>sync();document.addEventListener('visibilitychange',visibility);
    const hide=event=>{if(event.persisted){suspended=true;sync();}else dispose();};
    const show=()=>{suspended=false;sync();};window.addEventListener('pagehide',hide);window.addEventListener('pageshow',show);
    function dispose(){
      if(disposed)return;disposed=true;video.pause();cancelFrame();video.removeAttribute('src');video.load();
      document.removeEventListener('visibilitychange',visibility);window.removeEventListener('pagehide',hide);window.removeEventListener('pageshow',show);
      gl.deleteTexture(texture);video.remove();panel.remove();
    }
    gl.canvas.addEventListener('webglcontextlost',dispose,{once:true});refresh();
    return {update,play,pause,dispose,get texture(){return disposed?null:texture;},get aspect(){return video.videoWidth&&video.videoHeight?video.videoWidth/video.videoHeight:4/3;},
      get snapshot(){return {status:state(),inside_room:inRoom,playing:!video.paused&&wanted(),paused:video.paused,user_paused:userPaused,muted:video.muted,loop:video.loop,
        source_url:config.film.source_url,video_url:config.film.video_url,current_time_s:video.currentTime,duration_s:Number.isFinite(video.duration)?video.duration:null,
        ready_state:video.readyState,frames_uploaded:uploaded,frame_size_px:[video.videoWidth,video.videoHeight],error,autoplay_blocked:blocked};}};
  }
  const api={insidePolygon,insideRoom,create};if(typeof module!=='undefined'&&module.exports)module.exports=api;scope.SeminarProjection=api;
})(typeof globalThis!=='undefined'?globalThis:this);
