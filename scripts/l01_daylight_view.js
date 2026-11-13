// Geometry-based, relative daylight transport. No calibrated photometry.
const daylightFragmentSource=`#version 300 es
precision highp float;
precision highp sampler2DArray;
in vec3 world;
uniform vec4 color;
uniform float contrast;
uniform float unlit;
uniform mat4 lightVP[14];
uniform sampler2DArray shadowDepth;
uniform vec3 sunDirection;
uniform float sunEnergy;
uniform vec3 emitterPosition[13];
uniform vec3 emitterNormal[13];
uniform float emitterArea[13];
uniform vec4 portals[24];
uniform int portalId[24];
uniform int portalCount;
uniform vec2 apertureHeight;
uniform float wallThickness;
uniform float skyEnergy;
uniform float artificialEnergy;
uniform float bounceEnergy;
uniform float exposure;
uniform float shadowResolution;
uniform vec2 filterRadius;
out vec4 outColor;
float cross2(vec2 a,vec2 b){return a.x*b.y-a.y*b.x;}
int apertureMask(vec3 point,vec3 direction,float offset,float maximumT){
 int mask=0;
 for(int i=0;i<24;i++){
  if(i>=portalCount)break;
  vec2 a=portals[i].xy+vec2(0.,-offset),b=portals[i].zw+vec2(0.,-offset),edge=b-a;
  float denominator=cross2(direction.xz,edge);
  if(abs(denominator)<.00000001)continue;
  vec2 delta=a-point.xz;
  float t=cross2(delta,edge)/denominator,u=cross2(delta,direction.xz)/denominator;
  float height=point.y+t*direction.y;
  if(t>.000001&&t<maximumT&&u>=0.&&u<=1.&&height>=apertureHeight.x&&height<=apertureHeight.y)mask|=(1<<portalId[i]);
 }
 return mask;
}
float visibility(int layer,vec3 point,float cosine,bool enabledRay){
 vec4 q=lightVP[layer]*vec4(point,1.);
 float safeW=abs(q.w)>.00000001?q.w:(q.w<0.?-.00000001:.00000001);
 vec3 p=q.xyz/safeW*.5+.5;
 const vec2 samples[9]=vec2[9](vec2(0),vec2(1,0),vec2(-1,0),vec2(0,1),vec2(0,-1),vec2(1,1),vec2(1,-1),vec2(-1,1),vec2(-1,-1));
 int taps=layer==0?9:5;
 float radius=layer==0?filterRadius.x:filterRadius.y;
 float bias=(layer==0?.00012:.000008)*(1.+2.*(1.-cosine));
 // Compare each PCF tap against the receiver plane at that tap, not
 // against one constant depth. This avoids self-shadow stripes on grazing planes.
 vec3 dx=dFdx(p),dy=dFdy(p);float determinant=dx.x*dy.y-dx.y*dy.x;
 vec2 gradient=abs(determinant)>.000000000001?vec2(dx.z*dy.y-dy.z*dx.y,dx.x*dy.z-dy.x*dx.z)/determinant:vec2(0.);
 if(!enabledRay||q.w<=0.||any(lessThan(p,vec3(0.)))||any(greaterThan(p,vec3(1.))))return 0.;
 float sum=0.;
 for(int k=0;k<9;k++){
  if(k>=taps)break;
  vec2 offset=samples[k]*radius/shadowResolution;
  float depth=texture(shadowDepth,vec3(p.xy+offset,float(layer))).r;
  sum+=p.z+dot(gradient,offset)-bias<=depth?1.:0.;
 }
 return sum/float(taps);
}
void main(){
 if(unlit>.5){outColor=color;return;}
 vec3 n=cross(dFdx(world),dFdy(world));float lengthN=length(n);
 if(lengthN<.00000001){outColor=color;return;}
 n=normalize(n);if(!gl_FrontFacing)n=-n;
 float energy=bounceEnergy*(.78+.22*max(n.y,0.));
 for(int i=0;i<13;i++){
  vec3 ray=emitterPosition[i]-world;float r2=dot(ray,ray);vec3 l=normalize(ray);
  float receiver=max(dot(n,l),0.),emission=max(dot(emitterNormal[i],l),0.);
  bool enabledRay=receiver>0.&&emission>0.;
  if(i<9)enabledRay=enabledRay&&(apertureMask(world,ray,0.,1.00001)&(1<<(i/3)))!=0;
  float shadow=visibility(i+1,world,receiver,enabledRay);
  float formFactor=emitterArea[i]/(3.14159265*r2+emitterArea[i]);
  energy+=(i<9?skyEnergy:artificialEnergy)*formFactor*receiver*emission*shadow;
 }
 float cosine=max(dot(n,sunDirection),0.);
 int inner=apertureMask(world,sunDirection,0.,100000.);
 int outer=apertureMask(world,sunDirection,wallThickness,100000.);
 float solarShadow=visibility(0,world,cosine,sunEnergy>0.&&cosine>0.&&(inner&outer)!=0);
 energy+=sunEnergy*cosine*solarShadow;
 vec3 hdr=pow(max(color.rgb,vec3(0.)),vec3(2.2))*energy*exposure*(1.-.06*contrast);
 vec3 mapped=hdr/(vec3(1.)+hdr);
 outColor=vec4(pow(mapped,vec3(1./2.2)),color.a);
}`;

function createDaylightRenderer(gl,definition,vertexBuffer,groups){
 const resolution=gl?Math.min(definition.shadow_mapping.resolution_px,gl.getParameter(gl.MAX_TEXTURE_SIZE)):0;
 let choice=definition.default_scenario,minute=definition.scenarios.find(s=>s.id===choice).default_minute,artificialMode=definition.artificial_lighting.default_mode,dirty=true,currentScenario;
 const centre=[.825,.30,-.90],vps=[],emitters=[...definition.emitters,...definition.artificial_lighting.panels];
 function look(eye,target){const z=unit(eye.map((v,i)=>v-target[i])),x=unit(cross(Math.abs(z[1])>.99?[0,0,1]:[0,1,0],z)),y=cross(z,x);return new Float32Array([x[0],y[0],z[0],0,x[1],y[1],z[1],0,x[2],y[2],z[2],0,-dot(x,eye),-dot(y,eye),-dot(z,eye),1])}
 function ortho(half,near,far){return new Float32Array([1/half,0,0,0,0,1/half,0,0,0,0,-2/(far-near),0,0,0,-(far+near)/(far-near),1])}
 function perspective(){const near=.01,far=4,f=1/Math.tan(150*Math.PI/360);return new Float32Array([f,0,0,0,0,f,0,0,0,0,(far+near)/(near-far),-1,0,0,2*far*near/(near-far),0])}
 function smooth(a,b,x){const u=Math.max(0,Math.min(1,(x-a)/(b-a)));return u*u*(3-2*u)}
 function updateTime(){
  const base=definition.scenarios.find(s=>s.id===choice),step=definition.time_control.sample_interval_minutes;
  const index=Math.min(base.time_samples.length-2,Math.floor(minute/step)),fraction=(minute-index*step)/step;
  const a=base.time_samples[index],b=base.time_samples[index+1],values=a.map((x,i)=>x+(b[i]-x)*fraction),direction=unit(values.slice(0,3));
  // Recompute azimuth from the continuous direction to avoid wrapping through 180 degrees at north.
  const angle=base.time_samples[index][3],delta=((b[3]-angle+540)%360)-180,azimuth=(angle+delta*fraction+360)%360;
  const altitude=values[4],sky=smooth(definition.time_control.twilight_dark_altitude_deg,definition.time_control.twilight_full_day_altitude_deg,altitude);
  const lighting=definition.artificial_lighting,artificial=artificialMode==='on'?1:artificialMode==='off'?0:1-smooth(lighting.auto_full_on_altitude_deg,lighting.auto_off_altitude_deg,altitude);
  currentScenario={...base,azimuth_deg:azimuth,altitude_deg:altitude,sun_direction_gl:direction,direct_relative:Math.max(0,values[5]),sky_factor:sky,artificial_factor:artificial,
   direct_window_incidence_possible:altitude>0&&definition.emitters.some(e=>dot(e.outward_gl,direction)>0)};
  vps[0]=multiply(ortho(1.45,.1,8),look(centre.map((v,i)=>v+direction[i]*4),centre));
  emitters.forEach((e,i)=>vps[i+1]=multiply(perspective(),look(e.position_gl,i<9?centre:[e.position_gl[0],0,e.position_gl[2]])));dirty=true;
 }
 function setScenario(id){const s=definition.scenarios.find(s=>s.id===id);if(!s)throw Error('Unknown daylight scenario');choice=id;minute=s.default_minute;updateTime()}
 function setTime(value){minute=Math.max(0,Math.min(1440,Number(value)||0));updateTime()}
 function setArtificial(value){if(!['auto','on','off'].includes(value))throw Error('Unknown lighting mode');artificialMode=value;updateTime()}
 function scenario(){return currentScenario}
 function makeShader(type,source){const shader=gl.createShader(type);gl.shaderSource(shader,source);gl.compileShader(shader);if(!gl.getShaderParameter(shader,gl.COMPILE_STATUS))throw Error('Daylight shader: '+gl.getShaderInfoLog(shader));return shader}
 if(!gl){setScenario(choice);return {setScenario,setTime,setArtificial,scenario,renderedShadowFrames:0}}
 const depthProgram=gl.createProgram();
 gl.attachShader(depthProgram,makeShader(gl.VERTEX_SHADER,`#version 300 es\nin vec3 p;uniform mat4 vp;uniform mat4 model;void main(){vec3 q=(model*vec4(p*.25,1.)).xyz;gl_Position=vp*vec4(vec3(q.x,q.z,-q.y)/4000.,1.);}`));
 gl.attachShader(depthProgram,makeShader(gl.FRAGMENT_SHADER,`#version 300 es\nprecision highp float;void main(){}`));
 gl.linkProgram(depthProgram);if(!gl.getProgramParameter(depthProgram,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(depthProgram));
 const depth={p:gl.getAttribLocation(depthProgram,'p'),vp:gl.getUniformLocation(depthProgram,'vp'),model:gl.getUniformLocation(depthProgram,'model')};
 function depthArray(){const texture=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D_ARRAY,texture);gl.texStorage3D(gl.TEXTURE_2D_ARRAY,1,gl.DEPTH_COMPONENT24,resolution,resolution,14);gl.texParameteri(gl.TEXTURE_2D_ARRAY,gl.TEXTURE_MIN_FILTER,gl.NEAREST);gl.texParameteri(gl.TEXTURE_2D_ARRAY,gl.TEXTURE_MAG_FILTER,gl.NEAREST);gl.texParameteri(gl.TEXTURE_2D_ARRAY,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D_ARRAY,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);return texture}
 const staticDepth=depthArray(),liveDepth=depthArray(),staticFbo=gl.createFramebuffer(),liveFbo=gl.createFramebuffer();
 for(const[fbo,texture]of [[staticFbo,staticDepth],[liveFbo,liveDepth]]){gl.bindFramebuffer(gl.FRAMEBUFFER,fbo);gl.framebufferTextureLayer(gl.FRAMEBUFFER,gl.DEPTH_ATTACHMENT,texture,0,0);gl.drawBuffers([gl.NONE]);gl.readBuffer(gl.NONE);if(gl.checkFramebufferStatus(gl.FRAMEBUFFER)!==gl.FRAMEBUFFER_COMPLETE)throw Error('Daylight depth framebuffer unavailable')}
 gl.bindFramebuffer(gl.FRAMEBUFFER,null);
 const dynamic=g=>g.kind===7||g.kind===8||g.kind===9||g.kind>=100;
 // Room walls/glazing are handled by the two-sided analytic window apertures.
 // This also prevents the deliberately transparent cutaway walls from leaking light.
 const caster=g=>!g.hidden&&g.kind!==0&&g.kind!==1&&g.kind!==13;
 function renderGroup(g,matrix){gl.uniformMatrix4fv(depth.model,false,flat(matrix));gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,g.buffer);gl.drawElements(gl.TRIANGLES,g.index.length,gl.UNSIGNED_INT,0)}
 let renderedFrames=0,lastPose=null;
 function renderShadows(matrices,cover){
  const poseKey=JSON.stringify([matrices,cover]);if(!dirty&&poseKey===lastPose)return;
  gl.useProgram(depthProgram);gl.bindBuffer(gl.ARRAY_BUFFER,vertexBuffer);gl.enableVertexAttribArray(depth.p);gl.vertexAttribPointer(depth.p,3,gl.SHORT,false,0,0);
  gl.viewport(0,0,resolution,resolution);gl.enable(gl.DEPTH_TEST);gl.depthMask(true);gl.disable(gl.BLEND);gl.enable(gl.POLYGON_OFFSET_FILL);gl.polygonOffset(1.,1.);gl.clearDepth(1);
  for(let layer=0;layer<14;layer++){
   if(layer===0&&!scenario().direct_window_incidence_possible)continue;
   gl.uniformMatrix4fv(depth.vp,false,vps[layer]);
   if(dirty){gl.bindFramebuffer(gl.FRAMEBUFFER,staticFbo);gl.framebufferTextureLayer(gl.FRAMEBUFFER,gl.DEPTH_ATTACHMENT,staticDepth,0,layer);gl.clear(gl.DEPTH_BUFFER_BIT);for(const g of groups)if(caster(g)&&!dynamic(g))renderGroup(g,I())}
   gl.bindFramebuffer(gl.READ_FRAMEBUFFER,staticFbo);gl.framebufferTextureLayer(gl.READ_FRAMEBUFFER,gl.DEPTH_ATTACHMENT,staticDepth,0,layer);
   gl.bindFramebuffer(gl.DRAW_FRAMEBUFFER,liveFbo);gl.framebufferTextureLayer(gl.DRAW_FRAMEBUFFER,gl.DEPTH_ATTACHMENT,liveDepth,0,layer);
   gl.blitFramebuffer(0,0,resolution,resolution,0,0,resolution,resolution,gl.DEPTH_BUFFER_BIT,gl.NEAREST);
   gl.bindFramebuffer(gl.FRAMEBUFFER,liveFbo);for(const g of groups)if(caster(g)&&dynamic(g)&&(g.kind!==8||cover))renderGroup(g,matrices[g.kind]||I());
  }
  dirty=false;lastPose=poseKey;renderedFrames++;gl.bindFramebuffer(gl.FRAMEBUFFER,null);gl.disable(gl.POLYGON_OFFSET_FILL);gl.enable(gl.BLEND);
 }
 let locations=null;
 function apply(program){
  if(!locations){const names=['sunDirection','sunEnergy','skyEnergy','artificialEnergy','bounceEnergy','exposure','shadowResolution','filterRadius','portalCount','apertureHeight','wallThickness','shadowDepth','unlit'];locations=Object.fromEntries(names.map(k=>[k,gl.getUniformLocation(program,k)]));for(const name of ['lightVP','emitterPosition','emitterNormal','emitterArea','portals','portalId'])locations[name]=gl.getUniformLocation(program,name+'[0]')}
  const a=definition.optical_assumptions,c=scenario();gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D_ARRAY,liveDepth);gl.uniform1i(locations.shadowDepth,0);
  gl.uniformMatrix4fv(locations.lightVP,false,new Float32Array(vps.flatMap(m=>[...m])));
  gl.uniform3fv(locations.sunDirection,c.sun_direction_gl);gl.uniform1f(locations.sunEnergy,c.direct_window_incidence_possible?c.direct_relative:0);
  gl.uniform3fv(locations.emitterPosition,new Float32Array(emitters.flatMap(e=>e.position_gl)));gl.uniform3fv(locations.emitterNormal,new Float32Array(emitters.flatMap(e=>e.outward_gl)));
  gl.uniform1fv(locations.emitterArea,new Float32Array(emitters.map(e=>e.area_gl2)));
  gl.uniform4fv(locations.portals,new Float32Array(definition.portals.flatMap(p=>p.segment_gl)));gl.uniform1iv(locations.portalId,new Int32Array(definition.portals.map(p=>p.id)));gl.uniform1i(locations.portalCount,definition.portals.length);
  gl.uniform2fv(locations.apertureHeight,definition.window_vertical_gl);gl.uniform1f(locations.wallThickness,definition.wall_thickness_gl);
  gl.uniform1f(locations.skyEnergy,a.diffuse_window_radiance_relative*a.glazing_transmittance*c.sky_factor);gl.uniform1f(locations.artificialEnergy,definition.artificial_lighting.relative_radiance*c.artificial_factor);gl.uniform1f(locations.bounceEnergy,a.indirect_bounce_relative*c.sky_factor+definition.artificial_lighting.indirect_bounce_relative*c.artificial_factor);gl.uniform1f(locations.exposure,a.exposure);
  gl.uniform1f(locations.shadowResolution,resolution);gl.uniform2fv(locations.filterRadius,[definition.shadow_mapping.sun_filter_radius_texels,definition.shadow_mapping.window_filter_radius_texels]);gl.uniform1f(locations.unlit,0);
 }
 setScenario(choice);
 return {renderShadows,apply,setScenario,setTime,setArtificial,scenario,setUnlit(value){if(locations)gl.uniform1f(locations.unlit,value?1:0)},get renderedShadowFrames(){return renderedFrames}};
}
