"""Build the common L01 roundtrip in native FreeCAD and SolidCraft."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import subprocess
import lab_transfer_model as model
import lab_layout_model as layout
import lab_room_model as room
import robot_spec as robot

ROOT=layout.ROOT
def write(path,value):Path(path).write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')


def prepare(args):
    ls=layout.load();s=model.load();digest=hashlib.sha256(layout.SOURCE.read_bytes()+model.SOURCE.read_bytes()).hexdigest();stem='lab-transfer-l01-'+digest[:12];rev=stem;n=1
    while (ROOT/'cad/generated'/rev).exists():n+=1;rev=stem+'-r'+str(n)
    candidates=[]
    for path in (ROOT/'exports/generated').glob('lab-layout-l01-*/context.json'):
        context=json.loads(path.read_text())
        if context['source_sha256']==robot.digest(layout.SOURCE) and 'snapshots' in context:candidates.append(path)
    if not candidates:raise ValueError('Build the current layout with --prepare-only first')
    parent=max(candidates,key=lambda p:p.stat().st_mtime)
    validation=json.loads((parent.parent/'layout-validation.json').read_text())
    if not validation['passed']:raise ValueError('Current static layout must pass first')
    cad=ROOT/'cad/generated'/rev;out=ROOT/'exports/generated'/rev;cad.mkdir(parents=True);out.mkdir(parents=True)
    ctx={'revision':rev,'cad':str(cad),'out':str(out),'layout_context':str(parent),'layout_sha256':robot.digest(layout.SOURCE),'protocol_sha256':robot.digest(model.SOURCE)}
    if args.reuse_geometry:
        old=json.loads(args.reuse_geometry.read_text())
        if old['layout_sha256']!=ctx['layout_sha256']:raise ValueError('Changed layout requires fresh geometry')
        for key in ['snapshots','dynamic','styles','sample_step','sample_bodies','joint_specs']:ctx[key]=old[key]
        ctx['reuse_scene']=old['scene_file'];ctx['geometry_parent_context']=str(args.reuse_geometry)
    path=out/'context.json';write(path,ctx)
    subprocess.run([args.freecad_python,str(ROOT/'scripts/build_lab_transfer_freecad.py'),str(path)],check=True,cwd=ROOT)
    ctx=json.loads(path.read_text());print(str(path),flush=True)
    if not ctx['passed']:raise ValueError('Motion audit failed: '+str(out/'motion-validation.json'))
    commands=compile_commands(ctx,ls,s);write(out/'scene.commands.json',{'commands':commands})
    return ctx


def compile_commands(ctx,ls,s):
    commands=room.solidcraft_commands(room.load(),room.parameters(room.load()));d=model.data(s,ls);p=d['p']
    def add(command,**params):commands.append({'command':command,'params':params})
    for snapshot in ctx['snapshots']+ctx['dynamic']:
        if snapshot['step']:
            add('file.insert_step',path=snapshot['step'],name=snapshot['id'],names='product',matrix=snapshot['matrix'])
            for b in snapshot['bodies']:add('appearance.assign',bodies=[b['name']],**b['appearance'])
        else:add('component.create',name=snapshot['id'],parent='root',activate=False,grounded=False)
        add('occurrence.ground',occurrence=snapshot['id'],grounded=snapshot.get('grounded',True))
    for tag,joints in ctx['joint_specs'].items():
        base=d['base'] if tag=='ArmC' else d['station']
        for j in joints:
            frame={'origin':robot.transform(base,j['origin']),'z':model.direction(base,j['axis']),'x':model.direction(base,j['reference_x'])}
            add('joint.create',name=tag+'_'+j['id'],type=j['type'],a={'occurrence':tag+'_'+j['parent'],'frame':frame},b={'occurrence':tag+'_'+j['child'],'frame':frame},flip=True,values=[0],limits=[j['limits']],quiet=True)
    for name in ['Origin','X','Y','Z','Yaw']:
        add('component.create',name='Sample_'+name,parent='root',activate=False,grounded=name=='Origin')
    add('file.insert_step',path=ctx['sample_step'],name='Sample_Tilt',names='product')
    for b in ctx['sample_bodies']:add('appearance.assign',bodies=[b['name']],**b['appearance'])
    for before,after,kind,axis in [('Origin','X','slider',[1,0,0]),('X','Y','slider',[0,1,0]),('Y','Z','slider',[0,0,1]),('Z','Yaw','revolute',[0,0,1]),('Yaw','Tilt','revolute',[0,1,0])]:
        x=[0,1,0] if axis==[1,0,0] else [1,0,0];frame={'origin':[0,0,0],'z':axis,'x':x}
        add('joint.create',name='Sample_'+after,type=kind,a={'occurrence':'Sample_'+before,'frame':frame},b={'occurrence':'Sample_'+after,'frame':frame},flip=True,values=[0],limits=[[-10000,10000]],quiet=True)
    frames=json.loads((Path(ctx['out'])/'samples.json').read_text());keys=[]
    def track(joint,values):
        points=[]
        for frame,value in zip(frames,values):
            point=[round(frame['time_s']*1000),value]
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
    add('motion.study',name='L01SampleRoundtrip',steps=round(frames[-1]['time_s']*1000),keys=keys)
    add('motion.play',study='L01SampleRoundtrip',step=0,quiet=True)
    add('browser.visibility',folder='joints',visible=False)
    for c in ls['corridors']:
        x0,x1,y0,y1=layout.xyz(c['bounds'],p)
        add('solid.box',name=c['id'],body_name=c['id'],corner=[x0,y0,0.1],length=x1-x0,width=y1-y0,height=1.5)
        add('appearance.assign',bodies=[c['id']],color=c['color'],opacity=0.32)
    add('document.metadata.set',values={'org.solidcraftbot.lab-transfer':{'source':str(model.SOURCE.relative_to(ROOT)),'layout_sha256':ctx['layout_sha256'],'protocol_sha256':ctx['protocol_sha256'],'sampling':s['checks'],'simulation_only':True}})
    return commands


def math_degrees_atan(axis):
    import math
    # Azimuth is immaterial for an upright axis; use the same convention as FC.
    return math.degrees(math.atan2(axis[1],axis[0])) if abs(axis[0])+abs(axis[1])>1e-10 else 0


def finish(ctx,args):
    out=Path(ctx['out']);cad=Path(ctx['cad']);report=json.loads((out/'motion-validation.json').read_text())
    if ctx['layout_sha256']!=robot.digest(layout.SOURCE) or ctx['protocol_sha256']!=robot.digest(model.SOURCE):raise ValueError('Source changed during build')
    scene=cad/'LabTransfer_L01.sc'
    if not scene.exists():subprocess.run([args.solidcraft_cli,'run',str(out/'scene.commands.json'),'--save',str(scene),'--quiet'],check=True,cwd=ROOT)
    timeline=json.loads((out/'timeline.json').read_text());frames=json.loads((out/'samples.json').read_text())
    macro=cad/'L01_SampleRoundtrip.FCMacro'
    macro.write_text((ROOT/'scripts/templates/lab_transfer_playback.FCMacro').read_text(encoding='utf-8').replace('__DOCUMENT__',repr(ctx['scene_file'])).replace('__FRAMES__',repr(frames)),encoding='utf-8')
    native_motion=out/'solidcraft-motion.json'
    if not native_motion.exists():raise ValueError('Export the native L01SampleRoundtrip study before finalizing')
    check=check_motion(json.loads(native_motion.read_text()),timeline,model.load(),layout.load())
    report['solidcraft_motion_comparison']=check;report['passed']=report['passed'] and check['passed']
    import sys
    sys.path.insert(0,str(ROOT/'scripts/freecad'));from persist_station_view import persist
    if ctx.get('presentation_bounds'):
        report['presentation']=persist(ctx['scene_file'],{'bodies':[{'id':name,'appearance':style} for name,style in ctx['styles'].items()]},ctx['presentation_bounds'])
    report.update(format='solidcraftbot.lab-transfer-build/1',revision=ctx['revision'],layout_sha256=ctx['layout_sha256'],protocol_sha256=ctx['protocol_sha256'],
                  asset_sources=layout.load()['assets'],limitations=model.load()['limitations'],
                  files={'solidcraft':str(scene.relative_to(ROOT)),'freecad':str(Path(ctx['scene_file']).relative_to(ROOT)),
                         'timeline':str((out/'timeline.json').relative_to(ROOT)),'samples':str((out/'samples.json').relative_to(ROOT)),
                         'validation':str((out/'motion-validation.json').relative_to(ROOT))},
                  source_files_sha256={str(p.relative_to(ROOT)):robot.digest(p) for p in [model.SOURCE,layout.SOURCE,Path(__file__),ROOT/'scripts/lab_transfer_model.py',ROOT/'scripts/build_lab_transfer_freecad.py']},
                  artifact_sha256={'solidcraft':robot.digest(scene),'freecad':robot.digest(ctx['scene_file'])},renderings=[str(p.relative_to(ROOT)) for p in cad.glob('*.png')]+[str(p.relative_to(ROOT)) for p in cad.glob('*.gif')])
    report['files']['freecad_playback']=str(macro.relative_to(ROOT))
    write(out/'build-report.json',report);target=ROOT/'cad/lab-transfer-l01';target.mkdir(exist_ok=True);write(target/'shared-build-report.json',report)
    print(json.dumps({'passed':report['passed'],'samples':report['samples_checked'],'minimum_furniture_distance_mm':report['minimum_furniture_distance_mm']}))


def check_motion(native,timeline,s,ls):
    import math
    d=model.data(s,ls);errors=[];missing=[]
    for sample in native['samples']:
        frame=model.at_time(timeline,sample['step']/1000,s,ls,d)
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
    parser.add_argument('--freecad-python',default=str(Path.home()/'AppData/Local/Programs/FreeCAD 27.1/bin/python.exe'))
    parser.add_argument('--solidcraft-cli',default=shutil.which('solidcraft-cli') or 'solidcraft-cli');args=parser.parse_args()
    ctx=json.loads(args.finish.read_text()) if args.finish else prepare(args)
    if not args.prepare_only:finish(ctx,args)


if __name__=='__main__':main()
