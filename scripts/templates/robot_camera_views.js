/* Synthetic pinhole views of the existing mesh. Optical +Z forward, +X right,
 * +Y down, as in robot_cameras.py. No target tracking or calibrated intrinsics. */
(function(scope){
  'use strict';
  const identity={r:[1,0,0,0,1,0,0,0,1],p:[0,0,0]};
  const vector=(r,v)=>[0,1,2].map(i=>v.reduce((s,x,j)=>s+r[i*3+j]*x,0));
  function worldFrame(camera,mount){
    const a=mount||identity,b=camera.optical_frame;
    return {r:a.r.map((_,i)=>[0,1,2].reduce((s,k)=>s+a.r[Math.floor(i/3)*3+k]*b.r[k*3+i%3],0)),
      p:vector(a.r,b.p).map((x,i)=>x+a.p[i])};
  }
  function inverse(frame){
    const r=[0,3,6,1,4,7,2,5,8].map(i=>frame.r[i]);
    return {r,p:vector(r,frame.p).map(x=>-x)};
  }
  function columnMatrix(f){return new Float32Array([
    f.r[0],f.r[3],f.r[6],0,f.r[1],f.r[4],f.r[7],0,f.r[2],f.r[5],f.r[8],0,...f.p,1]);}
  function projection(camera,aspect){
    // Inscribe the rectangular image in the source's circular view cone.
    // Its length is an illustration size, not a measured sensor range.
    const y=camera.cone_far_radius_mm/camera.cone_range_mm/Math.sqrt(1+aspect*aspect);
    const near=.5,far=5000;
    return new Float32Array([1/(y*aspect),0,0,0,0,-1/y,0,0,
      0,0,(far+near)/(far-near),1,0,0,-2*far*near/(far-near),0]);
  }
  function create(mesh){
    const canvas=document.createElement('canvas');
    const gl=canvas.getContext('webgl',{alpha:false,antialias:true,preserveDrawingBuffer:true});
    if(!gl)throw new Error('WebGL is required for depth-correct robot camera views');
    function shader(kind,source){const s=gl.createShader(kind);gl.shaderSource(s,source);gl.compileShader(s);
      if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw new Error(gl.getShaderInfoLog(s));return s;}
    const program=gl.createProgram();
    gl.attachShader(program,shader(gl.VERTEX_SHADER,`
      attribute vec3 position,normal; uniform mat4 model,view,projection;
      varying vec3 n;
      void main(){n=mat3(view*model)*normal;gl_Position=projection*view*model*vec4(position,1.0);}`));
    gl.attachShader(program,shader(gl.FRAGMENT_SHADER,`
      precision mediump float; varying vec3 n; uniform vec3 color;
      void main(){float light=.58+.42*abs(dot(normalize(n),normalize(vec3(.3,-.5,-.8))));
        gl_FragColor=vec4(color*light,1.0);}`));
    gl.linkProgram(program);
    if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw new Error(gl.getProgramInfoLog(program));
    gl.useProgram(program);gl.enable(gl.DEPTH_TEST);gl.disable(gl.CULL_FACE);
    const uniforms=Object.fromEntries(['model','view','projection','color'].map(n=>[n,gl.getUniformLocation(program,n)]));
    const position=gl.getAttribLocation(program,'position'),normal=gl.getAttribLocation(program,'normal');
    gl.enableVertexAttribArray(position);gl.enableVertexAttribArray(normal);
    const bodies=mesh.bodies.filter(b=>b.role!=='viewing_cone').map(body=>{
      const data=[];
      for(const face of body.f){
        const points=face.map(i=>body.v[i]),a=points[1].map((v,i)=>v-points[0][i]),b=points[2].map((v,i)=>v-points[0][i]);
        const n=[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]],length=Math.hypot(...n)||1;
        for(const point of points)data.push(...point,...n.map(x=>x/length));
      }
      const buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buffer);
      gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(data),gl.STATIC_DRAW);
      return {body,buffer,count:data.length/6};
    });
    function render(camera,matrices,width,height,color){
      if(canvas.width!==width||canvas.height!==height){canvas.width=width;canvas.height=height;}
      gl.viewport(0,0,width,height);
      gl.clearColor(.91,.94,.96,1);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
      const frame=worldFrame(camera,matrices.get(camera.group));
      gl.uniformMatrix4fv(uniforms.view,false,columnMatrix(inverse(frame)));
      gl.uniformMatrix4fv(uniforms.projection,false,projection(camera,width/height));
      for(const {body,buffer,count} of bodies){
        gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.vertexAttribPointer(position,3,gl.FLOAT,false,24,0);gl.vertexAttribPointer(normal,3,gl.FLOAT,false,24,12);
        gl.uniformMatrix4fv(uniforms.model,false,columnMatrix(matrices.get(body.group)||identity));
        gl.uniform3fv(uniforms.color,color(body).map(v=>v/255));
        // Physical surfaces occlude even when the assembly view draws them translucent.
        gl.drawArrays(gl.TRIANGLES,0,count);
      }
      if(gl.getError()!==gl.NO_ERROR)throw new Error('Robot camera render failed');
      return frame;
    }
    function draw(ctx,matrices,width,top,bottom,color,english,time){
      const gap=12,stack=width<600,panelWidth=stack?width-2*gap:(width-3*gap)/2,header=28,footer=26;
      const slotHeight=(bottom-top-footer)/(stack?2:1),height=Math.max(40,slotHeight-header-gap),frames={};
      // A fixed illustrative 16:9 sensor; responsive panels letterbox the same
      // image instead of changing the field of view as the browser is resized.
      const imageWidth=Math.min(panelWidth,height*16/9),imageHeight=imageWidth*9/16;
      mesh.camera_views.forEach((camera,index)=>{
        const x=stack?gap:gap+index*(panelWidth+gap),y=top+(stack?index*slotHeight:0),accent=camera.purpose==='tip'?'#b75219':'#086e99';
        ctx.fillStyle='#e5edf2';ctx.fillRect(x,y,panelWidth,header+height);
        ctx.fillStyle=accent;ctx.fillRect(x,y,4,header+height);
        ctx.font='600 13px system-ui,sans-serif';
        const title=camera.purpose==='tip'?(english?'Gripper camera':'Greiferkamera'):(english?'Overview':'Übersicht');
        const horizontalAngle=2*Math.atan(camera.cone_far_radius_mm/camera.cone_range_mm/Math.sqrt(1+(9/16)**2))*180/Math.PI;
        ctx.fillText(camera.id+' · '+title+' · '+horizontalAngle.toFixed(0)+'°',x+10,y+19);
        // Exact 16:9 backing size also preserves the projection at small widths.
        const unit=Math.max(1,Math.ceil(imageWidth/16));
        frames[camera.id]=render(camera,matrices,unit*16,unit*9,color);
        ctx.drawImage(canvas,x+(panelWidth-imageWidth)/2,y+header+(height-imageHeight)/2,imageWidth,imageHeight);
        ctx.strokeStyle=accent;ctx.lineWidth=1;ctx.strokeRect(x,y,panelWidth,header+height);
      });
      ctx.font='12px system-ui,sans-serif';ctx.fillStyle='#475e71';ctx.textAlign='center';
      ctx.fillText(english?'Simulated views · uncalibrated optics':'Simulierte Kamerasichten · Optik unkalibriert',width/2,bottom-8);ctx.textAlign='start';
      return {time_s:time,frames};
    }
    return {draw,render,canvas};
  }
  scope.RobotCameraViews={create,worldFrame,projection,inverse,columnMatrix};
  if(typeof module!=='undefined')module.exports=scope.RobotCameraViews;
})(globalThis);
