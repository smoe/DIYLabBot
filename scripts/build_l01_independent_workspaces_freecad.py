"""Native swept boxes for independently scheduled, source-referenced handoffs.

Each FK midpoint box is inflated by a conservative whole-body speed bound for
its entire time interval. Samples alone never establish workspace containment.
"""
import json, math, sys
from pathlib import Path
import FreeCAD as App
import Part
import l01_fleet_handoffs as serial
from l01_independent_fleet import validate_config
import check_l01_fleet_handoffs_freecad as shared
import check_tr01_floor_motion as check
import build_tr01_workcell_freecad as native
ROOT=serial.ROOT;m=serial.workcell
sys.path.insert(0,str(ROOT/'scripts/freecad'))
import solidcraftbot_freecad as geo
SOURCE=ROOT/'model/l01-independent-fleet.demo.json'

def main():
    config=validate_config(json.loads(SOURCE.read_text()));m.floor.assembly.validate_reference(config['serial_source'])
    compiled=serial.validated();report=json.loads((ROOT/'cad/tr01-workcell/shared-build-report.json').read_text());program=json.loads((ROOT/report['files']['program']).read_text());s=program['definition']
    layout=json.loads((ROOT/'cad/lab-layout-l01/shared-build-report.json').read_text());arm_path=(ROOT/layout['files']['freecad']).parent/'assets/ArmA_source.FCStd'
    car=App.openDocument(str(ROOT/report['files']['vehicle']));shapes=[geo.world_shape(o) for o in geo.features(car)];car_bounds=check.box(Part.makeCompound(shapes));radius=max(math.hypot(p[0],p[1]) for p in shared.corners(car_bounds))
    cargo=next(geo.world_shape(o) for o in geo.features(car) if o.SourceBody==s['cargo_slot_body']);cargo.translate(App.Vector(*[-v for v in program['cargo_grip_local_mm']]));cargo_bounds=check.box(cargo)
    arm=App.openDocument(str(arm_path));source=m.floor.robot.load(m.floor.assembly.validate_reference(s['arm_source']));reference=m.floor.robot.forward(source,geo.angles(arm));local={}
    for o in geo.features(arm):
        if getattr(o,'ModelRole','')=='viewing_cone':continue
        local.setdefault(o.RigidLink,[]).append(check.box(native.moved(geo.world_shape(o),serial.inverse(reference[o.RigidLink]))))
    local={k:shared.bounding_union(v) for k,v in local.items()};jobs={};details=[]
    for station in ('DNA','CF01','QC'):
        data=program['stations'][station];actor=data['actor'];_,scene,kin=m.actor_source(s,actor);parts=m.pickup.gripper_parts(scene,kin.p)
        for part in parts:part['bounds']=check.box(native.primitive(part['shape']))
        anchors=[[row[3] for row in f[:3]] for f in kin.frames];length=sum(math.dist(a,b) for a,b in zip([[0,0,0]]+anchors,anchors))
        # Triangle inequality bounds every link, tool and attached vessel about
        # the base for ALL joint angles. Any point-to-joint radius is <= 2R.
        link_radius=length+max(shared.norm(p) for b in local.values() for p in shared.corners(b))
        tool_radius=max(shared.norm(p) for part in parts for p in shared.corners(part['bounds']))+scene['gripper']['open_gap_mm']/2
        for direction in ('load','unload'):
            boxes=[];intervals=0
            for phase,definition in data['transfers'][direction].items():
                curve=m.floor.motion.Curve(definition['points']);q0=[math.degrees(v) for v in curve.points[0][serial.F[0]]];origin=data['bench_grip_mm'] if direction=='load' else data['car_grip_mm'];attachment=serial.mm(serial.inverse(kin.tool(q0)),serial.placement(origin))
                carried_radius=max(shared.norm(p) for p in shared.corners(shared.moved_box(cargo_bounds,attachment))) if phase=='loaded' else 0
                R=max(link_radius,length+shared.norm(program['actors'][actor]['tool_point'])+max(tool_radius,carried_radius))
                rates=m.floor.motion.bounds(curve)[serial.F[1]]['max_abs'];speed=2*R*sum(rates)
                count=max(1,math.ceil(curve.times[-1]/config['workspace_interval_step_s']));h=curve.times[-1]/count;jaw_travel=scene['gripper']['open_gap_mm']/2;inflation=speed*h/2+jaw_travel+1e-6
                for i in range(count):
                    q=[math.degrees(v) for v in curve.evaluate((i+.5)*h)[serial.F[0]]];fk=kin.forward(q);tool=kin.tool(q);moving=[shared.moved_box(b,fk[link]) for link,b in local.items()]
                    for part in parts:
                        mat=tool
                        if part['group']!='Tool':mat=serial.mm(tool,serial.placement([(-1 if part['group']=='FingerLeft' else 1)*scene['gripper']['open_gap_mm']/2,0,0]))
                        moving.append(shared.moved_box(part['bounds'],mat))
                    if phase=='loaded':moving.append(shared.moved_box(cargo_bounds,serial.mm(tool,attachment)))
                    b=shared.bounding_union(moving);boxes.append({'min':[v-inflation for v in b['min']],'max':[v+inflation for v in b['max']]})
                intervals+=count;details.append({'station':station,'direction':direction,'part':phase,'intervals':count,'speed_upper_mm_s':speed,'interval_inflation_mm':inflation,'arbitrary_jaw_position_displacement_upper_mm':jaw_travel})
            arm_box=shared.bounding_union(boxes)
            curve=m.floor.motion.Curve(m.floor.canonical(program['approaches'][station]['points']));bound=m.floor.extrema(curve)
            car_box={'min':[bound['min'][0]-radius,bound['min'][1]-radius,car_bounds['min'][2]],'max':[bound['max'][0]+radius,bound['max'][1]+radius,car_bounds['max'][2]]}
            jobs[station+':'+direction]={'arm':arm_box,'vehicle':car_box,'box':shared.bounding_union([arm_box,car_box]),'actor':actor,'area':s['stations'][station]['work_area'],'intervals':intervals}
    pins={**compiled['source_files_sha256'],str(SOURCE.relative_to(ROOT)):serial.traffic.local.digest(SOURCE),'scripts/build_l01_independent_workspaces_freecad.py':serial.traffic.local.digest(__file__),'scripts/l01_independent_fleet.py':serial.traffic.local.digest(ROOT/'scripts/l01_independent_fleet.py'),str(arm_path.relative_to(ROOT)):serial.traffic.local.digest(arm_path)}
    pins.update({report['files'][key]:report['artifact_sha256'][key] for key in ('program','vehicle','freecad','arm_validation','floor_validation')})
    result={'passed':True,'jobs':jobs,'details':details,'radius_mm':radius,'car_bounds':car_bounds,'cargo_bounds':cargo_bounds,'source_files_sha256':pins,'method':'Native link/tool/vessel boxes at FK interval midpoints inflated by 2R times analytic PVA joint-velocity bounds times half interval plus the entire half-opening jaw travel (all jaw positions from zero to open); full docking PVA extrema plus full-vehicle radius'}
    (ROOT/'exports/tr01-workcell/independent-workspaces.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'jobs':jobs,'compatible_initial_pairs':{a+' / '+b:check.box_distance(jobs[a+':load']['box'],jobs[b+':load']['box']) for a,b in [('DNA','CF01'),('DNA','QC'),('CF01','QC')]}}),flush=True)
if __name__=='__main__':
    import build_l01_independent_workspaces_freecad as adapter
    adapter.main()
