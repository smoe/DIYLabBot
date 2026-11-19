"""Compile tip-supply data and evidence; optionally screen nominal gauges in T01."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import tip_supply_model as model


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)+'\n', encoding='utf-8')


def evidence(spec, directory):
    result = {}
    for identity, source in spec['sources'].items():
        path = Path(directory)/source['file']
        if not path.is_file():
            raise ValueError('Missing manufacturer original: '+str(path)+'; source URL: '+source['url'])
        actual = model.robot.digest(path)
        if actual != source['sha256']:
            raise ValueError('Manufacturer original differs from reviewed bytes: '+identity)
        result[identity] = {**source, 'local_file': str(path.resolve()), 'verified_sha256': actual}
    return result


def dependencies(spec):
    names = ['model/tip-supply.shared.json', 'model/tip-supply.instances.json', 'model/tip-supply.schema.json',
             'model/assembly-reference.schema.json', 'scripts/tip_supply_model.py', 'scripts/build_tip_supply.py',
             'scripts/assembly_model.py', 'scripts/robot_spec.py', 'scripts/lab_layout_model.py',
             'scripts/tip_collector_model.py', 'scripts/build_tip_collector_freecad.py',
             'scripts/build_neutral_freecad.py', 'scripts/build_instrument_concepts.py', 'scripts/tool_paths.py',
             spec['fit_to']['assembly']['source']]
    station = model.collector.load(model.assembly.validate_reference(spec['fit_to']['assembly']))
    names.append(station['marking_asset'])
    return {name: model.robot.digest(model.ROOT/name) for name in names}


def freecad_screen(report_path):
    """Cylindrical gauges of documented nominal ODs, never invented tip solids."""
    import FreeCAD as App
    import Part
    import build_tip_collector_freecad as native
    spec = model.load()
    station = model.collector.load(model.assembly.validate_reference(spec['fit_to']['assembly']))
    station_p = model.collector.parameters(station)
    cad_path = Path(report_path).with_suffix('.FCStd')
    doc = native.build(station, station_p, cad_path)
    try:
        shapes = {obj.SourceBody: obj.Shape for obj in doc.Objects if 'SourceBody' in obj.PropertiesList}
        geometry = native.measurements(doc)
        analytic = native.analytic_check(doc, station, station_p)
        checks = []
        for variant, lane in spec['fit_to']['grooves'].items():
            p = model.parameters(spec, variant)
            for parameter in ('collar_od', 'body_diameter_callout'):
                diameter = p[parameter]
                gauge = Part.makeCylinder(diameter/2, station_p['fork_t'],
                                          App.Vector(station_p['lane_'+lane+'_x'], 0, station_p['fork_z']))
                overlap = shapes['Fork_'+lane].common(gauge).Volume
                expected_contact = diameter > station_p['groove_'+lane]
                checks.append({'variant': variant, 'parameter': parameter, 'diameter_mm': diameter,
                               'groove_width_mm': station_p['groove_'+lane], 'intersection_mm3': overlap,
                               'expected_gauge_contact': expected_contact,
                               'passed': (overlap > 1e-7) if expected_contact else (overlap < 1e-7)})
        passed = (len(geometry) == 14 and all(g['valid'] and g['solid_count'] == 1 for g in geometry)
                  and all(c['passed'] for c in analytic+checks))
        report = {'passed': passed, 'freecad_version': App.Version(), 'source_files_sha256': dependencies(spec),
                  'native_file': str(cad_path.resolve()), 'native_sha256': model.robot.digest(cad_path),
                  't01_analytic_checks': analytic, 'gauge_checks': checks,
                  'tip_fit_status': {v: model.fit_check(spec, v)['status'] for v in spec['variants']},
                  'full_tip_fit_checked': False, 'tip_or_box_solids_generated': False,
                  'scope': 'Six nominal cylindrical gauge intersections against the unchanged native T01 forks. Gauge height equals fork thickness; it is not a tip collar/shaft model or a compatibility qualification.'}
        write(report_path, report)
        if not passed:
            raise AssertionError('Native T01 gauge screen differs from the analytical width comparison')
    finally:
        App.closeDocument(doc.Name)


def build(*, evidence_dir, output_root, check_freecad=False, freecad_python=None):
    spec = model.load(); pins = dependencies(spec)
    sources = evidence(spec, evidence_dir)
    instances = model.compile_instances()
    stamp = hashlib.sha256(json.dumps(pins, sort_keys=True).encode()).hexdigest()[:12]
    revision = 'tip-supply-'+stamp; destination = Path(output_root)/revision; counter = 1
    while destination.exists():
        counter += 1; destination = Path(output_root)/(revision+'-r'+str(counter))
    destination.mkdir(parents=True)
    compiled_path = destination/'instances.json'; write(compiled_path, instances)
    files = {'instances': str(compiled_path.resolve())}
    native = {'status': 'not_run', 'full_tip_fit_checked': False, 'tip_or_box_solids_generated': False}
    if check_freecad:
        import tool_paths
        from build_instrument_concepts import freecad_environment
        runtime = freecad_python or tool_paths.default_freecad_python()
        if not runtime:
            raise ValueError('FreeCAD runtime unavailable; omit --check-freecad for the CAD-free build')
        native_path = destination/'native-gauge-screen.json'
        subprocess.run([runtime, str(Path(__file__).resolve()), '--native-screen', str(native_path.resolve())],
                       check=True, env=freecad_environment(runtime))
        native = json.loads(native_path.read_text())
        files.update(native_report=str(native_path.resolve()), native_t01=native['native_file'])
    if dependencies(spec) != pins:
        raise ValueError('Tip-supply source or generator changed during build')
    variants = {}
    for variant, definition in spec['variants'].items():
        variants[variant] = {'article': definition['article'], 'parameters': model.parameters(spec, variant),
                             'parameter_units': {k: v['unit'] for k, v in spec['parameters'].items()},
                             'dimension_evidence': definition['dimension_evidence'],
                             'unknown_measurements': definition['unknown_measurements'],
                             'fit_to_T01': model.fit_check(spec, variant)}
    report = {'format': 'solidcraftbot.tip-supply-report/1', 'passed': True,
              'scope': 'Source consistency, declared occupancy and manufacturer-original integrity; not manufacturing, physical tip fit or observed stock.',
              'revision': destination.name, 'source_files_sha256': pins, 'manufacturer_sources': sources,
              'variants': variants, 'geometry_definition': spec['geometry'],
              'instance_counts': {i['id']: i['occupied_count'] for i in instances},
              'native_screen': native, 'native_tip_and_box_geometry_supported': False,
              'files': files, 'artifact_sha256': {k: model.robot.digest(Path(v)) for k, v in files.items()},
              'open_tasks': spec['open_tasks'], 'limitations': spec['limitations']}
    path = destination/'build-report.json'; write(path, report)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-dir', type=Path, default=model.ROOT/'exports/tip-supply/evidence')
    parser.add_argument('--output-root', type=Path, default=model.ROOT/'exports/generated')
    parser.add_argument('--check-freecad', action='store_true', help='Check nominal gauges against native T01, not full tip compatibility')
    parser.add_argument('--freecad-python')
    args = parser.parse_args()
    path = build(**vars(args)); print('Tip-supply data/evidence checks passed: '+str(path), flush=True)


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--native-screen':
        freecad_screen(Path(sys.argv[2]))
    else:
        main()
