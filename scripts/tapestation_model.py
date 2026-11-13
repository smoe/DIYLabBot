"""Manual TapeStation workplace envelope, lowered once for both native CADs."""
import json
from pathlib import Path

import robot_spec
import tube_carrier_model as portable

ROOT = robot_spec.ROOT
SOURCE = ROOT/'model/tapestation.shared.json'
digest = robot_spec.digest
evaluate = robot_spec.evaluate


def load(path=SOURCE):
    spec = json.loads(Path(path).read_text())
    if (spec['format'] != 'solidcraftbot.tapestation/1'
            or spec['operation'] != 'manual_instrument_envelope_on_reference_bench/1'
            or spec['handling'] != 'manual_only' or spec['selected_model'] is not None
            or spec['robot_loading_implemented'] is not False or spec['result_import_implemented'] is not False
            or spec['units'] != {'length':'mm','angle':'deg'}):
        raise ValueError('Only the manual planning envelope is implemented')
    parameters(spec)
    return spec


def parameters(spec, overrides=None):
    p = robot_spec.parameters(spec, overrides)
    for name, definition in spec['parameters'].items():
        if definition['unit'] != 'mm' or not definition['range'][0] <= p[name] <= definition['range'][1]:
            raise ValueError('Outside declared planning dimensions: '+name)
    if p['bench_width'] < p['width']+2*p['side_clearance']+450 or p['bench_depth'] < p['depth']+2*p['side_clearance']:
        raise ValueError('Instrument clearance and PC area must fit on dedicated bench')
    return p


def expanded(spec, p):
    result = {'id':spec['id'], 'status':spec['status'], 'parameters':spec['parameters'],
              'parameter_values':p, 'components':[{'id':'Frame','grounded':True}],
              'bodies':[], 'operations':[], 'joints':[]}
    def box(name, origin, size, color, role):
        result['bodies'].append({'id':name,'component':'Frame','role':role,'appearance':{'color':color,'opacity':1}})
        result['operations'].append({'id':name,'body':name,'action':'create',
                                    'shape':{'kind':'box','origin':origin,'size':size}})
    box('Worktop', [0,0,'bench_z-30'], ['bench_width','bench_depth',30], '#b7c6c5','synthetic_worktop')
    for name, x, y in [('FL',25,25),('FR','bench_width-55',25),('RL',25,'bench_depth-55'),('RR','bench_width-55','bench_depth-55')]:
        box('Leg'+name,[x,y,0],[30,30,'bench_z-30'],'#7895a1','synthetic_bench_leg')
    # Two disjoint volumes express only the closed outer envelope and a lid seam.
    box('InstrumentHousing',['side_clearance','side_clearance','bench_z'],
        ['width','depth','height-20'],'#e2e8ed','planning_instrument_envelope')
    box('InstrumentLid',['side_clearance','side_clearance','bench_z+height-20'],
        ['width','depth',20],'#344e65','static_lid_envelope')
    box('PCFootprint',['side_clearance+width+100','side_clearance','bench_z'],
        [400,260,20],'#324d5d','illustrative_laptop_envelope')
    if spec.get('_mounting') == 'instrument_only':
        keep = {'InstrumentHousing', 'InstrumentLid', 'PCFootprint'}
        result['bodies'] = [body for body in result['bodies'] if body['id'] in keep]
        result['operations'] = [op for op in result['operations'] if op['body'] in keep]
        for op in result['operations']:
            origin = op['shape']['origin']
            op['shape']['origin'] = [f'({origin[0]})-side_clearance',
                                     f'({origin[1]})-side_clearance', f'({origin[2]})-bench_z']
        # PC beside the instrument along the bench, within a 750 mm island half.
        result['operations'][-1]['shape']['origin'] = [0, 'depth+100', 0]
    return result


def interfaces(spec, p):
    return {'TS01.Worktop':{'origin_mm':[0,0,p['bench_z']]},
            'TS01.ManualHandoff':{'origin_mm':[p['bench_width']/2,p['bench_depth']-100,p['bench_z']],
                                 'handling':'manual_only','robot_reach_qualified':False},
            'installation_keepout':{'origin_mm':[0,0,p['bench_z']],
                'size_mm':[p['width']+2*p['side_clearance'],p['depth']+2*p['side_clearance'],p['height']+p['top_clearance']],
                'kind':'planning_requirement_not_physical_body'}}


def pose(spec, p, name=None):
    return {}


def samples(spec, p):
    return [{'id':'closed','joint_values':{}}]


def solidcraft_commands(spec, p):
    import sys
    return portable.solidcraft_commands(spec,p,sys.modules[__name__])
