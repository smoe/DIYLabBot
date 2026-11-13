"""Discrete native BRep inspection of the actual exported six-axis PVA paths.

No continuous arm collision or human-safety certificate is inferred.
"""
import FreeCAD as App
import Part
import sys,json,math
from pathlib import Path
import tr01_workcell as m
import build_tr01_workcell_freecad as native
import check_tr01_floor_motion as floor_check
from build_extraction_kit_station import write
sys.path.insert(0,str(m.ROOT/'scripts/freecad'))
import solidcraftbot_freecad as geo


def main():
    root=m.ROOT;s=m.load();build=json.loads((root/'cad/tr01-workcell/shared-build-report.json').read_text())
    m.floor.verify(build['source_files_sha256'])
    for key in ('program','freecad','vehicle'):
        if m.floor.robot.digest(root/build['files'][key])!=build['artifact_sha256'][key]:raise ValueError('Changed workcell artifact: '+key)
    program=json.loads((root/build['files']['program']).read_text())
    if program['workcell_sha256']!=m.floor.robot.digest(m.SOURCE):raise ValueError('Stale workcell program')
    layout=json.loads((root/'cad/lab-layout-l01/shared-build-report.json').read_text())
    arm=App.openDocument(str((root/layout['files']['freecad']).parent/'assets/ArmA_source.FCStd'))
    source=m.floor.robot.load(m.floor.assembly.validate_reference(s['arm_source']));ref=m.floor.robot.forward(source,geo.angles(arm));local={}
    for obj in geo.features(arm):
        if getattr(obj,'ModelRole','')=='viewing_cone':continue
        local.setdefault(obj.RigidLink,[]).append(native.moved(geo.world_shape(obj),m.floor.robot.inverse(ref[obj.RigidLink])))
    local={link:Part.makeCompound(shapes) for link,shapes in local.items()}
    local_bounds={link:floor_check.box(shape) for link,shape in local.items()}
    def transformed_box(bounds,matrix):
        points=[m.floor.robot.transform(matrix,[x,y,z]) for x in (bounds['min'][0],bounds['max'][0]) for y in (bounds['min'][1],bounds['max'][1]) for z in (bounds['min'][2],bounds['max'][2])]
        return {'min':[min(p[i] for p in points) for i in range(3)],'max':[max(p[i] for p in points) for i in range(3)]}
    doc=App.openDocument(str(root/build['files']['freecad']))
    static=[(o.Label,geo.world_shape(o)) for o in doc.Objects if hasattr(o,'Shape') and not o.Shape.isNull() and '_view_CONE' not in o.Label]
    car=App.openDocument(str(root/build['files']['vehicle']))
    car_shapes=[(o.SourceBody,geo.world_shape(o)) for o in geo.features(car) if o.SourceBody not in ('TransportCover',s['cargo_slot_body'])]
    active=next(geo.world_shape(o) for o in geo.features(car) if o.SourceBody==s['cargo_slot_body'])
    active.translate(App.Vector(*[-v for v in program['cargo_grip_local_mm']]))
    checks=[]
    for station,data in program['stations'].items():
        if data['kind']!='robot':continue
        actor=data['actor'];_,scene,kin=m.actor_source(s,actor);dock=m.pickup.placement(s['stations'][station]['dock_pose_mm_rad'][:2]+[0],math.degrees(s['stations'][station]['dock_pose_mm_rad'][2]))
        obstacles=[(name,shape,floor_check.box(shape)) for name,shape in static if not name.startswith(actor+'.')]
        obstacles += [('TR01.'+name,native.moved(shape,dock),floor_check.box(native.moved(shape,dock))) for name,shape in car_shapes]
        parts=m.pickup.gripper_parts(scene,kin.p)
        for part in parts:
            part['native_shape']=native.primitive(part['shape']);part['native_bounds']=floor_check.box(part['native_shape'])
        active_bounds=floor_check.box(active)
        print(station,'native handoff checking',flush=True)
        for direction,transfer in data['transfers'].items():
            for phase,definition in transfer.items():
                curve=m.floor.motion.Curve(definition['points']);times=set(curve.times)
                # Bound joint motion by <= 1 degree per sample interval from
                # polynomial velocity bounds, then also cap tool travel at 5mm.
                bound=m.floor.motion.bounds(curve);rate=max(bound[m.F[1]]['max_abs']);speed=definition['fk_bounds']['velocity_mm_s']
                dt=min(.1,math.radians(1)/max(rate,1e-9),5/max(speed,1e-9))
                count=math.ceil(curve.times[-1]/dt);times.update(curve.times[-1]*i/count for i in range(count+1))
                failures=[];queries=0
                # Check the actual capped vessel against the closed tool,
                # including the cap. Intended contact is tangential, not an
                # exemption for positive-volume penetration into the cap.
                if phase=='loaded':
                    q0=[math.degrees(v) for v in curve.points[0][m.F[0]]];tcp=kin.tool(q0)
                    origin=data['bench_grip_mm'] if direction=='load' else data['car_grip_mm']
                    cargo=native.moved(active,m.pickup.placement(origin,0))
                    for part in parts:
                        matrix=tcp
                        if part['group']!='Tool':matrix=m.floor.robot.multiply(tcp,m.pickup.placement([(-1 if part['group']=='FingerLeft' else 1)*10.8/2,0,0],0))
                        overlap=native.moved(part['native_shape'],matrix).common(cargo).Volume
                        if overlap>1e-3:failures.append({'time_s':0,'moving':part['id'],'obstacle':'ActiveCargo','overlap_mm3':overlap})
                for t in sorted(times):
                    q=[math.degrees(v) for v in curve.evaluate(t)[m.F[0]]];fk=kin.forward(q);tool=kin.tool(q);moving=[]
                    for link,shape in local.items():moving.append((link,shape,fk[link],local_bounds[link]))
                    gap=10.8 if phase=='loaded' else scene['gripper']['open_gap_mm']
                    for part in parts:
                        matrix=tool
                        if part['group']!='Tool':matrix=m.floor.robot.multiply(tool,m.pickup.placement([(-1 if part['group']=='FingerLeft' else 1)*gap/2,0,0],0))
                        moving.append((part['id'],part['native_shape'],matrix,part['native_bounds']))
                    if phase=='loaded':
                        origin=data['bench_grip_mm'] if direction=='load' else data['car_grip_mm']
                        starttool=kin.tool([math.degrees(v) for v in curve.points[0][m.F[0]]])
                        attachment=m.floor.robot.multiply(m.floor.robot.inverse(starttool),m.pickup.placement(origin,0))
                        moving.append(('ActiveCargo',active,m.floor.robot.multiply(tool,attachment),active_bounds))
                    for name,local_shape,matrix,bounds_local in moving:
                        moving_bounds=transformed_box(bounds_local,matrix);shape=None
                        # L0 deliberately bolts onto its own support. That is
                        # the only moving/static contact exclusion.
                        for obstacle,other,bounds in obstacles:
                            if name=='L0_Base' and obstacle=='Mount'+actor:continue
                            if any(moving_bounds['max'][i]<=bounds['min'][i]+1e-6 or bounds['max'][i]<=moving_bounds['min'][i]+1e-6 for i in range(3)):continue
                            if shape is None:shape=native.moved(local_shape,matrix)
                            queries+=1;volume=shape.common(other).Volume
                            if volume>1e-3:failures.append({'time_s':t,'moving':name,'obstacle':obstacle,'overlap_mm3':volume})
                    if failures:break
                result={'station':station,'direction':direction,'phase':phase,'passed':not failures,'sample_count':len(times),'maximum_step_s':dt,'native_intersection_queries':queries,'failures':failures[:15]}
                checks.append(result);print(json.dumps(result),flush=True)
    result={'format':'solidcraftbot.tr01-handoff-clearance/1','passed':all(c['passed'] for c in checks),'checks':checks,
        'scope':'Discrete full native moving arm/tool/carried tube versus other parked arms, stationary devices, racks, adjacent tubes and docked open vehicle; no self-collision or continuous interval clearance certificate',
        'excluded_contacts':['L0_Base to its own Mount support'],
        'source_sha256':program['workcell_sha256']}
    write(root/'exports/tr01-workcell/native-arm-clearance.json',result)
    report=json.loads((root/'cad/tr01-workcell/shared-build-report.json').read_text());report['arm_discrete_collision_passed']=result['passed']
    destination=(root/report['files']['program']).parent/'native-arm-clearance.json';write(destination,result)
    report['files']['arm_validation']=str(destination.relative_to(root));report.setdefault('artifact_sha256',{})['arm_validation']=m.floor.robot.digest(destination)
    write(destination.parent/'build-report.json',report);write(root/'cad/tr01-workcell/shared-build-report.json',report)

if __name__=='__main__':
    import check_tr01_handoffs_freecad as adapter
    adapter.main()
