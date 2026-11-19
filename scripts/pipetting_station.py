"""PS01: referenced workspace, portable deck/labware and explicitly nominal tip frames."""
import copy
import json
import math
from pathlib import Path
import re

import analytics_concept as tools
import assembly_model as assembly
import robot_spec as robot
import synthetic_workspace as workspace
import tip_supply_model as tips
from tube_carrier_model import numeric_shape

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'model/pipetting-station-ps01.shared.json'
SETUP = ROOT/'model/pipetting-station-ps01.setup.json'
LABWARE = ROOT/'model/pipetting-labware.shared.json'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def exact(value, fields, label):
    require(isinstance(value, dict) and set(value) == set(fields.split()), 'Invalid '+label+' fields')


def number(value, *, positive=False):
    require(type(value) in (int, float) and math.isfinite(value) and (value > 0 if positive else value >= 0), 'Finite nonnegative number required')
    return value


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def bound(ref):
    require('source_sha256' in ref, 'Pinned source required')
    return read(assembly.validate_reference(ref))


def parameters(spec):
    require(set(spec['parameters']) == set('deck_w deck_d deck_t pitch_x pitch_y bay_w bay_d pad_t'.split()), 'Supported deck parameters required')
    p = robot.parameters(spec)
    for key, definition in spec['parameters'].items():
        exact(definition, 'expression unit range description', 'deck parameter')
        require(definition['unit'] == 'mm' and len(definition['range']) == 2, 'Explicit mm parameter range required')
        require(definition['range'][0] <= p[key] <= definition['range'][1], 'Deck parameter outside its design range')
    require(p['bay_w'] < p['pitch_x'] and p['bay_d'] < p['pitch_y'], 'Deck bays overlap')
    require(2*p['pitch_x']+p['bay_w'] <= p['deck_w'] and 2*p['pitch_y']+p['bay_d'] <= p['deck_d'], 'Bays extend outside deck')
    return p


def load(path=SOURCE):
    spec = read(path)
    exact(spec, 'format id revision date status units recipe parameters grid tool_capabilities qualifications limitations', 'station')
    require(spec['format'] == 'solidcraftbot.pipetting-station/1' and spec['id']=='PipettingStation_PS01' and spec['status'] == 'Concept; no manufacturing release', 'Unqualified PS01 station required')
    require(spec['units'] == {'length':'mm','angle':'deg'} and spec['recipe'] == 'nine_bay_open_pipetting_deck/1', 'Supported station recipe and units required')
    require(spec['grid'] == {'rows':3,'columns':3,'row_order':'rear_to_front','slot_prefix':'PS01.S'}, 'Supported nine-bay ordering required')
    parameters(spec)
    cap = spec['tool_capabilities']
    exact(cap, 'tip_supply selection channels minimum_qualified_volume_ul resolution_ul dose_accuracy_verified physical_tip_change_verified physical_tool_change_verified', 'tool capability')
    require(cap['selection'] == 'smallest_nominal_capacity' and cap['channels'] == 1, 'Single-channel nominal capacity selection required')
    require(cap['minimum_qualified_volume_ul'] is None and cap['resolution_ul'] is None, 'Minimum volume and resolution are unqualified')
    require(all(cap[k] is False for k in ('dose_accuracy_verified','physical_tip_change_verified','physical_tool_change_verified')), 'No qualified physical pipetting capability')
    tips.validate(bound(cap['tip_supply']))
    expected = {'robot_motion_implemented':False,'hardware_execution_implemented':False,'collision_free_working_paths':False,'human_speed_comparison':None,'tip_box_fit_verified':False,'sterility_verified':False}
    require(spec['qualifications'] == expected, 'PS01 is a planning and static-CAD concept')
    return spec


def part(identity, shape, color, cuts=None, role='concept_structure'):
    return {'id':identity,'shape':shape,'cuts':cuts or [],'additions':[],
            'appearance':{'color':color,'opacity':1},'role':role}


def box(origin, size):
    return {'kind':'box','origin':origin,'size':size}


def cylinder(origin, radius, height):
    return {'kind':'cylinder','origin':origin,'radius':radius,'height':height}


def deck(spec):
    p = parameters(spec)
    # Row A is at the rear. The 30 mm Y offset follows the asymmetric deck origin.
    center_y = p['pitch_y']/4
    parts = [part('Deck', box([-p['deck_w']/2, center_y-p['deck_d']/2, 0], [p['deck_w'],p['deck_d'],p['deck_t']]), '#687f8d')]
    frames = {}
    for row in range(3):
        for col in range(3):
            name = 'PS01.S%02d'%(row*3+col+1)
            x, y = (col-1)*p['pitch_x'], (1-row)*p['pitch_y']+center_y
            parts.append(part(name.replace('.','_')+'_Pad', box([x-p['bay_w']/2,y-p['bay_d']/2,p['deck_t']], [p['bay_w'],p['bay_d'],p['pad_t']]), '#c2cdd2', role='design_pad_not_a_tip_box'))
            frames[name] = workspace.pose([x,y,p['deck_t']+p['pad_t']],0)
    return parts, frames


def labware(path=LABWARE):
    catalog = read(path)
    exact(catalog, 'format id units sources types limitations', 'labware catalog')
    require(catalog['format'] == 'solidcraftbot.pipetting-labware/1' and catalog['units'] == {'length':'mm','volume':'uL'}, 'Labware contract required')
    for source in catalog['sources'].values():
        file = assembly.project_path(source['path'])
        require(file.is_relative_to(ROOT/'cad/vendor/opentrons') and robot.digest(file) == source['sha256'], 'Labware source bytes changed')
    return catalog


def well_id(value):
    match = re.fullmatch(r'([A-Z]+)([1-9][0-9]*)', value)
    require(match is not None, 'Unrecognized original well ID')
    return match[1]+match[2].zfill(2)


def labware_type(catalog, case):
    require(case in catalog['types'], 'Unknown labware type')
    definition = catalog['types'][case]
    wells = {}; cavities = []
    if definition['recipe'] == 'opentrons_circular_plate/1':
        exact(definition, 'recipe source_id color', 'plate definition')
        original = read(assembly.project_path(catalog['sources'][definition['source_id']]['path']))
        require(original['schemaVersion'] == 2 and original['parameters']['format'] == '96Standard', 'Supported circular 96-well definition required')
        size = [original['dimensions'][key] for key in ('xDimension','yDimension','zDimension')]
        ordering = original['ordering']
        require(len(ordering) == 12 and all(len(column) == 8 for column in ordering), 'Expected 8 by 12 plate ordering')
        require(len({key for column in ordering for key in column}) == 96 and set(original['wells']) == {key for column in ordering for key in column}, 'Unique complete plate ordering required')
        for col, column in enumerate(ordering):
            for row, key in enumerate(column):
                w = original['wells'][key]
                require(w['shape'] == 'circular', 'Only circular imported plate wells supported')
                x, y, z = w['x']-size[0]/2, w['y']-size[1]/2, w['z']
                radius, depth = w['diameter']/2, w['depth']
                number(radius, positive=True); number(depth, positive=True); number(w['totalLiquidVolume'],positive=True)
                require(abs(x)+radius < size[0]/2 and abs(y)+radius < size[1]/2 and z > 0 and abs(z+depth-size[2]) < 1e-6, 'Well outside plate envelope')
                wells[well_id(key)] = {'row':row,'column':col,'original_id':key,'capacity_ul':w['totalLiquidVolume'],
                                      'mouth_mm':[x,y,z+depth],'bottom_mm':[x,y,z], 'cross_section_mm2':math.pi*radius**2,
                                      'cavity':cylinder([x,y,z],radius,depth)}
                cavities.append(cylinder([x,y,z],radius,depth+.1))
        rows, cols = 8, 12
    elif definition['recipe'] == 'rectangular_reservoir_grid/1':
        exact(definition, 'recipe rows columns pitch_mm inner_size_mm wall_mm bottom_mm capacity_ul color basis', 'reservoir definition')
        rows, cols = definition['rows'], definition['columns']
        require(type(rows) is int and type(cols) is int and 1 <= rows <= 26 and 1 <= cols <= 24, 'Bounded reservoir grid required')
        sx, sy, depth = definition['inner_size_mm']; px, py = definition['pitch_mm']
        wall, floor = definition['wall_mm'], definition['bottom_mm']
        for value in [sx,sy,depth,px,py,wall,floor,definition['capacity_ul']]: number(value,positive=True)
        require(sx+wall < px and sy+wall < py and definition['capacity_ul'] < sx*sy*depth, 'Reservoir walls or capacity invalid')
        size = [(cols-1)*px+sx+2*wall,(rows-1)*py+sy+2*wall,depth+floor]
        for row in range(rows):
            for col in range(cols):
                x,y=(col-(cols-1)/2)*px,((rows-1)/2-row)*py
                shape=box([x-sx/2,y-sy/2,floor],[sx,sy,depth])
                wells[f'{chr(65+row)}{col+1:02d}']={'row':row,'column':col,'capacity_ul':definition['capacity_ul'],
                    'mouth_mm':[x,y,depth+floor],'bottom_mm':[x,y,floor],'cross_section_mm2':sx*sy,'cavity':shape}
                cavities.append(box(shape['origin'],[sx,sy,depth+.1]))
    else:
        raise ValueError('Unsupported labware recipe')
    parts = [part('Container',box([-size[0]/2,-size[1]/2,0],size),definition['color'],cavities,'labware_envelope')]
    return {'rows':rows,'columns':cols,'size_mm':size,'wells':wells,'parts':parts}


def compile_setup(path=SETUP):
    import labware_transfer as handling
    setup = read(path)
    exact(setup, 'format id workspace assets labware tip_stocks tool_visualization handling limitations', 'station setup')
    require(setup['format'] == 'solidcraftbot.pipetting-setup/1', 'PS01 setup required')
    spatial = workspace.load(assembly.validate_reference(setup['workspace']))
    require(set(spatial['devices']) == {'PS01','PS01Arm','PS01TransferArm','PS01Waste'}, 'PS01, pipetting/handling arms and T01 required')
    transfer_layout, transfer_source = handling.load(setup['handling'])
    supported = handling.bindings(transfer_layout)
    station = load(assembly.validate_reference(spatial['devices']['PS01']['source']))
    parts, local_frames = deck(station)
    frames = {name:robot.multiply(spatial['devices']['PS01']['matrix'],m) for name,m in local_frames.items()}
    tip_source = bound(station['tool_capabilities']['tip_supply'])
    assets = {key:bound(value) for key,value in setup['assets'].items()}
    require(setup['assets']['tips'] == station['tool_capabilities']['tip_supply'], 'One shared tip definition required')
    exact(setup['tool_visualization'],'case_only mount basis','tool visualization')
    require(setup['tool_visualization']['case_only'] is True and setup['tool_visualization']['mount'] == 'current_arm_flange', 'Explicit case-only tool binding required')
    tool_ref = setup['assets']['tool_envelope']; kit = assets['tool_envelope']
    require(tool_ref.get('case') == 'pipette' and kit['format'] == 'solidcraftbot.analytics-tools/1'
            and kit['cases']['pipette']['operation'] == 'flange_pipette_envelope', 'Only independent pipette envelope case is supported')
    # This case uses tcp_length_mm only; the historical kit mount is not a dependency.
    tool_parts, tool_frames = tools.kit_parts(kit, 'pipette')
    groups = [{'id':'Deck','parts':parts,'matrix':spatial['devices']['PS01']['matrix']}]
    bench = spatial['bench']
    groups.append({'id':'Bench','parts':[part('Surface',numeric_shape(bench['operations'][0]['shape'],{}),bench['bodies'][0]['appearance']['color'])],'matrix':robot.identity()})
    locations = {}; used_bays = set(); ids = set(); labwares = {}; tip_racks = []
    def instance(item):
        assembly.validate_instance(item)
        require(set(item) <= {'id','asset','host','xyz','yaw_deg','variant','pose'} and item['host'] in frames, 'Supported deck instance and bay required')
        require(item['id'] not in ids and item['host'] not in used_bays, 'Duplicate instance or occupied deck bay')
        require(item['asset'] in setup['assets'], 'Unknown deck asset')
        ids.add(item['id']);used_bays.add(item['host'])
        matrix=robot.multiply(frames[item['host']],workspace.pose(item['xyz'],item['yaw_deg']))
        if item['id'] in supported:
            require(supported[item['id']]['host']==item['host'] and item['xyz']==[0,0,0] and item['yaw_deg']==0,
                    'Carried payload must be centered on its declared carrier')
            matrix=robot.multiply(matrix,workspace.pose([0,0,handling.seat_height(transfer_source)],0))
        return matrix
    for item in setup['labware']:
        exact(item,'id asset host xyz yaw_deg','labware instance')
        matrix = instance(item); reference = setup['assets'][item['asset']]
        catalog = labware(assembly.validate_reference(reference)); definition = labware_type(catalog,reference['case'])
        p = parameters(station)
        # Every transformed footprint corner must remain on its own rectangular pad.
        local = workspace.pose(item['xyz'],item['yaw_deg'])
        require(item['xyz'][2]==0, 'Labware must sit on its declared pad')
        corners=[robot.transform(local,[x,y,0]) for x in [-definition['size_mm'][0]/2,definition['size_mm'][0]/2] for y in [-definition['size_mm'][1]/2,definition['size_mm'][1]/2]]
        require(all(abs(c[0])<=p['bay_w']/2 and abs(c[1])<=p['bay_d']/2 for c in corners), 'Labware footprint exceeds bay')
        for identity,w in definition['wells'].items():
            locations[item['id']+'.'+identity] = {**w,'labware':item['id'],'well':identity,
                'mouth_world_mm':robot.transform(matrix,w['mouth_mm']),'bottom_world_mm':robot.transform(matrix,w['bottom_mm'])}
        labwares[item['id']]={'instance':item,'matrix':matrix,**definition}
        groups.append({'id':item['id'],'parts':definition['parts'],'matrix':matrix})
    for entry in setup['tip_stocks']:
        exact(entry,'assembly registration occupancy','tip stock')
        item = entry['assembly']; matrix = instance(item); registration=entry['registration']
        require(setup['assets'][item['asset']]==station['tool_capabilities']['tip_supply'], 'Tip rack must reference the shared tip definition')
        exact(registration,'anchor mouth_height_above_pad_mm basis','tip registration')
        require(registration['anchor']=='tip_grid_center' and registration['basis']=='synthetic_setup_assumption', 'Nominal grid registration required')
        number(registration['mouth_height_above_pad_mm'],positive=True)
        local=copy.deepcopy(item); local['xyz']=[0,0,0]; local['yaw_deg']=0
        result=tips.compile_instance(tip_source,local,entry['occupancy']); p=result['parameters']
        offset=[-p['tray_axis_span_x']/2,-p['strip_axis_span']/2,registration['mouth_height_above_pad_mm']]
        transform=robot.multiply(matrix,workspace.pose(offset,0))
        local_transform=robot.multiply(workspace.pose(item['xyz'],item['yaw_deg']),workspace.pose(offset,0))
        pad=parameters(station)
        for slot in result['slots']:
            slot['mouth_world_mm']=robot.transform(transform,slot['mouth_mm'])
            local_mouth=robot.transform(local_transform,slot['mouth_mm'])
            require(abs(local_mouth[0])+p['collar_od']/2<=pad['bay_w']/2 and abs(local_mouth[1])+p['collar_od']/2<=pad['bay_d']/2,
                    'Nominal tip mouth grid exceeds its designated pad')
        result['matrix']=transform;result['registration']=registration
        tip_racks.append(result)
    require(labwares and tip_racks, 'At least one labware and tip rack required')
    arm_item=spatial['devices']['PS01Arm']; arm=assembly.load_instance(robot,arm_item['source'],arm_item.get('overrides'))
    links={name:robot.multiply(arm_item['matrix'],matrix) for name,matrix in robot.forward(arm).items()}
    flange=robot.multiply(links[arm['flange_reference']['link']],workspace.pose([robot.evaluate(v,robot.parameters(arm)) for v in arm['flange_reference']['point']],0))
    groups.append({'id':'PipetteEnvelope','parts':tool_parts,'matrix':flange})
    context={'setup':setup,'station':station,'spatial':spatial,'groups':groups,'frames':frames,'labware':labwares,
            'locations':locations,'tip_racks':tip_racks,'tip_source':tip_source,'arm':arm,
            'arm_state':{'world_links':links,'flange_matrix':flange,'tcp_world_mm':robot.transform(flange,tool_frames['tcp'])},
            'unused_bays':sorted(set(frames)-used_bays)}
    context['arms']={'PS01Arm':{'arm':arm,'state':context['arm_state']}}
    return handling.extend(context,transfer_layout,transfer_source)


def source_paths(setup_path=SETUP):
    """Pins of selected sources; the unused historical tool-mount reference is excluded explicitly."""
    found=set()
    def visit(path, case_only=False):
        path=Path(path)
        if path in found:return
        found.add(path); data=read(path)
        if case_only:return
        def walk(value):
            if isinstance(value,dict):
                if isinstance(value.get('source'),str) and value['source'].startswith('model/'):
                    visit(assembly.validate_reference(value),value.get('case')=='pipette')
                elif isinstance(value.get('path'),str) and value['path'].startswith('cad/vendor/'):
                    p=assembly.project_path(value['path']); require(robot.digest(p)==value['sha256'],'Vendor source changed');found.add(p)
                else:
                    for child in value.values():walk(child)
            elif isinstance(value,list):
                for child in value:walk(child)
        walk(data)
    visit(setup_path)
    return sorted(found)
