"""Native pickup-scene snapshots, portable gripper bodies, meshes and collision samples."""
import json
import math
import sys
from pathlib import Path
import FreeCAD as App
import Part
import MeshPart
import centrifuge_robot_pickup as pickup
import centrifuge_model as cf
import robot_spec as robot
sys.path.insert(0,str(cf.ROOT/'scripts/freecad'))
import solidcraftbot_freecad as motion
from persist_station_view import persist


def app_placement(matrix):return App.Placement(App.Matrix(*[v for row in matrix for v in row]))


def build(context):
    scene=pickup.load();data=json.loads((Path(context['out'])/'trajectory.json').read_text());spec=cf.load();p=cf.parameters(spec)
    arm=pickup.arm_source(scene);arm_styles=robot.appearances(arm);cf_meta={b['id']:b for b in cf.expanded(spec,p)['bodies']}
    home=robot.forward(arm);doc=App.newDocument('CF01_RobotPickup');groups={};records=[];meshes=[]
    for key,value in [('SceneSource',str(pickup.SOURCE.relative_to(cf.ROOT))),('SceneSHA256',cf.digest(pickup.SOURCE))]:
        doc.addObject('App::FeaturePython',key).addProperty('App::PropertyString','Value','Source');setattr(doc.getObject(key),'Value',value)

    def add(name,group,shape,color,opacity,role,kind):
        if group not in groups:groups[group]=doc.addObject('App::Part',group.replace('.','_'))
        obj=doc.addObject('Part::Feature',name.replace('.','_'));groups[group].addObject(obj);obj.Shape=shape;obj.Label=name
        for key,value in [('SourceBody',name),('RigidLink',group),('ModelRole',role),('SceneAsset',kind)]:obj.addProperty('App::PropertyString',key,'Source');setattr(obj,key,value)
        records.append((obj,group,kind));mesh=MeshPart.meshFromShape(Shape=shape,LinearDeflection=2.0,AngularDeflection=.5,Relative=False)
        vertices,faces=mesh.Topology
        meshes.append({'id':name,'group':group,'role':role,'asset':kind,'color':color,'opacity':opacity,
            'v':[[round(x,2) for x in v] for v in vertices],'f':[list(t) for t in faces]})
    for kind,path in [('station',context['centrifuge_native']),('arm',context['arm_native'])]:
        native=App.openDocument(path)
        if kind=='arm':
            # Regenerate the native parametric geometry AND anchors together.
            for name,value in scene.get('robot_parameter_overrides_mm',{}).items():setattr(native.ModelParameters,name,value)
            native.recompute()
            for j in arm['joints']:
                anchor=native.getObject('J%d_Anchor'%(arm['joints'].index(j)+1))
                if math.dist(list(anchor.Placement.Base),[robot.evaluate(v,robot.parameters(arm)) for v in j['frame']['origin']])>1e-7:raise AssertionError('Variant joint anchor did not follow shared dimensions')
            native.addObject('App::FeaturePython','SceneVariant').addProperty('App::PropertyString','SourceJSON','Source')
            native.SceneVariant.SourceJSON=json.dumps({'scene_source':str(pickup.SOURCE),'parameter_overrides_mm':scene.get('robot_parameter_overrides_mm',{})})
            native.saveAs(str(Path(context['cad'])/'CF01_LongLink_Arm.FCStd'))
        for obj in motion.features(native):
            name=obj.SourceBody;group=obj.RigidLink;role=getattr(obj,'ModelRole','concept_geometry')
            if role=='viewing_cone':continue
            shape=motion.world_shape(obj)
            if kind=='arm':
                shape.Placement=app_placement(robot.inverse(home[group])).multiply(shape.Placement)
                color,opacity=motion.source_color(arm_styles,name,group);color='#'+''.join('%02x'%round(v*255) for v in color)
                name='Arm.'+name;group='Arm.'+group
            else:color=cf_meta[name]['appearance']['color'];opacity=cf_meta[name]['appearance']['opacity']
            add(name,group,shape,color,opacity,role,kind)
        App.closeDocument(native.Name)
    for b in pickup.gripper_parts(scene,p):
        s=b['shape'];shape=Part.makeBox(*s['size'],App.Vector(*s['origin'])) if s['kind']=='box' else Part.makeCylinder(s['radius'],s['height'],App.Vector(*s['origin']))
        add(b['id'],b['group'],shape,'#d5a03a',1,b['role'],'gripper')
    def primitive(s):
        if s['kind']=='box':return Part.makeBox(*s['size'],App.Vector(*s['origin']))
        if s['kind']=='cone':return Part.makeCone(s['radius'],s['top_radius'],s['height'],App.Vector(*s['origin']))
        return Part.makeCylinder(s['radius'],s['height'],App.Vector(*s['origin']))
    for b in pickup.rack_geometry(scene,p)['parts']:
        shape=primitive(b['shape'])
        for cut in b['cuts']:shape=shape.cut(primitive(cut))
        add(b['id'],b['group'],shape,'#61b99a',1,b['role'],'rack')
    bench=scene['bench_surface']
    appearance=pickup.workspace.load(pickup.assembly.validate_reference(scene['environment']))['bench']['bodies'][0]['appearance']
    add('BenchSurface','Scene',Part.makeBox(*bench['size_mm'],App.Vector(*bench['origin_mm'])),appearance['color'],appearance['opacity'],bench['role'],'bench')
    doc.recompute()
    mesh={'bodies':meshes,'robot_joints':arm['joints'],'robot_parameters':robot.parameters(arm),'robot_flange':pickup.Kinematics(arm,scene).flange,
        'station_joints':cf.expanded(spec,p)['joints'],'scene':scene,'trajectory':data,
        'source_hashes':context['source_hashes'],'parameters':p}
    (Path(context['out'])/'scene-mesh.json').write_text(json.dumps(mesh,separators=(',',':')),encoding='utf-8')
    # Snapshot states are generated from the exact same group transforms as playback.
    snapshots=[]
    for time_s,label in [(0,'Closed'),(21.5,'Grasp'),(24.5,'Extracted'),(29.5,'Withdrawn'),(42,'ClosedAfterPickup'),(55,'RackSeated'),(60,'RackReleased')]:
        sample=pickup.interpolate(data['samples'],time_s);matrices=pickup.matrices(scene,data,sample)
        for name,group in groups.items():group.Placement=app_placement(matrices[name])
        doc.recompute();filename=Path(context['cad'])/('CF01_Robot_'+label+'.FCStd');doc.saveAs(str(filename))
        parts=[]
        # STEP snapshots preserve body IDs in both CAD backends without inventing a second design source.
        export=App.newDocument('Snapshot_'+label)
        for old,group,kind in records:
            target=export.addObject('Part::Feature',old.SourceBody.replace('.','_'));target.Label=old.SourceBody.replace('.','_');target.Shape=motion.world_shape(old);parts.append(target)
        step=Path(context['out'])/(label+'.step')
        import Import
        Import.export(parts,str(step));App.closeDocument(export.Name)
        geometry=[{'body':o.SourceBody,'bbox':{'min':[motion.world_shape(o).BoundBox.XMin,motion.world_shape(o).BoundBox.YMin,motion.world_shape(o).BoundBox.ZMin],
            'max':[motion.world_shape(o).BoundBox.XMax,motion.world_shape(o).BoundBox.YMax,motion.world_shape(o).BoundBox.ZMax]}} for o,_,_ in records]
        persist(filename,{'bodies':[{'id':m['id'],'appearance':{'color':m['color'],'opacity':m['opacity']}} for m in meshes]},geometry)
        snapshots.append({'id':label,'time_s':time_s,'freecad':str(filename),'step':str(step)})
    cf.write(Path(context['out'])/'scene-snapshots.json',snapshots)
    # Exact BRep intersections across robot/tool and centrifuge, plus carried tube.
    checks=[]
    times=sorted(set([0,11.5,14.5,17.5,20.5,21.5,22.5,24.5,26.5,28.5,29.5,30.5,33,36,39,41,42]))
    for time_s in times:
        sample=pickup.interpolate(data['samples'],time_s);matrices=pickup.matrices(scene,data,sample)
        for name,group in groups.items():group.Placement=app_placement(matrices[name])
        doc.recompute();shapes=[(o,group,kind,motion.world_shape(o)) for o,group,kind in records];collisions=[]
        station=[a for a in shapes if a[2]=='station'];moving=[a for a in shapes if a[2] in ('arm','gripper')]
        for a,ag,ak,ash in moving:
            for b,bg,bk,bsh in station:
                if b.SourceBody in ('Tube01','ClosedCap01') and ak=='gripper':continue # Intended grasp contacts; separate continuity/clearance checks.
                if not ash.BoundBox.intersect(bsh.BoundBox):continue
                volume=ash.common(bsh).Volume
                if volume>1e-3:collisions.append({'a':a.SourceBody,'b':b.SourceBody,'volume_mm3':volume})
        if time_s>=scene['checks']['attachment_time_s']:
            tubes=[a for a in station if a[0].SourceBody in ('Tube01','ClosedCap01')]
            fixed=[a for a in station if a[0].SourceBody not in ('Tube01','ClosedCap01')]
            for a,_,_,ash in tubes:
                for b,_,_,bsh in fixed:
                    if not ash.BoundBox.intersect(bsh.BoundBox):continue
                    volume=ash.common(bsh).Volume
                    if volume>1e-3:collisions.append({'a':a.SourceBody,'b':b.SourceBody,'volume_mm3':volume})
        checks.append({'time_s':time_s,'collisions':collisions,'passed':not collisions});print(json.dumps(checks[-1]),flush=True)
    cf.write(Path(context['out'])/'native-scene-validation.json',{'passed':all(c['passed'] for c in checks),'samples':checks,'bodies':len(meshes),
        'scope':'Exact sampled arm/tool versus station intersections and carried tube versus remaining station; intended pad/tube contact omitted. Not continuous collision or force validation.'})
    App.closeDocument(doc.Name)
    print(json.dumps({'bodies':len(meshes),'triangles':sum(len(m['f']) for m in meshes),'mesh_bytes':(Path(context['out'])/'scene-mesh.json').stat().st_size}),flush=True)
    if not all(c['passed'] for c in checks):raise AssertionError('Pickup scene has sampled station collisions; inspect native-scene-validation.json')


def main():
    build(json.loads((cf.ROOT/'tmp/cf01-robot-pickup-context.json').read_text()))
    snapshot_metrics()
    additional_validation()


def snapshot_metrics():
    context=json.loads((cf.ROOT/'tmp/cf01-robot-pickup-context.json').read_text());out=Path(context['out']);result={}
    for snapshot in json.loads((out/'scene-snapshots.json').read_text()):
        doc=App.openDocument(snapshot['freecad']);shapes=[motion.world_shape(o) for o in motion.features(doc)]
        volume=sum(s.Volume for s in shapes);center=[sum(sum(sol.CenterOfMass[i]*sol.Volume for sol in s.Solids) for s in shapes)/volume for i in range(3)]
        result[snapshot['id']]={'bodies':len(shapes),'volume_mm3':volume,'center_mm':center,'valid':all(s.isValid() for s in shapes)};App.closeDocument(doc.Name)
    cf.write(out/'snapshot-metrics.json',result)


def additional_validation():
    context=json.loads((cf.ROOT/'tmp/cf01-robot-pickup-context.json').read_text());out=Path(context['out']);arm=robot.load();indices={'Arm.'+l['id']:i for i,l in enumerate(arm['links'])};checks=[]
    for snapshot in json.loads((out/'scene-snapshots.json').read_text()):
        doc=App.openDocument(snapshot['freecad']);items=[(o,motion.world_shape(o)) for o in motion.features(doc)];collisions=[]
        for i,(a,ash) in enumerate(items):
            for b,bsh in items[i+1:]:
                aa,bb=a.SceneAsset,b.SceneAsset
                pair=(aa=='arm' and bb=='arm' and abs(indices[a.RigidLink]-indices[b.RigidLink])>1)
                pair=pair or ({aa,bb}=={'arm','gripper'} and (a.RigidLink if aa=='arm' else b.RigidLink)!='Arm.L6_BareFlange')
                if {aa,bb}=={'station','gripper'}:
                    tube=a if aa=='station' else b;finger=a if aa=='gripper' else b
                    pair=tube.SourceBody=='ClosedCap01' or (tube.SourceBody=='Tube01' and finger.SourceBody not in ('LeftFingerPad','RightFingerPad'))
                if not pair or not ash.BoundBox.intersect(bsh.BoundBox):continue
                volume=ash.common(bsh).Volume
                if volume>1e-3:collisions.append({'a':a.SourceBody,'b':b.SourceBody,'volume_mm3':volume})
        checks.append({'phase':snapshot['id'],'passed':not collisions,'collisions':collisions});print(json.dumps(checks[-1]),flush=True);App.closeDocument(doc.Name)
    cf.write(out/'native-self-and-grip-validation.json',{'passed':all(c['passed'] for c in checks),'samples':checks,
        'scope':'Five native snapshots: non-adjacent arm links, gripper versus arm except mounting link, and cap/non-pad tube clearance. Intended tube/pad contacts omitted.'})
    if not all(c['passed'] for c in checks):raise AssertionError('Pickup scene has sampled self/gripper collisions')


if __name__=='__main__':
    import build_centrifuge_robot_pickup_freecad as backend
    backend.main()
