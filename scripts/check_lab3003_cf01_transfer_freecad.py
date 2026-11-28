"""Check the Lab 3.003 transfer against native solids and bounded PVA motion."""
import argparse
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
import itertools
import json
import math
from pathlib import Path
import sys

import centrifuge_model as cf
import centrifuge_robot_pickup as pickup
import export_building_walkthrough_freecad as mesh
import lab_layout_model as layout
from lab_transfer_model import obb
import robot_spec as robot
import tr01_workcell as workcell
from sample_motion import motion


ROOT = Path(__file__).resolve().parents[1]
VERIFIER_SHA256 = robot.digest(Path(__file__).resolve())
FORMAT = 'solidcraftbot.lab3003-cf01-transfer-collision/1'
PROGRAM = 'solidcraftbot.lab3003-cf01-arm-program/1'
NON_SOLIDS = {'planning_overlay', 'viewing_cone', 'room_marker', 'marker',
              'surface_marking_visual_only'}
PAD_IDS = {'Tool.LeftFingerPad', 'Tool.RightFingerPad'}
VOLUME_EPS_MM3 = 0.001
NUMERICAL_MARGIN_MM = 0.00001
PVA = ('positions_rad', 'velocities_rad_s', 'accelerations_rad_s2')
JAW_PVA = ('positions_mm', 'velocities_mm_s', 'accelerations_mm_s2')
STAGES = {'approach', 'closing', 'loaded', 'release', 'withdraw'}


def bbox(shape):
    box = shape.BoundBox
    return (box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax)


def lower_distance(a, b):
    return math.hypot(max(0., a[0]-b[3], b[0]-a[3]),
                      max(0., a[1]-b[4], b[1]-a[4]),
                      max(0., a[2]-b[5], b[2]-a[5]))


def corners(box):
    return itertools.product(*zip(box[:3], box[3:]))


def _swept_box(box, frame, joint):
    """Enclose a rigid shape for the whole travel of its single station joint."""
    minima = [math.inf]*3
    maxima = [-math.inf]*3
    lo, hi = joint['limits']
    origin = joint['origin']
    axis = joint['axis']
    if joint['type'] not in {'revolute', 'slider'}:
        raise ValueError('A native station sweep requires a rigid revolute or slider joint')
    if joint['type'] == 'revolute':
        lo, hi = math.radians(lo), math.radians(hi)
    for point in corners(box):
        if joint['type'] == 'slider':
            endpoints = [robot.transform(frame, cf.plus(point, axis, value)) for value in (lo, hi)]
            for i, coordinate in enumerate(zip(*endpoints)):
                minima[i] = min(minima[i], *coordinate)
                maxima[i] = max(maxima[i], *coordinate)
            continue
        offset = [value-zero for value, zero in zip(point, origin)]
        axial = sum(value*direction for value, direction in zip(offset, axis))
        center = robot.transform(frame, cf.plus(origin, axis, axial))
        radial = [value-axial*direction for value, direction in zip(offset, axis)]
        cross = [axis[1]*radial[2]-axis[2]*radial[1],
                 axis[2]*radial[0]-axis[0]*radial[2],
                 axis[0]*radial[1]-axis[1]*radial[0]]
        for i, row in enumerate(frame[:3]):
            a = sum(x*y for x, y in zip(row, radial))
            b = sum(x*y for x, y in zip(row, cross))
            if hi-lo >= math.tau:
                amplitude = math.hypot(a, b)
                probes = (-amplitude, amplitude)
            else:
                peak = math.atan2(b, a)
                extrema = (peak+k*math.pi for k in
                           range(math.ceil((lo-peak)/math.pi), math.floor((hi-peak)/math.pi)+1))
                probes = [a*math.cos(angle)+b*math.sin(angle) for angle in (lo, hi, *extrema)]
            minima[i] = min(minima[i], center[i]+min(probes))
            maxima[i] = max(maxima[i], center[i]+max(probes))
    return tuple([value-NUMERICAL_MARGIN_MM for value in minima]+
                 [value+NUMERICAL_MARGIN_MM for value in maxima])


@dataclass(frozen=True)
class Body:
    id: str
    shape: object
    box: tuple
    kind: str
    link: int = 0
    radii: tuple = ()
    jaw_factor: float = 0.
    enclosure: object = None


def body(identity, shape, kind, link=0, radii=(), jaw_factor=0., enclosure=None):
    return Body(identity, shape, bbox(shape), kind, link, radii, jaw_factor, enclosure)


def directional_lower_distance(a, b):
    """Projection gaps of enclosing boxes give lower bounds on BRep distance."""
    first, second = a.enclosure, b.enclosure
    if first is None:
        return 0.
    best = 0.
    for own, other, other_box in ((first, second, b.box), (second, first, a.box)):
        if own is None:
            continue
        other_center = other['center'] if other else [(lo+hi)/2 for lo, hi in zip(other_box, other_box[3:])]
        delta = [x-y for x, y in zip(own['center'], other_center)]
        for axis, radius in zip(own['axes'], own['half']):
            projection = abs(sum(x*y for x, y in zip(axis, delta)))
            if other:
                reach = sum(size*abs(sum(x*y for x, y in zip(axis, direction)))
                            for size, direction in zip(other['half'], other['axes']))
            else:
                reach = sum(abs(value)*(hi-lo)/2 for value, lo, hi in zip(axis, other_box, other_box[3:]))
            best = max(best, projection-radius-reach-NUMERICAL_MARGIN_MM)
    return best


def _verified_artifact(path, expected):
    path = Path(path).resolve()
    if len(expected) != 64 or robot.digest(path) != expected:
        raise ValueError('Changed native input: '+str(path))
    return path


class Lab3003TransferOracle:
    """Independent FreeCAD collision query using the cassette's actual vessel."""

    def __init__(self, lab, arm_binding, *,
                 arm_native, arm_sha256, vehicle_native, vehicle_sha256,
                 station_native, station_sha256, samples=None,
                 building_report=None, building_root=None, lab_report=None, lab_root=None,
                 stock=None, dock_native=None, dock_sha256=None):
        import FreeCAD as App
        sys.path.insert(0, str(ROOT/'scripts/freecad'))
        import solidcraftbot_freecad as native
        from build_synthetic_lab_scene_freecad import primitive
        from build_tr01_workcell_freecad import moved as placed

        self.app, self.native, self.placed = App, native, placed
        devices = {device['id']: device for device in lab['device_instances']}
        self.cf_frame = devices['CF01']['bound_pose']
        self.vehicle_frame = devices['TR01']['bound_pose']
        self.arm_spec = arm_binding['arm']
        self.excluded_arm = set(arm_binding.get('exclude_bodies', []))
        self.park = arm_binding['park_joints_deg']
        self.source_pins = dict(arm_binding.get('source_files_sha256', {}))
        for name in ('build_synthetic_lab_scene_freecad.py', 'build_tr01_workcell_freecad.py',
                     'centrifuge_robot_pickup.py', 'lab_transfer_model.py', 'sample_motion.py',
                     'tr01_workcell.py'):
            path = ROOT/'scripts'/name
            self.source_pins[path.relative_to(ROOT).as_posix()] = robot.digest(path)
        motion_path = Path(motion.__file__).resolve()
        self.source_pins[motion_path.relative_to(ROOT).as_posix()] = robot.digest(motion_path)
        self.samples = dict(samples or [('B2_Tube01', 1), ('B2_Tube07', 7)])
        if len(self.samples) != len(set(self.samples.values())):
            raise ValueError('Each delivered vessel needs its own rotor slot')

        scene = pickup.load()
        work = json.loads(workcell.SOURCE.read_text())
        self.cassette_gap_mm = work['gripper_overrides']['open_gap_mm']
        arm_base = arm_binding['bound_pose']
        scene['arm_fixture'].update(position_mm=[row[3] for row in arm_base[:3]],
                                    yaw_deg=math.degrees(math.atan2(arm_base[1][0], arm_base[0][0])))
        self.kin = pickup.Kinematics(self.arm_spec, scene)
        self.gripper = scene['gripper']
        self.tool = [({**part}, primitive(part['shape'])) for part in pickup.gripper_parts(scene, {})]
        self.park_fk = robot.forward(self.arm_spec, self.park)
        if any(self.park):
            raise ValueError('The arm displacement bound uses the certified zero reference.')
        self.park_tool = self.kin.tool(self.park)
        self.link_ids = [link['id'] for link in self.arm_spec['links']]
        self.axes = [tuple(row[3] for row in robot.frame(joint, self.kin.p)[:3])
                     for joint in self.arm_spec['joints']]
        self.axis_hops = [math.dist(a, b) for a, b in zip(self.axes, self.axes[1:])]
        self.arm = []

        self.native_artifacts = {}
        arm = self._artifact(arm_native, arm_sha256)
        vehicle = self._artifact(vehicle_native, vehicle_sha256)
        station = self._artifact(station_native, station_sha256)
        self._load_arm(arm)
        if stock is None:
            building = self._build_artifact(building_report, building_root, 'building')
            laboratory = self._build_artifact(lab_report, lab_root, 'lab')
            self.fixed = self._load_environment(building, laboratory, lab, devices)
        else:
            dock = self._artifact(dock_native, dock_sha256)
            self.fixed = self._load_dock(dock, stock, lab)
        self._load_vehicle(vehicle, lab)
        self._load_station(station, lab)
        self._tool_body_cache = {}
        self._cargo_body_cache = {}
        self._rigid_contact_cache = {}
        self._local_bounds = {identity: bbox(shape) for _, identity, shape, _, _ in self.arm}
        self._local_bounds.update({'Tool.'+part['id']: bbox(shape) for part, shape in self.tool})
        self._local_bounds.update({'Carried.'+identity: self.vehicle[identity].box for identity in self.samples})
        self._static_cache = {}

    @classmethod
    def from_stock(cls, stock_preview, arm_report, dock_certificate, pusher_report):
        """Start quickly using the exact dock BReps plus complete stock body bounds."""
        import build_lab3003_armc_preview as preview
        import lab3003_armc_variant as variant

        stock_preview = Path(stock_preview).resolve()
        payload, stock = preview.checked_stock(stock_preview)
        lab, = (room for room in payload['laboratories'] if room['id'] == 'Lab3003')
        binding = variant.bind(lab)
        arm_report, dock_certificate, pusher_report = map(
            lambda p: Path(p).resolve(), (arm_report, dock_certificate, pusher_report))
        arm, artifacts = variant.read_native(arm_report, binding)
        dock = json.loads(dock_certificate.read_text())
        pusher = json.loads(pusher_report.read_text())
        mesh.verify_pins(dock['source_files_sha256'])
        mesh.verify_pins(pusher['source_files_sha256'])
        if (arm['stock_html_sha256'] != stock['html_sha256'] or
                dock.get('passed') is not True or dock.get('cover_on') is not True or
                dock['geometry_changes']['body_ids'] or
                dock['native_model']['sha256'] != stock['native_model']['sha256'] or
                pusher.get('lowering_geometry_passed') is not True or
                pusher.get('local_tool_escape_found') is not True):
            raise ValueError('Same checked stock, complete dock, and supported lowering proof required')
        if [(row['id'], row['slot']) for row in pusher['samples']] != [('B2_Tube01', 1), ('B2_Tube07', 7)]:
            raise ValueError('The lowering evidence must cover both exact tube identities and pockets')
        native = {Path(path).name: (path, sha)
                  for path, sha in pusher['native_inputs_sha256'].items()}
        vehicle, vehicle_hash = native['floor-mixed.FCStd']
        station, station_hash = native['centrifuge-native.FCStd']
        result = cls(lab, binding, stock=payload, dock_native=dock['native_model']['file'],
                     dock_sha256=dock['native_model']['sha256'], arm_native=artifacts['freecad'],
                     arm_sha256=arm['artifacts']['freecad']['sha256'],
                     vehicle_native=vehicle, vehicle_sha256=vehicle_hash,
                     station_native=station, station_sha256=station_hash)
        result.stock_html_sha256 = stock['html_sha256']
        result.native_artifacts.update({str(path): robot.digest(path) for path in (
            stock_preview/'index.html', stock_preview/'tr01-preview-report.json', arm_report,
            artifacts['mesh'], dock_certificate, pusher_report)})
        result.source_pins.update(arm['source_files_sha256'])
        result.source_pins.update(dock['source_files_sha256'])
        result.source_pins.update(pusher['source_files_sha256'])
        return result

    def _artifact(self, path, expected):
        path = _verified_artifact(path, expected)
        self.native_artifacts[str(path)] = expected
        return path

    def _build_artifact(self, path, root, scene):
        path = Path(path).resolve()
        root = Path(root).resolve()
        report = mesh.checked_report(path, scene, root=root)
        self.native_artifacts[str(path)] = robot.digest(path)
        return self._artifact(root/report['files']['freecad'], report['artifact_sha256']['freecad'])

    def _shapes(self, path):
        document = self.app.openDocument(str(path))
        try:
            return [(obj.SourceBody, getattr(obj, 'RigidLink', ''), obj.ModelRole,
                     self.native.world_shape(obj)) for obj in self.native.features(document)
                    if obj.ModelRole not in NON_SOLIDS]
        finally:
            self.app.closeDocument(document.Name)

    def _radii(self, reference_box, link):
        if link == 0:
            return (0.,)*6
        tail = max(math.dist(point, self.axes[link-1]) for point in corners(reference_box))
        return tuple(tail + sum(self.axis_hops[k:link-1]) if k < link else 0. for k in range(6))

    def _load_arm(self, path):
        expected = {op['body']: link['id'] for link in robot.expanded(self.arm_spec)['links']
                    for op in link['recipe'] if op['action'] == 'create' and
                    op['role'] not in NON_SOLIDS and op['body'] not in self.excluded_arm}
        found = set()
        for identity, link, _, shape in self._shapes(path):
            source = identity.split('__Solid', 1)[0]
            if source in self.excluded_arm:
                continue
            if source not in expected or expected[source] != link:
                raise ValueError('Unexpected native ArmC body or link: '+identity)
            if shape.isNull() or not shape.isValid() or not shape.Solids:
                raise ValueError('Invalid native ArmC solid: '+identity)
            found.add(source)
            index = self.link_ids.index(link)
            # At the exact variant reference the BReps are in the arm base frame.
            local = self.placed(shape, robot.inverse(self.park_fk[link]))
            reference = self.placed(local, self.park_fk[link])
            self.arm.append((link, 'ArmC.'+identity, local, index, self._radii(bbox(reference), index)))
        if found != set(expected) or len(self.arm) != len({entry[1] for entry in self.arm}):
            raise ValueError('ArmC native body coverage is incomplete or duplicated')

    def _load_environment(self, building, laboratory, lab, devices):
        inverse = robot.inverse(lab['transform'])
        static = []
        anchor = [row[3] for row in self.kin.base[:3]]
        radius = max(entry[4][0] for entry in self.arm) + 225.
        query = tuple([anchor[i]-radius for i in range(3)]+[anchor[i]+radius for i in range(3)])
        world_points = [robot.transform(lab['transform'], point) for point in corners(query)]
        coarse = tuple([min(p[i] for p in world_points) for i in range(3)]+
                       [max(p[i] for p in world_points) for i in range(3)])
        for identity, _, _, shape in self._shapes(building):
            if lower_distance(bbox(shape), coarse) == 0.:
                static.append(body(identity, self.placed(shape, inverse), 'building'))
        for identity, _, _, shape in self._shapes(laboratory):
            prefix, separator, part = identity.partition('__')
            if not separator or prefix in {'ArmC', 'MountArmC', 'CF01', 'TR01'} or prefix not in devices:
                continue
            placed = self.placed(shape, robot.multiply(inverse, devices[prefix]['transform']))
            if lower_distance(bbox(placed), query) == 0.:
                static.append(body(devices[prefix]['body_prefix']+part, placed, 'fixture'))
        return static

    def _load_dock(self, dock, stock, lab):
        """Load exact local solids, and preserve missing bodies as padded box bounds."""
        doc = self.app.openDocument(str(dock))
        prefixes = ('Lab3003_ArmC_', 'Lab3003_CF01_', 'TR01_', 'Lab3003_TR01_')
        try:
            local = {obj.Label: body(obj.Label, self.native.world_shape(obj), 'dock')
                     for obj in doc.Objects if obj.TypeId == 'Part::Feature' and
                     not obj.Label.startswith(prefixes)}
        finally:
            self.app.closeDocument(doc.Name)
        if 'Lab3003_LeftBench_Worktop' not in local:
            raise ValueError('The checked native dock worktop is missing')

        scene = stock['scenes']['building']
        states = stock['tr01_lap']['fixture_states']
        objects = {obj['id']: obj for obj in stock['objects']}
        owner = {name: obj['id'] for obj in objects.values() for name in obj['moving_body_ids']}
        parents = {}
        inverse = robot.inverse(lab['transform'])
        anchor = tuple(row[3] for row in self.kin.base[:3])
        reach = max(entry[4][0] for entry in self.arm) + 225.
        query_box = (*[v-reach for v in anchor], *[v+reach for v in anchor])

        def fixture_pose(identity):
            if identity not in parents:
                obj = objects[identity]
                state = states.get(identity, obj.get('initial_state', obj['reference_state']))
                angle = obj['states'][state]-obj['states'][obj['reference_state']]
                joint = obj['joint']
                axis = self.app.Vector(*joint['axis'])
                if joint['type'] == 'revolute':
                    rotation = self.app.Rotation(axis, angle)
                    centre = self.app.Vector(*joint['origin_mm'])
                    placement = self.app.Placement(centre-rotation.multVec(centre), rotation)
                elif joint['type'] == 'prismatic':
                    placement = self.app.Placement(axis*angle, self.app.Rotation())
                else:
                    raise ValueError('Unknown stock joint: '+joint['type'])
                if obj.get('parent_object_id'):
                    placement = fixture_pose(obj['parent_object_id']).multiply(placement)
                parents[identity] = placement
            return parents[identity]

        static = list(local.values())
        padding = scene['linear_tessellation_deflection_mm'] + scene['maximum_float32_error_mm']
        for group in scene['groups']:
            name = group['id']
            if (name in local or group['role'] in NON_SOLIDS or
                    name.startswith(prefixes[:2]) or
                    name.startswith(prefixes[3]) and group['role'] not in {'camera_mount', 'camera_envelope'}):
                continue
            bounds = group['bounds_mm']
            pts = list(corners(tuple(bounds['min']+bounds['max'])))
            if name in owner:
                frame = fixture_pose(owner[name])
                pts = [list(frame.multVec(self.app.Vector(*point))) for point in pts]
            pts = [robot.transform(inverse, point) for point in pts]
            box = tuple([min(p[i] for p in pts)-padding for i in range(3)] +
                        [max(p[i] for p in pts)+padding for i in range(3)])
            if lower_distance(box, query_box) == 0.:
                static.append(Body(name, None, box, 'bounds_only'))
        return static

    def _load_vehicle(self, path, lab):
        source = layout.load(validate_builds=False)
        vehicle = next(item for item in source['instances'] if item['id'] == 'TR01')
        provider = layout.provider(vehicle['asset'])
        spec = layout.instance_source(source, vehicle)
        expanded = provider.expanded(spec, provider.parameters(spec), layout.instance_variant(spec, vehicle))
        self.vehicle = {identity: body(identity, self.placed(shape, self.vehicle_frame), 'vehicle')
                        for identity, _, _, shape in self._shapes(path)}
        expected = {entry['id'] for entry in expanded['bodies']}
        if self.vehicle.keys() != expected:
            raise ValueError('Incomplete checked native TR01 geometry')
        self.cargo_axes = {}
        self.grip_widths = {}
        for identity in self.samples:
            shaft = next(op['shape'] for op in expanded['operations']
                         if op['body'] == identity and op['action'] == 'create')
            if shaft['axis'] != [0, 0, 1]:
                raise ValueError('Expected a coaxial vertical cassette tube')
            origin = robot.transform(self.vehicle_frame, shaft['origin'])
            tip = robot.transform(self.vehicle_frame, cf.plus(shaft['origin'], shaft['axis'], shaft['height']))
            self.cargo_axes[identity] = (origin, tip)
            self.grip_widths[identity] = 2.*shaft['radius']

    def _load_station(self, path, lab):
        source = layout.load(validate_builds=False)
        station = next(item for item in source['instances'] if item['id'] == 'CF01')
        self.station = layout.instance_source(source, station)
        self.station_p = cf.parameters(self.station)
        self.station_geometry = cf.expanded(self.station, self.station_p)
        doc = self.app.openDocument(str(path))
        try:
            values = {joint['id']: getattr(doc.Controller, joint['id']).Value
                      for joint in self.station_geometry['joints']}
            cf.validate_pose(self.station_geometry, values)
            self.station_shapes = [
                (obj.SourceBody, obj.RigidLink, self.placed(self.native.world_shape(obj),
                    robot.inverse(pickup.rigid_from_cf(self.station_geometry, obj.RigidLink, values))))
                for obj in self.native.features(doc)
                if obj.ModelRole not in NON_SOLIDS|{'illustrative_tube', 'closed_cap_envelope'}
            ]
        finally:
            self.app.closeDocument(doc.Name)
        expected = {entry['id'] for entry in self.station_geometry['bodies']
                    if entry['role'] not in NON_SOLIDS|{'illustrative_tube', 'closed_cap_envelope'}}
        if not expected <= {entry[0].split('__Solid', 1)[0] for entry in self.station_shapes}:
            raise ValueError('Incomplete checked native CF01 geometry')

    def rotor_angle(self, slot):
        return -360. * (slot - 1) / self.station['rotor']['slots']

    def seated_pose(self, tube_id, slot, rotor_deg, lift_mm=0.):
        """Rigid transform of the original lab-local cassette body to its own pocket."""
        bottom, axis = cf.pocket(self.station, self.station_p, slot)
        rotated = pickup.placement([0., 0., 0.], rotor_deg)
        station = robot.multiply(self.cf_frame, rotated)
        x, y, z = [sum(station[i][j]*axis[j] for j in range(3)) for i in range(3)]
        rotation = self.app.Rotation(self.app.Vector(0., 0., 1.), self.app.Vector(x, y, z)).toMatrix()
        destination = robot.transform(station, cf.plus(bottom, axis, lift_mm))
        source = self.cargo_axes[tube_id][0]
        result = robot.identity()
        for i in range(3):
            for j in range(3):
                result[i][j] = rotation.A[4*i+j]
            result[i][3] = destination[i] - sum(result[i][j]*source[j] for j in range(3))
        return result

    def _static(self, tube_id, stage, rotor_slot, rotor_deg, lid_state, cover_on, seated, lift_mm):
        key = (tube_id, stage, rotor_slot, rotor_deg, lid_state, cover_on, tuple(seated), lift_mm)
        if key not in self._static_cache:
            if rotor_slot != self.samples[tube_id] or not math.isclose(rotor_deg, self.rotor_angle(rotor_slot), abs_tol=1e-8):
                raise ValueError('CF01 transfer requires an exactly indexed assigned rotor slot')
            if lid_state not in {'closed', 'open'} or cover_on and stage in {'closing', 'loaded', 'release', 'withdraw'}:
                raise ValueError('Uncovered cassette and a known stationary lid state required')
            if lift_mm not in {0., self.station_p['lift_travel']} or lift_mm and lid_state != 'open':
                raise ValueError('Only the separately checked extended pusher is supported')
            values = {**cf.pose(self.station, self.station_p, lid_state), 'Rotor': rotor_deg,
                      'Lift': self.station_p['park_gap']+lift_mm if lift_mm else 0., 'TubeLift': 0.}
            cf.validate_pose(self.station_geometry, values)
            frames = {component['id']: robot.multiply(self.cf_frame,
                      pickup.rigid_from_cf(self.station_geometry, component['id'], values))
                      for component in self.station_geometry['components']}
            loaded = set(seated)
            if stage in {'loaded', 'release', 'withdraw'}:
                loaded.add(tube_id)
            obstacles = self.fixed + [
                entry for name, entry in self.vehicle.items()
                if name not in loaded and (name != 'TransportCover' or cover_on)]
            for identity, group, shape in self.station_shapes:
                frame = frames[group]
                box = bbox(shape)
                obstacles.append(body('CF01.'+identity, self.placed(shape, frame), 'station',
                                      enclosure=obb(frame, box[:3], box[3:])))
            for identity in loaded:
                if identity != tube_id or stage in {'release', 'withdraw'}:
                    placement = self.seated_pose(identity, self.samples[identity], rotor_deg,
                                                lift_mm if identity == tube_id else 0.)
                    obstacles.append(body('Seated.'+identity,
                        self.placed(self.vehicle[identity].shape, placement), 'seated'))
            self._static_cache[key] = obstacles
        return self._static_cache[key]

    def _moving(self, joints_deg, gap_mm, tube_id, carried_pose, carried_from_tcp):
        if len(joints_deg) != 6 or not all(math.isfinite(value) and lo <= value <= hi
                for value, (lo, hi) in zip(joints_deg, self.kin.limits)):
            raise ValueError('Every ArmC pose needs six finite in-range joint values')
        if not 0. < gap_mm <= self.gripper['open_gap_mm']+1e-8:
            raise ValueError('Gripper gap outside its checked interval')
        fk = self.kin.forward(joints_deg)
        tool = [row[:] for row in fk[self.arm_spec['flange_reference']['link']]]
        tip = robot.transform(tool, [*self.kin.flange[:2], self.kin.flange[2]+self.kin.length])
        for row, coordinate in zip(tool, tip):
            row[3] = coordinate
        result = [self._moving_body(identity, shape, fk[link], 'arm', index, radii)
                  for link, identity, shape, index, radii in self.arm]
        for spec, shape in self.tool:
            factor = {'Tool': 0., 'FingerLeft': -.5, 'FingerRight': .5}[spec['group']]
            offset = pickup.placement([gap_mm*factor, 0., 0.], 0.)
            identity = 'Tool.'+spec['id']
            if identity not in self._tool_body_cache:
                reference = self.placed(shape, robot.multiply(robot.inverse(self.kin.base), self.park_tool))
                bounds = bbox(reference)
                span = self.gripper['open_gap_mm']*abs(factor)
                enclosing = tuple([v-span for v in bounds[:3]]+[v+span for v in bounds[3:]])
                self._tool_body_cache[identity] = self._radii(enclosing, 6)
            result.append(self._moving_body(identity, shape, robot.multiply(tool, offset), 'tool',
                                            6, self._tool_body_cache[identity], abs(factor)))
        if carried_pose is not None or carried_from_tcp is not None:
            if carried_pose is not None and carried_from_tcp is not None:
                raise ValueError('Use an explicit vessel pose or a fixed TCP attachment')
            reference = self.vehicle[tube_id].shape
            radii = ()
            if carried_from_tcp is not None:
                key = (tube_id, tuple(tuple(row) for row in carried_from_tcp))
                carried_pose = robot.multiply(tool, carried_from_tcp)
                if key not in self._cargo_body_cache:
                    at_park = robot.multiply(robot.multiply(robot.inverse(self.kin.base), self.park_tool),
                                             carried_from_tcp)
                    self._cargo_body_cache[key] = self._radii(bbox(self.placed(reference, at_park)), 6)
                radii = self._cargo_body_cache[key]
            result.append(self._moving_body('Carried.'+tube_id, reference, carried_pose, 'carried', 6, radii))
        return result

    def _moving_body(self, identity, shape, matrix, kind, link, radii, jaw_factor=0.):
        bounds = self._local_bounds[identity]
        enclosure = obb(matrix, bounds[:3], bounds[3:])
        return body(identity, self.placed(shape, matrix), kind, link, radii, jaw_factor, enclosure)

    @staticmethod
    def _rigid_interface(a, b):
        if a.kind == b.kind == 'arm':
            return abs(a.link-b.link) <= 1
        if a.kind == b.kind == 'tool':
            return True
        return a.kind == 'arm' and a.link == 6 and b.kind == 'tool'

    @staticmethod
    def _contact(a, b, tube_id, stage, cassette_departure=False):
        pair = {a.id, b.id}
        target = {'closing': tube_id, 'loaded': 'Carried.'+tube_id, 'release': 'Seated.'+tube_id}.get(stage)
        if target in pair and pair & PAD_IDS:
            return 'gripper_pad_to_active_vessel'
        if a.id == 'ArmC.Base_plate' and b.id == 'Lab3003_LeftBench_Worktop':
            return 'mounted_arm_base_on_worktop'
        if a.id == 'Carried.'+tube_id and b.id == 'CF01.RetractablePusher':
            return 'active_vessel_bottom_at_pusher'
        if cassette_departure and a.id == 'Carried.'+tube_id and b.id == 'B2_Cassette':
            return 'proved_vertical_departure_from_cassette_support'
        return None

    def _pair_geometry(self, a, b, gap_mm, carried_from_tcp):
        """Reuse native geometry only where rigid invariance removes all arm joints."""
        key = None
        if a.link == 0 and b.kind in {'dock', 'building', 'fixture'}:
            key = a.id, b.id
        elif a.kind == 'tool' and b.kind == 'carried' and carried_from_tcp is not None:
            key = a.id, b.id, gap_mm if a.jaw_factor else None, tuple(map(tuple, carried_from_tcp))
        if key is not None and key in self._rigid_contact_cache:
            return self._rigid_contact_cache[key]
        distance = a.shape.distToShape(b.shape)[0]
        overlap = a.shape.common(b.shape).Volume if distance <= NUMERICAL_MARGIN_MM else 0.
        if key is not None:
            self._rigid_contact_cache[key] = distance, overlap
        return distance, overlap

    def pose_clearance(self, joints_deg, *, tube_id, stage, gap_mm, rotor_slot, rotor_deg=None,
                       lid_state='open', cover_on=False, seated=(), carried_pose=None,
                       carried_from_tcp=None, margin_mm=0., q_radius_deg=None, gap_radius_mm=0.,
                       lift_mm=None, overlap_only=False, cassette_departure=False):
        """Check one pose, or certify a neighbourhood with full polynomial coordinate bounds."""
        if stage not in STAGES or tube_id not in self.samples:
            raise ValueError('Known transfer stage and vessel required')
        if (stage == 'loaded') != (carried_from_tcp is not None or carried_pose is not None):
            raise ValueError('Only the gripper-owned stage may have a carried vessel')
        if q_radius_deg is not None and carried_pose is not None:
            raise ValueError('Interval certification requires a rigid TCP attachment')
        if overlap_only and (margin_mm or q_radius_deg is not None or gap_radius_mm):
            raise ValueError('A planning overlap query cannot certify clearance')
        rotor_deg = self.rotor_angle(rotor_slot) if rotor_deg is None else rotor_deg
        lift_mm = (self.station_p['lift_travel'] if lid_state == 'open' else 0.) if lift_mm is None else lift_mm
        fixed = self._static(tube_id, stage, rotor_slot, rotor_deg, lid_state, cover_on, seated, lift_mm)
        moving = self._moving(joints_deg, gap_mm, tube_id, carried_pose, carried_from_tcp)
        angles = tuple(math.radians(value) for value in (q_radius_deg or [0.]*6))
        shifts = {entry.id: sum(a*b for a, b in zip(entry.radii, angles))+entry.jaw_factor*gap_radius_mm
                  for entry in moving}
        best, limiting, contracts, pending = math.inf, None, {}, []
        pairs = itertools.chain(itertools.product(moving, fixed),
                                ((a, b) for a, b in itertools.combinations(moving, 2)
                                 if not self._rigid_interface(a, b)))
        if overlap_only:
            for a, b in pairs:
                x = min(a.box[3], b.box[3])-max(a.box[0], b.box[0])
                if x <= 0.:
                    continue
                y = min(a.box[4], b.box[4])-max(a.box[1], b.box[1])
                if y <= 0.:
                    continue
                z = min(a.box[5], b.box[5])-max(a.box[2], b.box[2])
                if z <= 0. or x*y*z <= VOLUME_EPS_MM3:
                    continue
                if b.shape is None:
                    pending.append([a.id, b.id])
                    continue
                if directional_lower_distance(a, b) > 0.:
                    continue
                overlap = a.shape.common(b.shape).Volume
                if overlap > VOLUME_EPS_MM3:
                    return {'passed': False, 'collision': [a.id, b.id], 'overlap_mm3': overlap,
                            'limiting_pair': [a.id, b.id], 'unresolved': pending}
            return {'passed': not pending, 'collision': None, 'limiting_pair': pending[0] if pending else None,
                    'unresolved': pending}
        for a, b in pairs:
            distance = lower_distance(a.box, b.box)
            movement = shifts[a.id]+shifts.get(b.id, 0.)
            # Common upstream FK rotations preserve the distance between
            # moving bodies and therefore need no relative-motion reserve.
            if b.id in shifts and a.radii and b.radii:
                shared = min(a.link, b.link)
                movement = sum((a.radii[k]+b.radii[k])*angles[k] for k in range(shared, 6))
                movement += (a.jaw_factor+b.jaw_factor)*gap_radius_mm
            threshold = margin_mm+movement+NUMERICAL_MARGIN_MM
            if distance <= threshold:
                distance = max(distance, directional_lower_distance(a, b))
            if distance > threshold:
                clearance = distance-movement
            elif b.shape is None:
                clearance = distance-movement
                if clearance <= threshold-movement:
                    pending.append([a.id, b.id])
            else:
                contact = self._contact(a, b, tube_id, stage, cassette_departure)
                distance, overlap = self._pair_geometry(a, b, gap_mm, carried_from_tcp)
                clearance = distance-movement
                if overlap > VOLUME_EPS_MM3:
                    return {'passed': False, 'collision': [a.id, b.id], 'overlap_mm3': overlap,
                            'minimum_clearance_mm': 0., 'limiting_pair': [a.id, b.id]}
                if contact is not None:
                    contracts[contact] = contracts.get(contact, 0)+1
                    continue
                if q_radius_deg is not None and clearance <= margin_mm+NUMERICAL_MARGIN_MM:
                    pending.append([a.id, b.id])
            if clearance < best:
                best, limiting = clearance, [a.id, b.id]
        return {'passed': not pending and best >= margin_mm, 'collision': None,
                'minimum_clearance_mm': best, 'limiting_pair': limiting, 'contact_pairs': contracts,
                'unresolved': pending}

    def pose_overlap(self, joints_deg, **kwargs):
        """Reject known BRep interference quickly while searching for a path."""
        return self.pose_clearance(joints_deg, overlap_only=True, **kwargs)

    def _cassette_departure(self, arm, grip, tube_id, carried):
        """Prove one-sided separation from the actual horizontal support.

        For the planar, constant-pitch arm subchain at pickup, the variable
        height terms are L*cos(q2) + F*cos(q2+q3). With rest-to-rest initial
        jets, q'(u) has a factor u squared. Bound the factored derivative
        before integrating. Tiny residual rotations of the actual exported
        polynomial cost a whole-solid displacement reserve proportional to
        the same u cubed. No positive separation is demanded at the initial
        support contact itself.
        """
        index = arm.times.index(grip)
        coefficients = arm.segments[index]
        if any(row[1] or row[2] for row in coefficients):
            raise ValueError('Cassette pickup must depart from coincident rest and support')
        axes = [tuple(row[2] for row in frame[:3]) for frame in self.kin.frames]
        if (axes != [(0, 0, 1), (0, 1, 0), (0, 1, 0), (0, 0, 1), (0, 1, 0), (0, 0, 1)] or
                any(self.axes[i][0] != self.axes[1][0] for i in (2, 4)) or
                any(coefficients[3]) or
                abs(sum(coefficients[i][0] for i in (1, 2, 4))+math.pi) > 1e-9):
            raise ValueError('The source ArmC subchain does not match the vertical support model')
        if tuple(self.kin.base[2][:3]) != (0., 0., 1.):
            raise ValueError('Cassette departure requires the bound horizontal arm mount')
        lengths = [self.axes[b][2]-self.axes[a][2] for a, b in ((1, 2), (2, 4))]
        if any(length <= 0. for length in lengths):
            raise ValueError('Positive shoulder and forearm span required')
        plane = self.vehicle['B2_Cassette'].box[5]
        cargo = self.vehicle[tube_id]
        if abs(cargo.box[2]-plane) > 1e-8 or abs(self.cargo_axes[tube_id][0][2]-plane) > 1e-8:
            raise ValueError('Actual cassette and tube do not share the intended support plane')

        def extrema(poly):
            return [motion.polynomial(poly, u) for u in (0., 1., *motion.real_roots(motion.derivative(poly)))]

        alpha = coefficients[1]
        beta = [a+b for a, b in zip(alpha, coefficients[2])]
        height_rate = 0.
        for angle, span in zip((alpha, beta), lengths):
            bounds = extrema(angle)
            lo, hi = min(bounds), max(bounds)
            factored_rate = min(extrema(motion.derivative(angle)[2:]))
            if not -math.pi < lo <= hi < 0. or factored_rate <= 0.:
                raise ValueError('No strictly increasing analytic cassette departure height')
            height_rate += span*min(-math.sin(lo), -math.sin(hi))*factored_rate

        pose = robot.multiply(robot.multiply(robot.inverse(self.kin.base), self.park_tool), carried)
        radii = self._radii(bbox(self.placed(cargo.shape, pose)), 6)
        pitch = [a+b+d for a, b, d in zip(alpha, coefficients[2], coefficients[4])]
        drift = sum(radii[index]*sum(abs(x) for x in row[3:]) for index, row in (
            (0, coefficients[0]), (4, pitch), (5, coefficients[5])))
        reserve = height_rate/3.-drift-NUMERICAL_MARGIN_MM
        if reserve <= 0.:
            raise ValueError('No whole-vessel clearance from the physical cassette support')
        return {'start_s': grip, 'end_s': arm.times[index+1], 'plane_z_mm': plane,
                'height_lower_coefficient_mm': reserve, 'residual_rotation_reserve_mm': drift,
                'scope': 'Carried vessel stays above the stationary cassette support plane, '
                         'with height bounded below by the stated coefficient times u cubed.'}

    def parked_station_clearance(self, home, gap_mm):
        """Separate the bent parked arm from lid, latch, rotor, lift and seated-tube sweeps."""
        joints = {joint['child']: joint for joint in self.station_geometry['joints']}
        sweeps = []
        for name, group, shape in self.station_shapes:
            if group == 'Frame':
                continue
            joint = joints[group]
            if joint['parent'] != 'Frame':
                raise ValueError('A moving native CF01 body has an unsupported ancestor: '+name)
            sweeps.append(('CF01.'+name, _swept_box(bbox(shape), self.cf_frame, joint)))
        rotor = joints['RotorGroup']
        for tube_id, slot in self.samples.items():
            vessel = self.vehicle[tube_id].shape
            stored = self.seated_pose(tube_id, slot, 0.)
            local = self.placed(vessel, robot.multiply(robot.inverse(self.cf_frame), stored))
            sweeps.append(('Rotor.'+tube_id, _swept_box(bbox(local), self.cf_frame, rotor)))
            indexed = self.rotor_angle(slot)
            boxes = [bbox(self.placed(vessel, self.seated_pose(tube_id, slot, indexed, lift)))
                     for lift in (0., self.station_p['lift_travel'])]
            sweeps.append(('Lift.'+tube_id, tuple(min(a, b)-NUMERICAL_MARGIN_MM for a, b in zip(
                boxes[0][:3], boxes[1][:3]))+tuple(max(a, b)+NUMERICAL_MARGIN_MM for a, b in zip(
                    boxes[0][3:], boxes[1][3:]))))
        moving = self._moving(home, gap_mm, next(iter(self.samples)), None, None)
        clearance, arm_body, fixture = min((lower_distance(entry.box, swept), entry.id, name)
                                           for entry in moving for name, swept in sweeps)
        return {'passed': clearance > NUMERICAL_MARGIN_MM, 'minimum_clearance_mm': clearance,
                'limiting_pair': [arm_body, fixture], 'swept_body_count': len(sweeps),
                'scope': 'Axis-aligned bounds of each native CF01 joint sweep and occupied tube sweep '
                         'versus the stationary runtime home arm and gripper.'}

    def open_lid_index_clearance(self):
        """Check the occupied half-turn with the lid open and the pusher parked."""
        (tube_id, first_slot), (other, second_slot) = self.samples.items()
        interval = sorted((self.rotor_angle(first_slot), self.rotor_angle(second_slot)))
        rotor = next(joint for joint in self.station_geometry['joints'] if joint['id'] == 'Rotor')
        if rotor['axis'] != [0, 0, 1] or interval != [-180., 0.]:
            raise ValueError('The open-lid index proof needs the two opposite lab pockets and vertical rotor axis')

        rotating = [('CF01.'+name, shape) for name, group, shape in self.station_shapes if group == rotor['child']]
        tube_world = self.seated_pose(tube_id, first_slot, 0.)
        rotating.append(('Rotor.'+tube_id, self.placed(self.vehicle[tube_id].shape,
                        robot.multiply(robot.inverse(self.cf_frame), tube_world))))
        exposed_ids = {'CF01.'+name for name, group, _shape in self.station_shapes
                       if group not in ('Frame', rotor['child'])}
        parked = self._static(other, 'approach', second_slot, self.rotor_angle(second_slot),
                              'open', False, (tube_id,), 0.)
        brake_joints = [joint for joint in self.station_geometry['joints']
                        if joint['id'] in ('BrakeUpper', 'BrakeLower')]
        if len(brake_joints) != 2:
            raise ValueError('The open-lid index proof requires both native parking-brake pads')
        # The ordinary station CAD pose retains its held-brake policy. The
        # opt-in rotor index uses the released pad positions from the same joints.
        brake_values = cf.pose(self.station, self.station_p, 'open')
        brake_values.update({joint['id']: joint['limits'][1] for joint in brake_joints})
        released = {}
        for joint in brake_joints:
            brake_frame = robot.multiply(self.cf_frame,
                pickup.rigid_from_cf(self.station_geometry, joint['child'], brake_values))
            for name, group, shape in self.station_shapes:
                if group == joint['child']:
                    key = 'CF01.'+name
                    released[key] = body(key, self.placed(shape, brake_frame), 'station')
        fixtures = [entry for entry in parked if entry.kind not in ('station', 'seated')
                    or entry.id in exposed_ids]
        fixtures = [released.get(entry.id, entry) for entry in fixtures]
        if len(rotating) < 2 or not exposed_ids or not released:
            raise ValueError('The open-index proof requires native rotor, lid, latch and pusher bodies')
        sweep = self._station_rotation_clearance(rotating, rotor, interval, fixtures)
        if not sweep['passed']:
            return sweep

        lid = next(joint for joint in self.station_geometry['joints'] if joint['id'] == 'Lid')
        lid_bodies = [('CF01.'+name, shape) for name, group, shape in self.station_shapes if group == lid['child']]
        outside = [entry for entry in parked if entry.kind not in ('station', 'seated')]
        lid_sweep = self._station_rotation_clearance(lid_bodies, lid, lid['limits'], outside)
        return {
            **sweep, 'passed': lid_sweep['passed'], 'angle_interval_deg': interval, 'seated_tube_id': tube_id,
            'lid_fixture_sweep': lid_sweep,
            'scope': 'Native rotor and seated vessel sweep against the fully open lid, retracted latches and '
                     'brake pads, parked pusher and surrounding solids. The full lid opening arc is checked '
                     'against external fixtures. The shaft and frame interfaces use the separate CF01 checks.',
        }

    def _station_rotation_clearance(self, rotating, joint, interval, fixtures):
        if not rotating or not fixtures:
            raise ValueError('The native station sweep needs its moving and stationary bodies')
        best, limiting, queries = math.inf, None, 0
        for name, shape in rotating:
            bounds = bbox(shape)
            axis = joint['axis']
            radius = 0.
            for point in corners(bounds):
                offset = [value-center for value, center in zip(point, joint['origin'])]
                axial = sum(value*direction for value, direction in zip(offset, axis))
                radius = max(radius, math.hypot(*(value-axial*direction for value, direction in zip(offset, axis))))
            outer = _swept_box(bounds, self.cf_frame, {**joint, 'limits': interval})
            for fixed in fixtures:
                lower = lower_distance(outer, fixed.box)
                pending = [(*interval, 0)] if lower <= NUMERICAL_MARGIN_MM else []
                if not pending and lower < best:
                    best, limiting = lower, [name, fixed.id]
                while pending:
                    lo, hi, depth = pending.pop()
                    outer_interval = _swept_box(bounds, self.cf_frame, {**joint, 'limits': [lo, hi]})
                    lower = lower_distance(outer_interval, fixed.box)
                    if lower <= NUMERICAL_MARGIN_MM and fixed.shape is not None:
                        values = {**cf.pose(self.station, self.station_p, 'open'), joint['id']: (lo+hi)/2}
                        frame = robot.multiply(self.cf_frame,
                            pickup.rigid_from_cf(self.station_geometry, joint['child'], values))
                        distance = self.placed(shape, frame).distToShape(fixed.shape)[0]
                        queries += 1
                        lower = distance-2*radius*math.sin(math.radians(hi-lo)/4)-NUMERICAL_MARGIN_MM
                    if lower > NUMERICAL_MARGIN_MM:
                        if lower < best:
                            best, limiting = lower, [name, fixed.id]
                    elif depth >= 12:
                        return {'passed': False, 'pair': [name, fixed.id], 'unresolved_deg': [lo, hi]}
                    else:
                        mid = (lo+hi)/2
                        pending.extend([(mid, hi, depth+1), (lo, mid, depth+1)])
        return {
            'passed': best > NUMERICAL_MARGIN_MM, 'minimum_clearance_mm': best,
            'limiting_pair': limiting,
            'rotating_bodies': len(rotating), 'fixed_bodies': len(fixtures), 'distance_queries': queries,
        }

    def check_curve(self, sample, *, home=None, mirror=False, max_depth=15):
        """Certify all noncontact pairs between exact polynomial knots where possible."""
        points = sample['points']
        jaw_points = sample['jaw_points']
        arm = motion.Curve(_canonical(points, PVA))
        jaw = motion.Curve(_canonical(jaw_points, JAW_PVA))
        grip, seat = sample['grip_s'], sample['seat_s']
        if arm.times[0] != jaw.times[0] or arm.times[-1] != jaw.times[-1] or not arm.times[0] < grip < seat < arm.times[-1]:
            raise ValueError('Shared exact channel duration and ordered custody events required')
        if len(arm.points[0][PVA[0]]) != 6 or len(jaw.points[0][PVA[0]]) != 1:
            raise ValueError('Arm and jaw channels must specify exactly six and one coordinates')
        home = self.park if home is None else home
        park = [math.radians(value) for value in home]
        for point in (arm.points[0], arm.points[-1]):
            if (max(abs(a-b) for a, b in zip(point[PVA[0]], park)) > 1e-8 or
                    any(abs(x) > 1e-8 for key in PVA[1:] for x in point[key])):
                raise ValueError('The station handoff must start and end with the arm parked at rest')
        limits = motion.bounds(arm)[PVA[0]]
        jaw_limits = motion.bounds(jaw)[PVA[0]]
        if (any(lo < math.radians(a)-1e-8 or hi > math.radians(b)+1e-8
                for lo, hi, (a, b) in zip(limits['min'], limits['max'], self.kin.limits)) or
                jaw_limits['min'][0] <= 0. or jaw_limits['max'][0] > self.gripper['open_gap_mm']+1e-8):
            raise ValueError('Arm and jaw coordinates must stay inside mechanism limits between knots')
        tube_id, slot = sample['id'], sample['slot']
        if mirror:
            closed, released = self.grip_widths[tube_id], self.gripper['open_gap_mm']
            parked = self.cassette_gap_mm
            expected_gaps = [parked, parked, closed, closed, released, released, parked]
            if ([point[PVA[0]][0] for point in jaw.points] != expected_gaps
                    or any(any(point[PVA[1]]+point[PVA[2]]) for point in jaw.points)):
                raise ValueError('Transfer jaws must close on the native shaft and open to the checked release gap')
        grip_q = [math.degrees(value) for value in arm.evaluate(grip)['positions_rad']]
        carried = robot.inverse(self.kin.tool(grip_q))
        seat_q = [math.degrees(value) for value in arm.evaluate(seat)['positions_rad']]
        end = robot.multiply(self.kin.tool(seat_q), carried)
        lift_mm = self.station_p['lift_travel']
        intended = self.seated_pose(tube_id, slot, self.rotor_angle(slot), lift_mm)
        # The native TR01 solid has a coaxial shaft and cap. Twist does not
        # change its geometry, so probe the actual bottom and shaft axis.
        witness = max(math.dist(robot.transform(end, p), robot.transform(intended, p))
                      for p in self.cargo_axes[tube_id])
        if witness > (NUMERICAL_MARGIN_MM/100 if mirror else 0.005):
            return {'passed': False, 'id': tube_id, 'slot': slot, 'seat_axis_error_mm': witness,
                    'reason': 'carried vessel does not reach the modeled pocket'}
        support = self._cassette_departure(arm, grip, tube_id, carried)
        fixed_seats = tuple(identity for identity in self.samples
                            if self.samples[identity] < slot)
        closed_case = self.pose_clearance(home, tube_id=tube_id, rotor_slot=slot,
            stage='approach', gap_mm=jaw.points[0][PVA[0]][0], lid_state='closed',
            cover_on=not fixed_seats, seated=fixed_seats, lift_mm=0.)
        if not closed_case['passed']:
            return {'passed': False, 'id': tube_id, 'slot': slot,
                    'reason': 'collision at parked pre-transfer fixture state', 'failure': closed_case}
        close_start = max(t for t in jaw.times if t < grip)
        times = sorted(set(arm.times+ jaw.times + [grip, seat]))
        intervals, queries = [], 0
        discrete_candidates = []

        def query(t, begin, end, stage, bounded):
            nonlocal queries
            q = arm.evaluate(t)['positions_rad']
            gap = jaw.evaluate(t)['positions_rad'][0]
            args = {'tube_id': tube_id, 'stage': stage, 'gap_mm': gap, 'rotor_slot': slot,
                    'seated': fixed_seats, 'carried_from_tcp': carried if stage == 'loaded' else None}
            args['cassette_departure'] = stage == 'loaded' and grip <= begin <= end <= support['end_s']
            if bounded:
                args['q_radius_deg'] = [math.degrees(value) for value in _radius(arm, begin, end, q)]
                args['gap_radius_mm'] = _radius(jaw, begin, end, [gap])[0]
            queries += 1
            return self.pose_clearance([math.degrees(value) for value in q], **args)

        def contact_stage(t, side):
            if t < close_start or t == close_start and side == 'left':
                return 'approach'
            if t < grip or t == grip and side == 'left':
                return 'closing'
            if t < seat or t == seat and side == 'left':
                return 'loaded'
            return 'withdraw'

        # The closed interval certificate includes ordinary internal knots.
        # Independently evaluate both geometry owners at every custody event.
        endpoints = sorted({times[0], close_start, grip, seat, times[-1]})
        for t in endpoints:
            for side in ('left', 'right') if t in (grip, seat) else ('right',):
                result = query(t, t, t, contact_stage(t, side), False)
                if not result['passed']:
                    return {'passed': False, 'id': tube_id, 'slot': slot, 'time_s': t, 'side': side,
                            'seat_axis_error_mm': witness, 'queries': queries, 'failure': result}
        pending = [(a, b, 0) for a, b in reversed(list(zip(times, times[1:])))]
        while pending:
            a, b, depth = pending.pop()
            midpoint = (a+b)/2
            stage = contact_stage(midpoint, 'right')
            result = query(midpoint, a, b, stage, True)
            if queries % 100 == 0:
                print(f'{tube_id}: {queries} BRep queries, {len(intervals)} intervals certified, '
                      f'latest model time {midpoint:.3f} s', flush=True)
            if result['collision']:
                return {'passed': False, 'id': tube_id, 'slot': slot, 'time_s': midpoint,
                        'seat_axis_error_mm': witness, 'queries': queries, 'failure': result}
            if result['passed']:
                intervals.append({'start_s': a, 'end_s': b, 'queries': queries,
                                  'clearance_lower_mm': result['minimum_clearance_mm'],
                                  'limiting_pair': result['limiting_pair']})
            elif depth < max_depth:
                pending.extend([(midpoint, b, depth+1), (a, midpoint, depth+1)])
            else:
                discrete_candidates.append({'start_s': a, 'end_s': b, 'detail': result})
                break
        return {'passed': not discrete_candidates, 'id': tube_id, 'slot': slot,
                'duration_s': arm.times[-1]-arm.times[0], 'parked_closed_fixture_check': closed_case,
                'cassette_departure_evidence': support,
                'seat_axis_error_mm': witness, 'lift_mm': lift_mm,
                'raised_pose_from_cassette': intended, 'queries': queries, 'intervals': intervals,
                'unresolved_intervals': discrete_candidates,
                'scope': 'Exact PVA midpoint BReps with conservative joint and jaw displacement bounds; '
                         'named fixture/pad contacts checked for penetration at discrete frames.'}


def _canonical(points, fields):
    return [{'time_s': row['time_s'], **{out: row[key] for out, key in zip(PVA, fields)}} for row in points]


def _radius(curve, start, end, center):
    """Bound every polynomial value relative to its midpoint value on the interval."""
    radii = [0.]*len(center)
    first = max(0, bisect_left(curve.times, start)-1)
    last = min(len(curve.segments), bisect_right(curve.times, end))
    for index in range(first, last):
        coefficients = curve.segments[index]
        a, b = curve.times[index:index+2]
        u, v = max(0., (start-a)/(b-a)), min(1., (end-a)/(b-a))
        for j, values in enumerate(coefficients):
            probes = [u, v, *motion.real_roots(motion.derivative(values), u, v)]
            radii[j] = max(radii[j], *(abs(motion.polynomial(values, x)-center[j]) for x in probes))
    return [math.nextafter(value, math.inf) for value in radii]


def _stationary_arm_hold(track, start, end):
    points = track['points']
    times = [point['time_s'] for point in points]
    if start not in times or end not in times:
        return False
    hold = points[times.index(start):times.index(end)+1]
    return len(hold) >= 2 and all(
        point[PVA[0]] == hold[0][PVA[0]] and not any(point[PVA[1]]+point[PVA[2]])
        for point in hold)


def _verify_return_samples(loads, returns):
    """Check exact reversal and matching stationary custody transition poses."""
    if [(row['id'], row['slot']) for row in returns] != [
            (row['id'], row['slot']) for row in reversed(loads)]:
        raise ValueError('Return the last loaded tube first to recreate the checked occupancies')
    for load, unload in zip(reversed(loads), returns):
        duration = load['points'][-1]['time_s']
        jaw = load['jaw_points']
        if (len(jaw) != 7 or jaw[2]['time_s'] != load['grip_s'] or jaw[4]['time_s'] != load['seat_s']
                or not _stationary_arm_hold(load, jaw[1]['time_s'], jaw[2]['time_s'])
                or not _stationary_arm_hold(load, jaw[3]['time_s'], jaw[4]['time_s'])):
            raise ValueError('Return custody reversal requires both arm poses held throughout jaw travel')
        if (unload.get('direction') != 'unload' or unload['grip_s'] != duration-jaw[3]['time_s']
                or unload['seat_s'] != duration-jaw[1]['time_s']):
            raise ValueError('Return custody must change only after the jaws complete their movement')
        for channel, fields in (('points', PVA), ('jaw_points', JAW_PVA)):
            original, reverse = load[channel], unload[channel]
            if len(original) != len(reverse) or original[0]['time_s'] != 0.:
                raise ValueError('Return channels must reproduce the entire zero-origin forward motion')
            for forward, backward in zip(reversed(original), reverse):
                position, velocity, acceleration = fields
                if (backward['time_s'] != duration-forward['time_s']
                        or backward[position] != forward[position]
                        or backward[velocity] != [-value for value in forward[velocity]]
                        or backward[acceleration] != forward[acceleration]):
                    raise ValueError('Return channels must exactly reverse the forward PVA coefficients')


def _reflected_evidence(load):
    duration = load['duration_s']
    allowance = NUMERICAL_MARGIN_MM/10
    intervals = [{**interval, 'start_s': duration-interval['end_s'],
                  'end_s': duration-interval['start_s'],
                  'clearance_lower_mm': interval['clearance_lower_mm']-allowance}
                 for interval in reversed(load['intervals'])]
    return {key: load[key] for key in ('id', 'slot', 'passed', 'duration_s', 'lift_mm',
                                       'seat_axis_error_mm', 'raised_pose_from_cassette')} | {
        'intervals': intervals,
        'source_load_id': load['id'],
        'reflection_allowance_mm': allowance,
        'scope': 'Exact time reversal of the certified load arm and jaw curves. '
                 'The raised target tube and cassette tube keep their physical poses '
                 'through each stationary jaw change. The other tube, indexed rotor, '
                 'open lid and extended pusher match the source check at reflected times.',
    }


def _read_positive_checkpoint(path, identity, sample):
    path = Path(path)
    if not path.is_file():
        return None
    receipt = json.loads(path.read_text())
    if receipt.get('format') != FORMAT+'/sample' or any(receipt.get(key) != value for key, value in identity.items()):
        raise ValueError('Native checkpoint inputs changed: '+str(path))
    evidence = receipt['sample']
    if evidence.get('passed') is not True:
        return None
    start = sample['points'][0]['time_s']
    for interval in evidence['intervals']:
        if interval['start_s'] != start or interval['end_s'] <= start or interval['clearance_lower_mm'] <= 0.:
            raise ValueError('Gapped or nonpositive native checkpoint: '+str(path))
        start = interval['end_s']
    if ((evidence['id'], evidence['slot']) != (sample['id'], sample['slot'])
            or start != sample['points'][-1]['time_s']):
        raise ValueError('Incomplete native checkpoint: '+str(path))
    return evidence


def verify_program(oracle, program_path, *, checkpoint_dir=None, only_sample=None, resume=False,
                   open_lid_index=False):
    path = Path(program_path).resolve()
    program = json.loads(path.read_text())
    expected = list(oracle.samples.items())
    if program.get('format') != PROGRAM or [(sample['id'], sample['slot']) for sample in program['samples']] != expected:
        raise ValueError('The complete two-vessel ArmC program is required')
    home = program.get('home_joints_deg')
    if home is not None:
        route = 'model/lab3003-cf01-arm-route.motion.json'
        if (route not in program['source_files_sha256'] or not isinstance(home, list) or len(home) != 6
                or any(type(q) not in (int, float) or not math.isfinite(q) or not lo <= q <= hi
                       for q, (lo, hi) in zip(home, oracle.kin.limits))
                or home != json.loads((ROOT/route).read_text()).get('home_joints_deg')):
            raise ValueError('Motion home must match the bounded route source')
    returns = program.get('return_samples')
    if returns is not None:
        _verify_return_samples(program['samples'], returns)
    if only_sample is not None and only_sample not in oracle.samples:
        raise ValueError('Unknown sample selection')
    pins = dict(oracle.source_pins)
    for key, value in {**program['source_files_sha256'],
            str(Path(__file__).relative_to(ROOT)): VERIFIER_SHA256}.items():
        if key in pins and pins[key] != value:
            raise ValueError('The proof inputs bind conflicting revision pins: '+key)
        pins[key] = value
    mesh.verify_pins(pins)
    parked_station = None
    if home is not None:
        gaps = {sample['jaw_points'][index]['positions_mm'][0]
                for sample in program['samples'] for index in (0, -1)}
        if len(gaps) != 1:
            raise ValueError('Both directions need a common parked gripper position')
        parked_station = oracle.parked_station_clearance(home, gaps.pop())
        if not parked_station['passed']:
            raise ValueError('Station sweep is unresolved at runtime home: '+str(parked_station))
    index_sweep = None
    if open_lid_index:
        if home is None or returns is None:
            raise ValueError('Open index requires a checked parked ArmC with both forward and return handoffs')
        index_sweep = oracle.open_lid_index_clearance()
        if not index_sweep['passed']:
            raise ValueError('Open-lid index sweep is unresolved: '+str(index_sweep))
    digest = robot.digest(path)
    samples = []
    identity = {'program_sha256': digest, 'source_files_sha256': pins,
                'native_inputs_sha256': oracle.native_artifacts}

    def verify_inputs():
        mesh.verify_pins(pins)
        if robot.digest(path) != digest or any(robot.digest(Path(name)) != sha
                                             for name, sha in oracle.native_artifacts.items()):
            raise ValueError('A motion or native artifact changed during verification')

    if checkpoint_dir is not None:
        checkpoint_dir = Path(checkpoint_dir)
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
    for sample in program['samples']:
        if only_sample is not None and sample['id'] != only_sample:
            continue
        receipt = checkpoint_dir/(sample['id']+'.json') if checkpoint_dir is not None else None
        evidence = _read_positive_checkpoint(receipt, identity, sample) if resume and receipt else None
        if evidence is None:
            evidence = oracle.check_curve(sample, home=home, mirror=returns is not None)
        samples.append(evidence)
        diagnostic = {key: evidence[key] for key in
                      ('id', 'passed', 'time_s', 'side', 'reason', 'failure', 'queries') if key in evidence}
        if evidence.get('unresolved_intervals'):
            interval = evidence['unresolved_intervals'][0]
            diagnostic['unresolved_interval'] = {
                'start_s': interval['start_s'], 'end_s': interval['end_s'],
                'limiting_pair': interval['detail']['limiting_pair']}
        print(json.dumps(diagnostic), flush=True)
        verify_inputs()
        if receipt is not None:
            staged = receipt.with_suffix('.tmp')
            staged.write_text(json.dumps({'format': FORMAT+'/sample', **identity, 'sample': evidence}, indent=2)+'\n')
            staged.replace(receipt)
    complete = only_sample is None
    passed = all(sample['passed'] for sample in samples)
    result = {'format': FORMAT if complete else FORMAT+'/partial', 'passed': passed,
            **identity, 'samples': samples,
            'stock_html_sha256': getattr(oracle, 'stock_html_sha256', None),
            'gripper': {**oracle.gripper, 'cassette_open_gap_mm': oracle.cassette_gap_mm},
            'intended_contacts': ['same and adjacent links at their mechanical interfaces',
                                  'flange and mounted gripper', 'gripper rigid parts',
                                  'stationary arm base on the worktop',
                                  'only active vessel against pads during grasp, grip and release',
                                  'cassette plane contact at grip with independent one-sided lift separation',
                                  'active vessel bottom meeting the separately checked raised pusher'],
            'scope': 'Numerical native BRep trajectory verification of the ArmC and actual cassette vessel. '
                     'CF01 index and lid are held during the arm trajectory. Cover handling, machine limits '
                     'and hardware clearance are outside this report.'}
    if home is not None:
        result['home_joints_deg'] = home
        result['parked_station_sweep'] = parked_station
    if index_sweep is not None:
        result['open_lid_index_sweep'] = index_sweep
    if returns is not None and complete and passed:
        result['return_samples'] = [_reflected_evidence(sample) for sample in reversed(samples)]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('program', type=Path)
    parser.add_argument('--stock-preview', type=Path, required=True)
    parser.add_argument('--arm-report', type=Path, required=True)
    parser.add_argument('--dock-certificate', type=Path, required=True)
    parser.add_argument('--pusher-report', type=Path, required=True)
    parser.add_argument('--checkpoint-dir', type=Path)
    parser.add_argument('--only-sample', help='Write a native checkpoint for just one supported vessel')
    parser.add_argument('--resume', action='store_true', help='Reuse compatible positive native checkpoints')
    parser.add_argument('--open-lid-index', action='store_true', help='Verify the occupied open-lid index sweep')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    oracle = Lab3003TransferOracle.from_stock(args.stock_preview, args.arm_report,
                                            args.dock_certificate, args.pusher_report)
    result = verify_program(oracle, args.program, checkpoint_dir=args.checkpoint_dir,
                            only_sample=args.only_sample, resume=args.resume, open_lid_index=args.open_lid_index)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2)+'\n')
    if not result['passed']:
        raise SystemExit('Lab 3.003 native trajectory or interval clearance failed; see '+str(args.out))


if __name__ == '__main__':
    main()
