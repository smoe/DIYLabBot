"""Mount the shared TR01 camera kit on the covered Lab 3.003 instance."""
import json
import math

import check_tr01_floor_motion as clearance
import export_building_walkthrough_freecad as mesh
import robot_components
import robot_spec as robot
import tr01_camera_model as kit


def native_camera(lab, device, physical, truck, proof, stock):
    import FreeCAD as App
    import Part
    from build_synthetic_lab_scene_freecad import primitive
    from check_walkthrough_robot_native import placed
    from solidcraftbot_freecad import world_shape

    spec = kit.load()
    source = kit.expanded(spec)
    styles = {body['id']: body for body in source['bodies']
              if body['role'] in {'camera_envelope', 'camera_mount'}}
    pieces = {op['body']: primitive(op['shape']) for op in source['operations'] if op['body'] in styles}
    mount = device['bound_pose']
    mounted = {name: placed(shape, mount) for name, shape in pieces.items()}
    truck_shapes = {obj.Label: world_shape(obj) for obj in truck.values()}
    for name, shape in mounted.items():
        for label, other in truck_shapes.items():
            if clearance.box_distance(clearance.box(shape), clearance.box(other)) == 0:
                if shape.common(other).Volume > 1e-7:
                    raise ValueError(f'Camera body {name} intersects {label}')

    required = (set(proof['native_collision_clearance']['physical_obstacles']) |
                set(proof['native_vertical_separations_mm']) | {'Lab3003_Floor'})
    obstacles = {name: world_shape(physical[name]) for name in required & physical.keys()}
    missing = required - obstacles.keys()
    if missing:
        validation = mesh.project_path(stock['files']['freecad_validation'])
        if mesh.digest(validation) != stock['artifact_sha256']['freecad_validation']:
            raise ValueError('Changed native building geometry report')
        bounds = json.loads(validation.read_text())
        if not bounds['passed']:
            raise ValueError('Checked building obstacle bounds required')
        world_to_room = robot.inverse(lab['transform'])
        for item in bounds['geometry']:
            name = item['body']
            if name not in missing:
                continue
            lo, hi = (item['bbox'][key] for key in ('min', 'max'))
            obstacles[name] = placed(Part.makeBox(*(b-a for a,b in zip(lo, hi)), App.Vector(*lo)), world_to_room)
    if obstacles.keys() != required:
        raise ValueError('Missing camera collision obstacles: ' + ', '.join(sorted(required-obstacles.keys())))

    camera = Part.makeCompound(list(pieces.values()))
    radii = clearance.box(camera)
    radius = max(math.hypot(x, y) for x in (radii['min'][0], radii['max'][0])
                 for y in (radii['min'][1], radii['max'][1]))
    program = json.loads(mesh.project_path(proof['motion_program']['file']).read_text())
    checked = clearance.validate(program, camera,
        [(name, shape, clearance.box(shape)) for name, shape in sorted(obstacles.items())], radius, App)
    if not checked['passed']:
        raise ValueError('The added TR01 camera did not retain the checked route clearance')
    report = {
        'passed': True, 'scope': 'Additional camera-kit solids over the complete covered TR01 route.',
        'minimum_certified_clearance_mm': checked['routes'][0]['minimum_certified_clearance_mm'],
        'obstacle_count': len(obstacles), 'source_sha256': mesh.digest(kit.SOURCE),
        'checked_intervals': len(checked['routes'][0]['leaves']),
    }
    bodies = {device['body_prefix'] + name: (shape, styles[name]) for name, shape in mounted.items()}
    camera_frame = source['camera_frame']
    view = spec['camera']['view']
    frame = {**camera_frame, 'lens_body_id': device['body_prefix'] + spec['camera']['id'] + '_Lens',
             'range_mm': robot.evaluate(view['range_mm'], source['parameters']),
             'far_radius_mm': robot.evaluate(view['far_radius_mm'], source['parameters'])}
    return bodies, frame, report


def assign_monitor(wall, lab, device, frame):
    """Use the mounted lens as a pose owner for a synthetic live feed."""
    identity = lab['id'] + '.' + device['id']
    entry, = (camera for camera in wall['cameras'] if camera['device_id'] == identity)
    settings = wall['settings']
    width, height = settings['resolution_px']
    world = device['world_pose']
    origin = frame['origin_mm']
    _, down, axis = robot_components.axes(frame)
    up = [-value for value in down]
    camera_id = identity + '.' + frame['id'].removesuffix('.Optical')
    entry.update(
        id=camera_id, label='TR01 · Bordkamera', kind='modeled_camera',
        availability='available', reason=None,
        origin_label='Mitfahrende Modellkamera / synthetisches Livebild',
        eye_mm=robot.transform(world, origin),
        target_mm=robot.transform(world, [x + u * frame['range_mm'] for x, u in zip(origin, axis)]),
        up=[sum(world[i][j]*up[j] for j in range(3)) for i in range(3)],
        near_mm=settings['near_mm'], far_mm=settings['modeled_far_mm'],
        fov_y_deg=math.degrees(2*math.atan(frame['far_radius_mm']/frame['range_mm']/math.hypot(1, width/height))),
        mount_body_id=frame['lens_body_id'],
    )
    defaults = list(wall['default_assignments'])
    defaults[-1] = defaults[0]
    defaults[0] = camera_id
    wall['default_assignments'] = defaults
    return {'camera_id': camera_id, 'monitor_id': wall['monitors'][0]['id']}
