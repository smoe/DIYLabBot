"""Build the common L01 roundtrip in native FreeCAD and SolidCraft."""
from pathlib import Path
import argparse
import copy
import tool_paths
import hashlib
import json
import math
import shutil
import subprocess
import lab_transfer_motion as model
import lab_layout_model as layout
import lab_room_model as room
import robot_spec as robot
from build_instrument_concepts import freecad_environment

ROOT=layout.ROOT
def write(path,value):Path(path).write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')


def check_pins(pins,label):
    changed=[name for name,digest in pins.items() if not (ROOT/name).is_file() or robot.digest(ROOT/name)!=digest]
    if changed:raise ValueError(label+' changed during L01 build: '+', '.join(changed))


def furniture_distance_lower_bound(a,b,required,exact_distance):
    """Use an AABB separation certificate, refining only below the margin."""
    lower=math.sqrt(math.fsum(max(0.,a['min'][i]-b['max'][i],b['min'][i]-a['max'][i])**2 for i in range(3)))
    if lower>=required:return lower,False
    distance=float(exact_distance())
    if not math.isfinite(distance) or distance<0.:raise ValueError('Invalid exact native furniture distance')
    return distance,True


def preview_clock(duration):
    """The installed SC study accepts at most 100000 dimensionless steps."""
    if not math.isfinite(duration) or duration<=0.:raise ValueError('Positive preview duration required')
    steps=min(100000,max(1,math.ceil(duration*1000)))
    return {'steps':steps,'duration_s':duration,'seconds_per_step':duration/steps}


def geometry_artifacts(ctx):
    return [Path(ctx['scene_file']),Path(ctx['sample_step']),
            *[Path(v['step']) for v in ctx['snapshots']+ctx['dynamic'] if v.get('step')]]


def geometry_contract(s,ls):
    files=[*model.construction_sources(s,ls),ROOT/'scripts/lab_transfer_motion.py',ROOT/'scripts/build_lab_transfer_freecad.py',
           ROOT/'scripts/build_lab_layout_freecad.py',ROOT/'scripts/build_neutral_freecad.py',ROOT/'scripts/build_centrifuge_freecad.py',
           ROOT/'scripts/freecad/solidcraftbot_freecad.py']
    return {'layout_sha256':robot.digest(layout.SOURCE),'arm':s['arm'],'sample':copy.deepcopy(s['sample']),'tool':copy.deepcopy(s['tool']),
            'geometry_sources_sha256':{str(p.relative_to(ROOT)):robot.digest(p) for p in files}}


def verify_geometry_contract(ctx,s=None,ls=None):
    stored=ctx.get('geometry_contract',{});pins=stored.get('geometry_sources_sha256')
    if not pins:raise ValueError('Complete geometry source pins are required')
    check_pins(pins,'Geometry source')
    if stored!=geometry_contract(s or model.load(),ls or layout.load()):raise ValueError('Geometry source contract changed')


def checked_reuse(path,contract):
    path=Path(path);old=json.loads(path.read_text())
    if old.get('passed') is not True or old.get('geometry_contract')!=contract:
        raise ValueError('Reusable geometry requires current equivalent geometry sources and a passed context')
    pins=old['geometry_contract'].get('geometry_sources_sha256')
    if not pins:raise ValueError('Reusable geometry requires complete geometry source pins')
    check_pins(pins,'Reusable geometry source')
    for field in ('geometry_inputs_sha256','geometry_artifacts_sha256','native_input_sha256'):
        if not old.get(field):raise ValueError('Reusable geometry has no complete byte binding: '+field)
        check_pins(old[field],'Reusable '+field)
    required={str(p.resolve().relative_to(ROOT)) for p in geometry_artifacts(old)}
    if not required<=set(old['geometry_artifacts_sha256']):raise ValueError('Reusable geometry omits a scene or STEP artifact')
    native=Path(old['out'])/'motion-validation.json'
    if not native.is_file() or robot.digest(native)!=old.get('native_report_sha256'):
        raise ValueError('Reusable native report is missing or changed')
    report=json.loads(native.read_text());verify_native_inputs(old,report)
    if report.get('passed') is not True:raise ValueError('Reusable native proof did not pass')
    pins={**old['geometry_inputs_sha256'],**old['geometry_artifacts_sha256'],**old['native_input_sha256'],
          str(path.resolve().relative_to(ROOT)):robot.digest(path),str(native.resolve().relative_to(ROOT)):robot.digest(native)}
    return old,pins


def verify_native_inputs(ctx,report):
    pins=ctx.get('native_input_sha256')
    if not pins or report.get('native_input_sha256')!=pins:
        raise ValueError('Native report is not bound to the audited timeline and samples; rebuild')
    required={str((Path(ctx['out'])/name).resolve().relative_to(ROOT)) for name in ('timeline.json','samples.json')}
    if set(pins)!=required:raise ValueError('Native inputs must bind exactly timeline.json and samples.json')
    check_pins(pins,'Native input')
    native=Path(ctx['out'])/'motion-validation.json'
    if not native.is_file() or robot.digest(native)!=ctx.get('native_report_sha256'):
        raise ValueError('Native report bytes changed after the audit')


def prepare(args):
    ls=layout.load();s=model.load();digest=hashlib.sha256(layout.SOURCE.read_bytes()+model.SOURCE.read_bytes()).hexdigest();stem='lab-transfer-l01-'+digest[:12];rev=stem;n=1
    while (ROOT/'cad/generated'/rev).exists():n+=1;rev=stem+'-r'+str(n)
    candidates=[]
    for path in (ROOT/'exports/generated').glob('lab-layout-l01-*/context.json'):
        context=json.loads(path.read_text())
        validation=path.parent/'layout-validation.json'
        if (context['source_sha256']==robot.digest(layout.SOURCE) and 'snapshots' in context
                and Path(context.get('scene_file','')).is_file() and validation.is_file()
                and json.loads(validation.read_text()).get('passed') is True):candidates.append(path)
    if not candidates:raise ValueError('A current passed FreeCAD layout context is required; build the layout with --prepare-only first')
    parent=max(candidates,key=lambda p:p.stat().st_mtime)
    validation=json.loads((parent.parent/'layout-validation.json').read_text())
    if not validation['passed']:raise ValueError('Current static layout must pass first')
    cad=ROOT/'cad/generated'/rev;out=ROOT/'exports/generated'/rev;cad.mkdir(parents=True);out.mkdir(parents=True)
    ctx={'revision':rev,'cad':str(cad),'out':str(out),'layout_context':str(parent),'layout_sha256':robot.digest(layout.SOURCE),'protocol_sha256':robot.digest(model.SOURCE)}
    code=[Path(__file__),ROOT/'scripts/build_lab_transfer_freecad.py',ROOT/'scripts/build_lab_layout_freecad.py',
          ROOT/'scripts/build_neutral_freecad.py',ROOT/'scripts/build_centrifuge_freecad.py',
          ROOT/'scripts/templates/lab_transfer_playback.FCMacro',ROOT/'scripts/freecad/solidcraftbot_freecad.py',
          ROOT/'scripts/build_lab_room_freecad.py',ROOT/'scripts/lab_room_model.py',ROOT/'scripts/build_instrument_concepts.py',
          ROOT/'scripts/freecad/persist_station_view.py',ROOT/'scripts/freecad/persist_view.py']
    ctx['build_sources_sha256']={**model.dependencies(s,ls),**{str(p.relative_to(ROOT)):robot.digest(p) for p in code}}
    context=json.loads(parent.read_text());inputs=[parent,parent.parent/'layout-validation.json',Path(context['scene_file'])]
    inputs.extend(Path(v['step']) for v in context['snapshots'] if v.get('step'))
    inputs.extend(layout.assembly.resolve_artifact(ref) for ref in ls['assets'].values())
    inputs.extend(layout.assembly.project_path(ref['report']) for ref in ls['assets'].values())
    ctx['geometry_inputs_sha256']={str(p.resolve().relative_to(ROOT)):robot.digest(p) for p in inputs}
    ctx['geometry_contract']=geometry_contract(s,ls)
    verify_geometry_contract(ctx,s,ls)
    if args.reuse_geometry:
        old,pins=checked_reuse(args.reuse_geometry,ctx['geometry_contract'])
        ctx['geometry_inputs_sha256'].update(pins)
        for key in ['snapshots','dynamic','styles','sample_step','sample_bodies','joint_specs']:ctx[key]=old[key]
        ctx['reuse_scene']=old['scene_file'];ctx['geometry_parent_context']=str(args.reuse_geometry)
    path=out/'context.json';write(path,ctx)
    subprocess.run([args.freecad_python,str(ROOT/'scripts/build_lab_transfer_freecad.py'),str(path)],check=True,cwd=ROOT,env=freecad_environment(args.freecad_python))
    ctx=json.loads(path.read_text());print(str(path),flush=True)
    check_pins(ctx['build_sources_sha256'],'Source');check_pins(ctx['geometry_inputs_sha256'],'Geometry input');verify_geometry_contract(ctx,s,ls)
    if not ctx['passed']:raise ValueError('Motion audit failed: '+str(out/'motion-validation.json'))
    commands=compile_commands(ctx,ls,s);write(out/'scene.commands.json',{'commands':commands})
    ctx['solidcraft_commands_sha256']=robot.digest(out/'scene.commands.json');write(path,ctx)
    return ctx


def compile_commands(ctx,ls,s):
    room_source=room.load(layout.assembly.validate_reference(ls['assets']['room']))
    commands=room.solidcraft_commands(room_source,room.parameters(room_source));d=model.data(s,ls);p=d['p']
    def add(command,**params):commands.append({'command':command,'params':params})
    def import_group(name,step,bodies,matrix,grounded):
        # STEP products supply bodies, not a guaranteed named occurrence.
        # Assemble at source zero first, then place the actual rigid group.
        if step:add('file.insert_step',path=step,name=name+'_Import',names='product')
        add('component.create',name=name,parent='root',activate=False,grounded=False)
        if bodies:add('component.move_bodies',bodies=[b['name'] for b in bodies],component=name)
        add('occurrence.move',occurrence=name+':1',matrix=matrix,move_grounded=True)
        add('occurrence.ground',occurrence=name+':1',grounded=grounded)
        for b in bodies:add('appearance.assign',bodies=[b['name']],**b['appearance'])
    for snapshot in ctx['snapshots']+ctx['dynamic']:
        import_group(snapshot['id'],snapshot['step'],snapshot['bodies'],snapshot['matrix'],snapshot.get('grounded',True))
    for tag,joints in ctx['joint_specs'].items():
        base=d['base'] if tag=='ArmC' else d['station']
        for j in joints:
            frame={'origin':robot.transform(base,j['origin']),'z':model.direction(base,j['axis']),'x':model.direction(base,j['reference_x'])}
            add('joint.create',name=tag+'_'+j['id'],type=j['type'],a={'occurrence':tag+'_'+j['parent']+':1','frame':frame},b={'occurrence':tag+'_'+j['child']+':1','frame':frame},flip=True,values=[0],limits=[j['limits']],quiet=True)
    for name in ['Origin','X','Y','Z','Yaw']:
        add('component.create',name='Sample_'+name,parent='root',activate=False,grounded=name=='Origin')
    import_group('Sample_Tilt',ctx['sample_step'],ctx['sample_bodies'],robot.identity(),False)
    for before,after,kind,axis in [('Origin','X','slider',[1,0,0]),('X','Y','slider',[0,1,0]),('Y','Z','slider',[0,0,1]),('Z','Yaw','revolute',[0,0,1]),('Yaw','Tilt','revolute',[0,1,0])]:
        x=[0,1,0] if axis==[1,0,0] else [1,0,0];frame={'origin':[0,0,0],'z':axis,'x':x}
        add('joint.create',name='Sample_'+after,type=kind,a={'occurrence':'Sample_'+before+':1','frame':frame},b={'occurrence':'Sample_'+after+':1','frame':frame},flip=True,values=[0],limits=[[-10000,10000]],quiet=True)
    frames=json.loads((Path(ctx['out'])/'samples.json').read_text());keys=[];clock=preview_clock(frames[-1]['time_s'])
    def track(joint,values):
        points=[]
        for frame,value in zip(frames,values):
            point=[frame['time_s']/clock['seconds_per_step'],value]
            if points and point[0]==points[-1][0]:points[-1]=point;continue
            while len(points)>1:
                a,b=points[-2:];pred=a[1]+(point[1]-a[1])*(b[0]-a[0])/(point[0]-a[0])
                if abs(pred-b[1])>1e-10:break
                points.pop()
            points.append(point)
        keys.append({'joint':joint,'points':points})
    for i in range(6):track('ArmC_J'+str(i+1),[f['q'][i] for f in frames])
    for j in d['ce']['joints']:track('CF01_'+j['id'],[f['cf'][j['id']] for f in frames])
    for i,name in enumerate('XYZ'):track('Sample_'+name,[f['sample_bottom'][i] for f in frames])
    azimuths=[]
    for frame in frames:
        value=math_degrees_atan(frame['sample_axis'])
        if azimuths:
            while value-azimuths[-1]>180:value-=360
            while value-azimuths[-1]<-180:value+=360
        azimuths.append(value)
    track('Sample_Yaw',azimuths)
    import math
    track('Sample_Tilt',[math.degrees(math.acos(max(-1,min(1,f['sample_axis'][2])))) for f in frames])
    add('motion.study',name='L01SampleRoundtripPreview',steps=clock['steps'],keys=keys)
    add('motion.play',study='L01SampleRoundtripPreview',step=0,quiet=True)
    add('browser.visibility',folder='joints',visible=False)
    for c in ls['corridors']:
        x0,x1,y0,y1=layout.xyz(c['bounds'],p)
        add('solid.box',name=c['id'],body_name=c['id'],corner=[x0,y0,0.1],length=x1-x0,width=y1-y0,height=1.5)
        add('appearance.assign',bodies=[c['id']],color=c['color'],opacity=0.32)
    add('document.metadata.set',values={'org.solidcraftbot.lab-transfer':{'source':str(model.SOURCE.relative_to(ROOT)),'layout_sha256':ctx['layout_sha256'],'protocol_sha256':ctx['protocol_sha256'],'sampling':s['checks'],'simulation_only':True,
        'canonical_motion':'timeline.json; C2 quintic PVA','solidcraft_motion':'derived linear preview; not an executable C2 transport program',
        'native_pva_interpolation_supported':False,'preview_error_mm':s['motion']['preview_error_mm'],'preview_clock':clock}})
    return commands


def math_degrees_atan(axis):
    import math
    # Azimuth is immaterial for an upright axis; use the same convention as FC.
    return math.degrees(math.atan2(axis[1],axis[0])) if abs(axis[0])+abs(axis[1])>1e-10 else 0


def finish(ctx,args):
    out=Path(ctx['out']);cad=Path(ctx['cad']);report=json.loads((out/'motion-validation.json').read_text())
    if ctx.get('passed') is not True or report.get('passed') is not True:
        raise ValueError('Only a passed native audit can be finalized')
    check_pins(ctx['build_sources_sha256'],'Source');check_pins(ctx['geometry_inputs_sha256'],'Geometry input')
    verify_geometry_contract(ctx)
    verify_native_inputs(ctx,report)
    check_pins(ctx['geometry_artifacts_sha256'],'Audited geometry')
    if ctx['layout_sha256']!=robot.digest(layout.SOURCE) or ctx['protocol_sha256']!=robot.digest(model.SOURCE):raise ValueError('Source changed during build')
    scene=cad/'LabTransfer_L01.sc'
    if robot.digest(out/'scene.commands.json')!=ctx.get('solidcraft_commands_sha256'):raise ValueError('SolidCraft preview commands changed after preparation')
    if not scene.exists():
        subprocess.run([args.solidcraft_cli,'run',str(out/'scene.commands.json'),'--save',str(scene),'--quiet'],check=True,cwd=ROOT)
        ctx['solidcraft_artifact_sha256']=robot.digest(scene);write(out/'context.json',ctx)
    if robot.digest(scene)!=ctx.get('solidcraft_artifact_sha256'):raise ValueError('SolidCraft scene is not the prepared preview artifact')
    timeline=json.loads((out/'timeline.json').read_text());frames=json.loads((out/'samples.json').read_text())
    macro=cad/'L01_SampleRoundtrip.FCMacro'
    model.verify_sources(timeline)
    macro.write_text((ROOT/'scripts/templates/lab_transfer_playback.FCMacro').read_text(encoding='utf-8')
                     .replace('__DOCUMENT__',repr(ctx['scene_file'])).replace('__ROOT__',repr(str(ROOT)))
                     .replace('__TIMELINE_PATH__',repr(str(out/'timeline.json'))).replace('__TIMELINE_SHA256__',repr(robot.digest(out/'timeline.json'))),encoding='utf-8')
    native_motion=out/'solidcraft-motion.json'
    request=out/'solidcraft-motion-export.commands.json'
    write(request,{'commands':[{'command':'motion.export','params':{'study':'L01SampleRoundtripPreview','samples':257,'path':str(native_motion)}}]})
    subprocess.run([args.solidcraft_cli,'run',str(request),'--in',str(scene),'--quiet'],check=True,cwd=ROOT)
    if robot.digest(scene)!=ctx['solidcraft_artifact_sha256']:raise ValueError('SolidCraft scene changed during pose export')
    check=check_motion(json.loads(native_motion.read_text()),timeline,model.load(),layout.load())
    report['solidcraft_motion_comparison']=check;report['passed']=report['passed'] and check['passed']
    import sys
    sys.path.insert(0,str(ROOT/'scripts/freecad'));from persist_station_view import persist
    if ctx.get('presentation_bounds'):
        report['presentation']=persist(ctx['scene_file'],{'bodies':[{'id':name,'appearance':style} for name,style in ctx['styles'].items()]},ctx['presentation_bounds'])
    report.update(format='solidcraftbot.lab-transfer-build/2',revision=ctx['revision'],layout_sha256=ctx['layout_sha256'],protocol_sha256=ctx['protocol_sha256'],
                  asset_sources=layout.load()['assets'],limitations=model.load()['limitations'],
                  files={'solidcraft':str(scene.relative_to(ROOT)),'freecad':str(Path(ctx['scene_file']).relative_to(ROOT)),
                         'timeline':str((out/'timeline.json').relative_to(ROOT)),'samples':str((out/'samples.json').relative_to(ROOT)),
                         'validation':str((out/'motion-validation.json').relative_to(ROOT))},
                  source_files_sha256=ctx['build_sources_sha256'],geometry_inputs_sha256=ctx['geometry_inputs_sha256'],
                  artifact_sha256={'solidcraft':robot.digest(scene),'freecad':robot.digest(ctx['scene_file'])},renderings=[str(p.relative_to(ROOT)) for p in cad.glob('*.png')]+[str(p.relative_to(ROOT)) for p in cad.glob('*.gif')])
    report['files']['freecad_playback']=str(macro.relative_to(ROOT))
    report['canonical_motion']={'format':timeline['format'],'interpolation':'C2_quintic','segments':timeline['segments'],'qualified':False}
    report['solidcraft_preview']={'study':'L01SampleRoundtripPreview','interpolation':'linear','native_pva_interpolation_supported':False,
                                  'clock':preview_clock(timeline['duration_s']),
                                  'scope':'Derived display preview only; planning and dynamics use the canonical PVA timeline, not these keys.'}
    report['solidcraft_preview'].update(ctx['preview_validation'])
    report['dynamics_validation']=model.validate_timeline(timeline)
    check_pins(ctx['build_sources_sha256'],'Source');check_pins(ctx['geometry_inputs_sha256'],'Geometry input')
    verify_geometry_contract(ctx)
    verify_native_inputs(ctx,report)
    ctx['geometry_artifacts_sha256']={str(p.resolve().relative_to(ROOT)):robot.digest(p) for p in geometry_artifacts(ctx)}
    report['geometry_artifacts_sha256']=ctx['geometry_artifacts_sha256']
    report['files']['solidcraft_motion']=str(native_motion.relative_to(ROOT))
    report['artifact_sha256'].update({name:robot.digest(ROOT/path) for name,path in report['files'].items()})
    write(out/'context.json',ctx)
    write(out/'build-report.json',report);target=ROOT/'cad/lab-transfer-l01';target.mkdir(exist_ok=True);write(target/'shared-build-report.json',report)
    print(json.dumps({'passed':report['passed'],'samples':report['samples_checked'],'minimum_furniture_distance_lower_bound_mm':report['minimum_furniture_distance_lower_bound_mm']}))


def check_motion(native,timeline,s,ls):
    import math
    d=model.data(s,ls);ev=model.Evaluator(timeline,s,ls,d);errors=[];missing=[];clock=preview_clock(timeline['duration_s'])
    for sample in native['samples']:
        frame=ev(sample['step']*clock['seconds_per_step'])
        actual={p['occurrence'].split(':')[0]:p['pose'] for p in sample['positions']}
        wanted={'ArmC_'+name:robot.multiply(d['base'],m) for name,m in robot.forward(d['arm'],frame['q']).items()}
        # Station group transforms independently evaluated from its original axes.
        for c in d['ce']['components']:
            group=c['id'];origin=model.cf.transform(d['ce'],group,[0,0,0],frame['cf'])
            cols=[model.add(model.cf.transform(d['ce'],group,v,frame['cf']),origin,-1) for v in [[1,0,0],[0,1,0],[0,0,1]]]
            matrix=robot.identity()
            for i in range(3):matrix[i]=[cols[j][i] for j in range(3)]+[origin[i]]
            wanted['CF01_'+group]=robot.multiply(d['station'],matrix)
        for name,matrix in wanted.items():
            if name not in actual:missing.append(name);continue
            pose=actual[name];pe=math.dist(pose['origin'],[matrix[i][3] for i in range(3)]);re=max(abs(pose[axis][i]-matrix[i][j]) for j,axis in enumerate('xyz') for i in range(3))
            errors.append({'step':sample['step'],'instance':name,'position_mm':pe,'rotation_element_error':re})
        if 'Sample_Tilt' not in actual:missing.append('Sample_Tilt')
        else:
            pose=actual['Sample_Tilt'];errors.append({'step':sample['step'],'instance':'Sample_Tilt','position_mm':math.dist(pose['origin'],frame['sample_bottom']),
                'rotation_element_error':max(abs(a-b) for a,b in zip(pose['z'],frame['sample_axis']))})
    return {'passed':bool(errors) and not missing and all(e['position_mm']<0.05 and e['rotation_element_error']<0.001 for e in errors),
            'frames':len(native['samples']),'missing':sorted(set(missing)),'max_position_error_mm':max((e['position_mm'] for e in errors),default=None),
            'max_rotation_element_error':max((e['rotation_element_error'] for e in errors),default=None),'checks':len(errors)}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--prepare-only',action='store_true');parser.add_argument('--finish',type=Path)
    parser.add_argument('--reuse-geometry',type=Path,help='Reuse unchanged checked source geometry for a new trajectory audit')
    tool_paths.add_tool_arguments(parser, freecad=True, solidcraft=True)
    args=parser.parse_args(); tool_paths.resolve_tool_arguments(parser, args, required={'freecad_python'} if args.prepare_only else True)
    ctx=json.loads(args.finish.read_text()) if args.finish else prepare(args)
    if not args.prepare_only:finish(ctx,args)


if __name__=='__main__':main()
