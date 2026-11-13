"""Conservative added-obstacle certificate for serial fleet arm handoffs.

Original arm/static checks remain discrete. The added cars/cargo are separated
from whole-arm reachable spheres and full-approach swept boxes, without samples.
"""
import FreeCAD as App
import Part
import json,math,sys
from pathlib import Path
import l01_fleet_handoffs as fleet
import check_tr01_floor_motion as check
import build_tr01_workcell_freecad as native
ROOT=fleet.ROOT;m=fleet.workcell
sys.path.insert(0,str(ROOT/'scripts/freecad'))
import solidcraftbot_freecad as geo

def corners(b):return [[x,y,z] for x in (b['min'][0],b['max'][0]) for y in (b['min'][1],b['max'][1]) for z in (b['min'][2],b['max'][2])]
def moved_box(bounds,matrix):
    points=[m.floor.robot.transform(matrix,p) for p in corners(bounds)];return {'min':[min(p[k] for p in points) for k in range(3)],'max':[max(p[k] for p in points) for k in range(3)]}
def norm(p):return math.sqrt(sum(v*v for v in p))
def bounding_union(boxes):return {'min':[min(b['min'][k] for b in boxes) for k in range(3)],'max':[max(b['max'][k] for b in boxes) for k in range(3)]}

def main():
    compiled=fleet.derive();report=compiled['workcell_report'];program=json.loads((ROOT/report['files']['program']).read_text());s=program['definition'];layout=json.loads((ROOT/'cad/lab-layout-l01/shared-build-report.json').read_text());arm_path=(ROOT/layout['files']['freecad']).parent/'assets/ArmA_source.FCStd'
    car=App.openDocument(str(ROOT/report['files']['vehicle']));shapes=[geo.world_shape(o) for o in geo.features(car)];car_bounds=check.box(Part.makeCompound(shapes));radius=max(math.hypot(x,y) for x in (car_bounds['min'][0],car_bounds['max'][0]) for y in (car_bounds['min'][1],car_bounds['max'][1]))
    cargo=next(geo.world_shape(o) for o in geo.features(car) if o.SourceBody==s['cargo_slot_body']);cargo.translate(App.Vector(*[-v for v in program['cargo_grip_local_mm']]));cargo_bounds=check.box(cargo)
    arm=App.openDocument(str(arm_path));source=m.floor.robot.load(m.floor.assembly.validate_reference(s['arm_source']));reference=m.floor.robot.forward(source,geo.angles(arm));links=[v['id'] for v in source['links']];local={}
    for o in geo.features(arm):
        if getattr(o,'ModelRole','')=='viewing_cone':continue
        local.setdefault(o.RigidLink,[]).append(check.box(native.moved(geo.world_shape(o),fleet.inverse(reference[o.RigidLink]))))
    local={name:bounding_union(bounds) for name,bounds in local.items()};actors={}
    for name in program['actors']:
        _,scene,kin=m.actor_source(s,name);anchors=[[row[3] for row in frame[:3]] for frame in kin.frames];prefix=[];distance=0.;previous=[0,0,0]
        for p in anchors:distance+=math.dist(previous,p);prefix.append(distance);previous=p
        link_radius=0.
        for index,link in enumerate(links):
            anchor=[0,0,0] if index==0 else anchors[index-1];distance=0 if index==0 else prefix[index-1]
            link_radius=max(link_radius,distance+max(math.dist(p,anchor) for p in corners(local[link])))
        tip=program['actors'][name]['tool_point'];tip_radius=prefix[-1]+math.dist(tip,anchors[-1]);tool_radius=0.
        for part in m.pickup.gripper_parts(scene,kin.p):
            b=check.box(native.primitive(part['shape']));tool_radius=max(tool_radius,max(norm(p) for p in corners(b))+scene['gripper']['open_gap_mm']/2)
        base=[row[3] for row in kin.base[:3]];actors[name]={'base':base,'link_radius':link_radius,'tip_radius':tip_radius,'tool_radius':tool_radius}
    checks=[];required=m.floor.load()['collision']['minimum_clearance_mm'];ids=[v['id'] for v in compiled['missions']]
    for phase in compiled['phases']:
        if phase['kind'] not in ('dock','arm'):continue
        state=phase['state'];i=ids.index(phase['vehicle']);obstacles=[]
        for j,p in enumerate(state['cars']):
            if j!=i:obstacles.append(('vehicle:'+ids[j],moved_box(car_bounds,fleet.placement([*p[:2],0],p[2]))))
        for j,owner in enumerate(state['owners']):
            if owner['type']=='bench' and (j!=i or phase['kind']=='dock'):obstacles.append(('cargo:'+ids[j],moved_box(cargo_bounds,owner['matrix'])))
            elif j!=i and owner['type']=='arm':raise ValueError('Parallel arm handoffs are outside this certificate')
        if phase['kind']=='dock':
            curve=m.floor.motion.Curve(m.floor.canonical(program['approaches'][phase['curve_ref']]['points']));bound=m.floor.extrema(curve)
            swept={'min':[bound['min'][0]-radius,bound['min'][1]-radius,car_bounds['min'][2]],'max':[bound['max'][0]+radius,bound['max'][1]+radius,car_bounds['max'][2]]}
            method='Full original PVA translation extrema plus orientation-independent full-vehicle radius; reverse has the same geometric set'
        else:
            a=actors[phase['actor']];r=max(a['link_radius'],a['tip_radius']+a['tool_radius']);owner=state['owners'][i]
            if owner['type']=='arm':r=max(r,a['tip_radius']+max(norm(p) for p in corners(moved_box(cargo_bounds,owner['attachment']))))
            swept={'min':[v-r for v in a['base']],'max':[v+r for v in a['base']]};method='All-angle whole-arm workspace bound from successive joint-anchor distances, native link/tool boxes and attached capped vessel'
        distances=[{'obstacle':name,'clearance_lower_mm':check.box_distance(swept,bounds)} for name,bounds in obstacles];passed=all(v['clearance_lower_mm']>=required for v in distances)
        checks.append({'start_s':phase['start_s'],'kind':phase['kind'],'station':phase['station'],'vehicle':phase['vehicle'],'part':phase.get('part'),'passed':passed,'method':method,'swept_box':swept,'distances':distances})
    result={'passed':all(c['passed'] for c in checks),'program_sha256':compiled['program_sha256'],'checker_sha256':fleet.traffic.local.digest(__file__),'native_inputs_sha256':{report['files'][k]:report['artifact_sha256'][k] for k in ('vehicle','program','freecad','arm_validation','floor_validation')},'checks':checks,'summary':{'added_obstacle_checks':len(checks),'minimum_added_obstacle_clearance_mm':min(d['clearance_lower_mm'] for c in checks for d in c['distances']),'required_mm':required,'original_static_arm_proof':'discrete and unchanged; no continuous full-scene arm certificate','added_obstacle_proof':'continuous conservative enclosing boxes, including other waiting vehicles and their bench cargo'}}
    result['native_inputs_sha256'][str(arm_path.relative_to(ROOT))]=fleet.traffic.local.digest(arm_path)
    (ROOT/'exports/tr01-workcell/fleet-handoffs-clearance.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result['summary']));print('passed',result['passed'])
    if not result['passed']:
        print(json.dumps([v for v in checks if not v['passed']],indent=2));raise SystemExit('Additional fleet obstacles are not cleared')
if __name__=='__main__':
    import check_l01_fleet_handoffs_freecad as adapter
    adapter.main()
