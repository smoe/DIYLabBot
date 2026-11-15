"""Tessellate checked final native bodies for two separate walkthrough scenes.

This adapter reads final placed BReps, including their Boolean openings.  It
does not rebuild walls from their bounds or register the local L01 room into
the uncalibrated building frame.  Importing the packing/verification helpers
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


def export_scene(scene, report, path, deflection_mm, App, geo, angular_deflection_rad=.35):
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
        for obj in sorted(objects, key=lambda entry: entry.SourceBody):
            name = obj.SourceBody
            shape = geo.world_shape(obj)
            if shape.isNull() or not shape.isValid() or not shape.Solids:
                raise ValueError('Invalid final native body: '+name)
            native_faces += len(shape.Faces)
            points, triangles, normals = native_face_mesh(shape, deflection_mm, angular_deflection_rad, MeshPart)
            bb = shape.BoundBox
            bounds = {'min': [bb.XMin, bb.YMin, bb.ZMin], 'max': [bb.XMax, bb.YMax, bb.ZMax]}
            role = str(getattr(obj, 'ModelRole', expected[name].get('role', 'native_geometry')))
            mesh.add(name, points, triangles, styles[name], normals=normals,
                     role=role, level_id=expected[name].get('_walkthrough_level'),
                     instance_id=str(getattr(obj, 'LayoutInstance', getattr(obj, 'RigidLink', ''))), bbox=bounds)
        result = mesh.result()
        result.update({'coordinate_frame': 'building_presentation' if scene == 'building' else 'l01_local',
                       'units': 'mm', 'up_axis': 'Z', 'handedness': 'right',
                       'linear_tessellation_deflection_mm': deflection_mm,
                       'angular_tessellation_deflection_rad': angular_deflection_rad,
                       'normals': 'Area-weighted within each original BRep face; sharp face boundaries retained',
                       'native_triangulation_cache': 'Cleared before explicit tolerance meshing; BRep unchanged',
                       'native_face_count': native_faces,
                       'native_body_count': len(objects), 'native_revision': report['revision'],
                       'scope': 'Final native placed Boolean BRep surfaces; Float32 display mesh, no box substitutes'})
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
    import FreeCAD as App
    sys.path.insert(0, str(ROOT/'scripts/freecad'))
    import solidcraftbot_freecad as geo
    scenes = {}
    pins = {}
    for scene, report in checked.items():
        native = project_path(report['files']['freecad'])
        scenes[scene] = export_scene(scene, report, native,
            building_deflection_mm if scene == 'building' else lab_deflection_mm, App, geo, angular_deflection_rad)
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
    result = {'format': FORMAT, 'scenes': scenes, 'source_files_sha256': pins,
              'limitations': ['Native CAD qualification remains the scope of each pinned build report.',
                  'Tessellation and Float32 positions approximate display surfaces; they are not collision or navigation proofs.',
                  'Building presentation and local L01 are separate frames; no unmeasured L01-to-building registration is asserted.']}
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
