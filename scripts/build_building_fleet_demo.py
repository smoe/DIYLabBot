"""Opt-in BF01 HTML from a complete checked program; normal export untouched."""
import argparse
import copy
import gzip
import hashlib
import json
from pathlib import Path
import time
import math
import base64
import export_building_walkthrough_freecad as native
import building_fleet_model as model
import building_fleet_comm as telemetry
from export_building_fleet_vehicle_freecad import checked_camera_report

ROOT=Path(__file__).resolve().parents[1]
VIEW=ROOT/'scripts/building_fleet_view.js'
PLAYBACK_FIELDS=('format','complete','seed','duration_s','levels','room_route_object_ids',
    'targets','homes','trajectories','lift_schedule','received_messages','camera_captures',
    'qualification','statistics','source_files_sha256','artifacts')
ADDITIONAL_HTML_TARGET_BYTES=10*1024*1024
ANCHOR='    window.__buildingWalkthrough=Object.freeze({'
BRIDGE=r"""
    let fleetHooks=null;const fleetActive=true;let fleetSavedCamera=null;
    const fleetVisualGeometry=window.__walkthroughProgressiveGeometry??null;
    const fleetPayload=JSON.parse(document.getElementById('building-fleet-data').textContent);
    const fleetBusy=()=>({status:'rejected_busy',reason:'Aufzug im Flottenbetrieb; Fahrzeug folgen zum Mitfahren'});
    // The opt-in page owns the compiled cabin. Neither overlay buttons,
    // physical source buttons nor implicit walking may create a passenger.
    if(elevator){for(const key of ['call','board','select','exit'])elevator[key]=()=>fleetBusy();
      elevator.walkStep=()=>fleetBusy();
      elevator.walkingBarriers=()=>elevatorConfig.shaft_bounds_mm?[{id:'FleetLiftShaft',min:[...elevatorConfig.shaft_bounds_mm.min],max:[...elevatorConfig.shaft_bounds_mm.max]}]:[];
      Object.defineProperty(elevator,'walkingAllowed',{get:()=>false});}
    let fleetCaptureFrame=null;
    function fleetCaptureMatrix(aspect){
      if(!fleetCaptureFrame)return cameraMatrix(aspect);
      const forward=fleetCaptureFrame.forward,right=fleetCaptureFrame.right,z=forward.map(v=>-v),up=cross(z,right);
      const view=new Float32Array([right[0],up[0],z[0],0,right[1],up[1],z[1],0,right[2],up[2],z[2],0,-dot(right,eye),-dot(up,eye),-dot(z,eye),1]);
      const f=1/Math.tan(fleetCaptureFrame.fov*Math.PI/360),projection=new Float32Array([f/aspect,0,0,0,0,f,0,0,0,0,(far+near)/(near-far),-1,0,0,2*far*near/(near-far),0]);
      return multiply(projection,view);
    }
    const fleetBridge={gl,canvas,stage:stageNode,requestRender,
      get geometryRevision(){return fleetVisualGeometry?.revision??0;},
      visualLevelReady:level=>fleetVisualGeometry?.levelReady(level)??true,
      observeVisualGeometry:snapshot=>fleetVisualGeometry?.observe(snapshot),
      startAt:id=>setStop(id),
      atMonitorWall:()=>stopId==='camera-wall',
      connectMonitorFeeds:source=>{if(!monitorWall)throw Error('Source-bound physical monitor wall unavailable');return monitorWall.connectReceivedSource(source);},
      syncMonitorFeeds:()=>monitorWall?.synchronizeReceivedSource(),
      projectPoint:point=>{const p=projectPoint(point);return{...p,x:p.x/canvas.width,y:p.y/canvas.height};},
      cameraMatrix:fleetCaptureMatrix,clearMovement:clearInputKeys,
      beginFollow:()=>{if(!fleetSavedCamera)fleetSavedCamera={eye:[...eye],yaw,pitch,sceneId,selectedLevel,isolated,location:locationLabel.textContent,context:contextLabel.textContent};clearInputKeys();},
      endFollow:()=>{if(fleetSavedCamera){eye=fleetSavedCamera.eye;yaw=fleetSavedCamera.yaw;pitch=fleetSavedCamera.pitch;sceneId=fleetSavedCamera.sceneId;selectedLevel=fleetSavedCamera.selectedLevel;isolated=fleetSavedCamera.isolated;levelSelect.value=selectedLevel;isolationButton.setAttribute('aria-pressed',String(isolated));locationLabel.textContent=fleetSavedCamera.location;contextLabel.textContent=fleetSavedCamera.context;fleetSavedCamera=null;}root.dataset.freeCamera='true';clearInputKeys();requestRender();},
      doorOpen:id=>{const o=objectStates.get(id);return Boolean(o&&o.state==='open'&&!o.transition);},
      activate:hooks=>{fleetHooks=hooks;clearInputKeys();},
      follow:state=>{if(fleetVisualGeometry&&!fleetVisualGeometry.levelReady(state.level_id)){fleetVisualGeometry.requestView(state.level_id,()=>fleetBridge.follow(state));return;}clearInputKeys();sceneId='building';isolated=false;selectedLevel=state.level_id;levelSelect.value=selectedLevel;
        eye=state.pose_xyz_mm.map((v,i)=>v/1000+(i===2?eyeHeight:0));eye[0]-=Math.cos(state.yaw_rad)*eyeHeight;eye[1]-=Math.sin(state.yaw_rad)*eyeHeight;
        yaw=state.yaw_rad;pitch=-Math.atan2(eyeHeight/2,eyeHeight);root.dataset.freeCamera='false';locationLabel.textContent=state.id+' folgen';contextLabel.textContent='Synthetische BF01-Fahrt · '+selectedLevel;},
      applyLift:state=>{const cabin=objectStates.get(elevatorConfig.object_id);cabin.value=state.z_mm;cabin.transition=null;
        const floorState=Object.entries(cabin.config.states).find(([,value])=>Math.abs(value-state.z_mm)<1e-7);cabin.state=floorState?floorState[0]:'moving';if(floorState)cabin.targetState=floorState[0];
        for(const [id,value]of Object.entries(state.door_values)){const object=objectStates.get(id);if(!object||object.config.mechanism!=='lift_door')throw Error('Unknown compiled lift door');const previous=object.value;object.value=value;object.transition=null;object.state=value===object.config.states.open?'open':value===object.config.states.closed?'closed':value>=previous?'opening':'closing';object.targetState=object.state==='opening'?'open':object.state==='closing'?'closed':object.state;}
        liftUIKey=null;},
      capture:(capture,width,height,drawFleet,frame,fovDeg)=>{
        const saved={eye,yaw,pitch,sceneId,selectedLevel,isolated},poses=[];
        const angle=capture.yaw_rad,c=Math.cos(angle),s=Math.sin(angle),rotate=p=>[c*p[0]-s*p[1],s*p[0]+c*p[1],p[2]];
        const local=rotate(frame.origin_mm),forward=normalize(rotate(frame.axis)),right=normalize(rotate(frame.x));
        if(Math.abs(dot(forward,right))>1e-7)throw Error('Camera source axes must be orthogonal');
        eye=capture.pose_xyz_mm.map((v,i)=>(v+local[i])/1000);yaw=Math.atan2(forward[1],forward[0]);pitch=Math.asin(forward[2]);sceneId='building';isolated=false;fleetCaptureFrame={forward,right,fov:fovDeg};
        // Historical synthetic captures use source initial static articulations,
        // independently of a later user door toggle. The caller already set
        // the compiled dynamic cabin/door pose at the capture timestamp.
        for(const object of objectStates.values())if(object.config.id!==elevatorConfig.object_id&&object.config.mechanism!=='lift_door'){
          poses.push([object,object.value,object.state,object.targetState,object.transition]);const initial=object.config.initial_state||object.config.reference_state;
          object.value=object.config.states[initial];object.state=object.targetState=initial;object.transition=null;}
        try{
          gl.viewport(0,0,width,height);
          drawScene(prepareScene('building',true),fleetCaptureMatrix(width/height),eye,true);drawFleet();
        }finally{
          for(const [object,value,state,target,transition]of poses){object.value=value;object.state=state;object.targetState=target;object.transition=transition;}
          eye=saved.eye;yaw=saved.yaw;pitch=saved.pitch;sceneId=saved.sceneId;selectedLevel=saved.selectedLevel;isolated=saved.isolated;fleetCaptureFrame=null;gl.depthMask(true);gl.disable(gl.BLEND);gl.useProgram(program);
        }
      }
    };
    liftPanel.addEventListener('click',event=>{event.preventDefault();event.stopImmediatePropagation();recordLift(fleetBusy());},true);
    Promise.resolve().then(()=>BuildingFleetView.mount(fleetBridge,fleetPayload)).catch(fail);
"""
STYLE='''<style>#building-fleet-panel{padding:1rem;margin:1rem 0;background:#f5f7f4;border:1px solid #aebdb6;border-radius:12px}#building-fleet-panel h2{font-size:1.2rem}.bf-controls{display:flex;gap:.6rem;flex-wrap:wrap;align-items:center}.bf-controls input[type=range]{flex:1;min-width:180px}.bf-table{max-height:24rem;overflow:auto}#building-fleet-panel table{border-collapse:collapse;width:100%;font-size:.82rem}#building-fleet-panel td,#building-fleet-panel th{padding:.4rem;text-align:left;border-bottom:1px solid #c8d1cc}#building-fleet-panel ol{max-height:12rem;overflow:auto;font:12px monospace}.bf-camera{display:flex;gap:1rem;flex-wrap:wrap;margin:1rem 0}.bf-camera>div:first-child{max-width:100%;width:320px}.bf-camera>div:first-child>canvas{display:block;max-width:100%;width:320px;background:#192a2d}#building-fleet-panel p,#building-fleet-panel td{overflow-wrap:anywhere}.bf-mosaic{display:grid;grid-template-columns:repeat(auto-fit,minmax(80px,1fr));gap:4px;flex:1;min-width:230px}.bf-mosaic figure{margin:0}.bf-mosaic canvas{width:100%;background:#233}.bf-mosaic figcaption{font-size:10px}.bf-labels{position:absolute;inset:0;pointer-events:none;overflow:hidden}.bf-labels span{position:absolute;transform:translate(-50%,-100%);font:bold 11px sans-serif;background:#fff9;border-radius:3px;padding:2px 4px;color:#173d37}</style>'''


def pinned(ref):
    if type(ref)is not dict or set(ref)!={'path','sha256'}:raise ValueError('Exact pinned artifact reference required')
    path=native.project_path(ref['path'])
    if native.digest(path)!=ref['sha256']:raise ValueError('Changed BF01 input: '+ref['path'])
    return path


def completed_program(program):
    if program.get('format')!='solidcraftbot.building-fleet-program/1' or program.get('complete')is not True:raise ValueError('Complete compiled fleet program required; prepared components are not a demo')
    rows=program.get('trajectories',[])
    if len(rows)!=20 or {r['vehicle_id']for r in rows}!={'BF%02d'%i for i in range(1,21)}:raise ValueError('Exactly BF01..BF20 required')
    if not isinstance(program.get('received_messages'),list)or not isinstance(program.get('camera_captures'),dict):raise ValueError('Received telemetry and own camera capture records required')
    capture_owners={}
    for message in program['received_messages']:
        telemetry.validate(message)
        if message['kind']=='perception':
            capture=program['camera_captures'].get(message['payload']['camera_ref'])
            if not capture or capture['captured_s']!=message['payload']['captured_s']or capture['level_id']!=message['payload']['level']:raise ValueError('Camera capture must bind the delivered perception identity/time/level')
            owner=capture_owners.setdefault(message['payload']['camera_ref'],message['vehicle_id'])
            if owner!=message['vehicle_id']:raise ValueError('Camera reference belongs to another vehicle')
            if type(capture['captured_s'])not in(int,float)or not math.isfinite(capture['captured_s'])or capture['captured_s']<0:raise ValueError('Finite own capture timestamp required')
            if not isinstance(capture['pose_xyz_mm'],list)or len(capture['pose_xyz_mm'])!=3 or any(type(v)not in (int,float)or not math.isfinite(v)for v in capture['pose_xyz_mm']+[capture['yaw_rad']]):raise ValueError('Finite own camera capture pose required')
            reported=message['payload']['pose_mm']
            actual=capture['pose_xyz_mm'][:2]+[capture['yaw_rad']]
            if any(abs(a-b)>1e-7 for a,b in zip(reported,actual)):raise ValueError('Rendered camera pose differs from the vehicle-reported capture pose')
    return program


def checked_export_report(path,program_path):
    """Require current independent checks bound to the exact exported bytes."""
    report=model.read_json(path)
    if report.get('format')!='solidcraftbot.building-fleet-export-check/2'or report.get('passed')is not True:
        raise ValueError('Successful independent BF01 export-check/2 report required')
    if pinned(report.get('program'))!=program_path:
        raise ValueError('Export check belongs to another exact program')
    required={'coverage','homes','dynamics','no_stop','support','collision','resources','lift','perception','telemetry'}
    rows=report.get('checks',{})
    if not required<=set(rows)or any(type(rows[k])is not dict or rows[k].get('passed')is not True or len(rows[k])<2 for k in required):
        raise ValueError('Independent check metrics/evidence required for every BF01 contract')
    pins=report.get('source_files_sha256',{})
    source=model.load()
    expected={**model.source_pins(source),**model.protected_pins()}
    names=('building_fleet_checks.py','building_fleet_support.py','building_fleet_motion.py',
           'building_fleet_clearance.py','building_fleet_navigation.py','building_fleet_control.py',
           'building_fleet_services.py','building_fleet_sim.py','building_fleet_lift_checks.py',
           'building_fleet_lift_geometry.py','building_fleet_floor.py','building_fleet_runner.py',
           'building_fleet_missions.py','building_fleet_resources.py','building_fleet_comm.py',
           'building_fleet_dispatch.py','building_fleet_geometry_checks.py','building_fleet_depot.py','building_fleet_zones.py',
           'building_fleet_assignment_checks.py','building_fleet_port_paths.py')
    expected.update({'scripts/'+name:model.digest(ROOT/'scripts'/name)for name in names})
    if any(pins.get(name)!=digest for name,digest in expected.items()):
        raise ValueError('Export check omits a current checker/support/primitive source pin')
    native.verify_pins(pins)
    return report


def html_budget(additional_bytes):
    """Report the presentation target; never discard motion to meet it."""
    return {'target_bytes':ADDITIONAL_HTML_TARGET_BYTES,'additional_bytes':additional_bytes,
            'budget_met':additional_bytes<=ADDITIONAL_HTML_TARGET_BYTES,
            'policy':'Presentation target; exceedance is reported without dropping PVA, received telemetry or captures'}


def world_presentation(world_path,*,include_monitor_overlay=False,progressive_output=None,lab3003_preview=None):
    """Render the checked physical world with the current shared viewer adapter."""
    import build_building_walkthrough as builder
    import walkthrough_world
    world_path=native.project_path(world_path)
    if world_path.name!=walkthrough_world.REPORT:
        raise ValueError('A separate physical world report is required for BF01 presentation')
    report,manifest,bundle=walkthrough_world.read(world_path.parent,ROOT)
    paths=(Path(builder.__file__),builder.TEMPLATE,builder.INTERACTION_SCRIPT,builder.SEMINAR_SCRIPT,
           ROOT/'scripts/templates/quintic_motion.js',ROOT/'scripts/walkthrough_robots.js',
           ROOT/'scripts/camera_monitor_wall.js',ROOT/'scripts/monitor_frustum.js',world_path,
           *(native.project_path(path)for path in report['files'].values()))
    pins={str(path.relative_to(ROOT)):native.digest(path)for path in paths}
    payload={**manifest,'scenes':bundle['scenes']}
    if include_monitor_overlay:
        overlay=builder.compile_monitor_overlay(manifest)
        if overlay is None:raise ValueError('Source-bound physical monitor wall required')
        payload=builder.attach_monitor_overlay(payload,overlay)
        pins=builder.merge_pins(pins,overlay['source_files_sha256'])
    template=builder.TEMPLATE.read_text(encoding='utf-8')
    if lab3003_preview is not None:
        if progressive_output is None:
            raise ValueError('Shared laboratory playback requires the progressive fleet viewer')
        import building_fleet_lab3003 as lab
        payload=lab.attach(payload,lab3003_preview)
        template=lab.viewer(template)
        pins=builder.merge_pins(pins,payload['source_files_sha256'],{
            str(path.relative_to(ROOT)):native.digest(path) for path in
            (Path(lab.__file__),ROOT/'scripts/walkthrough_lab3003_cf01.js',ROOT/'scripts/walkthrough_tr01_lap.js')})
    if progressive_output is not None:
        import building_fleet_progressive_presentation as progressive
        payload=progressive.derive(payload,progressive_output,world_report_sha256=native.digest(world_path))
        for path in (Path(progressive.__file__),progressive.SCRIPT,progressive.WORKER):
            pins[str(path.relative_to(ROOT))]=native.digest(path)
    normal=builder.embed_html(template,payload)
    if progressive_output is not None:
        normal=progressive.attach(normal)
    native.verify_pins(pins)
    return normal,pins


def view_program(program,manifest):
    """Project every playback datum and add source-derived numeric lift endpoints."""
    # Keep every playback datum verbatim. Audit-only curves, scan/brake
    # proofs, resource catalogs and own-input traces remain in the exact
    # independently checked source program, never a second browser runtime.
    value={key:copy.deepcopy(program[key])for key in PLAYBACK_FIELDS}
    objects={o['id']:o for o in manifest['objects']};lift=manifest['elevator']
    doors={k:o for k,o in objects.items()if o.get('mechanism')=='lift_door'}
    initial={k:o['states']['closed']for k,o in doors.items()}
    for port in lift['ports']:
        if port['active']and port['level_id']==lift['reference_level']:
            for ident in port.get('door_object_ids',[]):initial[ident]=doors[ident]['states']['open']
    value['lift_initial_state']={'z_mm':lift['reference_z_mm'],'door_values':initial}
    for row in value['lift_schedule']:
        if row['kind']=='doors':
            identifiers={ident for port in lift['ports']if port['active']and port['level_id']==row['level']for ident in port.get('door_object_ids',[])}
            row['target_values']={ident:doors[ident]['states'][row['target']]for ident in identifiers}
    return value


def opt_in_html(normal,payload=None):
    if payload is None:return normal
    if normal.count(ANCHOR)!=1:raise ValueError('Current normal viewer bridge anchor changed')
    text=normal.replace(ANCHOR,BRIDGE+ANCHOR)
    replacements={
      '<a class="quiet-button" id="walkthrough-fleet-link" href="bf01/">Transporter-Demo · BF01</a>':'<a class="quiet-button" id="walkthrough-fleet-link" href="../">Gebäuderundgang</a>',
      '    function command(id,name){':'    function command(id,name){\n      if(fleetActive&&(id===elevatorConfig?.object_id||objectStates.get(id)?.config.mechanism===\'lift_door\'))return fleetBusy();',
      '    function robotCommand(id,name){':'    function robotCommand(id,name){\n      if(fleetActive)return fleetBusy();',
      '    function move(seconds){':'    function move(seconds){\n      if(fleetHooks?.following)return;',
      '    function viewObject(id){':'    function viewObject(id){\n      if(fleetHooks?.following)return {status:\'rejected_following\',id};',
      '    function setStop(id){':'    function setStop(id){\n      if(fleetHooks?.following)return {status:\'rejected_following\',id};',
      'const animating=advanceObjects(now),liftActive=liftDoors?.advance();':'const animating=advanceObjects(now),liftActive=fleetActive?false:liftDoors?.advance();',
      'gl.viewport(0,0,width,height);drawScene(prepareScene(sceneId),cameraMatrix(width/height),eye);':'gl.viewport(0,0,width,height);const scene=prepareScene(sceneId);drawScene(scene,cameraMatrix(width/height),eye);if(fleetHooks){fleetHooks.draw(cameraMatrix(width/height));gl.useProgram(program);gl.bindVertexArray(scene.vao);}',
      '    liftDoors?.initialize();setStop(':'    if(!fleetActive)liftDoors?.initialize();setStop(',
      "    canvas.addEventListener('pointermove',event=>{":"    canvas.addEventListener('pointermove',event=>{\n      if(fleetHooks?.following)return;",
    }
    for before,after in replacements.items():
        if text.count(before)!=1:raise ValueError('Current normal viewer adapter hook changed: '+before)
        text=text.replace(before,after)
    before="    isolationButton.addEventListener('click',()=>{"
    if text.count(before)!=1:raise ValueError('Current isolation hook changed')
    text=text.replace(before,before+"if(fleetHooks?.following)return;")
    before="    levelSelect.addEventListener('change',()=>{"
    if text.count(before)!=1:raise ValueError('Current level-select hook changed')
    text=text.replace(before,before+"if(fleetHooks?.following){levelSelect.value=selectedLevel;return;}")
    script=VIEW.read_text().replace('</script','<\\/script')
    encoded=json.dumps(payload,separators=(',',':'),allow_nan=False).replace('<','\\u003c')
    text=text.replace('</head>',STYLE+'<script>'+script+'</script></head>')
    text=text.replace('<script id="walkthrough-data"', '<section id="building-fleet-panel" hidden></section><script id="building-fleet-data" type="application/json">'+encoded+'</script><script id="walkthrough-data"',1)
    return text


def build(program_path,native_proof_path,vehicle_mesh_path,output,*,export_check_report=None):
    started=time.monotonic();program_path=native.project_path(program_path);proof_path=native.project_path(native_proof_path);mesh_path=native.project_path(vehicle_mesh_path)
    source=model.load();program=completed_program(model.read_json(program_path));native.verify_pins(program['source_files_sha256'])
    if export_check_report is None:raise ValueError('Independent export check required; compiler flags alone are not evidence')
    export_path=native.project_path(export_check_report);checked_export_report(export_path,program_path)
    proof=model.read_json(proof_path)
    if proof.get('passed')is not True or proof.get('audit_scope')!='full_fleet_program'or proof['program']['sha256']!=native.digest(program_path):raise ValueError('Successful exact native full-fleet proof required; a connector proof is insufficient')
    native.verify_pins(proof['source_files_sha256'])
    from check_building_fleet_freecad import checked_walkthrough
    walk_path=pinned(program['artifacts']['walkthrough_report']);_,_,manifest,_=checked_walkthrough(walk_path);camera_path=pinned(program['artifacts']['camera_report']);checked_camera_report(camera_path)
    vehicle=model.read_json(mesh_path);native.verify_pins(vehicle['source_files_sha256'])
    if vehicle.get('format')!='solidcraftbot.building-fleet-vehicle-mesh/1'or vehicle['camera_report']['sha256']!=native.digest(camera_path):raise ValueError('Current checked native vehicle mesh required')
    import tr01_camera_model as kit
    expected={b['id']for b in kit.expanded(kit.load())['bodies']if b['role']!='viewing_cone'}
    if {g['id']for g in vehicle['scene']['groups']}!=expected:raise ValueError('Incomplete physical vehicle mesh')
    normalized=view_program(program,manifest);compressed=gzip.compress(json.dumps(normalized,separators=(',',':'),allow_nan=False).encode(),mtime=0)
    payload={'program_gzip_base64':base64.b64encode(compressed).decode(),'vehicle_mesh':vehicle,'camera_presentation':source['camera_presentation'],'program_source_sha256':native.digest(program_path)}
    normal,presentation_pins=world_presentation(walk_path);html=opt_in_html(normal,payload);extra=len(html.encode())-len(normal.encode())
    budget=html_budget(extra)
    limitations=copy.deepcopy(source['limitations'])
    if not budget['budget_met']:
        limitations.append('Additional opt-in HTML exceeds the 10 MiB presentation target; no PVA nodes, received telemetry or camera captures were thinned.')
    output=native.project_path(output)
    if output.exists():raise FileExistsError(output)
    output.mkdir(parents=True);(output/'index.html').write_text(html)
    for name,digest in presentation_pins.items():
        if name in program['source_files_sha256']and program['source_files_sha256'][name]!=digest:
            raise ValueError('Presentation conflicts with the compiled world source: '+name)
    pins={**program['source_files_sha256'],**presentation_pins,str(program_path.relative_to(ROOT)):native.digest(program_path),str(proof_path.relative_to(ROOT)):native.digest(proof_path),str(export_path.relative_to(ROOT)):native.digest(export_path),str(mesh_path.relative_to(ROOT)):native.digest(mesh_path),str(VIEW.relative_to(ROOT)):native.digest(VIEW),str(Path(__file__).relative_to(ROOT)):native.digest(__file__)}
    native.verify_pins(pins)
    result={'format':'solidcraftbot.building-fleet-browser-build/1','passed':True,'browser_checked':False,'source_files_sha256':pins,'html_sha256':native.digest(output/'index.html'),'normal_html_sha256':hashlib.sha256(normal.encode()).hexdigest(),'additional_html_bytes':extra,'html_budget':budget,'gzip_program_bytes':len(compressed),
            'presentation':{'world_report':program['artifacts']['walkthrough_report'],
                'source_files_sha256':presentation_pins,
                'scope':'Current shared renderer applied to the exact checked physical world; no camera-wall overlay is a physical input'},
            'playback_projection':{'included_fields':list(PLAYBACK_FIELDS),'omitted_audit_only_fields':sorted(set(program)-set(PLAYBACK_FIELDS)),
                'full_program':{'path':str(program_path.relative_to(ROOT)),'sha256':native.digest(program_path)},
                'trajectory_pva_unchanged':normalized['trajectories']==program['trajectories'],
                'received_messages_unchanged':normalized['received_messages']==program['received_messages'],
                'own_captures_unchanged':normalized['camera_captures']==program['camera_captures']},'elapsed_s':time.monotonic()-started,'scope':'Lossless playback projection of a complete source/native-checked fleet program embedded into opt-in HTML; audit-only data remain in the exact full program. Actual browser proof remains separate. Normal walkthrough file unchanged.','limitations':limitations}
    (output/'build-report.json').write_text(json.dumps(result,indent=2)+'\n');return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('program');parser.add_argument('--native-proof',required=True);parser.add_argument('--export-check',required=True);parser.add_argument('--vehicle-mesh',required=True);parser.add_argument('--output-dir',required=True);parser.add_argument('--serve',action='store_true');args=parser.parse_args();build(args.program,args.native_proof,args.vehicle_mesh,args.output_dir,export_check_report=args.export_check)
    if args.serve:
        from functools import partial
        from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
        server=ThreadingHTTPServer(('127.0.0.1',0),partial(SimpleHTTPRequestHandler,directory=str(native.project_path(args.output_dir))));print('http://127.0.0.1:'+str(server.server_port),flush=True);server.serve_forever()


if __name__=='__main__':main()
