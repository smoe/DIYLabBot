"""Tessellate checked building bodies and instance L01 equipment into that frame.

This adapter reads final placed BReps, including their Boolean openings.  It
does not rebuild walls from bounds or assert surveyed building registration.
Importing the packing/verification helpers
does not require FreeCAD; only ``export`` loads the native runtime.
"""
from array import array
import argparse
import base64
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FORMAT = 'solidcraftbot.building-walkthrough-mesh/1'
REPORT_FORMATS = {
    'building': 'solidcraftbot.building-stack-build/1',
    'lab': 'solidcraftbot.lab-layout-build/1',
}


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def project_path(name, root=ROOT):
    root = Path(root).resolve()
    path = Path(name)
    path = (root/path).resolve() if not path.is_absolute() else path.resolve()
    if not path.is_relative_to(root):
        raise ValueError('A project-local source or artifact is required: '+str(name))
    return path


def verify_pins(pins, root=ROOT):
    if not isinstance(pins, dict) or not pins:
        raise ValueError('Nonempty checked source pins are required')
    for name, expected in pins.items():
        if not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected):
            raise ValueError('Invalid SHA256 pin: '+str(name))
        path = project_path(name, root)
        if not path.is_file() or digest(path) != expected:
            raise ValueError('Changed or missing checked input: '+str(name))


def checked_report(path, scene, root=ROOT):
    """Reject failed, stale or altered native proofs before opening FreeCAD."""
    path = project_path(path, root)
    report = json.loads(path.read_text(encoding='utf-8'))
    if report.get('format') != REPORT_FORMATS[scene] or report.get('passed') is not True:
        raise ValueError('A successful checked '+scene+' native build is required')
    verify_pins(report.get('source_files_sha256'), root)
    files, hashes = report.get('files', {}), report.get('artifact_sha256', {})
    if not files or set(files) != set(hashes) or 'freecad' not in files:
        raise ValueError('Every native build artifact requires a SHA256 pin')
    verify_pins({files[key]: hashes[key] for key in files}, root)
    if scene == 'building':
        if report.get('backends') not in {'freecad', 'both'} or report.get('freecad_checks_passed') is not True:
            raise ValueError('A successful native FreeCAD building proof is required')
        source = report.get('source')
        if report['source_files_sha256'].get(source) != report.get('source_sha256'):
            raise ValueError('Building source and native proof differ')
    else:
        source = 'model/lab-layout-l01.shared.json'
        if report['source_files_sha256'].get(source) != report.get('source_sha256'):
            raise ValueError('L01 source and native proof differ')
        validation = report.get('layout_validation', {})
        if validation.get('passed') is not True or validation.get('geometry_valid') is not True:
            raise ValueError('A valid complete L01 native scene is required')
    return report


def native_styles(path):
    """Read the already checked native presentation, without starting a GUI."""
    result = {}
    with zipfile.ZipFile(path) as archive:
        document = ET.fromstring(archive.read('Document.xml'))
        gui = ET.fromstring(archive.read('GuiDocument.xml'))
        providers = {entry.get('name'): entry for entry in gui.findall('ViewProviderData/ViewProvider')}
        for obj in document.findall('ObjectData/Object'):
            entry = obj.find("Properties/Property[@name='SourceBody']/String")
            if entry is None:
                continue
            body = entry.get('value')
            provider = providers.get(obj.get('name'))
            appearance = None if provider is None else provider.find("Properties/Property[@name='ShapeAppearance']/MaterialList")
            if appearance is None or appearance.get('version') != '3':
                raise ValueError('Missing checked native material: '+str(body))
            raw = archive.read(appearance.get('file'))
            if len(raw) != struct.calcsize('<5I2f3I'):
                raise ValueError('Unsupported native material encoding: '+str(body))
            count, _, rgba, _, _, _, transparency, _, _, _ = struct.unpack('<5I2f3I', raw)
            if count != 1 or not math.isfinite(transparency) or not 0 <= transparency <= 1:
                raise ValueError('Invalid native material: '+str(body))
            if body in result:
                raise ValueError('Duplicate native body identity: '+str(body))
            result[body] = {'color': [((rgba >> shift) & 255)/255 for shift in (24, 16, 8)],
                            'opacity': 1-float(transparency)}
    return result


def packed(values):
    """Encode typed arrays explicitly little-endian on every exporter host."""
    if sys.byteorder != 'little':
        values = array(values.typecode, values)
        values.byteswap()
    return base64.b64encode(values.tobytes()).decode('ascii')


class MeshBuilder:
    """Indexed triangles with explicit face normals and stable body ranges."""
    def __init__(self):
        self.positions = array('f')
        self.normals = array('f')
        self.indices = array('I')
        if self.positions.itemsize != 4 or self.indices.itemsize != 4:
            raise RuntimeError('32-bit float and unsigned integer arrays are required')
        self.groups = []
        self.maximum_float32_error_mm = 0.
        self.degenerate_triangles_omitted = 0

    def add(self, body, vertices, faces, style, *, role, level_id=None, instance_id=None, bbox=None, normals=None):
        if any(group['id'] == body for group in self.groups):
            raise ValueError('Duplicate scene body: '+str(body))
        points = [tuple(float(value) for value in point) for point in vertices]
        if not points or any(len(point) != 3 or not all(math.isfinite(v) for v in point) for point in points):
            raise ValueError('Finite native XYZ vertices are required: '+str(body))
        if normals is not None:
            normals = [tuple(float(value) for value in normal) for normal in normals]
            if len(normals) != len(points) or any(len(normal) != 3 or not all(math.isfinite(v) for v in normal)
                    or abs(sum(v*v for v in normal)-1) > 1e-5 for normal in normals):
                raise ValueError('One unit native-face normal per vertex is required')
        if (len(style['color']) != 3 or any(not math.isfinite(v) or not 0 <= v <= 1 for v in style['color'])
                or not math.isfinite(style['opacity']) or not 0 <= style['opacity'] <= 1):
            raise ValueError('Normalized native color/opacity required')
        start = len(self.indices)
        unique = {}
        for face in faces:
            if len(face) != 3 or any(type(i) is not int or not 0 <= i < len(points) for i in face):
                raise ValueError('Valid native triangle indices required: '+str(body))
            a, b, c = (points[i] for i in face)
            u, v = [b[i]-a[i] for i in range(3)], [c[i]-a[i] for i in range(3)]
            normal = (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])
            length = math.sqrt(sum(value*value for value in normal))
            if length < 1e-12:
                self.degenerate_triangles_omitted += 1
                continue
            normal = tuple(value/length for value in normal)
            # Matching planar triangles can share a vertex.  Sharp BRep edges
            # retain distinct face normals instead of becoming rounded boxes.
            for index in face:
                direction = normal if normals is None else normals[index]
                key = (points[index], direction)
                if key not in unique:
                    unique[key] = len(self.positions)//3
                    point = points[index]
                    self.positions.extend(point)
                    self.normals.extend(direction)
                    self.maximum_float32_error_mm = max(self.maximum_float32_error_mm,
                        *(abs(a-b) for a, b in zip(point, self.positions[-3:])))
                self.indices.append(unique[key])
        count = len(self.indices)-start
        if count == 0:
            raise ValueError('A nonempty native surface is required: '+str(body))
        bounds = bbox or {'min': [min(point[i] for point in points) for i in range(3)],
                          'max': [max(point[i] for point in points) for i in range(3)]}
        self.groups.append({'id': body, 'level_id': level_id, 'role': role, 'instance_id': instance_id,
                            'color': style['color'], 'opacity': style['opacity'],
                            'index_start': start, 'index_count': count, 'bounds_mm': bounds})

    def result(self):
        if not self.groups:
            raise ValueError('An empty walkthrough scene cannot be exported')
        bounds = {'min': [min(g['bounds_mm']['min'][i] for g in self.groups) for i in range(3)],
                  'max': [max(g['bounds_mm']['max'][i] for g in self.groups) for i in range(3)]}
        return {'positions_base64': packed(self.positions), 'normals_base64': packed(self.normals),
                'indices_base64': packed(self.indices), 'vertex_count': len(self.positions)//3,
                'index_count': len(self.indices), 'groups': self.groups, 'bounds_mm': bounds,
                'maximum_float32_error_mm': self.maximum_float32_error_mm,
                'degenerate_triangles_omitted': self.degenerate_triangles_omitted}


def building_manifest(report):
    import building_stack as model
    source = project_path(report['source'])
    spec = model.load(source)
    parameters = model.parameters(spec)
    expanded = model.expanded(spec, parameters)
    contract = model.interfaces(spec, parameters)
    bodies = {body['id']: body for body in expanded['bodies']}
    if len(bodies) != report['closed_body_count']:
        raise ValueError('The native building proof has another body manifest')
    levels = {level['id'] for level in contract['levels']}
    assigned = {body: room['level'] for room in contract.get('furnishings', {}).get('rooms', []) for body in room['body_ids']}
    assigned.update({body: laboratory['level_id'] for laboratory in contract.get('laboratories', [])
                     for body in laboratory['furniture_body_ids']})
    for name, body in bodies.items():
        prefix = name.split('__', 1)[0]
        body['_walkthrough_level'] = body.get('level_id', assigned.get(name, prefix if prefix in levels else None))
    return bodies


def native_face_mesh(shape, deflection_mm, angular_deflection_rad, MeshPart):
    """Mesh once with declared tolerances and smooth only within a BRep face.

    MeshPart's explicit angular tolerance avoids inheriting extremely fine
    manufacturer triangulation caches.  ``cleaned`` removes triangulations,
    while retaining the same BRep surfaces and topology.  Each original face
    gets its own normal accumulation, preserving sharp native boundaries.
    """
    clean = shape.cleaned()
    reference = MeshPart.meshFromShape(Shape=clean, LinearDeflection=deflection_mm,
        AngularDeflection=angular_deflection_rad, Relative=False, Segments=True)
    mesh_points, mesh_facets = reference.Topology
    segments = [reference.getSegment(i) for i in range(reference.countSegments())]
    covered = [index for segment in segments for index in segment]
    if (len(segments) != len(clean.Faces) or len(covered) != len(set(covered))
            or set(covered) != set(range(len(mesh_facets)))):
        raise ValueError('Native mesh must retain every original BRep face segment exactly once')
    vertices, triangles, normals = [], [], []
    for segment in segments:
        indexes = sorted({index for facet in segment for index in mesh_facets[facet]})
        local = {index: i for i, index in enumerate(indexes)}
        points = [tuple(mesh_points[index]) for index in indexes]
        facets = [[local[index] for index in mesh_facets[facet]] for facet in segment]
        sums = [[0., 0., 0.] for point in points]
        for facet in facets:
            a, b, c = (points[i] for i in facet)
            u, v = [b[i]-a[i] for i in range(3)], [c[i]-a[i] for i in range(3)]
            cross = (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])
            for index in facet:
                for axis in range(3):
                    sums[index][axis] += cross[axis]
        offset = len(vertices)
        for point, normal in zip(points, sums):
            length = math.sqrt(sum(value*value for value in normal))
            # A zero-area seam vertex can be unused by any valid triangle;
            # MeshBuilder omits the degenerate triangles which contain it.
            direction = tuple(value/length for value in normal) if length > 1e-12 else (0., 0., 1.)
            vertices.append(point)
            normals.append(direction)
        triangles.extend([[offset+int(index) for index in facet] for facet in facets])
    if len(triangles) != reference.CountFacets:
        raise ValueError('Native-face triangulations differ from the complete BRep mesh')
    return vertices, triangles, normals


def rigid_point(matrix, point, vector=False):
    return tuple(sum(matrix[axis][column]*point[column] for column in range(3))
                 +(0 if vector else matrix[axis][3]) for axis in range(3))


def validate_rigid(matrix):
    if (not isinstance(matrix, list) or len(matrix) != 4
            or any(not isinstance(row, list) or len(row) != 4 for row in matrix)
            or any(type(value) not in (int, float) or not math.isfinite(value) for row in matrix for value in row)
            or matrix[3] != [0, 0, 0, 1]):
        raise ValueError('Finite rigid placement matrix required')
    columns = [[matrix[row][column] for row in range(3)] for column in range(3)]
    if any(abs(sum(a*b for a, b in zip(columns[i], columns[j]))-(1 if i == j else 0)) > 1e-8
           for i in range(3) for j in range(3)):
        raise ValueError('Equipment placement must not scale or shear native geometry')
    a, b, c = columns
    determinant = a[0]*(b[1]*c[2]-b[2]*c[1])-a[1]*(b[0]*c[2]-b[2]*c[0])+a[2]*(b[0]*c[1]-b[1]*c[0])
    if determinant < 1-1e-8:
        raise ValueError('Equipment placement must preserve handedness')


def rigid_bounds(matrix, bounds):
    points = [rigid_point(matrix, [bounds['max' if bits & (1 << axis) else 'min'][axis]
                                  for axis in range(3)]) for bits in range(8)]
    return {'min': [min(point[axis] for point in points) for axis in range(3)],
            'max': [max(point[axis] for point in points) for axis in range(3)]}


def combine_scenes(building, equipment):
    """Join already world-placed display arrays without another geometry source."""
    if any(scene.get('coordinate_frame') != 'building_presentation' or scene.get('units') != 'mm'
           or scene.get('up_axis') != 'Z' or scene.get('handedness') != 'right' for scene in (building, equipment)):
        raise ValueError('Both mesh inputs must already use the same building frame and units')
    result = dict(building)
    vertex_offset, index_offset = building['vertex_count'], building['index_count']
    for key, kind in [('positions_base64', 'f'), ('normals_base64', 'f'), ('indices_base64', 'I')]:
        arrays = []
        for scene in (building, equipment):
            values = array(kind)
            values.frombytes(base64.b64decode(scene[key], validate=True))
            if sys.byteorder != 'little':
                values.byteswap()
            arrays.append(values)
        if kind == 'I':
            arrays[1] = array('I', (value+vertex_offset for value in arrays[1]))
        arrays[0].extend(arrays[1])
        result[key] = packed(arrays[0])
    result['groups'] = building['groups']+[
        {**group, 'index_start': group['index_start']+index_offset} for group in equipment['groups']]
    if len({group['id'] for group in result['groups']}) != len(result['groups']):
        raise ValueError('Building and equipment native body IDs must be disjoint')
    for key in ('vertex_count', 'index_count', 'native_body_count', 'native_face_count', 'degenerate_triangles_omitted'):
        result[key] = building[key]+equipment[key]
    result['maximum_float32_error_mm'] = max(building['maximum_float32_error_mm'], equipment['maximum_float32_error_mm'])
    result['bounds_mm'] = {key: [operation(scene['bounds_mm'][key][axis] for scene in (building, equipment))
        for axis in range(3)] for key, operation in [('min', min), ('max', max)]}
    result['equipment_instances'] = equipment['equipment_instances']
    result['auxiliary_instances'] = equipment['auxiliary_instances']
    result['equipment_placement_checks'] = equipment['equipment_placement_checks']
    result['equipment_tessellation_deflection_mm'] = equipment['linear_tessellation_deflection_mm']
    result['scope'] = 'One building frame: checked native building plus rigidly placed checked L01 equipment; no duplicated laboratory shell'
    return result


def equipment_placement_checks(groups, laboratories, wall_tolerance):
    import relative_floorplan as floor
    checks = []
    for laboratory in laboratories:
        polygon = laboratory['interior_polygon_mm']
        sign = 1 if floor.signed_area(polygon) > 0 else -1
        for device in laboratory['device_instances']:
            bodies = [group for group in groups if group.get('laboratory_id') == laboratory['id']
                      and (group['instance_id'] == device['id'] or group.get('supporting_device_id') == device['id'])]
            if not bodies:
                raise ValueError('Missing native equipment instance: '+device['id'])
            bounds = {key: [operation(group['bounds_mm'][key][axis] for group in bodies)
                           for axis in range(3)] for key, operation in [('min', min), ('max', max)]}
            points = [[bounds[x][0], bounds[y][1]] for x in ('min', 'max') for y in ('min', 'max')]
            clearance = min(sign*((b[0]-a[0])*(point[1]-a[1])-(b[1]-a[1])*(point[0]-a[0]))/math.dist(a, b)
                for a, b in zip(polygon, polygon[1:]+polygon[:1]) for point in points)
            if clearance < -wall_tolerance-1e-6 or not device['host_anchor_checked']:
                raise ValueError('Native laboratory equipment loses room or host: '+device['id'])
            checks.append({'laboratory_id': laboratory['id'], 'instance_id': device['id'],
                'body_count': len(bodies), 'bounds_mm': bounds, 'host': device['host'],
                'host_anchor_checked': device['host_anchor_checked'], 'minimum_room_clearance_mm': clearance,
                'wall_face_tolerance_mm': wall_tolerance, 'passed': True,
                'scope': 'Conservative native instance bounds in the source room; host anchor and plane from the shared placement compiler'})
    return checks


def native_equipment_bindings(laboratories):
    """Include the functional arm risers produced by the same layout definition."""
    import lab_layout_model as layout
    result = []
    for laboratory in laboratories:
        if not laboratory.get('layout_source'):
            continue
        devices = laboratory['device_instances']
        result.extend((laboratory, device) for device in devices)
        source = json.loads(project_path(laboratory['layout_source']['source']).read_text())
        for prop in layout.primitives(source):
            owners = [device for device in devices if device['asset'] == 'arm' and device['host'] == prop['host']
                      and all(abs(device['standalone_pose'][axis][3]-prop['xyz'][axis]) < 1e-7 for axis in (0, 1))]
            if len(owners) != 1:
                raise ValueError('A functional layout support needs one source arm owner: '+prop['id'])
            if owners[0].get('direct_mount'):
                continue
            result.append((laboratory, {**owners[0], 'id': prop['id'],
                'body_prefix': laboratory['id']+'_'+prop['id']+'_', 'supporting_device_id': owners[0]['id']}))
    return result


def equipment_link_placements(laboratory, device):
    """Place the checked native arm bodies in a binding's parked configuration."""
    import lab_layout_model as layout
    import robot_spec as robot

    if 'park_joints_deg' not in device:
        return {}
    source = json.loads(project_path(laboratory['layout_source']['source']).read_text())
    item = next(item for item in source['instances'] if item['id'] == device['id'])
    arm = layout.instance_source(source, item)
    before = robot.forward(arm, item['joints_deg'])
    after = robot.forward(arm, device['park_joints_deg'])
    local_from_standalone = robot.inverse(device['standalone_pose'])
    result = {}
    for link in robot.expanded(arm)['links']:
        name = link['id']
        matrix = robot.multiply(robot.multiply(device['world_pose'], after[name]),
                                robot.multiply(robot.inverse(before[name]), local_from_standalone))
        validate_rigid(matrix)
        for operation in link['recipe']:
            if operation['action'] == 'create':
                result[operation['body']] = matrix
    return result


def export_scene(scene, report, path, deflection_mm, App, geo, angular_deflection_rad=.35, laboratories=None):
    import MeshPart
    styles = native_styles(path)
    if scene == 'building':
        expected = building_manifest(report)
    else:
        expected = {entry['body']: entry for entry in report['layout_validation']['scene_geometry']}
        if len(expected) != report['layout_validation']['body_count']:
            raise ValueError('L01 proof has an incomplete native body manifest')
    doc = App.openDocument(str(path))
    try:
        objects = geo.features(doc)
        names = [obj.SourceBody for obj in objects]
        if len(names) != len(set(names)) or set(names) != set(expected) or set(styles) != set(expected):
            raise ValueError('Native final body identities differ from the checked '+scene+' manifest')
        mesh = MeshBuilder()
        native_faces = 0
        devices = native_equipment_bindings(laboratories or [])
        for laboratory, device in devices:
            validate_rigid(device['transform'])
        parked_links = {(laboratory['id'], device['id']): equipment_link_placements(laboratory, device)
                        for laboratory, device in devices if 'park_joints_deg' in device}
        coverage = {laboratory['id']+'.'+device['id']: 0 for laboratory, device in devices}
        for obj in sorted(objects, key=lambda entry: entry.SourceBody):
            name = obj.SourceBody
            match = [(laboratory, device) for laboratory, device in devices if name.startswith(device['id']+'__')]
            if laboratories is not None and not match:
                continue
            if len(match) > 1:
                raise ValueError('Ambiguous native equipment instance: '+name)
            shape = geo.world_shape(obj)
            if shape.isNull() or not shape.isValid() or not shape.Solids:
                raise ValueError('Invalid final native body: '+name)
            native_faces += len(shape.Faces)
            points, triangles, normals = native_face_mesh(shape, deflection_mm, angular_deflection_rad, MeshPart)
            bb = shape.BoundBox
            bounds = {'min': [bb.XMin, bb.YMin, bb.ZMin], 'max': [bb.XMax, bb.YMax, bb.ZMax]}
            role = str(getattr(obj, 'ModelRole', expected[name].get('role', 'native_geometry')))
            identity, level = name, expected[name].get('_walkthrough_level')
            instance_id = str(getattr(obj, 'LayoutInstance', getattr(obj, 'RigidLink', '')))
            if match:
                laboratory, device = match[0]
                body = name[len(device['id']+'__'):]
                transform = device['transform']
                park = parked_links.get((laboratory['id'], device['id']))
                if park:
                    transform = park[body.split('__Solid', 1)[0]]
                points = [rigid_point(transform, point) for point in points]
                normals = [rigid_point(transform, normal, vector=True) for normal in normals]
                bounds = rigid_bounds(transform, bounds)
                identity = device['body_prefix']+body
                level, instance_id = laboratory['level_id'], device['id']
                coverage[laboratory['id']+'.'+instance_id] += 1
            mesh.add(identity, points, triangles, styles[name], normals=normals,
                     role=role, level_id=level, instance_id=instance_id, bbox=bounds)
            if match:
                mesh.groups[-1].update(laboratory_id=laboratory['id'], original_body_id=name)
                if device.get('supporting_device_id'):
                    mesh.groups[-1]['supporting_device_id'] = device['supporting_device_id']
        if devices:
            for laboratory, device in devices:
                key = laboratory['id']+'.'+device['id']
                if coverage[key] != report['layout_validation']['instance_metrics'][device['id']]['body_count']:
                    raise ValueError('Incomplete native equipment coverage: '+key)
        result = mesh.result()
        result.update({'coordinate_frame': 'building_presentation' if scene == 'building' or devices else 'l01_local',
                       'units': 'mm', 'up_axis': 'Z', 'handedness': 'right',
                       'linear_tessellation_deflection_mm': deflection_mm,
                       'angular_tessellation_deflection_rad': angular_deflection_rad,
                       'normals': 'Area-weighted within each original BRep face; sharp face boundaries retained',
                       'native_triangulation_cache': 'Cleared before explicit tolerance meshing; BRep unchanged',
                       'native_face_count': native_faces,
                       'native_body_count': len(mesh.groups), 'native_revision': report['revision'],
                       'scope': 'Final native placed Boolean BRep surfaces; Float32 display mesh, no box substitutes'})
        if devices:
            auxiliary = {laboratory['id']+'.'+device['id'] for laboratory, device in devices if device.get('supporting_device_id')}
            result['equipment_instances'] = [{'id': key, 'body_count': value} for key, value in coverage.items() if key not in auxiliary]
            result['auxiliary_instances'] = [{'id': key, 'body_count': value} for key, value in coverage.items() if key in auxiliary]
        return result
    finally:
        App.closeDocument(doc.Name)


def export(building_report, lab_report, output, building_deflection_mm=3., lab_deflection_mm=1., angular_deflection_rad=.35):
    for value in (building_deflection_mm, lab_deflection_mm):
        if not math.isfinite(value) or not 0 < value <= 10:
            raise ValueError('Tessellation deflection must be finite in (0, 10] mm')
    if not math.isfinite(angular_deflection_rad) or not 0 < angular_deflection_rad <= .5:
        raise ValueError('Angular tessellation deflection must be finite in (0, 0.5] radians')
    reports = {'building': project_path(building_report), 'lab': project_path(lab_report)}
    before = {name: digest(path) for name, path in reports.items()}
    checked = {name: checked_report(path, name) for name, path in reports.items()}
    import building_stack as stack
    building_spec = stack.load(project_path(checked['building']['source']))
    building_parameters = stack.parameters(building_spec)
    laboratories = stack.interfaces(building_spec, building_parameters)['laboratories']
    import FreeCAD as App
    sys.path.insert(0, str(ROOT/'scripts/freecad'))
    import solidcraftbot_freecad as geo
    scenes = {}
    pins = {}
    for scene, report in checked.items():
        native = project_path(report['files']['freecad'])
        scenes[scene] = export_scene(scene, report, native,
            building_deflection_mm if scene == 'building' else lab_deflection_mm, App, geo, angular_deflection_rad,
            laboratories=laboratories if scene == 'lab' else None)
        for name, value in report['source_files_sha256'].items():
            if name in pins and pins[name] != value:
                raise ValueError('Conflicting source revisions in the native scenes: '+name)
            pins[name] = value
        pins[str(reports[scene].relative_to(ROOT))] = before[scene]
        pins[report['files']['freecad']] = report['artifact_sha256']['freecad']
        for key, name in report['files'].items():
            pins[name] = report['artifact_sha256'][key]
        checked_report(reports[scene], scene)
        if digest(reports[scene]) != before[scene]:
            raise ValueError('A native build report changed during export')
    pins[str(Path(__file__).relative_to(ROOT))] = digest(__file__)
    scenes['lab']['equipment_placement_checks'] = equipment_placement_checks(
        scenes['lab']['groups'], laboratories, building_parameters['display_thickness']/2)
    scenes = {'building': combine_scenes(scenes['building'], scenes['lab'])}
    result = {'format': FORMAT, 'scenes': scenes, 'source_files_sha256': pins,
              'limitations': ['Native CAD qualification remains the scope of each pinned build report.',
                  'Tessellation and Float32 positions approximate display surfaces; they are not collision or navigation proofs.',
                  'L01 equipment is rigidly instanced into a source-derived building room variant; surveyed registration remains unqualified.',
                  'The native building CAD contains laboratory furniture; equipment instancing is implemented in this browser exporter only.']}
    verify_pins(pins)
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, separators=(',', ':'), allow_nan=False)+'\n', encoding='utf-8')
    print('Exported '+', '.join(name+': '+str(scene['native_body_count'])+' native bodies, '+str(scene['index_count']//3)+' triangles'
                              for name, scene in scenes.items()), flush=True)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--building-report', default=str(ROOT/'cad/building-stack/shared-build-report.json'))
    parser.add_argument('--lab-report', default=str(ROOT/'cad/lab-layout-l01/shared-build-report.json'))
    parser.add_argument('--out', required=True)
    parser.add_argument('--building-deflection-mm', type=float, default=3.)
    parser.add_argument('--lab-deflection-mm', type=float, default=1.)
    parser.add_argument('--angular-deflection-rad', type=float, default=.35)
    args = parser.parse_args(argv)
    return export(args.building_report, args.lab_report, args.out, args.building_deflection_mm, args.lab_deflection_mm, args.angular_deflection_rad)


if __name__ == '__main__':
    # FreeCAD's module initialization adjusts __main__ in the bundled runtime;
    # keep the adapter's pure helper globals in its ordinary imported module.
    import export_building_walkthrough_freecad as adapter
    adapter.main()
