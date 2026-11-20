"""Native arm-mounted syringe composition and discrete clearance inspection."""
import argparse
import json
import math
from pathlib import Path
import sys
import time

import FreeCAD as App
import Part

import build_tube_carrier_freecad as primitive_native
from build_arm_syringe import (audit_clearances, bbox_distance, carrier_bodies, checked_arm_cache,
                              canonical_material_core, compare_derived_metrics, digest,
                              guard_pair_groups, merge_clearance_checks, route_derivation_diagnostics,
                              pneumatic_connections, require_hose_self_clearance, write,
                              route_material_checks, clipped_mode,
                              CONTACT_DISTANCE_TOLERANCE_MM, OVERLAP_ZERO_TOLERANCE_MM3)


FREECAD_COLLAR_SEAM_DEG = 135.


def clipped_hose_checks(model, spec, p, state, shapes):
    """Inspect real clip bores, host fits and complete bounded route sections."""
    if not clipped_mode(spec):return None
    import close_hose_clips
    import spatial_hose_carrier as curve
    local = close_hose_clips.expanded(model.arm(spec), p, spec['hose_routing']['clips'])
    path = state['hose_path'];supports = {};tube = shapes['PneumaticHose']
    rotation = lambda matrix, vector: [sum(matrix[i][j]*vector[j] for j in range(3)) for i in range(3)]
    for name, interface in local['support_interfaces'].items():
        matrix = state['part_matrices'][interface['component']]
        world = lambda point: model.robot.transform(matrix, point)
        clip, host = shapes[interface['clip_body']], shapes[interface['host_body']]
        center = interface['center_mm'];axis = interface['axis'];x = interface['x_axis']
        y = [axis[1]*x[2]-axis[2]*x[1], axis[2]*x[0]-axis[0]*x[2], axis[0]*x[1]-axis[1]*x[0]]
        bore = []
        for offset in (-interface['physical_support_length_mm']/4, 0., interface['physical_support_length_mm']/4):
            c = [v+offset*a for v, a in zip(center, axis)]
            for angle in (math.pi/4, 3*math.pi/4, 5*math.pi/4, 7*math.pi/4):
                hose_point = world(radial_point(c, x, y, interface['tube_outer_radius_mm'], angle))
                wall_point = world(radial_point(c, x, y, interface['bore_radius_mm'], angle))
                bore.append({'hose_point_mm': hose_point, 'clip_wall_point_mm': wall_point,
                    'hose_membership_error_mm': point_distance(tube, hose_point),
                    'clip_membership_error_mm': point_distance(clip, wall_point),
                    'native_radial_gap_mm': point_distance(clip, hose_point)})
        fit = interface['host_fit'];host_points = []
        if fit['kind'] == 'cylinder':
            for angle in (math.pi/4, 3*math.pi/4, 5*math.pi/4, 7*math.pi/4):
                host_points.append(radial_point(fit['center_mm'], [1, 0, 0], [0, 1, 0],
                                                fit['source_radius_mm'], angle))
        else:
            origin, size = fit['origin_mm'], fit['size_mm'];end = [a+b for a, b in zip(origin, size)]
            z = center[2]-4 if interface['mount_kind'] == 'plate_edge' else center[2]
            edge = origin[0] if fit['source_edge'] == 'negative_x' else end[0]
            inside = edge+1 if fit['source_edge'] == 'negative_x' else edge-1
            host_points = [[edge, (origin[1]+end[1])/2, z], [inside, origin[1], z], [inside, end[1], z]]
        host_rows = [{'point_mm': world(point),
                      'host_membership_error_mm': point_distance(host, world(point)),
                      'native_clamp_gap_mm': point_distance(clip, world(point))} for point in host_points]
        native_center = curve.path_position(path, path['clip_material_stations_mm'][name])['point_mm']
        expected = state['clip_support_interfaces'][name]
        expected_center = expected['center_mm'];expected_axis = expected.get('axis', expected.get('tangent'))
        frame_error = max(math.dist(world(center), native_center), math.dist(world(center), expected_center),
                          math.dist(rotation(matrix, axis), expected_axis))
        overlaps = {'hose_mm3': abs(clip.common(tube).Volume), 'host_mm3': abs(clip.common(host).Volume)}
        passed = (frame_error <= 1e-7 and max(overlaps.values()) <= OVERLAP_ZERO_TOLERANCE_MM3
            and all(max(row['hose_membership_error_mm'], row['clip_membership_error_mm'],
                        abs(row['native_radial_gap_mm']-interface['radial_clearance_mm'])) <= 1e-6 for row in bore)
            and all(max(row['host_membership_error_mm'],
                        abs(row['native_clamp_gap_mm']-fit['radial_or_face_gap_mm'])) <= 1e-6 for row in host_rows))
        supports[name] = {'passed': passed, 'clip_body': interface['clip_body'], 'host_body': interface['host_body'],
            'component': interface['component'], 'attachment_link': interface['link'],
            'center_mm': world(center), 'frame_error_mm': frame_error,
            'physical_support_length_mm': interface['physical_support_length_mm'],
            'required_hose_gap_mm': interface['radial_clearance_mm'],
            'required_host_gap_mm': fit['radial_or_face_gap_mm'], 'bore_witnesses': bore,
            'host_witnesses': host_rows, 'overlap_volume_mm3': overlaps,
            'material_station_mm': path['clip_material_stations_mm'][name],
            'qualification': interface['qualification']}

    def actual_host_distance(point, names):
        vertex = Part.Vertex(App.Vector(*point));candidates = []
        rejected = []
        for name in names:
            distance, pairs, _ = vertex.distToShape(shapes[name])
            for a, b in pairs:
                pa, pb = point_values(a), point_values(b)
                membership = max(math.dist(pa, point), point_distance(shapes[name], pb))
                measured = math.dist(pa, pb)
                row = {'host_body': name, 'point_mm': point, 'nearest_host_point_mm': pb,
                       'distance_mm': measured, 'native_distance_mm': distance,
                       'witness_membership_error_mm': membership}
                if membership <= 1e-7 and abs(measured-distance) <= 1e-7:candidates.append(row)
                else:rejected.append(row)
        if not candidates:raise ValueError('No valid native host-surface witness for close hose section')
        return min(candidates, key=lambda row: row['distance_mm']), rejected

    fixed, loops = {}, {}
    definitions = {row['id']: row for row in spec['hose_routing']['sections']}
    arm = model.arm(spec);ap = model.robot.parameters(arm);fk = model.robot.forward(arm, state['joints_deg'])
    for section in path['section_records']:
        definition = definitions[section['id']]
        index, count = section['segment_start_index'], section['segment_count']
        offset = sum(row['length_mm'] for row in path['segments'][:index]);length = section['actual_length_mm']
        number = max(1, math.ceil(length/2.));step = length/number
        points = [curve.path_position(path, offset+length*i/number)['point_mm'] for i in range(number+1)]
        if definition['kind'] == 'fixed_link':
            witnesses, rejected = [], []
            for point in points:
                witness, invalid = actual_host_distance(point, definition['host_bodies'])
                witnesses.append(witness);rejected.extend(invalid)
            maximum = max(witnesses, key=lambda row: row['distance_mm']);upper = maximum['distance_mm']+step/2
            fixed[section['id']] = {'passed': upper <= definition['max_offset_mm'],
                'host_bodies': definition['host_bodies'], 'maximum_sampled_distance_mm': maximum['distance_mm'],
                'maximum_distance_upper_bound_mm': upper, 'maximum_allowed_distance_mm': definition['max_offset_mm'],
                'sample_count': len(points), 'maximum_arclength_gap_mm': step, 'worst_witness': maximum,
                'witnesses': witnesses, 'rejected_kernel_witnesses': rejected,
                'scope': 'Native distance to the union of named physical host bodies; 1-Lipschitz interval upper bound'}
        else:
            joint = next(row for row in arm['joints'] if row['id'] == definition['joint'])
            parent = fk[joint['parent']];origin = model.robot.transform(parent,
                [model.robot.evaluate(value, ap) for value in joint['frame']['origin']])
            axis = rotation(parent, joint['frame']['axis']);radial = [];axial = []
            for point in points:
                delta = [a-b for a, b in zip(point, origin)];projection = sum(a*b for a, b in zip(delta, axis))
                axial.append(projection);radial.append(math.sqrt(max(0, sum(v*v for v in delta)-projection**2)))
            radial_upper = max(radial)+step/2;axial_bounds = [min(axial)-step/2, max(axial)+step/2]
            limit = definition['axial_range_mm']
            loops[section['id']] = {'passed': radial_upper <= definition['max_reach_mm']
                and limit[0] <= axial_bounds[0] and axial_bounds[1] <= limit[1],
                'joint': joint['id'], 'joint_origin_mm': origin, 'joint_axis': axis,
                'maximum_sampled_radial_distance_mm': max(radial), 'radial_distance_upper_bound_mm': radial_upper,
                'maximum_radial_reach_mm': definition['max_reach_mm'],
                'sampled_axial_range_mm': [min(axial), max(axial)], 'axial_range_bounds_mm': axial_bounds,
                'allowed_axial_range_mm': limit, 'sample_count': len(points), 'maximum_arclength_gap_mm': step,
                'scope': 'Joint-local radial/axial pocket with 1-Lipschitz interval bounds; named pose only'}
    passed = all(row['passed'] for group in (supports, fixed, loops) for row in group.values())
    return {'passed': passed, 'supports': supports, 'fixed_sections': fixed, 'joint_loops': loops,
        'material_stations_mm': path['clip_material_stations_mm'],
        'section_lengths_mm': {row['id']: row['actual_length_mm'] for row in path['section_records']},
        'scope': 'Native static fit and bounded complete-section routing; clamp closure and non-slip retention are assumptions',
        'qualification': {'axial_retention_verified': False, 'strength_verified': False,
                          'manufacturing_fit_verified': False, 'continuous_motion_verified': False}}


def bounds(shape):
    box = shape.optimalBoundingBox(False, False)
    return {'min': [box.XMin, box.YMin, box.ZMin],
            'max': [box.XMax, box.YMax, box.ZMax]}


def measurement(obj, world_shape):
    shape = world_shape(obj)
    if shape.Volume <= 0:
        raise ValueError('Empty native body: '+obj.SourceBody)
    center = sum((solid.CenterOfMass*solid.Volume for solid in shape.Solids), App.Vector())/shape.Volume
    return {'body': obj.SourceBody, 'group': obj.RigidLink,
            'valid': shape.isValid(), 'solid_count': len(shape.Solids),
            'closed_solids': all(solid.isClosed() for solid in shape.Solids),
            'volume_mm3': shape.Volume,
            'world_center_of_mass_mm': [center.x, center.y, center.z],
            'bbox': bounds(shape)}


def center_of_solids(shape):
    volume = sum(solid.Volume for solid in shape.Solids)
    if volume <= 0:
        raise ValueError('No closed solids in native geometry')
    point = sum((solid.CenterOfMass*solid.Volume for solid in shape.Solids), App.Vector())/volume
    return [point.x, point.y, point.z]


def placement(matrix):
    value = App.Matrix()
    for i in range(4):
        for j in range(4):
            setattr(value, 'A%d%d' % (i+1, j+1), matrix[i][j])
    return App.Placement(value)


def source_shapes(model, spec, p, source, output):
    """Construct new tooling from primitives; copy none of the robot geometry."""
    native_spec = model.cad_spec(spec, p)
    zero = {joint['id']: 0 for joint in source['joints']}

    class Provider:
        ROOT = model.ROOT
        SOURCE = model.SOURCE
        digest = staticmethod(model.digest)
        evaluate = staticmethod(model.evaluate)
        expanded = staticmethod(lambda _spec, _p: source)
        pose = staticmethod(lambda _spec, _p: zero)
        validate_pose = staticmethod(lambda _source, values: None)

    primitive_native.model = Provider
    doc = primitive_native.build(native_spec, p, Path(output))
    for name, definition in native_spec['parameters'].items():
        if definition.get('unit') == 'deg':
            # Direct App::PropertyAngle assignment caps values at 360 degrees;
            # an expression retains the source's multi-turn motor limit.
            doc.ModelParameters.setExpression(name, str(p[name])+' deg')
    doc.recompute()
    doc.save()
    result = {obj.SourceBody: primitive_native.motion.world_shape(obj).copy()
              for obj in primitive_native.objects(doc)}
    App.closeDocument(doc.Name)
    if set(result) != {row['id'] for row in source['bodies']}:
        raise ValueError('Tooling source geometry is incomplete')
    return result


def add_tooling(doc, model, spec, p, source, shapes, state):
    motion = primitive_native.motion
    parameters = doc.addObject('App::FeaturePython', 'SyringeParameters')
    native_spec = model.native_spec(spec, p)
    for name, definition in native_spec['parameters'].items():
        kind = 'App::PropertyAngle' if definition.get('unit') == 'deg' else 'App::PropertyDistance'
        parameters.addProperty(kind, name, 'Shared-source dimensions')
        setattr(parameters, name, p[name])
        if definition.get('unit') == 'deg':
            parameters.setExpression(name, str(p[name])+' deg')
        parameters.setEditorMode(name, 1)
    controller = doc.addObject('App::FeaturePython', 'SyringeController')
    for name, kind, value in [
        ('PumpStroke', 'App::PropertyDistance', state['stroke_mm']),
        ('EffectiveStroke', 'App::PropertyDistance', state['stroke_mm']),
        ('MotorRotation', 'App::PropertyAngle', state['motor_angle_deg']),
        ('IsolationValve', 'App::PropertyAngle', state['valve_angle_deg']),
        ('EffectiveValve', 'App::PropertyAngle', state['valve_angle_deg']),
    ]:
        controller.addProperty(kind, name, 'Syringe CAD state')
        setattr(controller, name, value)
    controller.setExpression('EffectiveStroke',
        'max(0 mm; min(SyringeParameters.strokeFine; PumpStroke))')
    controller.setExpression('MotorRotation',
        '360 deg * EffectiveStroke / SyringeParameters.pitch')
    controller.setExpression('EffectiveValve',
        'max(0 deg; min(SyringeParameters.valveAngle; IsolationValve))')
    for name in ('EffectiveStroke', 'MotorRotation', 'EffectiveValve'):
        controller.setEditorMode(name, 1)
    for name, value in {
        'SourceFile': str(model.SOURCE.relative_to(model.ROOT)),
        'SourceSHA256': model.digest(model.SOURCE),
        'Qualification': 'Unmeasured concept; no dosing accuracy, leakage or perfusion qualification',
        'DimensionEditing': 'Regenerate from the shared source after changing construction dimensions',
        'HoseSnapshot': 'Static geometry for arm joints '+json.dumps(state['joints_deg'])+
                        '; regenerate after arm pose changes',
        'OperatingWindowStatus': spec['operating_window_status'],
        'OperatingWindowDeg': json.dumps(spec['operating_window_deg'], sort_keys=True),
        'CarrierSnapshot': ('No carrier; rigid source-derived split clips follow their host links; hose remains static.'
                            if clipped_mode(spec) else
                            'Static conservative shell and nominal collar compound; no articulated native chain. '
                            'Regenerate with the hose after manual arm edits.'),
        'ClipSupportInterfaces': json.dumps(state.get('clip_support_interfaces'), sort_keys=True),
        'HoseRoutingDesign': json.dumps(state.get('hose_routing_design'), sort_keys=True),
        'ConnectionInterfaces': json.dumps(state['connection_interfaces'], sort_keys=True),
        'TipSeat': json.dumps(state['tip_seat'], sort_keys=True),
    }.items():
        controller.addProperty('App::PropertyString', name, 'Concept qualification')
        setattr(controller, name, value)
        controller.setEditorMode(name, 1)
    groups = {row['id']: doc.addObject('App::Part', row['id']) for row in source['components']}
    arm_world = model.robot.forward(model.arm(spec), state['joints_deg'])
    for group_name, mount in model.mounts(spec, p).items():
        host = doc.getObject(mount['link'])
        if host is None:
            raise ValueError('Native arm attachment link missing: '+mount['link'])
        host.addObject(groups[group_name])
        local = model.robot.multiply(model.robot.inverse(arm_world[mount['link']]),
                                     state['part_matrices'][group_name])
        groups[group_name].Placement = placement(local)
    for joint in source['joints']:
        group = groups[joint['child']]
        parent = groups[joint['parent']]
        if joint['type'] == 'slider':
            parent.addObject(group)
            for axis, scale in zip('xyz', joint['axis']):
                group.setExpression('Placement.Base.'+axis,
                                    f'{scale} * SyringeController.EffectiveStroke')
        else:
            anchor = doc.addObject('App::Part', joint['id']+'_Anchor')
            parent.addObject(anchor)
            frame = motion.frame_placement({'origin': [model.evaluate(v, p) for v in joint['origin']],
                                            'x': joint['reference_x'], 'z': joint['axis']})
            anchor.Placement = frame
            turn = doc.addObject('App::Part', joint['id']+'_Motion')
            anchor.addObject(turn)
            field = 'MotorRotation' if joint['id'] == 'MotorRotation' else 'EffectiveValve'
            turn.setExpression('Placement.Rotation.Angle', 'SyringeController.'+field)
            turn.addObject(group)
            group.Placement = frame.inverse()
    by_id = {row['id']: row for row in source['bodies']}
    for name, shape in shapes.items():
        row = by_id[name]
        obj = doc.addObject('Part::Feature', name)
        groups[row['component']].addObject(obj)
        obj.Shape = shape
        for field, value in [('SourceBody', name), ('RigidLink', row['component']),
                             ('ModelRole', row['role'])]:
            obj.addProperty('App::PropertyString', field, 'Shared source')
            setattr(obj, field, value)
    doc.recompute()
    return groups, controller


def clearance_checks(model, spec, p, arm_meta, own_meta, shapes):
    """Audit only new geometry versus the actual arm and other new links."""
    boxes = {name: bounds(shape) for name, shape in shapes.items()}
    return audit_clearances(arm_meta, own_meta, shapes, model.allowed_contacts(spec, p), boxes)


def add_carrier(doc, state, *, parameterization_report=None):
    import spatial_hose_carrier
    rows = carrier_bodies(state)
    if not rows:
        return None
    group = doc.addObject('App::Part', 'CarrierSnapshot')
    record = state['carrier']
    shapes = {'CarrierEnvelope': spatial_hose_carrier.freecad_envelope(Part, App, record),
              'CarrierLinks': spatial_hose_carrier.freecad_links(Part, App, record)}
    if len(shapes['CarrierLinks'].Solids) != len(record['links']):
        raise ValueError('Native collar coverage differs before parameterization')
    rings, invariants = [], []
    for original, link in zip(shapes['CarrierLinks'].Solids, record['links']):
        ring = original.copy()
        ring.rotate(App.Vector(*link['center_mm']), App.Vector(*link['axis']), FREECAD_COLLAR_SEAM_DEG)
        before, after = bounds(original), bounds(ring)
        invariant = {'id': link['id'], 'volume_difference_mm3': abs(ring.Volume-original.Volume),
            'centroid_difference_mm': ring.CenterOfMass.distanceToPoint(original.CenterOfMass),
            'bounds_difference_mm': max(abs(a-b) for key in ('min', 'max')
                                        for a, b in zip(before[key], after[key])),
            'valid_closed_solid': ring.isValid() and ring.isClosed()}
        invariant['passed'] = invariant['valid_closed_solid'] and max(invariant[key] for key in
            ('volume_difference_mm3', 'centroid_difference_mm', 'bounds_difference_mm')) <= 1e-7
        invariants.append(invariant);rings.append(ring)
    representation = {'passed': len(rings) == record['nominal_link_count']
                                and all(row['passed'] for row in invariants),
        'circular_profile_seam_deg': FREECAD_COLLAR_SEAM_DEG, 'geometry_invariance': invariants,
        'scope': 'Fixed parameterization of axisymmetric annular proxies; physical geometry is unchanged, '
                 'with no articulated-chain or manufacturer-link claim'}
    if not representation['passed']:
        raise ValueError('Native collar parameterization changed physical proxy geometry')
    if parameterization_report is not None:parameterization_report.update(representation)
    shapes['CarrierLinks'] = Part.makeCompound(rings)
    for row in rows:
        obj = doc.addObject('Part::Feature', row['id'])
        group.addObject(obj)
        obj.Shape = shapes[row['id']]
        for key, value in [('SourceBody', row['id']), ('RigidLink', row['component']), ('ModelRole', row['role'])]:
            obj.addProperty('App::PropertyString', key, 'Shared carrier snapshot')
            setattr(obj, key, value)
        if row['id'] == 'CarrierLinks':
            obj.addProperty('App::PropertyAngle', 'CircularProfileSeam', 'Native representation')
            obj.CircularProfileSeam = FREECAD_COLLAR_SEAM_DEG
            obj.setEditorMode('CircularProfileSeam', 1)
    doc.recompute()
    return spatial_hose_carrier.freecad_guard(Part, App, record)


def carrier_checks(state, geometry, shapes, guard, hose_radii, parameterization=None):
    """Check geometric representations separately from the filled reservation."""
    import pneumatic_hose
    record = state['carrier']
    path = record['path']
    length = path['length_mm']
    annular = math.pi*(record['outer_radius_mm']**2-record['inner_radius_mm']**2)*length
    filled = math.pi*record['outer_radius_mm']**2*length
    links_volume = sum(math.pi*(row['outer_radius_mm']**2-row['inner_radius_mm']**2)*row['width_mm']
                       for row in record['links'])
    volume_errors = {'shell': abs(shapes['CarrierEnvelope'].Volume-annular)/annular,
                     'filled_guard': abs(guard.Volume-filled)/filled,
                     'collars': abs(shapes['CarrierLinks'].Volume-links_volume)/links_volume}
    outside = shapes['CarrierLinks'].cut(guard)
    outside_valid = outside.isNull() or outside.isValid()
    outside_volume = 0. if outside.isNull() else outside.Volume
    centerline_material = shapes['CarrierEnvelope'].common(
        pneumatic_hose.freecad_wire(Part, App, path)).Length
    collar_errors = []
    for index, (solid, row) in enumerate(zip(shapes['CarrierLinks'].Solids, record['links'])):
        collar_errors.append({'id': row['id'], 'centroid_error_mm': math.dist(
            [solid.CenterOfMass.x, solid.CenterOfMass.y, solid.CenterOfMass.z], row['center_mm'])})
    counts = {row['id']: row['expected_solid_count'] for row in carrier_bodies(state)}
    valid = all(geometry[name]['valid'] and geometry[name]['closed_solids']
                and geometry[name]['solid_count'] == count for name, count in counts.items())
    ring_margin = record['collar_containment']
    clearance = record['inner_radius_mm']-hose_radii[1]
    distance, solutions, _ = shapes['CarrierLinks'].distToShape(shapes['PneumaticHose'])
    witnesses = [{'collar_point_mm': point_values(a), 'hose_point_mm': point_values(b),
                  'collar_membership_error_mm': shapes['CarrierLinks'].distToShape(Part.Vertex(a))[0],
                  'hose_membership_error_mm': shapes['PneumaticHose'].distToShape(Part.Vertex(b))[0],
                  'separation_error_mm': abs(a.distanceToPoint(b)-distance)} for a, b in solutions]
    common = shapes['CarrierLinks'].common(shapes['PneumaticHose'])
    common_empty = common.isNull() or not (common.Vertexes or common.Edges or common.Faces)
    material_gap = {'passed': distance > CONTACT_DISTANCE_TOLERANCE_MM and bool(witnesses)
                              and all(max(row[key] for key in ('collar_membership_error_mm',
                                  'hose_membership_error_mm', 'separation_error_mm')) <= CONTACT_DISTANCE_TOLERANCE_MM
                                      for row in witnesses) and common_empty,
        'distance_mm': distance, 'witnesses': witnesses, 'common_is_empty': common_empty,
        'common_volume_mm3': 0. if common.isNull() else common.Volume,
        'scope': 'Native collar/full-hose distance with independently verified two-body witness membership; '
                 'no collar contact exemption'}
    passed = (valid and guard.isValid() and len(guard.Solids) == 1
              and max(volume_errors.values()) < 1e-6 and outside_valid and outside_volume <= 1e-5
              and centerline_material < 1e-7 and clearance > 0
              and len(collar_errors) == record['nominal_link_count']
              and max(row['centroid_error_mm'] for row in collar_errors) < 1e-6
              and ring_margin['outer_margin_lower_bound_mm'] > 0
              and ring_margin['inner_margin_lower_bound_mm'] > 0 and material_gap['passed']
              and (parameterization is None or parameterization.get('passed') is True))
    return {'passed': passed, 'expected_solid_counts': counts,
            'nominal_link_count': record['nominal_link_count'], 'nominal_arc_pitch_mm': record['pitch_mm'],
            'minimum_centerline_bend_radius_mm': path['min_bend_radius_mm'],
            'relative_volume_errors': volume_errors,
            'filled_guard': {'valid': guard.isValid(), 'solid_count': len(guard.Solids),
                             'delivered_material_body': False, 'outer_radius_mm': record['outer_radius_mm']},
            'collar_containment': {'native_cut_valid': outside_valid, 'outside_guard_volume_mm3': outside_volume,
                                   'source_local_bounds': ring_margin},
            'collar_pose_checks': collar_errors,
            'collar_parameterization': parameterization,
            'collar_hose_material_gap': material_gap,
            'protected_centerline_shell_material_intersection_mm': centerline_material,
            'assumed_hose_to_inner_envelope_radial_gap_mm': clearance,
            'material_contact_policy': 'Carrier shell/collars are checked against the actual full hose, arm and tooling.',
            'scope': record['scope'], 'qualification': record['qualification']}


def point_values(point):
    return [point.x, point.y, point.z]


def point_distance(shape, point):
    return shape.distToShape(Part.Vertex(App.Vector(*point)))[0]


def radial_point(center, x, y, radius, angle):
    return [v+radius*(math.cos(angle)*a+math.sin(angle)*b) for v, a, b in zip(center, x, y)]


def native_contact_plane(a, b, origin, normal, x):
    """Inspect native contact support without exempting any off-plane contact."""
    distance, solutions, _ = a.distToShape(b)
    points, rejected = [], []
    for pair in solutions:
        for value in pair:
            point = point_values(value)
            gaps = [point_distance(shape, point) for shape in (a, b)]
            # Some OCC compound contact solutions contain a default Vector(0,0,0).
            # A purported contact point must independently lie on both bodies.
            if max(gaps) <= CONTACT_DISTANCE_TOLERANCE_MM:
                points.append(point)
            else:
                rejected.append({'point_mm': point, 'distance_to_a_mm': gaps[0],
                                 'distance_to_b_mm': gaps[1]})
    extent = max((abs(sum((v-o)*n for v, o, n in zip(point, origin, normal)))
                  for point in points), default=0.)
    common = a.common(b)
    null = common.isNull()
    empty = null or not (common.Vertexes or common.Edges or common.Faces)
    if not empty:
        local = common.copy()
        frame = primitive_native.motion.frame_placement({'origin': origin, 'x': x, 'z': normal})
        local.transformShape(frame.inverse().toMatrix())
        box = bounds(local)
        extent = max(extent, abs(box['min'][2]), abs(box['max'][2]))
    overlap = 0. if empty else common.Volume
    return {'passed': distance <= CONTACT_DISTANCE_TOLERANCE_MM
                        and (bool(points) or not empty) and (empty or common.isValid())
                        and extent <= CONTACT_DISTANCE_TOLERANCE_MM
                        and 0 <= overlap <= OVERLAP_ZERO_TOLERANCE_MM3,
            'distance_mm': distance, 'overlap_mm3': overlap,
            'contact_plane_extent_mm': extent, 'native_contact_points_mm': points,
            'rejected_inconsistent_native_points': rejected,
            'common_is_null': null, 'common_is_empty': empty, 'common_valid': empty or common.isValid(),
            'common_area_mm2': 0. if empty else common.Area,
            'common_length_mm': 0. if empty else common.Length,
            'scope': 'Native common-shape support and independently verified two-body contact witnesses lie on the declared plane'}


def straight_endpoint(path, reverse=False):
    """Return the material end, outward tangent and uninterrupted straight run."""
    import pneumatic_hose
    segments = list(reversed(path['segments'])) if reverse else path['segments']
    first = segments[0]
    point = first['end_mm' if reverse else 'start_mm']
    end = first['start_mm' if reverse else 'end_mm']
    if first['kind'] != 'line':
        return point, None, 0.
    tangent = pneumatic_hose._unit([b-a for a, b in zip(point, end)])
    length = 0.
    for segment in segments:
        if segment['kind'] != 'line':break
        a = segment['end_mm' if reverse else 'start_mm']
        b = segment['start_mm' if reverse else 'end_mm']
        direction = pneumatic_hose._unit([y-x for x, y in zip(a, b)])
        if math.dist(direction, tangent) > 1e-9:break
        length += segment['length_mm']
    return point, tangent, length


def socket_mating_checks(interfaces, state, shapes, geometry):
    import pneumatic_hose
    hose = shapes['PneumaticHose']
    records = {}
    for label, interface in interfaces.items():
        socket = shapes[interface['body']]
        origin, out, x = (interface[key] for key in ('material_end_mm', 'outward', 'x_axis'))
        y = pneumatic_hose._cross(out, x)
        endpoint, tangent, straight = straight_endpoint(state['hose_path'], reverse=label == 'tip')
        delta = [v-o for v, o in zip(endpoint, origin)]
        axial = sum(v*n for v, n in zip(delta, out))
        coaxial = math.sqrt(sum((v-axial*n)**2 for v, n in zip(delta, out)))
        axis_error = math.inf if tangent is None else math.dist(tangent, out)
        measured_depth = sum((m-e)*n for m, e, n in zip(interface['socket_mouth_mm'], endpoint, out))
        depth_error = abs(measured_depth-interface['insertion_depth_mm'])
        floor = [{'point_mm': point, 'tube_distance_mm': point_distance(hose, point),
                  'socket_distance_mm': point_distance(socket, point)}
                 for point in interface['floor_witness_points_mm']]
        gaps = []
        for fraction in (1/3, 2/3):
            center = [v+fraction*interface['insertion_depth_mm']*n for v, n in zip(origin, out)]
            for angle in (0, math.pi/2, math.pi, 3*math.pi/2):
                tube_wall = radial_point(center, x, y, interface['tube_outer_radius_mm'], angle)
                socket_wall = radial_point(center, x, y, interface['socket_radius_mm'], angle)
                gaps.append({'tube_wall_mm': tube_wall, 'socket_wall_mm': socket_wall,
                             'tube_wall_socket_distance_mm': point_distance(socket, tube_wall),
                             'socket_wall_tube_distance_mm': point_distance(hose, socket_wall),
                             'tube_wall_distance_mm': point_distance(hose, tube_wall),
                             'socket_wall_distance_mm': point_distance(socket, socket_wall)})
        clamp = shapes[interface['clamp_body']]
        clamp_center = [v+(interface['insertion_depth_mm']+interface['strain_relief_length_mm']/2)*n
                        for v, n in zip(origin, out)]
        clamp_gaps = []
        for angle in (0, math.pi/2, math.pi, 3*math.pi/2):
            point = radial_point(clamp_center, x, y, interface['tube_outer_radius_mm'], angle)
            clamp_gaps.append({'point_mm': point, 'native_radial_gap_mm': point_distance(clamp, point)})
        contact = native_contact_plane(hose, socket, origin, out, x)
        required = interface['insertion_depth_mm']+interface['strain_relief_length_mm']+interface['straight_lead_mm']
        expected_gap = interface['radial_clearance_mm']
        gap_error = max(abs(row[key]-expected_gap) for row in gaps
                        for key in ('tube_wall_socket_distance_mm', 'socket_wall_tube_distance_mm'))
        floor_ok = all(max(row['tube_distance_mm'], row['socket_distance_mm']) <= CONTACT_DISTANCE_TOLERANCE_MM
                       for row in floor)
        surface_ok = all(max(row['tube_wall_distance_mm'], row['socket_wall_distance_mm']) <= CONTACT_DISTANCE_TOLERANCE_MM
                         for row in gaps)
        clamp_ok = (geometry[interface['clamp_body']]['group'] == interface['component']
                    and all(abs(row['native_radial_gap_mm']-expected_gap) <= 1e-6 for row in clamp_gaps))
        records[label] = {'passed': contact['passed'] and floor_ok and surface_ok and expected_gap > 0
                                   and gap_error <= 1e-6 and coaxial <= CONTACT_DISTANCE_TOLERANCE_MM
                                   and abs(axial) <= CONTACT_DISTANCE_TOLERANCE_MM and axis_error <= 1e-9
                                   and depth_error <= CONTACT_DISTANCE_TOLERANCE_MM
                                   and straight+CONTACT_DISTANCE_TOLERANCE_MM >= required
                                   and interface['seal_qualified'] is False,
                          'body': interface['body'], 'coaxial_error_mm': coaxial,
                          'axial_endpoint_error_mm': abs(axial), 'axis_alignment_error': axis_error,
                          'measured_insertion_depth_mm': measured_depth, 'insertion_depth_error_mm': depth_error,
                          'required_straight_run_mm': required, 'achieved_straight_run_mm': straight,
                          'radial_clearance_mm': expected_gap,
                          'minimum_native_radial_gap_mm': min(row[key] for row in gaps for key in
                              ('tube_wall_socket_distance_mm', 'socket_wall_tube_distance_mm')),
                          'maximum_radial_gap_error_mm': gap_error, 'radial_gap_witnesses': gaps,
                          'floor_witnesses': floor, 'floor_contact': contact,
                          'strain_relief': {'passed': clamp_ok, 'clamp_body': interface['clamp_body'],
                                            'native_component': geometry[interface['clamp_body']]['group'],
                                            'required_component': interface['component'], 'radial_gap_witnesses': clamp_gaps},
                          'seal_qualified': False, 'assumption': interface['assumption']}
        records[label]['passed'] = records[label]['passed'] and clamp_ok
    return {'passed': set(records) == {'pump', 'tip'} and all(row['passed'] for row in records.values()),
            'interfaces': records, 'scope': 'Native inserted socket geometry; no insertion-force, retention or gas-seal qualification'}


def radial_material_interval(shape, center, direction, length):
    end = [v+length*n for v, n in zip(center, direction)]
    section = shape.common(Part.makeLine(App.Vector(*center), App.Vector(*end)))
    values = [sum((v-o)*n for v, o, n in zip(point_values(vertex.Point), center, direction))
              for vertex in section.Vertexes]
    return (min(values), max(values)) if values else None


def tip_seat_checks(model, spec, p, state, shapes):
    import pneumatic_hose
    seat = model.tip_seat(spec, p)
    head = state['part_matrices']['WristHead'];tip = state['part_matrices'][seat['component']]
    transform = lambda point: model.robot.transform(head, point)
    axis = [head[i][2] for i in range(3)];x = [head[i][0] for i in range(3)];y = pneumatic_hose._cross(axis, x)
    center = transform(seat['seal_center_mm'])
    shaft_shape, tip_shape = shapes[seat['shaft_body']], shapes[seat['tip_body']]
    witnesses = []
    for angle in (0, math.pi/2, math.pi, 3*math.pi/2):
        point = radial_point(center, x, y, seat['seal_radius_mm'], angle)
        witnesses.append({'point_mm': point, 'shaft_distance_mm': point_distance(shaft_shape, point),
                          'tip_distance_mm': point_distance(tip_shape, point)})
    contact = native_contact_plane(shaft_shape, tip_shape, center, axis, x)
    relief = []
    for fraction in (.25, .5, .75):
        station = list(seat['seal_center_mm']);station[2] += fraction*seat['engagement_length_mm']
        station = transform(station)
        for angle in (0, math.pi/2, math.pi, 3*math.pi/2):
            direction = [math.cos(angle)*a+math.sin(angle)*b for a, b in zip(x, y)]
            a = radial_material_interval(shaft_shape, station, direction, seat['tip_mouth_inner_radius_mm']+1)
            b = radial_material_interval(tip_shape, station, direction, seat['tip_mouth_inner_radius_mm']+1)
            gap = b[0]-a[1] if a is not None and b is not None else None
            relief.append({'fraction_above_seal': fraction, 'native_radial_gap_mm': gap,
                           'expected_radial_gap_mm': fraction*seat['mouth_radial_relief_mm']})
    expected_tcp = model.robot.transform(tip, seat['tip_tcp_mm'])
    tcp_error = math.dist(expected_tcp, state['tip_tcp_mm'])
    alignment = math.dist(center, model.robot.transform(tip, seat['seal_center_mm']))
    relief_ok = all(row['native_radial_gap_mm'] is not None and row['native_radial_gap_mm'] > 0
                    and abs(row['native_radial_gap_mm']-row['expected_radial_gap_mm']) <= 1e-6 for row in relief)
    return {'passed': contact['passed'] and relief_ok and alignment <= CONTACT_DISTANCE_TOLERANCE_MM
                       and tcp_error <= CONTACT_DISTANCE_TOLERANCE_MM
                       and all(max(row['shaft_distance_mm'], row['tip_distance_mm']) <= CONTACT_DISTANCE_TOLERANCE_MM
                               for row in witnesses),
            'shaft_body': seat['shaft_body'], 'tip_body': seat['tip_body'],
            'seal_radius_mm': seat['seal_radius_mm'], 'seal_circle_witnesses': witnesses,
            'seal_contact': contact, 'coaxial_error_mm': alignment,
            'engagement_length_mm': seat['engagement_length_mm'], 'mouth_radial_relief_mm': seat['mouth_radial_relief_mm'],
            'native_relief_samples': relief, 'rederived_tcp_mm': expected_tcp, 'tcp_error_mm': tcp_error,
            'seal_qualified': False, 'insertion_force_qualified': False,
            'scope': 'Native single-circle taper contact and opening radial relief; no retention, force or gas-seal qualification'}


def head_air_probe(model, spec, p, state, shapes, own):
    interfaces = model.connection_interfaces(spec, p, state['part_matrices'])
    local = model.connection_interfaces(spec, p)['tip']['pneumatic_junction_mm']
    seat = model.tip_seat(spec, p)
    middle = model.robot.transform(state['part_matrices']['WristHead'],
                                   [seat['seal_center_mm'][0], seat['seal_center_mm'][1], local[2]])
    points = [interfaces['tip']['pneumatic_junction_mm'], middle, state['tip_tcp_mm']]
    wire = Part.Wire([Part.makeLine(App.Vector(*a), App.Vector(*b)) for a, b in zip(points, points[1:])])
    names = [row['id'] for row in own['bodies'] if row['component'] in ('WristHead', 'ConsumableTip')]
    observations = [{'body': name, 'material_intersection_mm': shapes[name].common(wire).Length,
                     'axis_distance_mm': shapes[name].distToShape(wire)[0]} for name in names]
    required = min(p['hoseInnerRadius'], seat['shaft_bore_radius_mm'], seat['tip_inner_exit_radius_mm'])
    return {'passed': all(row['material_intersection_mm'] <= CONTACT_DISTANCE_TOLERANCE_MM
                         and row['axis_distance_mm']+CONTACT_DISTANCE_TOLERANCE_MM >= required for row in observations),
            'points_mm': points, 'length_mm': wire.Length, 'observations': observations,
            'minimum_axis_clearance_mm': min(row['axis_distance_mm'] for row in observations),
            'required_axis_clearance_mm': required,
            'scope': 'Head-only side-port to shaft bore and consumable exit; independent of the isolation-valve state'}


def filled_hose_lumen(path, radius):
    import pneumatic_hose
    pieces = []
    for segment in path['segments']:
        start = segment['start_mm']
        if segment['kind'] == 'line':
            axis = pneumatic_hose._unit([b-a for a, b in zip(start, segment['end_mm'])])
            piece = Part.makeCylinder(radius, segment['length_mm'], App.Vector(*start), App.Vector(*axis))
        else:
            axis = pneumatic_hose._unit(pneumatic_hose._cross(segment['axis'],
                    [v-c for v, c in zip(start, segment['center_mm'])]))
            wire = pneumatic_hose.freecad_wire(Part, App, {'format': path['format'], 'segments': [segment]})
            profile = Part.Wire([Part.makeCircle(radius, App.Vector(*start), App.Vector(*axis))])
            piece = wire.makePipeShell([profile], True, False)
        pieces.append(piece)
    result = (pieces[0].multiFuse(pieces[1:]) if len(pieces) > 1 else pieces[0]).removeSplitter()
    expected = math.pi*radius*radius*path['length_mm']
    if (not result.isValid() or len(result.Solids) != 1 or not result.Solids[0].isClosed()
            or abs(result.Volume-expected) > 1e-5):
        raise ValueError('Native full tube lumen does not match its exact centerline inventory')
    return result


def air_path_checks(model, spec, p, state, shapes, own):
    import spatial_hose_carrier
    probe = head_air_probe(model, spec, p, state, shapes, own)
    recipe = model.air_path_recipe(spec, p, state['stroke_mm'])
    reference = state['part_matrices']['PumpFrame']
    inverse = model.robot.inverse(reference)
    groups = {}
    for row in recipe:
        shape = row['shape'];origin, axis = App.Vector(*shape['origin']), App.Vector(*shape['axis'])
        if shape['kind'] == 'cylinder':
            solid = Part.makeCylinder(shape['radius'], shape['height'], origin, axis)
        elif shape['kind'] == 'cone':
            solid = Part.makeCone(shape['radius'], shape['top_radius'], shape['height'], origin, axis)
        else:
            raise ValueError('Unsupported native air-inventory primitive: '+shape['kind'])
        matrix = state['part_matrices'][row['component']]
        group = groups.setdefault(json.dumps(matrix), {'matrix': matrix, 'pieces': [], 'components': []})
        group['pieces'].append(solid)
        if row['component'] not in group['components']:group['components'].append(row['component'])
    components, group_measurements = [], []
    for group in groups.values():
        pieces = group['pieces']
        shape = (pieces[0].multiFuse(pieces[1:]) if len(pieces) > 1 else pieces[0]).removeSplitter()
        local_volume = shape.Volume
        shape.transformShape(placement(model.robot.multiply(inverse, group['matrix'])).toMatrix())
        invariant = abs(shape.Volume-local_volume)
        if (not shape.isValid() or not shape.Solids or not all(solid.isClosed() for solid in shape.Solids)
                or invariant > 1e-7):
            raise ValueError('Native source-local air-cavity group is invalid or changed under rigid placement')
        components.extend(shape.Solids)
        group_measurements.append({'source_components': group['components'],
            'local_volume_mm3': local_volume, 'placed_volume_mm3': shape.Volume,
            'rigid_placement_volume_difference_mm3': invariant, 'solid_count': len(shape.Solids)})
    local_path = spatial_hose_carrier.transform_path(state['hose_path'], inverse)
    tube = filled_hose_lumen(local_path, p['hoseInnerRadius'])
    if not components:
        raise ValueError('Native ideal air-cavity components are invalid before adding the tube')
    # Join each rigid cavity group in its own declared frame first. Construct
    # the network in PumpFrame before world placement to preserve tiny joins.
    union = components[0].multiFuse(components[1:]+[tube]).removeSplitter()
    local_volume = union.Volume
    union.transformShape(placement(reference).toMatrix())
    placement_volume_error = abs(union.Volume-local_volume)
    expected = model.air_volumes(spec, p, state['stroke_mm'])
    error = abs(union.Volume-expected['total'])/expected['total']
    inventory = {'passed': union.isValid() and len(union.Solids) == 1
                           and all(solid.isClosed() for solid in union.Solids) and error <= 1e-6
                           and placement_volume_error <= 1e-7,
                 'valid': union.isValid(), 'solid_count': len(union.Solids),
                 'native_volume_mm3': union.Volume, 'expected_volume_ul': expected['total'],
                 'relative_volume_error': error, 'recipe_ids': [row['id'] for row in recipe],
                 'native_recipe_connected_components': len(components),
                 'native_union_strategy': 'Fuse rigid cavity groups locally, then groups and exact tube in PumpFrame, then place in world',
                 'native_recipe_groups': group_measurements,
                 'construction_frame': 'PumpFrame', 'construction_frame_matrix': reference,
                 'native_local_volume_mm3': local_volume,
                 'rigid_placement_volume_difference_mm3': placement_volume_error,
                 'native_tube_lumen_volume_mm3': tube.Volume,
                 'excluded_ambient_tip_relief_ul': expected['unpressurized_tip_relief_air_ul'],
                 'ideal_open_valve_reference': True, 'delivered_material_body': False,
                 'scope': 'Union of the declared ideal open-valve cavity inventory and tube lumen, including inserted portions once; '
                          'not an open-flow requirement for an isolated-valve pose or a leak measurement'}
    return {'passed': probe['passed'] and inventory['passed'], 'head_probe': probe, 'cavity_union': inventory}


def build(case_path, output_path, report_path):
    import arm_syringe as model
    import pneumatic_hose
    from build_arm_syringe import arm_bodies
    case = json.loads(Path(case_path).read_text(encoding='utf-8'))
    spec = model.load()
    p = model.parameters(spec, case.get('overrides', {}))
    if not isinstance(case.get('compiled_state'), dict):
        raise ValueError('The native adapter requires its source-compiled route and selected loop witness')
    state = case['compiled_state']
    evaluated_state = model.state(spec, p, case['state'],
        loop_parameter_mm=case['routing_proof'] if clipped_mode(spec) else state['hose_slack_parameter_mm'])
    for value in (state, evaluated_state):
        clearance = value.get('source_clearance')
        if not isinstance(clearance, dict) or clearance.get('passed') is not True or not clearance.get('scope'):
            raise ValueError('Source-frame external-clearance evidence is required for each selected native route')
    self_clearance = require_hose_self_clearance(state)
    independent_self_clearance = require_hose_self_clearance(evaluated_state)
    material_checks = route_material_checks(state['hose_path'], p)
    independent_material_checks = route_material_checks(evaluated_state['hose_path'], p)
    state_agreement = compare_derived_metrics(canonical_material_core(state, p),
                                             canonical_material_core(evaluated_state, p))
    derivation = {'physical_curve_equivalence_established': state_agreement['passed'],
                  'leading': route_derivation_diagnostics(state['hose_path'],
                      sample_step_mm=spec['hose_routing']['sample_step_mm'] if clipped_mode(spec) else None),
                  'independent': route_derivation_diagnostics(evaluated_state['hose_path'],
                      sample_step_mm=spec['hose_routing']['sample_step_mm'] if clipped_mode(spec) else None),
                  'scope': 'Known subdivision, fitter and conservative sampled-reach diagnostics are retained separately; '
                           'they cannot override raw geometry, material, radius or clearance checks'}
    metrics = case.get('metrics', state['metrics'])
    metrics_agreement = compare_derived_metrics(metrics, evaluated_state['metrics'])
    own = model.expanded(spec, p)
    cache = checked_arm_cache(case['arm_report'], 'freecad', model.ROOT)
    if digest(cache['path']) != cache['sha256']:
        raise ValueError('Native source arm changed before opening')
    arm = model.arm(spec)
    rows = arm_bodies(arm)
    motion = primitive_native.motion
    doc = App.openDocument(cache['path'])
    doc.saveAs(str(output_path))
    motion.set_angles(doc, [0]*6)
    original = {obj.SourceBody: obj for obj in motion.features(doc)}
    if set(original) != {row['id'] for row in rows}:
        raise ValueError('Checked arm body coverage changed')
    zero_centres = {name: center_of_solids(motion.world_shape(obj)) for name, obj in original.items()}
    motion.set_angles(doc, state['joints_deg'])
    own_path = Path(output_path).with_name(Path(output_path).stem+'.parts.FCStd')
    own_shapes = source_shapes(model, spec, p, own, own_path)
    if set(own_shapes) & set(original):
        raise ValueError('New tooling shadows an existing robot body')
    groups, controller = add_tooling(doc, model, spec, p, own, own_shapes, state)
    carrier_parameterization = {}
    guard = add_carrier(doc, state, parameterization_report=carrier_parameterization)
    hose = doc.addObject('Part::Feature', 'PneumaticHose')
    hose.Shape = pneumatic_hose.freecad_shape(Part, App, state['hose_path'],
        state['hose_inner_radius_mm'], state['hose_outer_radius_mm'])
    for key, value in [('SourceBody', 'PneumaticHose'), ('RigidLink', 'HoseSnapshot'),
                       ('ModelRole', 'static_pneumatic_hose')]:
        hose.addProperty('App::PropertyString', key, 'Shared source')
        setattr(hose, key, value)
    doc.recompute()
    objects = {obj.SourceBody: obj for obj in motion.features(doc)}
    shapes = {name: motion.world_shape(obj) for name, obj in objects.items()}
    geometry = {name: measurement(obj, motion.world_shape) for name, obj in objects.items()}
    own_errors = []
    for row in own['bodies']:
        expected = model.robot.transform(state['part_matrices'][row['component']],
                                         center_of_solids(own_shapes[row['id']]))
        own_errors.append({'body': row['id'],
                          'error_mm': math.dist(expected, geometry[row['id']]['world_center_of_mass_mm'])})
    arm_world = model.robot.forward(arm, state['joints_deg'])
    arm_errors = []
    for row in rows:
        expected = model.robot.transform(arm_world[row['group']], list(zero_centres[row['id']]))
        arm_errors.append({'body': row['id'],
                          'error_mm': math.dist(expected, geometry[row['id']]['world_center_of_mass_mm'])})
    dynamic = carrier_bodies(state)
    clearances = clearance_checks(model, spec, p, rows, own['bodies']+dynamic, shapes)
    carrier_report = None
    if guard is not None:
        guarded_shapes = {**shapes, 'CarrierOuterGuard': guard}
        guard_boxes = {name: bounds(shape) for name, shape in guarded_shapes.items()}
        guard_audit = audit_clearances(rows, own['bodies'], guarded_shapes, [], guard_boxes,
                                       guard_pair_groups(rows, own['bodies']))
        clearances = merge_clearance_checks(clearances, guard_audit)
        carrier_report = carrier_checks(state, geometry, shapes, guard,
                                         (state['hose_inner_radius_mm'], state['hose_outer_radius_mm']),
                                         carrier_parameterization)
    interfaces = model.connection_interfaces(spec, p, state['part_matrices'])
    mating = socket_mating_checks(interfaces, state, shapes, geometry)
    endpoints = pneumatic_connections(clearances, interfaces, mating)
    seat_report = tip_seat_checks(model, spec, p, state, shapes)
    air_report = air_path_checks(model, spec, p, state, shapes, own)
    clip_report = clipped_hose_checks(model, spec, p, state, shapes)
    wire = pneumatic_hose.freecad_wire(Part, App, state['hose_path'])
    lumen = hose.Shape.common(wire).Length
    diagnostic = pneumatic_hose.diagnostics(state['hose_path'], state['hose_inner_radius_mm'],
                                           state['hose_outer_radius_mm'])
    hose_native_volume = hose.Shape.Volume
    hose_volume_error = abs(hose_native_volume-diagnostic['wall_volume_mm3'])/diagnostic['wall_volume_mm3']
    motor_error = abs(controller.MotorRotation.Value-state['motor_angle_deg'])
    controller.addProperty('App::PropertyString', 'StaticState', 'Concept qualification')
    controller.StaticState = case['state']
    doc.save()
    App.closeDocument(doc.Name)
    doc = App.openDocument(str(output_path));doc.recompute()
    reopened = {obj.SourceBody: measurement(obj, motion.world_shape) for obj in motion.features(doc)}
    expected_counts = {name: 1 for name in geometry}
    expected_counts.update({row['id']: row['expected_solid_count'] for row in dynamic})
    reopen_ok = set(reopened) == set(geometry) and all(row['valid'] and row['closed_solids']
                and row['solid_count'] == expected_counts[name] for name, row in reopened.items())
    App.closeDocument(doc.Name)
    result = {'passed': reopen_ok and clearances['passed'] and motor_error < 1e-7 and metrics_agreement['passed']
                       and state_agreement['passed'] and endpoints['passed']
                       and seat_report['passed'] and air_report['passed']
                       and (carrier_report is None or carrier_report['passed'])
                       and (clip_report is None or clip_report['passed'])
                       and max(row['error_mm'] for row in own_errors+arm_errors) < 1e-6
                       and lumen < 1e-7 and hose_volume_error < 1e-6
                       and all(row['valid'] and row['closed_solids'] and row['solid_count'] == expected_counts[name]
                               for name, row in geometry.items()),
              'case': case, 'geometry': geometry, 'arm_pose_checks': arm_errors,
              'metrics': metrics, 'native_metrics_agreement': metrics_agreement,
              'compiled_state_agreement': state_agreement,
              'route_derivation_diagnostics': derivation,
              'hose_self_clearance': self_clearance,
              'independent_hose_self_clearance': independent_self_clearance,
              'route_material_checks': material_checks,
              'independent_route_material_checks': independent_material_checks,
              'source_clearance': state['source_clearance'],
              'independent_source_clearance': evaluated_state['source_clearance'],
              'carrier_checks': carrier_report, 'clip_checks': clip_report, 'pneumatic_connections': endpoints,
              'tip_seat_checks': seat_report, 'air_path_checks': air_report,
              'new_part_pose_checks': own_errors, 'clearance_checks': clearances,
              'motor_coupling_error_deg': motor_error,
              'hose': {**diagnostic, 'native_wall_volume_mm3': hose_native_volume,
                       'relative_wall_volume_error': hose_volume_error,
                       'centerline_material_intersection_mm': lumen},
              'reopened': {'passed': reopen_ok}, 'own_parts_file': str(own_path),
              'arm_cache': cache, 'source_sha256': model.digest(model.SOURCE),
              'qualification': spec['qualification'],
              'scope': 'Named static arm/doser states; current-arm joints and native stroke/rotation coupling; hose snapshot only'}
    if digest(cache['path']) != cache['sha256']:
        raise ValueError('Original native arm bytes changed')
    write(report_path, result)
    print(json.dumps({'state': case['state'], 'passed': result['passed'],
                      'bodies': len(geometry), 'interferences': clearances['interferences'],
                      'minimum_clearance_mm': clearances['minimum_nonallowed_distance_mm']}), flush=True)
    if not result['passed']:
        raise AssertionError('Arm-mounted syringe native checks failed')
    return result


def probe_routes(reference_report, output_report, state_names=None, changed_rigid_bodies=None):
    """Inspect current hoses against a reposed, immutable historical assembly.

    This diagnostic does not regenerate rigid tooling, save an edited CAD file,
    or replace the canonical build report.  A complete current build is still
    required after choosing the source geometry and named inspection states.
    """
    import arm_syringe as model
    import pneumatic_hose
    from build_arm_syringe import arm_bodies
    started = time.monotonic()
    reference_report = Path(reference_report).resolve()
    output_report = Path(output_report).resolve()
    if not output_report.is_relative_to(model.ROOT/'exports'):
        raise ValueError('Route diagnostics belong in the ignored exports directory')
    output_report.parent.mkdir(parents=True, exist_ok=True)
    reference = json.loads(reference_report.read_text(encoding='utf-8'))
    if not reference.get('passed') or reference.get('format') != 'solidcraftbot.arm-syringe-build/1':
        raise ValueError('A passed historical arm-syringe report is required')
    entry = next((row for row in reference['states'] if row['id'] == 'working'), reference['states'][0])
    relative = Path(entry['files']['freecad'])
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Historical CAD path must remain relative to the worktree')
    native_path = model.ROOT/relative
    native_hash = entry['artifact_sha256']['freecad']
    if digest(native_path) != native_hash:
        raise ValueError('Historical native assembly differs from its report')
    spec = model.load()
    if spec.get('hose_carrier') is not None:
        raise ValueError('Historical hose-only probe does not support the current carrier/mount revision; use a full build')
    p = model.parameters(spec)
    names = state_names or list(spec['states'])
    if not names or len(names) != len(set(names)) or set(names)-set(spec['states']):
        raise ValueError('Choose distinct current source states')
    cache = checked_arm_cache(reference['arm_cache']['freecad']['report_path'], 'freecad', model.ROOT)
    source_paths = [model.SOURCE, Path(model.__file__), Path(__file__),
                    model.ROOT/'scripts/build_arm_syringe.py', model.ROOT/'scripts/pneumatic_hose.py']
    pins = {str(path.relative_to(model.ROOT)): digest(path) for path in source_paths}
    own = model.expanded(spec, p)
    arm_rows = arm_bodies(model.arm(spec))
    physical_arm = [row['id'] for row in arm_rows if row['role'] != 'viewing_cone']
    contacts = [row for row in model.allowed_contacts(spec, p)
                if 'PneumaticHose' in (row['a'], row['b'])]
    motion = primitive_native.motion
    doc = App.openDocument(str(native_path))
    results = []
    result = {
        'format': 'solidcraftbot.arm-syringe-route-diagnostic/1',
        'passed': False, 'backend': 'freecad',
        'reference_report': str(reference_report), 'reference_report_sha256': digest(reference_report),
        'reference_revision': reference['revision'],
        'reference_native': str(native_path), 'reference_native_sha256': native_hash,
        'source': str(model.SOURCE.relative_to(model.ROOT)), 'source_sha256': digest(model.SOURCE),
        'source_files_sha256': pins, 'states': results,
        'rigid_geometry_regenerated': False, 'canonical_build_updated': False,
        'known_changed_current_rigid_bodies': sorted(changed_rigid_bodies or []),
        'scope': 'Historical rigid assembly reposed with current source-derived hoses; '
                 'diagnostic only, no current rigid-geometry rebuild, continuous motion or hardware qualification',
    }
    try:
        objects = {obj.SourceBody: obj for obj in motion.features(doc)}
        expected = {row['id'] for row in arm_rows+own['bodies']} | {'PneumaticHose'}
        if set(objects)-expected or not ({row['id'] for row in arm_rows} | {'PneumaticHose'}) <= set(objects):
            raise ValueError('Historical arm/body identities differ from the current source')
        result['omitted_current_rigid_bodies'] = sorted(expected-set(objects))
        result['reference_body_count'] = len(objects)
        if not set(result['known_changed_current_rigid_bodies']) <= set(objects):
            raise ValueError('A declared changed rigid body is absent from the historical reference')
        result['historical_control_metadata'] = {
            'maxMotorAngle': {'reference_deg': doc.SyringeParameters.maxMotorAngle.Value,
                              'current_source_deg': p['maxMotorAngle'],
                              'scope': 'Derived metadata excluded from rigid-dimension equality; '
                                       'historical direct angle assignment was capped at 360 degrees'}}
        pairs = {'hose_arm': [('PneumaticHose', name) for name in physical_arm],
                 'hose_tooling': [('PneumaticHose', row['id']) for row in own['bodies']
                                  if row['id'] in objects]}
        for name in model.native_spec(spec, p)['parameters']:
            if (name in doc.SyringeParameters.PropertiesList and not name.startswith('hose')
                    and name != 'maxMotorAngle'):
                if abs(getattr(doc.SyringeParameters, name).Value-p[name]) > 1e-8:
                    raise ValueError('Rigid-tool parameter differs from reference: '+name)
        for name in names:
            case_started = time.monotonic()
            try:
                state = model.state(spec, p, name)
                motion.set_angles(doc, state['joints_deg'])
                doc.SyringeController.PumpStroke = state['stroke_mm']
                doc.SyringeController.IsolationValve = state['valve_angle_deg']
                doc.recompute()
                hose = pneumatic_hose.freecad_shape(Part, App, state['hose_path'],
                                                    state['hose_inner_radius_mm'], state['hose_outer_radius_mm'])
                objects['PneumaticHose'].Shape = hose
                doc.recompute()
                used = {body for group in pairs.values() for pair in group for body in pair}
                shapes = {body: motion.world_shape(objects[body]) for body in used}
                boxes = {body: bounds(shape) for body, shape in shapes.items()}
                clearances = audit_clearances(arm_rows, own['bodies'], shapes, contacts, boxes, pairs)
                diagnostic = pneumatic_hose.diagnostics(state['hose_path'], state['hose_inner_radius_mm'],
                                                        state['hose_outer_radius_mm'])
                volume_error = abs(hose.Volume-diagnostic['wall_volume_mm3'])/diagnostic['wall_volume_mm3']
                lumen = hose.common(pneumatic_hose.freecad_wire(Part, App, state['hose_path'])).Length
                case = {'id': name, 'passed': clearances['passed'] and hose.isValid()
                        and len(hose.Solids) == 1 and volume_error < 1e-6 and lumen < 1e-7,
                        'clearance_checks': clearances, 'metrics': state['metrics'],
                        'hose_slack_parameter_mm': state['hose_slack_parameter_mm'],
                        'hose': {**diagnostic, 'relative_wall_volume_error': volume_error,
                                 'centerline_material_intersection_mm': lumen}}
            except Exception as error:
                case = {'id': name, 'passed': False, 'error_type': type(error).__name__, 'error': str(error)}
            case['elapsed_s'] = time.monotonic()-case_started
            results.append(case)
            result['elapsed_s'] = time.monotonic()-started
            write(output_report, result)
            print(json.dumps(case), flush=True)
    finally:
        App.closeDocument(doc.Name)
    result['source_pins_current'] = all(digest(model.ROOT/name) == value for name, value in pins.items())
    result['reference_unchanged'] = digest(native_path) == native_hash
    result['passed'] = all(row['passed'] for row in results) and result['source_pins_current'] and result['reference_unchanged']
    result['elapsed_s'] = time.monotonic()-started
    write(output_report, result)
    if not result['passed']:
        raise AssertionError('Route diagnostic failed; inspect the recorded boundary or overlap findings')
    return result


def main():
    if len(sys.argv) > 1 and sys.argv[1] == 'probe-routes':
        parser = argparse.ArgumentParser(description=probe_routes.__doc__)
        parser.add_argument('reference_report', type=Path)
        parser.add_argument('output_report', type=Path)
        parser.add_argument('--state', action='append')
        parser.add_argument('--changed-rigid-body', action='append', default=[])
        args = parser.parse_args(sys.argv[2:])
        return probe_routes(args.reference_report, args.output_report, args.state, args.changed_rigid_body)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('report', type=Path)
    args = parser.parse_args()
    return build(args.case, args.output, args.report)


if __name__ == '__main__':
    main()
