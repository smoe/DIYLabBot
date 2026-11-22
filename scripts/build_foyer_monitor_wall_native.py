"""Build SolidCraft displays and a conservative shared-source neighbourhood.

This is deliberately not a new full-building SolidCraft certificate. Bodies
outside a declared source-AABB distance are pruned, before either CAD is read.
The complete FreeCAD world is audited separately by the native checker.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import time
from types import SimpleNamespace

import build_building_stack as evidence
import build_extraction_kit_station as common
import building_stack as building
import building_room_signs as room_signs
import microscope_model
import tool_paths
import tube_carrier_model as portable

ROOT = Path(__file__).resolve().parents[1]
FORMAT = 'solidcraftbot.foyer-monitor-wall-solidcraft-scope/1'
DEFAULT_RADIUS_MM = 2000.


def distance(first,second):
    return math.sqrt(sum(max(0.,first['min'][i]-second['max'][i],
                            second['min'][i]-first['max'][i])**2 for i in range(3)))


def shape_bounds(shape):
    """Bound glyph cylinders in their declared world frame before pruning."""
    if shape['kind'] != 'cylinder_bundle':
        return microscope_model.shape_bounds(shape)
    room_signs.validate_bundle(shape)
    frame = shape['frame']; axes = [frame[key] for key in ('x','y','z')]
    boxes = []
    for span in shape['glyph_spans']:
        for cylinder in shape['cylinders'][span['start']:span['start']+span['count']]:
            local = [a+b for a,b in zip(cylinder['origin'],span['offset_mm'])]
            origin = [frame['origin'][i]+sum(local[j]*axes[j][i] for j in range(3)) for i in range(3)]
            axis = [sum(cylinder['axis'][j]*axes[j][i] for j in range(3)) for i in range(3)]
            boxes.append(microscope_model.shape_bounds({**cylinder,'kind':'cylinder','origin':origin,'axis':axis}))
    return {edge:[fn(box[edge][i] for box in boxes) for i in range(3)]
            for edge,fn in [('min',min),('max',max)]}


def source_bounds(source):
    """Positive primitive unions conservatively enclose every subsequent cut."""
    boxes = {}
    for operation in source['operations']:
        if operation['action'] == 'cut':
            continue
        box = shape_bounds(operation['shape'])
        if any(not math.isfinite(v)for edge in ('min','max')for v in box[edge]):
            raise ValueError('Finite source bounds required')
        name = operation['body']
        if name not in boxes:
            boxes[name] = box
        else:
            boxes[name] = {edge:[fn(a,b)for a,b in zip(boxes[name][edge],box[edge])]
                           for edge,fn in [('min',min),('max',max)]}
    if set(boxes) != {body['id']for body in source['bodies']}:
        raise ValueError('Each source body needs a positive primitive bound')
    return boxes


def select_scope(source,wall,radius=DEFAULT_RADIUS_MM):
    if type(radius)not in (int,float) or not math.isfinite(radius) or radius <= 0:
        raise ValueError('Positive finite source neighbourhood radius required')
    boxes = source_bounds(source)
    monitors = set(wall['body_ids'])
    total = {edge:[fn(boxes[name][edge][i]for name in monitors)for i in range(3)]
             for edge,fn in [('min',min),('max',max)]}
    lower = {name:distance(total,box)for name,box in boxes.items()}
    chosen = sorted(name for name,value in lower.items()if value <= radius)
    if wall['wall_body_id']not in chosen or not monitors <= set(chosen):
        raise ValueError('Source scope must contain all displays and their mounting wall')
    subset = {**source,'bodies':[b for b in source['bodies']if b['id']in chosen],
              'operations':[op for op in source['operations']if op['body']in chosen]}
    return subset, {'selected_body_ids':chosen,'full_building_body_count':len(boxes),
                    'radius_mm':radius,'monitor_bounds_mm':total,
                    'excluded_body_lower_bounds_mm':{name:value for name,value in lower.items()if name not in chosen},
                    'source_body_bounds_mm':boxes,
                    'method':'Union AABBs of every positive shared primitive; subtraction cannot enlarge them. Selected before reading CAD output.'}


def solidcraft_scope_commands(source, spec, params):
    """Reuse the building's physical and glyph lowering for the selected bodies."""
    physical = room_signs.physical_source(source)
    provider = SimpleNamespace(SOURCE=building.SOURCE,expanded=lambda *_:physical,
                               pose=lambda *_:{},samples=lambda *_:[])
    commands = portable.solidcraft_commands(spec,params,provider)
    commands.extend(room_signs.solidcraft_ink_commands(source))
    return commands


def build(args):
    start = time.monotonic()
    spec = building.load(); params = building.parameters(spec)
    source = building.expanded(spec,params); wall = building.interfaces(spec,params)['monitor_wall']
    subset,scope = select_scope(source,wall,args.radius_mm)
    pins = evidence.snapshot(spec,building.SOURCE)
    pins[str(Path(__file__).relative_to(ROOT))] = building.digest(__file__)
    key = hashlib.sha256(json.dumps({'pins':pins,'radius_mm':args.radius_mm},sort_keys=True).encode()).hexdigest()[:12]
    stem = 'foyer-monitor-native-'+key; revision = stem; index = 1
    while any((ROOT/top/revision).exists()for top in ('exports/generated','cad/generated')):
        index += 1;revision = stem+'-r'+str(index)
    out = ROOT/'exports/generated'/revision; cad = ROOT/'cad/generated'/revision
    out.mkdir(parents=True);cad.mkdir(parents=True)
    files = {'commands':out/'commands.json','solidcraft':cad/'FoyerMonitorScope.sc',
             'solidcraft_measurements':out/'solidcraft.json'}
    commands = solidcraft_scope_commands(subset,building.native_spec(spec,params),params)
    common.write(files['commands'],{'commands':commands})
    common.verify_pins(pins)
    print('Building SolidCraft monitor scope:',len(subset['bodies']),'of',len(source['bodies']),'shared bodies',flush=True)
    subprocess.run([args.solidcraft_cli,'run',str(files['commands']),'--save',str(files['solidcraft']),
                    '--quiet','--json-out',str(files['solidcraft_measurements'])],
                   check=True,cwd=ROOT,stdout=subprocess.DEVNULL)
    raw = json.loads(files['solidcraft_measurements'].read_text())
    geometry = common.measurements(raw,subset,backend='solidcraft')
    common.verify_pins(pins)
    report = {'format':FORMAT,'revision':revision,'passed':True,
              'source':str(building.SOURCE.relative_to(ROOT)),
              'source_sha256':building.digest(building.SOURCE),'source_files_sha256':pins,
              'files':{key:str(path.relative_to(ROOT))for key,path in files.items()},
              'artifact_sha256':{key:building.digest(path)for key,path in files.items()},
              'geometry':geometry,'selection':scope,'elapsed_s':time.monotonic()-start,
              'full_solidcraft_building_built':False,
              'qualification':'Independent shared-source SolidCraft neighbourhood only; complete FreeCAD world comparison and clearance audit are separate.'}
    common.write(out/'build-report.json',report)
    print(str(out/'build-report.json'),flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--radius-mm',type=float,default=DEFAULT_RADIUS_MM)
    tool_paths.add_tool_arguments(parser,freecad=False)
    args = parser.parse_args();tool_paths.resolve_tool_arguments(parser,args)
    build(args)


if __name__ == '__main__':
    main()
