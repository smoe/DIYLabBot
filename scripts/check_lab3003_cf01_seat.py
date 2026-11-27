"""Check a necessary condition for the direct TR01-to-CF01 arm transfer."""

import json
import math
from pathlib import Path

import assembly_model
import centrifuge_model as cf
import centrifuge_robot_pickup as pickup
import lab3003_cf01_cycle as cycle
import lab_layout_model as layout
import robot_spec as robot
import tr01_workcell as workcell


def axis_distance(point, origin, axis):
    offset = [p - o for p, o in zip(point, origin)]
    along = math.fsum(x * y for x, y in zip(offset, axis))
    return math.hypot(*(x - along * y for x, y in zip(offset, axis)))


def pad_section(parts, gap):
    pads = {part['group']: part['shape'] for part in parts if part['role'] == 'illustrative_gripper_pad'}
    left, right = (pads[key] for key in ('FingerLeft', 'FingerRight'))
    if (left['kind'] != 'box' or right['kind'] != 'box' or left['size'] != right['size']
            or left['origin'][1:] != right['origin'][1:]):
        raise ValueError('The direct seating bound requires the matching source pad boxes')
    x, y, z = left['size']
    axial_depth = (left['origin'][2] + z) / 2
    radial = gap / 2 + right['origin'][0] + x / 2
    if (left['origin'][0] + x / 2 - gap / 2 != -radial
            or left['origin'][1] + y / 2 != 0 or axial_depth <= 0):
        raise ValueError('The pad witness requires opposed centers on the same tool cross-section')
    pad_margin = min(x / 2, y / 2, axial_depth - left['origin'][2],
                     left['origin'][2] + z - axial_depth)
    return radial, axial_depth, pad_margin


def overlap_bound(bottom, axis, grip, gap, parts, blank, cuts):
    """One opposed pad center must lie below the cross-section center."""
    radial, axial_depth, pad_margin = pad_section(parts, gap)
    center = cf.plus(bottom, axis, grip - axial_depth)
    radial_z = radial * math.hypot(*axis[:2])
    margins = {
        'pad_faces': pad_margin,
        'rotor_upper_face': blank['origin'][2] + blank['height'] - center[2],
        'rotor_lower_face': center[2] - radial_z - blank['origin'][2],
        'rotor_outer_wall': blank['radius'] - math.dist(center[:2], blank['origin'][:2]) - radial,
    }
    bore_margins = []
    for cut in cuts:
        distance = axis_distance(center, cut['origin'], cut['axis'])
        alignment = abs(math.fsum(a * b for a, b in zip(cut['axis'], axis)))
        if distance < 1e-8 and abs(alignment - 1) < 1e-8:
            bore_margins.append(radial - cut['radius'])
        else:
            bore_margins.append(distance - radial - cut['radius'])
    margins['rotor_cuts'] = min(bore_margins)
    radius = min(margins.values()) - 0.001
    return {'blocked': radius > 0, 'source_margin_mm': margins,
            'witness_ball_radius_mm': max(0, radius),
            'overlap_volume_lower_mm3': 4 * math.pi * max(0, radius)**3 / 3}


def check():
    definition, references = cycle._load_source()
    samples = definition['samples']
    station, inputs = cycle._bound_sources(definition['laboratory_id'], references['laboratories'], samples)
    parameters = cf.parameters(station)
    rotor_ops = [op for op in cf.expanded(station, parameters)['operations'] if op['body'] == 'Rotor']
    if (any(op['shape']['kind'] != 'cylinder' for op in rotor_ops)
            or [op['action'] for op in rotor_ops] != ['create'] + ['cut'] * (len(rotor_ops) - 1)):
        raise ValueError('The rotor certificate requires a cylindrical blank and cylindrical cuts')
    blank, *cuts = [op['shape'] for op in rotor_ops]
    if blank['axis'] != [0, 0, 1] or not cuts:
        raise ValueError('An upright rotor blank with source pocket cutters is required')

    source = layout.load(validate_builds=False)
    item = next(entry for entry in source['instances'] if entry['id'] == 'TR01')
    provider = layout.provider(item['asset'])
    transporter = layout.instance_source(source, item)
    cargo = provider.expanded(transporter, provider.parameters(transporter),
                              layout.instance_variant(transporter, item))
    # Only the existing grasp reference is used here. Loading the complete
    # standalone choreography would also require its unrelated arm and routes.
    workcell_model = json.loads(workcell.SOURCE.read_text())
    if (workcell_model['format'] != 'solidcraftbot.tr01-workcell/1'
            or assembly_model.validate_reference(workcell_model['layout']) != layout.SOURCE
            or assembly_model.validate_reference(workcell_model['tool_reference']) != pickup.SOURCE):
        raise ValueError('The TR01 cargo grasp reference changed')
    gripper = pickup.load()
    gripper['gripper'].update(workcell_model['gripper_overrides'])
    parts = pickup.gripper_parts(gripper, {})
    results = []
    for sample in samples:
        tube = next(op['shape'] for op in cargo['operations']
                    if op['action'] == 'create' and op['body'] == sample['id'])
        dimensions = workcell.tube_geometry(cargo, sample['id'], workcell_model['cargo_grip_offset_from_top_mm'])
        grip = dimensions['tool_axial_bounds_mm'][1]
        gap = 2 * tube['radius']
        bottom, axis = cf.pocket(station, parameters, sample['slot'])
        result = overlap_bound(bottom, axis, grip, gap, parts, blank, cuts)
        results.append({**sample, 'grip_above_tube_bottom_mm': grip, 'jaw_gap_mm': gap, **result})

    pins = {*inputs, *references.values(), cycle.SOURCE, workcell.SOURCE, pickup.SOURCE,
            Path(__file__), Path(cf.__file__), Path(pickup.__file__), Path(workcell.__file__)}
    return {
        'format': 'solidcraftbot.lab3003-cf01-direct-seat-check/1',
        'blocked': all(result['blocked'] for result in results),
        'results': results,
        'source_files_sha256': {str(path.relative_to(cf.ROOT)): robot.digest(path) for path in sorted(pins)},
        'scope': 'For every axial roll, one source pad encloses a ball strictly inside the source rotor '
                 'at the direct seated endpoint. Scope is the current rigid grip and seated tube axis.',
    }


if __name__ == '__main__':
    print(json.dumps(check(), indent=2))
