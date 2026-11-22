"""Audit the source-bound foyer displays against independently built CAD bodies.

The FreeCAD worker reads FCStd BReps; SolidCraft reads its own saved design.
Only the declared static native pose is checked, not moving-door sweeps,
walking clearances, mounting strength or hardware safety.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

import build_extraction_kit_station as common
import build_foyer_monitor_wall_native as scoped
import building_stack as building
import export_building_walkthrough_freecad as native
import foyer_monitor_wall
import microscope_model
import tool_paths

ROOT = Path(__file__).resolve().parents[1]
FORMAT = 'solidcraftbot.foyer-monitor-wall-native-audit/1'
VOLUME_TOLERANCE_MM3 = 1e-5
DIMENSION_TOLERANCE_MM = 0.01


def audit_source_pins(root=ROOT):
    """Capture the audit code and its report-verification helper before use."""
    paths = [Path(filename).resolve() for filename in (__file__, native.__file__)]
    return {path.relative_to(root).as_posix(): native.digest(path) for path in paths}


def build_input_evidence(path, report, root=ROOT):
    """Bind the original report bytes and every artifact it supplied to this audit."""
    root = Path(root).resolve()
    path = native.project_path(path, root)
    raw = path.read_bytes()
    if json.loads(raw) != report:
        raise ValueError('Native build report changed while its evidence was captured')
    files, hashes = report.get('files'), report.get('artifact_sha256')
    if (not isinstance(files,dict) or not files or not isinstance(hashes,dict)
            or set(files) != set(hashes)):
        raise ValueError('Every original native build artifact needs its own pin')
    record = {'report':{'path':str(path.relative_to(root)),
                        'sha256':hashlib.sha256(raw).hexdigest()},
              'artifacts':{key:{'path':name,'sha256':hashes[key]}for key,name in files.items()},
              'source_files_sha256':report['source_files_sha256']}
    verify_build_input_evidence({'build':record},root)
    return record


def verify_build_input_evidence(builds, root=ROOT):
    """Recheck both original reports, their source pins, and all CAD input bytes."""
    if not isinstance(builds,dict) or not builds:
        raise ValueError('Native build input evidence is required')
    pins = {}
    for record in builds.values():
        if (not isinstance(record,dict) or not record.get('artifacts')
                or not record.get('source_files_sha256')):
            raise ValueError('Complete original native build input evidence required')
        refs = [record['report'],*record['artifacts'].values()]
        for ref in refs:
            if not isinstance(ref,dict) or set(ref) != {'path','sha256'}:
                raise ValueError('Original native build inputs need path and SHA256')
            if ref['path'] in pins and pins[ref['path']] != ref['sha256']:
                raise ValueError('Native build inputs disagree: '+ref['path'])
            pins[ref['path']] = ref['sha256']
        native.verify_pins(record['source_files_sha256'],root)
    native.verify_pins(pins,root)
    return pins


def box_distance(first, second):
    """A conservative distance lower bound, never a native distance claim."""
    return math.sqrt(sum(max(0., first['min'][i] - second['max'][i],
                            second['min'][i] - first['max'][i])**2 for i in range(3)))


def validate_scope(wall, body_names):
    if wall.get('level_id') != 'EG' or wall.get('wall') != 'W052' or wall.get('area') != 'R0_019':
        raise ValueError('The explicit EG foyer wall is required')
    if wall['wall_body_id'] not in body_names:
        raise ValueError('The intended native mounting wall is required')
    monitors = foyer_monitor_wall.validate_instances(wall, body_names)
    for row in monitors:
        frame = row['screen_frame']
        vectors = [frame[k] for k in ('origin_mm', 'x_axis', 'y_axis', 'normal')]
        values = [v for vector in vectors for v in vector] + [frame['width_mm'], frame['height_mm']]
        if (any(len(vector) != 3 for vector in vectors)
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in values)
                or frame['width_mm'] <= 0 or frame['height_mm'] <= 0):
            raise ValueError('Finite screen dimensions and frame required')
        x, y, normal = vectors[1:]
        cross = [x[1]*y[2]-x[2]*y[1],x[2]*y[0]-x[0]*y[2],x[0]*y[1]-x[1]*y[0]]
        if (any(abs(sum(v*v for v in axis)-1) > 1e-7 for axis in (x,y,normal))
                or abs(sum(a*b for a,b in zip(x,y))) > 1e-7
                or max(abs(a-b) for a,b in zip(cross,normal)) > 1e-7
                or sum(a*b for a,b in zip(normal, [0,-1,0])) < 1-1e-7):
            raise ValueError('Screen front must face the actual foyer side')
    return monitors


def geometry_checks(wall, geometry, operations):
    by_name = {row['body']: row for row in geometry}
    monitors = validate_scope(wall, by_name)
    source = {row['body']: row for row in operations if row['body'] in wall['body_ids']}
    if set(source) != set(wall['body_ids']) or any(row['action'] != 'create' for row in source.values()):
        raise ValueError('One portable creation per monitor body required')
    checks = []
    for monitor in monitors:
        for name in monitor['body_ids']:
            expected = microscope_model.shape_bounds(source[name]['shape'])
            actual = by_name[name]['bbox']
            error = max(abs(a-b) for edge in ('min','max')
                        for a,b in zip(actual[edge], expected[edge]))
            checks.append({'body':name, 'instance_id':monitor['id'],
                           'maximum_bbox_error_mm':error,
                           'passed':error <= DIMENSION_TOLERANCE_MM})
        screen = by_name[monitor['screen_body_id']]['bbox']; frame = monitor['screen_frame']
        front = [(screen['min'][0]+screen['max'][0])/2,screen['min'][1],
                 (screen['min'][2]+screen['max'][2])/2]
        error = max([abs(a-b)for a,b in zip(front,frame['origin_mm'])]
                    +[abs(screen['max'][0]-screen['min'][0]-frame['width_mm']),
                      abs(screen['max'][2]-screen['min'][2]-frame['height_mm'])])
        checks.append({'body':monitor['screen_body_id'],'instance_id':monitor['id'],
                       'category':'actual_native_screen_front', 'maximum_frame_error_mm':error,
                       'passed':error <= DIMENSION_TOLERANCE_MM})
    return checks


def mounting_checks(wall, nearest):
    result = []
    for monitor in wall['monitors']:
        mounts = set(monitor['body_ids'])-{monitor['case_body_id'],monitor['screen_body_id']}
        if not mounts:
            raise ValueError('An actual native mounting body is required')
        for name in sorted(mounts):
            row = nearest[name]
            result.append({'body':name,'host_body':row['body'],'distance_mm':row['distance_mm'],
                           'passed':row['body'] == wall['wall_body_id'] and row['distance_mm'] <= 1e-6})
    return result


def check_clearance_result(result, required_bodies):
    """Do not interpret unchecked or incomplete SolidCraft replies as a pass."""
    if (not isinstance(result, dict)
            or not {'overlaps','near','nearest','unchecked','pairs_checked','truncated','bodies'} <= set(result)
            or any(type(result[key]) is not list for key in ('overlaps','near','unchecked'))
            or type(result['nearest']) is not dict or result['unchecked']
            or type(result['pairs_checked']) is not int or type(result['bodies']) is not int
            or result['pairs_checked'] < 0 or result['truncated'] is not False
            or result['bodies'] != len(required_bodies)
            or set(result['nearest']) != set(required_bodies)):
        raise ValueError('Complete exact SolidCraft clearance evidence required')
    for name, rows in result['nearest'].items():
        if (len(rows) != 1 or not isinstance(rows[0].get('body'), str)
                or rows[0]['body'] in required_bodies):
            raise ValueError('Each monitor body needs one exact nearest obstacle')
        distance = rows[0].get('distance_mm')
        if type(distance) not in (int,float) or not math.isfinite(distance) or distance < 0:
            raise ValueError('Finite nonnegative native distance required')
    for row in result['near']:
        distance = row.get('distance_mm')
        if (row.get('exact') is False or type(distance) not in (int,float)
                or not math.isfinite(distance) or distance < 0):
            raise ValueError('Finite exact native near distances are required')
    for row in result['overlaps']:
        volume = row.get('volume_mm3')
        if (type(volume) not in (int,float) or not math.isfinite(volume)
                or volume < 0 or volume > VOLUME_TOLERANCE_MM3):
            raise ValueError('The monitor wall overlaps its environment or has invalid overlap evidence')
    return result


def freecad_worker(job):
    import FreeCAD as App
    sys.path.insert(0, str(ROOT/'scripts/freecad'))
    import solidcraftbot_freecad as geo
    import build_tube_carrier_freecad as measurement

    native.verify_pins(job['source_files_sha256'])
    path = native.project_path(job['native_path'])
    if native.digest(path) != job['native_sha256']:
        raise ValueError('Changed FreeCAD building')
    doc = App.openDocument(str(path))
    try:
        shapes = {obj.SourceBody:geo.world_shape(obj) for obj in geo.features(doc)}
        geometry = measurement.measurements(doc)
        checks = geometry_checks(job['wall'], geometry, job['operations'])
        monitor_ids = set(job['wall']['body_ids'])
        host = job['wall']['wall_body_id']
        bounds = {row['body']:row['bbox'] for row in geometry}
        scopes = {'mounting_wall':[host],
                  'other_building_bodies':sorted(set(shapes)-monitor_ids-{host})}
        result = {}
        for category, names in scopes.items():
            nearest = {}; overlaps = []; contacts = []; exact = 0; bounded = 0
            for name in sorted(monitor_ids):
                best = math.inf; other_id = None
                candidates = sorted((box_distance(bounds[name],bounds[other]),other) for other in names)
                for lower, other in candidates:
                    if lower > best:
                        bounded += 1
                        continue
                    exact += 1
                    distance = shapes[name].distToShape(shapes[other])[0]
                    if not math.isfinite(distance) or distance < 0:
                        raise ValueError('Invalid native FreeCAD distance')
                    if distance < best:
                        best,other_id = distance,other
                    if lower <= 1e-7:
                        volume = shapes[name].common(shapes[other]).Volume
                        if volume > VOLUME_TOLERANCE_MM3:
                            overlaps.append({'a':name,'b':other,'volume_mm3':volume})
                        elif distance <= 1e-7:
                            contacts.append({'a':name,'b':other,'volume_mm3':volume})
                if other_id is None or not math.isfinite(best):
                    raise ValueError('Missing native nearest-obstacle evidence')
                nearest[name] = {'body':other_id,'distance_mm':best}
            result[category] = {'nearest':nearest,'overlaps':overlaps,'contacts':contacts,
                                'exact_distance_queries':exact,'aabb_pruned_pairs':bounded,
                                'passed':not overlaps}
        mounting = mounting_checks(job['wall'],result['mounting_wall']['nearest'])
        pruning = []
        for name,box in job.get('excluded_source_bounds',{}).items():
            actual = bounds[name]
            error = max([box['min'][i]-actual['min'][i]for i in range(3)]
                        +[actual['max'][i]-box['max'][i]for i in range(3)])
            pruning.append({'body':name,'maximum_bound_escape_mm':max(0.,error),
                            'passed':error <= DIMENSION_TOLERANCE_MM})
        report = {'passed':all(row['passed'] for row in checks+mounting) and all(row['passed'] for row in result.values()),
                  'geometry_checks':checks,'mounting_checks':mounting,'clearances':result,'freecad_version':App.Version(),
                  'full_native_building_body_count':len(shapes),
                  'scoped_geometry':[row for row in geometry if row['body'] in job['selected_body_ids']],
                  'source_pruning_checks':pruning,
                  'scope':'Exact static native FCStd BReps; mounting-wall contacts separated from environment'}
        report['passed'] &= all(row['passed']for row in pruning)
        native.verify_pins(job['source_files_sha256'])
        if native.digest(path) != job['native_sha256']:
            raise ValueError('Native check modified saved FreeCAD building')
        common.write(job['output'], report)
        return report
    finally:
        App.closeDocument(doc.Name)


def check(report_path, output, *, freecad_python, solidcraft_cli, solidcraft_report=None):
    pins = audit_source_pins()
    report_path = native.project_path(report_path)
    build_digest = native.digest(report_path)
    report = native.checked_report(report_path, 'building')
    fc_input = build_input_evidence(report_path,report)
    if fc_input['report']['sha256'] != build_digest:
        raise ValueError('Building report changed before the native audit')
    spec = building.load(ROOT/report['source']); params = building.parameters(spec)
    interface = building.interfaces(spec, params); expanded = building.expanded(spec, params)
    wall = interface.get('monitor_wall')
    if wall is None:
        raise ValueError('The native building does not contain the foyer monitor wall')
    selected_source = expanded
    selection = None
    if solidcraft_report:
        scope_path = native.project_path(solidcraft_report)
        sc_report = json.loads(scope_path.read_text())
        if (sc_report.get('format') != scoped.FORMAT or sc_report.get('passed') is not True
                or sc_report.get('source_sha256') != report['source_sha256']):
            raise ValueError('Current source-bound SolidCraft neighbourhood report required')
        native.verify_pins(sc_report['source_files_sha256'])
        native.verify_pins({name:sc_report['artifact_sha256'][key]for key,name in sc_report['files'].items()})
        selected_source,selection = scoped.select_scope(expanded,wall,sc_report['selection']['radius_mm'])
        if selection != sc_report['selection']:
            raise ValueError('SolidCraft neighbour selection no longer matches shared source bounds')
    else:
        sc_report = report
        scope_path = report_path
        if report.get('backends') != 'both' or not {'solidcraft','solidcraft_measurements'} <= set(report['files']):
            raise ValueError('Provide a separate current SolidCraft scope report for a FreeCAD-only building')
    native_builds = {'freecad':fc_input,'solidcraft':build_input_evidence(scope_path,sc_report)}
    verify_build_input_evidence(native_builds)
    for record in native_builds.values():
        for name, expected in record['source_files_sha256'].items():
            if pins.setdefault(name, expected) != expected:
                raise ValueError('Native audit and build source snapshots disagree: '+name)
    native.verify_pins(pins)
    output = native.project_path(output)
    if not output.is_relative_to(ROOT/'exports'):
        raise ValueError('New native monitor evidence belongs under exports/')
    if output.exists():
        raise FileExistsError('Native monitor audits preserve existing results: '+str(output))
    output.mkdir(parents=True)
    sc_raw = json.loads(native.project_path(sc_report['files']['solidcraft_measurements']).read_text())
    sc_geometry = common.measurements(sc_raw, selected_source, backend='solidcraft')
    monitors = validate_scope(wall, [row['body'] for row in sc_geometry])
    checks = geometry_checks(wall, sc_geometry, expanded['operations'])
    host = wall['wall_body_id']; selected = sorted(wall['body_ids'])
    against = sorted({row['body'] for row in sc_geometry}-set(selected))
    commands = [{'command':'inspect.clearance','params':{
                    'bodies':selected, 'against':targets, 'nearest':1,
                    'min_volume':VOLUME_TOLERANCE_MM3, 'clearance':1e-6, 'tolerance':1e-7}}
                for targets in ([host], [name for name in against if name != host])]
    common.write(output/'solidcraft.commands.json', {'commands':commands})
    sc_path = native.project_path(sc_report['files']['solidcraft']); before = native.digest(sc_path)
    subprocess.run([solidcraft_cli,'run',str(output/'solidcraft.commands.json'),'--in',str(sc_path),
                    '--results','--quiet','--json-out',str(output/'solidcraft.clearances.json')],
                   check=True, cwd=ROOT, stdout=subprocess.DEVNULL)
    if native.digest(sc_path) != before:
        raise ValueError('Native check modified saved SolidCraft building')
    rows = json.loads((output/'solidcraft.clearances.json').read_text())
    if not isinstance(rows,list) or len(rows) != 2:
        raise ValueError('Both SolidCraft environmental scopes must be checked')
    for row in rows:
        check_clearance_result(row,selected)
    mounting = mounting_checks(wall,{name:row[0]for name,row in rows[0]['nearest'].items()})
    sc = {'passed':all(row['passed'] for row in checks+mounting),'geometry_checks':checks,'mounting_checks':mounting,
          'clearances':dict(zip(('mounting_wall','other_building_bodies'),rows))}
    job = {'wall':wall,'operations':[row for row in expanded['operations'] if row['body'] in selected],
           'source_files_sha256':pins,'native_path':report['files']['freecad'],
           'native_sha256':report['artifact_sha256']['freecad'],'output':str(output/'freecad.json'),
           'selected_body_ids':[row['body']for row in sc_geometry],
           'excluded_source_bounds':({name:selection['source_body_bounds_mm'][name]
                                     for name in selection['excluded_body_lower_bounds_mm']}if selection else {})}
    common.write(output/'freecad.job.json', job)
    subprocess.run([freecad_python,str(Path(__file__)),'--freecad-worker',str(output/'freecad.job.json')],
                   check=True,cwd=ROOT,env=common.freecad_environment(freecad_python))
    fc = json.loads((output/'freecad.json').read_text())
    comparison = common.compare(sc_geometry,fc['scoped_geometry'])
    result = {'format':FORMAT,'passed':sc['passed'] and fc['passed'] and all(row['passed']for row in comparison),'instances':len(monitors),
              'grid_rows':wall['grid_rows'],'grid_columns':wall['grid_columns'],
              'body_count':len(selected),'source_files_sha256':pins,
              'native_build':{'path':str(report_path.relative_to(ROOT)),'sha256':build_digest},
              'native_builds':native_builds,
              'solidcraft':sc,'freecad':fc,'metric_scale_known':False,
              'cross_cad_comparisons':comparison,
              'solidcraft_full_building_checked':selection is None,
              'solidcraft_scope_body_count':len(sc_geometry),
              'solidcraft_source_selection':selection,
              'door_motion_checked':False,'hardware_executed':False,
              'scope':'Static monitor assembly: exact complete FreeCAD building world; independent SolidCraft shared-source neighbourhood with conservative pruning. Host-wall contacts separated; no full SolidCraft building, door-motion, human-clearance, structural or safety qualification.'}
    native.verify_pins(pins)
    result['native_input_files_sha256'] = verify_build_input_evidence(native_builds)
    result['artifacts_sha256'] = {path.name:native.digest(path) for path in sorted(output.iterdir())
                                 if path.is_file()}
    common.write(output/'report.json', result)
    if not result['passed']:
        raise ValueError('Native foyer monitor audit failed: '+str(output/'report.json'))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('build_report',nargs='?')
    parser.add_argument('output_dir',nargs='?')
    parser.add_argument('--freecad-worker',help=argparse.SUPPRESS)
    parser.add_argument('--solidcraft-report',help='Independent shared-source SolidCraft neighbourhood report')
    tool_paths.add_tool_arguments(parser)
    args = parser.parse_args()
    if args.freecad_worker:
        freecad_worker(json.loads(Path(args.freecad_worker).read_text()))
        return
    if not args.build_report or not args.output_dir:
        parser.error('build_report and output_dir are required')
    tool_paths.resolve_tool_arguments(parser,args)
    result = check(args.build_report,args.output_dir,freecad_python=args.freecad_python,
                   solidcraft_cli=args.solidcraft_cli,solidcraft_report=args.solidcraft_report)
    print(json.dumps({'passed':result['passed'],'instances':result['instances'],
                      'body_count':result['body_count'],'scope':result['scope']},indent=2))


if __name__ == '__main__':
    main()
