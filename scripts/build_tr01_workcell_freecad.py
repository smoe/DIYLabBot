"""Derive the handoff scene and preview meshes from the existing native solids.

Floor clearances use conservative interval certificates. Arm handoff collision
checks are discrete native BRep checks, separately reported, never a safety proof.
"""
import FreeCAD as App
import Part,Mesh
import sys,json,math,gzip,base64,struct,time,argparse,shutil
from pathlib import Path
import tr01_workcell as m
import check_tr01_floor_motion as check
ROOT=m.ROOT
sys.path.insert(0,str(ROOT/'scripts/freecad'))
import solidcraftbot_freecad as geo
from build_extraction_kit_station import write


def placement(matrix):return App.Placement(App.Matrix(*[v for row in matrix for v in row]))
def moved(shape,matrix):
    result=shape.copy(False,False);result.Placement=placement(matrix).multiply(result.Placement);return result

def primitive(s):
    if s['kind']=='box':return Part.makeBox(*s['size'],App.Vector(*s['origin']))
    return Part.makeCylinder(s['radius'],s['height'],App.Vector(*s['origin']))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--preview-only',action='store_true');args=parser.parse_args()
    s=m.load();out=ROOT/'exports/tr01-workcell';out.mkdir(exist_ok=True)
    cad=ROOT/'cad/tr01-workcell';cad.mkdir(exist_ok=True)
    definition_sha=m.floor.robot.digest(m.SOURCE)
    program={'format':'solidcraftbot.tr01-workcell-program/1','definition':s,'workcell_sha256':definition_sha,'stations':{}}
    for station in s['stations']:
        cache=ROOT/'exports/tr01-animation'/(station+'.handoff.json')
        data=json.loads(cache.read_text()) if cache.exists() else None
        if not data or data.get('workcell_sha256')!=definition_sha or data.get('compiler_sha256')!=m.floor.robot.digest(Path(m.__file__)):
            data=m.compile_station(s,station);data['workcell_sha256']=definition_sha;data['compiler_sha256']=m.floor.robot.digest(Path(m.__file__));write(cache,data)
        program['stations'][station]=data;print(station,'compiled',flush=True)
    floor_report_path=ROOT/'cad/tr01-l01/shared-build-report.json'
    floor_report=json.loads(floor_report_path.read_text());m.floor.verify(floor_report['source_files_sha256'])
    for key in ('program','vehicle_file'):
        if m.floor.robot.digest(ROOT/floor_report['files'][key])!=floor_report['artifact_sha256'][key]:raise ValueError('Changed floor artifact: '+key)
    floor_program=json.loads((ROOT/floor_report['files']['program']).read_text())
    layout_report=json.loads((ROOT/'cad/lab-layout-l01/shared-build-report.json').read_text())
    doc=App.openDocument(str(ROOT/layout_report['files']['freecad']))
    car=App.openDocument(str(ROOT/floor_report['files']['vehicle_file']))
    # The native source arm is reused in its own link frames for all actors.
    arm_path=(ROOT/layout_report['files']['freecad']).parent/'assets/ArmA_source.FCStd'
    arm=App.openDocument(str(arm_path));source=m.floor.robot.load(m.floor.assembly.validate_reference(s['arm_source']))
    reference=m.floor.robot.forward(source,geo.angles(arm));local=[]
    for obj in geo.features(arm):
        if getattr(obj,'ModelRole','')=='viewing_cone':continue
        shape=moved(geo.world_shape(obj),m.floor.robot.inverse(reference[obj.RigidLink]))
        local.append((obj.SourceBody,obj.RigidLink,shape))
    records=[];original=[]
    for obj in geo.features(doc):
        identity=getattr(obj,'LayoutInstance','');name=getattr(obj,'OriginalBody',obj.SourceBody);shape=geo.world_shape(obj)
        original.append((identity,name,shape))
        if identity in ('TR01','Guides','ArmA','ArmC') or identity in s.get('parked_instances',{}):continue
        if identity in ('RackManual','RackPair') and name=='Tube01':continue
        if identity=='MountArmA':shape.translate(App.Vector(s['actors']['ArmA']['xyz_mm'][0]-3800,0,0))
        kind=5 if identity=='TS01' else 6 if identity=='ArmB' else 4
        if identity=='Room':kind=0 if name=='Floor' else 1 if 'Wall' in name or 'Glazing' in name else 2 if any(t in name for t in ('UpperStorage','IslandCupboard','IslandShelf')) else 3
        records.append((identity+'.'+name,kind,shape))
    for identity,definition in s.get('parked_instances',{}).items():
        ls=m.floor.layout.load(validate_builds=False);item=next(i for i in ls['instances'] if i['id']==identity)
        base=m.floor.layout.matrix(item,m.floor.layout.parameters(ls));fk=m.floor.robot.forward(source,definition['joints_deg'])
        for name,link,shape in local:records.append((identity+'.'+name,6,moved(shape,m.floor.robot.multiply(base,fk[link]))))
    for rack in s['additional_racks']:
        item=next(i for i in m.floor.layout.load(validate_builds=False)['instances'] if i['id']==rack['source_instance'])
        base=m.floor.layout.xyz(item['xyz'],m.floor.layout.parameters(m.floor.layout.load(validate_builds=False)))
        for identity,name,shape in original:
            if identity!=rack['source_instance'] or name=='Tube01':continue
            shape=shape.copy();shape.translate(App.Vector(*[a-b for a,b in zip(rack['xyz_mm'],base)]));records.append((rack['id']+'.'+name,4,shape))
    mount=next(shape for identity,name,shape in original if identity=='MountArmA')
    old=next(i for i in m.floor.layout.load(validate_builds=False)['instances'] if i['id']=='ArmA')
    oldmat=m.floor.layout.matrix(old,m.floor.layout.parameters(m.floor.layout.load(validate_builds=False)))
    # The source support has its origin 65 mm below the arm; no second recipe.
    oldmat[2][3]-=65
    mount_local=moved(mount,m.floor.robot.inverse(oldmat));newbase=s['actors']['ArmDNA']['xyz_mm'][:];newbase[2]-=65
    records.append(('MountArmDNA',4,moved(mount_local,m.pickup.placement(newbase,s['actors']['ArmDNA']['yaw_deg']))))
    actor_data={};actor_shapes={};tool_shapes={};kinematics={}
    links=[link['id'] for link in source['links']]
    for actor_index,actor in enumerate(s['actors']):
        station=next(k for k,v in s['stations'].items() if v['actor']==actor)
        data=program['stations'][station];_,scene,kin=m.actor_source(s,actor);kinematics[actor]=kin;q=data['park_joints_deg'];fk=kin.forward(q);basekind=100+actor_index*20
        actor_data[actor]={'kind':basekind,'station':station,'park':q,'base':kin.base,'frames':kin.frames,'links':links,'open_gap_mm':scene['gripper']['open_gap_mm'],'flange_link':source['flange_reference']['link'],'tool_point':[*kin.flange[:2],kin.flange[2]+kin.length]}
        actor_shapes[actor]=[]
        for name,link,shape in local:
            records.append((actor+'.'+name,basekind+links.index(link),shape));actor_shapes[actor].append((name,link,shape))
        tool_shapes[actor]=[]
        for part in m.pickup.gripper_parts(scene,kin.p):
            shape=primitive(part['shape']);offset={'Tool':0,'FingerLeft':1,'FingerRight':2}[part['group']]
            records.append((actor+'.'+part['id'],basekind+7+offset,shape));tool_shapes[actor].append((part['id'],part['group'],shape))
    active=None;car_shapes=[];car_fixed=[]
    for obj in geo.features(car):
        shape=geo.world_shape(obj);car_shapes.append(shape)
        if obj.SourceBody==s['cargo_slot_body']:active=shape.copy();continue
        kind=8 if obj.SourceBody=='TransportCover' else 7
        records.append(('TR01.'+obj.SourceBody,kind,shape));car_fixed.append((obj.SourceBody,shape))
    assert active is not None
    # Cargo has its own owner transform. Its centre is derived from the tube.
    fs=m.floor.load();spec,p,variant=m.floor.vehicle_source(fs,m.floor.layout.load(validate_builds=False))
    cargo_grip=m.tube_geometry(m.floor.vehicle.expanded(spec,p,variant),s['cargo_slot_body'],s['cargo_grip_offset_from_top_mm'])['grip_mm']
    active.translate(App.Vector(*[-v for v in cargo_grip]));records.append(('ActiveCargo',9,active))
    # Static native composition at park; all dynamic meshes remain link-local.
    static=[]
    for name,kind,shape in records:
        world=shape
        if kind>=100:
            actor=next(a for a,d in actor_data.items() if d['kind']<=kind<d['kind']+20);d=actor_data[actor];kin=kinematics[actor]
            index=kind-d['kind']
            matrix=kin.forward(d['park'])[links[index]] if index<7 else kin.tool(d['park'])
            if index in (8,9):matrix=m.floor.robot.multiply(matrix,m.pickup.placement([(-1 if index==8 else 1)*d['open_gap_mm']/2,0,0],0))
            world=moved(shape,matrix)
        elif kind in (7,8,9):continue
        if name!='Room.Floor':static.append((name,world,check.box(world)))
    full_car=Part.makeCompound(car_shapes);bbox=check.box(full_car);radius=max(math.hypot(x,y) for x in (bbox['min'][0],bbox['max'][0]) for y in (bbox['min'][1],bbox['max'][1]))
    approaches={station:m.approach(s,station,radius) for station in s['stations']}
    print('Native scene ready; checking floor curves',flush=True)
    if args.preview_only:
        prior=json.loads((cad/'shared-build-report.json').read_text())
        if prior['source_sha256']!=definition_sha:raise ValueError('Preview-only requires unchanged workcell source')
        display_only={'scripts/tr01_workcell_player.html','scripts/render_tr01_workcell.py'}
        m.floor.verify({path:digest for path,digest in prior['source_files_sha256'].items() if path not in display_only})
        proof=ROOT/prior['files']['floor_validation']
        if m.floor.robot.digest(proof)!=prior['artifact_sha256']['floor_validation']:raise ValueError('Changed floor proof')
        floor_check=json.loads(proof.read_text())
    else:floor_check=check.validate({**floor_program,'routes':floor_program['routes']+list(approaches.values())},full_car,static,radius,App)
    program['approaches']=approaches;program['floor_routes']=floor_program['routes'];program['actors']=actor_data;program['cargo_grip_local_mm']=cargo_grip
    write(out/'program.json',program)
    # Save independent, source-referenced native inspection scene.
    derived=App.newDocument('TR01_Workcell')
    for name,shape,bounds in static:
        obj=derived.addObject('Part::Feature','Body');obj.Label=name;obj.Shape=shape
    derived.recompute();derived.saveAs(str(cad/'L01_Workcell.FCStd'))
    write(out/'native-floor-clearance.json',floor_check)
    # Meshes are display derivatives only, deliberately smaller than BRep proof.
    vertices=[];groups={}
    for name,kind,shape in records:
        pts,faces=shape.tessellate(8.);cap=16 if kind<100 else 12
        if len(faces)>100:
            b=shape.BoundBox
            preview=Part.makeBox(max(.01,b.XLength),max(.01,b.YLength),max(.01,b.ZLength),App.Vector(b.XMin,b.YMin,b.ZMin))
            pts,faces=preview.tessellate(8.)
        if len(faces)>cap:
            mesh=Mesh.Mesh([[pts[i] for i in face] for face in faces]);mesh.decimate(cap);pts,faces=mesh.Topology
        offset=len(vertices)//3
        for point in pts:vertices.extend(round(float(v)*4) for v in point)
        groups.setdefault(kind,[]).extend(offset+i for face in faces for i in face)
    payload=struct.pack('<II',len(vertices)//3,len(groups))+struct.pack('<'+'h'*len(vertices),*vertices)
    for kind,values in sorted(groups.items()):payload+=struct.pack('<II',kind,len(values))+struct.pack('<'+'I'*len(values),*values)
    mesh=base64.b64encode(gzip.compress(payload,9)).decode()
    # The player needs PVA, source FK and ownership, not lengthy proof tables.
    def compact(curve,public=False):
        points=m.floor.canonical(curve['points']) if public else curve['points']
        return {'duration':curve['duration_s'],'points':[[v['time_s'],v[m.F[0]],v[m.F[1]],v[m.F[2]]] for v in points]}
    display={'mesh':mesh,'actors':actor_data,'definition':s,'cargoGrip':cargo_grip,'stations':floor_program['definition']['stations'],
        'routes':[{**compact(r,True),'id':r['id'],'from':r['from'],'to':r['to']} for r in floor_program['routes']],
        'approaches':{key:compact(r,True) for key,r in approaches.items()},'handoffs':{},'floorChecked':floor_check['passed']}
    for station,data in program['stations'].items():
        display['handoffs'][station]={k:v for k,v in data.items() if k not in ('transfers','tool')}
        if data['kind']=='robot':display['handoffs'][station]['transfers']={direction:{phase:compact(curve) for phase,curve in curves.items()} for direction,curves in data['transfers'].items()}
    write(out/'preview-data.json',display)
    report={'format':'solidcraftbot.tr01-workcell-build/1','source_sha256':definition_sha,'floor_interval_check_passed':floor_check['passed'],
        'arm_dynamics_passed':all(c['no_stop']['passed'] for d in program['stations'].values() if d['kind']=='robot' for t in d['transfers'].values() for c in t.values()),
        'files':{'freecad':'cad/tr01-workcell/L01_Workcell.FCStd','program':'exports/tr01-workcell/program.json','floor_validation':'exports/tr01-workcell/native-floor-clearance.json'},
        'limitations':['FreeCAD composition only; new workcell SolidCraft scene not yet built','No hardware, person detection, drive steering or safety qualification','Arm collision checking must be read separately from floor interval checking']}
    revision='tr01-workcell-'+definition_sha[:12]+'-'+str(time.time_ns())
    revision_cad=ROOT/'cad/generated'/revision;revision_out=ROOT/'exports/generated'/revision
    revision_cad.mkdir();revision_out.mkdir()
    report['revision']=revision
    report['files']['preview_data']='exports/tr01-workcell/preview-data.json'
    report['files']['vehicle']=floor_report['files']['vehicle_file']
    for key,value in list(report['files'].items()):
        path=ROOT/value;destination=(revision_cad if key in ('freecad','vehicle') else revision_out)/path.name
        shutil.copy2(path,destination);report['files'][key]=str(destination.relative_to(ROOT))
    report['artifact_sha256']={key:m.floor.robot.digest(ROOT/path) for key,path in report['files'].items()}
    report['source_files_sha256']={**floor_report['source_files_sha256'],str(m.SOURCE.relative_to(ROOT)):definition_sha,
        **{s[key]['source']:s[key]['source_sha256'] for key in ('layout','floor_motion','arm_source','tool_reference','limits_reference')},
        **{str(path.relative_to(ROOT)):m.floor.robot.digest(path) for path in
            [Path(m.__file__),Path(__file__),Path(m.pickup.__file__),Path(m.sample_motion.__file__),Path(m.validation.__file__),Path(m.floor.motion.__file__),
             arm_path,floor_report_path,ROOT/floor_report['files']['program'],ROOT/floor_report['files']['vehicle_file'],
             ROOT/'scripts/check_tr01_handoffs_freecad.py',ROOT/'scripts/bench_access.py',ROOT/'scripts/tr01_workcell_player.html',ROOT/'scripts/render_tr01_workcell.py']}}
    write(revision_out/'build-report.json',report)
    write(cad/'shared-build-report.json',report);print(json.dumps({**report,'mesh_bytes':len(mesh)}),flush=True)


if __name__=='__main__':
    import build_tr01_workcell_freecad as adapter
    adapter.main()
