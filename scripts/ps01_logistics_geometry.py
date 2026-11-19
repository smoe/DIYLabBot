"""Referenced PS01 stations and a TR01 receiving nest, lowered once for both CADs."""
import copy
import functools
import itertools
import math

import pipetting_station as s
import labware_transfer as handling
import sample_transport_model as vehicle
from centrifuge_robot_pickup import Kinematics, rack_geometry

SOURCE = s.ROOT / 'model/ps01-logistics.shared.json'


def translated_part(part, offset):
    value = copy.deepcopy(part)
    for shape in [value['shape'], *value.get('cuts', []), *value.get('additions', [])]:
        shape['origin'] = [a + b for a, b in zip(shape['origin'], offset)]
    return value


def lowered_parts(expanded):
    result = {}
    for body in expanded['bodies']:
        result[body['id']] = {'id': body['id'], 'appearance': body['appearance'], 'role': body['role'], 'cuts': [], 'additions': []}
    for operation in expanded['operations']:
        target = result[operation['body']]; shape = copy.deepcopy(operation['shape'])
        if operation['action'] == 'create':
            target['shape'] = shape
        elif operation['action'] == 'join':
            target['additions'].append(shape)
        elif operation['action'] == 'cut':
            target['cuts'].append(shape)
        else:
            raise ValueError('Unsupported TR01 primitive operation')
    return list(result.values())


def vehicle_parts(spec, handling_spec, adapter):
    """The existing floor chassis and mounting pins support a separate LT01 nest.

    The opposite occupied 24-tube bay remains a neighboring-load witness.
    Cover height is derived from the carried box envelope, not copied from TR01.
    """
    p = vehicle.parameters(spec); hp = handling.parameters(handling_spec)
    variant = next(v for v in spec['variants'] if v['id'] == 'Floor_T48')
    expanded = vehicle.expanded(spec, p, variant)
    bay = adapter['bay_index'] + 1; prefix = 'B%d_' % bay
    parts = [part for part in lowered_parts(expanded) if part['id'] != 'TransportCover'
             and (not part['id'].startswith(prefix) or part['id'].startswith((prefix+'Support', prefix+'Key', prefix+'Latch')))]
    cx = (-1 if bay == 1 else 1) * p['bay_pitch'] / 2
    z = p['floor_deck_z'] + 2
    t = adapter['base_thickness_mm']; gap = adapter['locator_clearance_mm']; wall = adapter['locator_thickness_mm']
    width = max(p['cassette_length'], hp['carrier_w'] + 2*(gap+wall))
    depth = max(p['cassette_width'], hp['carrier_d'] + 2*(gap+wall))
    cuts = [s.cylinder([cx+pin['xy'][0], pin['xy'][1], z-1], pin['radius']+.3, t+2)
            for pin in spec['cassette_interface']['pin_pattern_mm']]
    parts.append(s.part('LT01ReceiverBase', s.box([cx-width/2, -depth/2, z], [width, depth, t]), '#a9bdc8', cuts=cuts))
    for index, (xsign, ysign) in enumerate(itertools.product((-1, 1), repeat=2)):
        x = cx + xsign*(hp['carrier_w']/2-6)-6
        y = ysign*(hp['carrier_d']/2+gap+wall/2)-wall/2
        parts.append(s.part('LT01Locator'+str(index), s.box([x, y, z+t], [12, wall, adapter['locator_height_mm']]), '#d4a044'))
    surface = [cx, 0, z+t]
    # Explicit manual fixture retention, not a modeled or qualified automatic latch.
    max_height = max(hp['box_h'], 46)
    inside_top = z+t+handling.seat_height(handling_spec)+max_height+6
    height = inside_top + 3 - p['floor_deck_z']
    cover = s.part('LT01TransportCover', s.box([-158, -83, p['floor_deck_z']], [316, 166, height]), '#c3e1ea',
                   cuts=[s.box([-155, -80, p['floor_deck_z']-1], [310, 160, height-2])], role='unqualified_removable_cover_envelope')
    cover['appearance']['opacity'] = .22
    return parts, cover, surface, expanded


class Scene:
    def __init__(self):
        self.spec = s.read(SOURCE)
        for ref in self.spec['sources'].values():
            s.bound(ref)
        self.context = s.compile_setup(s.assembly.validate_reference(self.spec['sources']['setup']))
        self.hp = handling.parameters(self.context['handling']['source'])
        self.stations = {item['id']: item for item in self.spec['stations']}
        self.vehicle_spec = vehicle.load(s.assembly.validate_reference(self.spec['sources']['vehicle']))
        self.car_parts, self.cover, self.car_surface, expanded = vehicle_parts(
            self.vehicle_spec, self.context['handling']['source'], self.spec['adapter'])
        self.frames = {}; self.arms = {}; self.static = []; self.waste = []
        groups = {g['id']: g for g in self.context['groups']}
        ports={p['port']:p['xy_mm'] for p in self.spec['handoff_ports']}
        original_carriers = self.context['handling']['carriers']
        excluded = set(original_carriers) | {'LabwareGripper', 'Plate01'}
        for identity, inst in self.stations.items():
            base = s.workspace.pose(inst['worktop_xyz_mm'], 0)
            for frame_id, matrix in self.context['handling']['frames'].items():
                if frame_id.startswith('PS01.'):
                    port=frame_id.split('.',1)[1]
                    local=s.workspace.pose([*ports[port],self.hp['dock_t']],0) if port in ports else matrix
                    self.frames[identity+'.'+port] = s.robot.multiply(base, local)
            for g in self.context['groups']:
                if g['id'] in excluded:
                    continue
                port=g['id'].removeprefix('PS01.')
                local=s.workspace.pose([*ports[port],0],0) if port in ports else g['matrix']
                self.static.append({**copy.deepcopy(g), 'id': identity+'.'+g['id'], 'matrix': s.robot.multiply(base, local)})
            for arm_id, arm in self.context['arms'].items():
                item = copy.deepcopy(self.context['spatial']['devices'][arm_id])
                item['id'] = identity+'.'+arm_id; item['matrix'] = s.robot.multiply(base, item['matrix'])
                self.arms[item['id']] = {'arm': arm['arm'], 'item': item,
                    'joints_deg': arm.get('joints_deg', s.robot.home(arm['arm']))}
                if arm_id == 'PS01Arm':
                    self.arms[item['id']]['state'] = {**arm['state'], 'world_links': {
                        k: s.robot.multiply(base, m) for k, m in arm['state']['world_links'].items()}}
            waste = copy.deepcopy(self.context['spatial']['devices']['PS01Waste'])
            waste['id'] = identity+'.PS01Waste'; waste['matrix'] = s.robot.multiply(base, waste['matrix']); self.waste.append(waste)
        self.payloads = {}; self.initial_placements = {}
        all_vehicle_parts = {p['id']: p for p in lowered_parts(expanded)}
        template_tube = all_vehicle_parts['B2_Tube01']
        tube_origin = template_tube['shape']['origin']
        rack_source = s.bound(self.context['handling']['source']['sources']['rack'])
        rack = rack_geometry({'rack': {**rack_source, 'selected_slot': 1, 'position_mm': [0,0,0], 'yaw_deg': 0},
                             'transport_requirement': {'position_target_mm': 0}},
                             {'tube_radius': template_tube['shape']['radius'], 'tube_length': template_tube['shape']['height']})
        for item in self.spec['fixture']:
            prototype = groups[item['prototype']]; parts = copy.deepcopy(prototype['parts'])
            if item['kind'] == 'well_plate':
                part = groups['Plate01']['parts'][0]
                parts.append(translated_part({**part, 'id': 'Plate'}, [0,0,handling.seat_height(self.context['handling']['source'])]))
                # A transport seal is a named synthetic process state, not a fabricated liquid volume.
                size = original_carriers[item['prototype']]['size_mm']
                seal = s.part('SealEnvelope', s.box([-size[0]/2,-size[1]/2,handling.seat_height(self.context['handling']['source'])+size[2]], [size[0],size[1],.2]), '#bddbe0', role='synthetic_transport_seal')
                seal['appearance']['opacity'] = .35; parts.append(seal)
            elif item['kind'] == 'tube_rack':
                slots = {slot['place_id']: slot for slot in rack['slots']}
                for vessel in item['vessels']:
                    point = slots[vessel['place_id']]['tube_bottom_mm']; point[2] += handling.seat_height(self.context['handling']['source'])
                    parts.append(translated_part({**template_tube, 'id': vessel['vessel_id']}, [a-b for a,b in zip(point,tube_origin)]))
            self.payloads[item['id']] = parts; self.initial_placements[item['id']] = self.frames[item['initial_endpoint']]

    @functools.lru_cache(maxsize=None)
    def kin(self, station_id):
        entry = self.arms[station_id+'.PS01TransferArm']; base = entry['item']['matrix']
        return Kinematics(entry['arm'], {'arm_fixture': {'position_mm': [base[i][3] for i in range(3)],
                           'yaw_deg': math.degrees(math.atan2(base[1][0],base[0][0]))},
                           'gripper': {'flange_to_grip_mm': self.hp['flange_to_grip']}})

    def car_frame(self, station_id):
        return s.workspace.pose([*self.stations[station_id]['dock_xy_mm'], 0], 0)

    def load_frame(self, station_id):
        return s.robot.multiply(self.car_frame(station_id), s.workspace.pose(self.car_surface, 0))

    def park(self, station_id):
        return s.robot.transform(s.workspace.pose(self.stations[station_id]['worktop_xyz_mm'],0), self.context['handling']['layout']['park']['tcp_world_mm'])

    def groups(self, placements=None, vehicle_frame=None, cover_on=False, jaws=None):
        result = copy.deepcopy(self.static)
        for cid, parts in self.payloads.items():
            result.append({'id': cid, 'parts': parts, 'matrix': (placements or self.initial_placements)[cid]})
        result.append({'id':'TR01', 'parts':self.car_parts + ([self.cover] if cover_on else []),
                       'matrix':vehicle_frame or self.car_frame('PS01')})
        for identity in self.stations:
            kin = self.kin(identity); q = self.arms[identity+'.PS01TransferArm']['joints_deg']
            gap = (jaws or {}).get(identity, self.hp['open_gap'])
            result.append({'id':identity+'.LabwareGripper', 'parts':handling.gripper_parts(self.context['handling']['source'],gap), 'matrix':kin.tool(q)})
        return result


def part_bounds(part):
    corners = []
    for shape in [part['shape'], *part.get('additions', [])]:
        origin = shape['origin']
        if shape['kind'] == 'box':
            lo = origin; hi = [a+b for a,b in zip(origin,shape['size'])]
        else:
            axis = shape.get('axis', [0,0,1]); end = [a+b*shape['height'] for a,b in zip(origin,axis)]
            radii = [shape['radius']*math.sqrt(max(0,1-v*v)) for v in axis]
            lo = [min(a,b)-r for a,b,r in zip(origin,end,radii)]; hi = [max(a,b)+r for a,b,r in zip(origin,end,radii)]
        corners.extend(itertools.product(*zip(lo,hi)))
    return {'min':[min(p[i] for p in corners) for i in range(3)], 'max':[max(p[i] for p in corners) for i in range(3)]}
