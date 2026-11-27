"""Check the covered TR01 half-turn and its folded ArmC fixture with native solids."""

import argparse
import math
from pathlib import Path
import sys

import check_tr01_floor_motion as clearance
import centrifuge_robot_pickup as pickup
import export_building_walkthrough_freecad as mesh
import lab3003_armc_variant as variant
import lab3003_tr01_return_lap as lap
import robot_spec as robot
import tr01_camera_model as camera
import tr01_floor_motion as tr01
import tr01_workcell


ROOT = robot.ROOT


def floor_support(curve, floor, wheels, app, part):
    radius = native_radius(shape for _, shape in wheels)
    faces = [face for face in floor.Faces
             if max(abs(face.BoundBox.ZMin), abs(face.BoundBox.ZMax)) < 1e-6]
    if not faces or not wheels:
        raise ValueError('The inspected lab floor and native TR01 wheels are required')
    native_top = part.makeCompound(faces)
    max_missing = 0.
    for start, end in zip(curve.times, curve.times[1:]):
        bounds = tr01.extrema(curve, start, end)
        x0, y0 = [value-radius for value in bounds['min'][:2]]
        x1, y1 = [value+radius for value in bounds['max'][:2]]
        rectangle = [app.Vector(x, y, 0.) for x, y in ((x0,y0), (x1,y0), (x1,y1), (x0,y1), (x0,y0))]
        max_missing = max(max_missing, part.Face(part.makePolygon(rectangle)).cut(native_top).Area)
    return {'passed': max_missing <= 1e-5, 'maximum_uncovered_mm2': max_missing,
            'intervals': len(curve.segments), 'wheel_sweep_radius_mm': radius,
            'method': 'native floor contains each entire XY interval expanded by the wheel rotation radius'}


def native_radius(shapes):
    return max(math.hypot(x, y) for shape in shapes for bounds in (clearance.box(shape),)
               for x in (bounds['min'][0], bounds['max'][0])
               for y in (bounds['min'][1], bounds['max'][1]))


def native_obstacles(physical, certificate, bounding_report, building_root, lab, app, part, placed):
    report = lap.read(bounding_report)
    path = building_root / report['files']['freecad_validation']
    if not report['freecad_checks_passed'] or report['artifact_sha256']['freecad'] != certificate['native_stock_sha256']:
        raise ValueError('Building bounds must come from the same original checked native stock')
    lap.verify_reference(path, report['artifact_sha256']['freecad_validation'])
    data = lap.read(path)
    if data['passed'] is not True:
        raise ValueError('Native building bounds must pass their original checks')
    all_names = (set(certificate['native_collision_clearance']['physical_obstacles'])
                 | set(certificate['native_vertical_separations_mm']))
    names = {name for name in all_names if not name.startswith('Lab3003_ArmC_')}
    native = {name: shape for name, shape in physical.items() if name in names}
    inverse = robot.inverse(lab['transform'])
    for item in data['geometry']:
        name = item['body']
        if name not in names-native.keys():
            continue
        lo, hi = (item['bbox'][key] for key in ('min', 'max'))
        native[name] = placed(part.makeBox(*(b-a for a,b in zip(lo,hi)), app.Vector(*lo)), inverse)
    if native.keys() != names:
        raise ValueError('Missing original collision bodies: '+', '.join(sorted(names-native.keys())))
    return native, path


def arm_at_home(lab, arm_report, home, gap, app, native, primitive, placed):
    arm = variant.bind(lab)
    report, files = variant.read_native(arm_report, arm)
    doc = app.openDocument(str(files['freecad']))
    try:
        current = robot.forward(arm['arm'], home)
        original = robot.forward(arm['arm'], arm['park_joints_deg'])
        correction = {
            link: robot.multiply(arm['bound_pose'], robot.multiply(current[link], robot.inverse(original[link])))
            for link in current
        }
        bodies = {}
        for obj in native.features(doc):
            name = obj.SourceBody
            if name not in report['body_metadata']:
                continue
            bodies['ArmC.'+name] = placed(native.world_shape(obj), correction[obj.RigidLink])
        if {name.removeprefix('ArmC.') for name in bodies} != report['body_metadata'].keys():
            raise ValueError('Complete ArmC native solids are required for the driving fixture')
    finally:
        app.closeDocument(doc.Name)
    scene = pickup.load()
    base = arm['bound_pose']
    scene['arm_fixture'].update(position_mm=[row[3] for row in base[:3]],
                                yaw_deg=math.degrees(math.atan2(base[1][0],base[0][0])))
    kinematics = pickup.Kinematics(arm['arm'], scene)
    if len(home) != 6 or not all(lo <= q <= hi for q,(lo,hi) in zip(home,kinematics.limits)):
        raise ValueError('The driving fixture requires an in-range ArmC home')
    if not 0 < gap <= scene['gripper']['open_gap_mm']:
        raise ValueError('The driving fixture requires a valid gripper gap')
    frame = kinematics.tool(home)
    for item in pickup.gripper_parts(scene, {}):
        factor = {'Tool': 0., 'FingerLeft': -.5, 'FingerRight': .5}[item['group']]
        joint = pickup.placement([gap*factor, 0., 0.], 0.)
        bodies['ArmC.Tool.'+item['id']] = placed(primitive(item['shape']), robot.multiply(frame,joint))
    return bodies, report, files


def check_sweep(curve, moving, obstacles, radius, settings, app):
    import numpy as np

    def bounds(shapes):
        return np.array([[box[k] for k in ('min', 'max')]
                         for shape in shapes for box in (clearance.box(shape),)])

    components = [solid for shape in moving for solid in shape.Solids]
    mobile = bounds(components)
    centres = mobile.mean(axis=1)
    extents = (mobile[:,1]-mobile[:,0])/2
    names, shapes = zip(*sorted(obstacles.items()))
    fixed = bounds(shapes)
    margin, tolerance = (settings[k] for k in ('minimum_clearance_mm', 'distance_tolerance_mm'))
    queries = 0
    intervals = []
    failures = []

    def visit(start, end, depth):
        nonlocal queries
        shift, pose = clearance.displacement(curve,start,end,radius)
        c,s = math.cos(pose[2]), math.sin(pose[2])
        rotation = np.array([[c,s,0.], [-s,c,0.], [0.,0.,1.]])
        position = centres@rotation+[pose[0],pose[1],0.]
        half = extents@np.abs(rotation)
        low, high = position-half, position+half
        detail = np.linalg.norm(np.maximum(0.,np.maximum(fixed[None,:,0]-high[:,None],
                                                       low[:,None]-fixed[None,:,1])),axis=2)
        threshold = margin+shift+tolerance
        local = {}
        for first,second in np.argwhere(detail<threshold):
            if first not in local:
                local[first] = components[first].copy()
                frame = app.Placement(app.Vector(pose[0],pose[1],0.),
                                      app.Rotation(app.Vector(0.,0.,1.),math.degrees(pose[2])))
                local[first].Placement = frame.multiply(local[first].Placement)
            distance = local[first].distToShape(shapes[second])[0]
            queries += 1
            if distance-tolerance < margin:
                failures.append({'time_s': (start+end)/2, 'body': names[second],
                                 'native_distance_mm': distance})
                return
            detail[first,second] = distance
        first, second = np.unravel_index(np.argmin(detail),detail.shape)
        lower = float(detail[first,second]-shift-tolerance)
        if lower >= margin:
            intervals.append({'start_s': start, 'end_s': end, 'minimum_clearance_mm': lower,
                              'limiting_body': names[second]})
        elif depth >= settings['maximum_depth'] or end-start <= settings['minimum_interval_s']:
            failures.append({'start_s': start, 'end_s': end, 'body': names[second], 'unresolved_lower_mm': lower})
        else:
            middle = (start+end)/2
            visit(start,middle,depth+1)
            if not failures:
                visit(middle,end,depth+1)

    for start,end in zip(curve.times,curve.times[1:]):
        visit(start,end,0)
        if failures:
            break
    return {'passed': not failures, 'intervals': intervals, 'failures': failures,
            'native_distance_queries': queries, 'obstacle_count': len(obstacles)}


def verify(args):
    import FreeCAD as app
    import Part as part
    sys.path.insert(0,str(ROOT/'scripts/freecad'))
    import solidcraftbot_freecad as native
    from build_synthetic_lab_scene_freecad import primitive
    from build_tr01_workcell_freecad import moved as placed

    payload, stock, cert, _ = lap.checked_baseline(args.stock_preview,args.baseline_certificate)
    if cert['required_clearance_mm'] != lap.LAYOUT_CLEARANCE_MM:
        raise ValueError('The prior physical clearance threshold is binding')
    program = lap.read(args.program)
    recipe = lap.compile_lap(args.stock_preview,args.baseline_certificate)
    if any(program[key] != recipe[key] for key in ('format','definition','routes','stock_html_sha256',
                                                   'baseline_certificate_sha256','source_files_sha256')):
        raise ValueError('Selected half-turn differs from the deterministic covered TR01 lap')
    lab, = (room for room in payload['laboratories'] if room['id']=='Lab3003')
    device, = (item for item in lab['device_instances'] if item['id']=='TR01')
    arm_program_sha256 = lap.digest(args.arm_program)
    home, gap = lap.parked_arm(args.arm_program)
    arm, arm_report, arm_files = arm_at_home(lab,args.arm_report,home,gap,app,native,primitive,placed)
    if arm_report['stock_html_sha256'] != stock['html_sha256']:
        raise ValueError('Parked arm geometry uses a different checked building fixture')
    print('Checking covered TR01 against the new ArmC home',flush=True)
    dock_file = Path(cert['native_model']['file'])
    doc = app.openDocument(str(dock_file))
    try:
        physical = {obj.Label: native.world_shape(obj)
                    for obj in doc.Objects if obj.TypeId=='Part::Feature'}
        inverse = robot.inverse(device['bound_pose'])
        truck = [(name.removeprefix('TR01_'),placed(shape,inverse))
                 for name,shape in physical.items() if name.startswith('TR01_')]
        if len(truck) != 57 or not any(name=='TransportCover' for name,_ in truck):
            raise ValueError('The route requires all loaded TR01 solids and transport cover')
        camera_source = camera.expanded(camera.load())
        camera_ids = {item['id'] for item in camera_source['bodies']
                      if item['role'] in {'camera_envelope','camera_mount'}}
        if stock['onboard_camera']['passed'] is not True or stock['onboard_camera']['source_sha256'] != lap.digest(camera.SOURCE):
            raise ValueError('The original covered lap needs its exact checked camera kit')
        moving = [shape for _,shape in truck] + [primitive(op['shape']) for op in camera_source['operations']
                                                   if op['body'] in camera_ids]
        radius = native_radius(moving)
        obstacles, bounds_path = native_obstacles(physical,cert,args.building_report,args.building_root,
                                                  lab,app,part,placed)
        route, = program['routes']
        curve = tr01.motion.Curve(tr01.canonical(route['points']))
        support = floor_support(curve,physical['Lab3003_Floor'],
                                [(name,shape) for name,shape in truck if name.startswith('Wheel_')],app,part)
        settings = program['definition']['collision']
        if settings['minimum_clearance_mm'] != lap.LAYOUT_CLEARANCE_MM:
            raise ValueError('The required TR01 native clearance is 15 mm')
        sections = lap._sections(route,program['definition'],radius)
        cutoff = route['half_turn']['start_s']
        first = tr01.motion.Curve([row for row in curve.points if row['time_s']<=cutoff])
        changed = tr01.motion.Curve([row for row in curve.points if row['time_s']>=cutoff])
        same_forward = check_sweep(first,moving,arm,radius,settings,app)
        print('New folded fixture forward clearance:',same_forward['passed'],
              'distance queries',same_forward['native_distance_queries'],flush=True)
        new_heading = check_sweep(changed,moving,{**obstacles,**arm},radius,settings,app)
        print('Half-turn and opposite dock clearance:',new_heading['passed'],
              'distance queries',new_heading['native_distance_queries'],flush=True)
        queries = [same_forward,new_heading]
    finally:
        app.closeDocument(doc.Name)

    checks = cert['native_collision_clearance']['routes'][0]['leaves']
    after = [row['minimum_clearance_mm'] for proof in queries for row in proof['intervals']]
    before = [row['clearance_lower_bound_mm'] for row in checks if row['end_s']<=cutoff]
    if not before:
        raise ValueError('Original forward clearance evidence is missing')
    minimum = min(*before,*after,stock['onboard_camera']['minimum_certified_clearance_mm'],
                  min(cert['native_vertical_separations_mm'].values()))
    files = [Path(path).resolve() for path in (
        args.stock_preview/'index.html', args.stock_preview/'tr01-preview-report.json',
        args.baseline_certificate, cert['motion_program']['file'],dock_file,
        args.arm_report,*arm_files.values(),args.building_report,bounds_path)]
    source_pins = {**arm_report['source_files_sha256'],**program['source_files_sha256']}
    for path in (Path(__file__).resolve(),Path(clearance.__file__).resolve(),camera.SOURCE,
                 Path(camera.__file__).resolve(),Path(pickup.__file__).resolve(),
                 Path(tr01_workcell.__file__).resolve(),tr01_workcell.SOURCE):
        source_pins[str(path.relative_to(ROOT))] = lap.digest(path)
    mesh.verify_pins(source_pins)
    lap.verify_reference(args.arm_program, arm_program_sha256)
    return {
        'format': lap.RECEIPT_FORMAT,
        'passed': support['passed'] and all(proof['passed'] for proof in queries),
        'program_sha256': lap.digest(args.program),
        'stock_html_sha256': stock['html_sha256'],
        'arm_program_sha256': arm_program_sha256,
        'home_joints_deg': home,
        'parked_jaw_gap_mm': gap,
        'minimum_certified_clearance_mm': minimum,
        'native_inputs_sha256': {str(path):lap.digest(path) for path in files},
        'source_files_sha256': source_pins,
        'floor_support': support,
        'section_dynamics': sections,
        'native_collision_clearance': {
            'passed': all(proof['passed'] for proof in queries),
            'same_forward_with_new_arm': same_forward,
            'half_turn_and_opposite_heading': new_heading,
            'unchanged_forward_baseline_certificate_sha256': program['baseline_certificate_sha256'],
        },
        'scope': 'Native covered TR01, actual camera and folded ArmC with open gripper;'
                 ' same checked lab fixtures, closed CF01, no people or drive qualification.',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('stock-preview','baseline-certificate','program','arm-program','arm-report',
                 'building-report','building-root','out'):
        parser.add_argument('--'+name,type=Path,required=True)
    args = parser.parse_args()
    result = verify(args)
    lap.write(args.out,result)
    if not result['passed']:
        raise SystemExit('Covered TR01 return lap did not pass all native checks; see '+str(args.out))
    print(args.out,flush=True)


if __name__=='__main__':
    main()
