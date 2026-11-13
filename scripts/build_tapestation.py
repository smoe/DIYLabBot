"""Build and check the static TS01 manual workplace in independent CAD backends."""
import argparse
import json
from pathlib import Path
import subprocess
import time

import tapestation_model as model
import tool_paths
from build_extraction_kit_station import (write, relative, measurements, compare,
                                          freecad_environment, verify_pins)


def freecad_build(output, report):
    import FreeCAD as App
    import build_tube_carrier_freecad as native
    spec = model.load(); p = model.parameters(spec)
    native.model = model
    doc = native.build(spec,p,Path(output))
    geometry = native.measurements(doc)
    interference = native.interference(doc)
    passed = (all(item['valid'] and item['solid_count']==1 for item in geometry)
              and not interference['between_components'] and not interference['within_rigid_components'])
    App.closeDocument(doc.Name)
    doc = App.openDocument(str(output)); doc.recompute()
    reopened = native.measurements(doc)
    checks = compare(geometry,reopened)
    App.closeDocument(doc.Name)
    write(report,{'geometry':geometry,'interference':interference,'reopened':checks,
                  'passed':passed and all(item['passed'] for item in checks)})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend',choices=['freecad','solidcraft','both'],default='both')
    parser.add_argument('--native-output',help=argparse.SUPPRESS)
    parser.add_argument('--native-report',help=argparse.SUPPRESS)
    tool_paths.add_tool_arguments(parser)
    args = parser.parse_args(argv)
    if args.native_output:
        freecad_build(args.native_output,args.native_report)
        return
    needed = {'freecad_python','solidcraft_cli'} if args.backend=='both' else {args.backend+'_python' if args.backend=='freecad' else 'solidcraft_cli'}
    tool_paths.resolve_tool_arguments(parser,args,required=needed)
    spec = model.load(); p = model.parameters(spec); source = model.expanded(spec,p)
    names = ['model/tapestation.schema.json','model/tapestation.shared.json','scripts/tapestation_model.py','scripts/build_tapestation.py',
             'scripts/build_tube_carrier_freecad.py','scripts/tube_carrier_model.py','scripts/robot_spec.py',
             'scripts/build_neutral_freecad.py','scripts/freecad/solidcraftbot_freecad.py',
             'scripts/build_extraction_kit_station.py','scripts/tool_paths.py']
    pins = {name:model.digest(model.ROOT/name) for name in names}
    revision = 'tapestation-'+model.digest(model.SOURCE)[:12]+'-'+str(time.time_ns())
    cad = model.ROOT/'cad/generated'/revision; out = model.ROOT/'exports/generated'/revision
    cad.mkdir(parents=True); out.mkdir(parents=True)
    files = {}; geometry = {}; checks = {}
    if args.backend in {'solidcraft','both'}:
        command_file = out/'commands.json'; sc = cad/'TS01.sc'; raw = out/'solidcraft.json'
        write(command_file,{'commands':model.solidcraft_commands(spec,p)})
        subprocess.run([args.solidcraft_cli,'run',str(command_file),'--save',str(sc),'--json-out',str(raw),'--quiet'],check=True)
        geometry['solidcraft'] = measurements(json.loads(raw.read_text()),source,backend='solidcraft')
        inspection = out/'interference.commands.json'; result = out/'interference.json'
        write(inspection,{'commands':[{'command':'inspect.interference','params':{'bodies':[b['id'] for b in source['bodies']]}}]})
        subprocess.run([args.solidcraft_cli,'run',str(inspection),'--in',str(sc),'--results','--quiet','--json-out',str(result)],check=True,stdout=subprocess.DEVNULL)
        from build_extraction_kit_station import check_solidcraft_interference
        checks['solidcraft'] = check_solidcraft_interference(json.loads(result.read_text()),len(source['bodies']))
        files.update(solidcraft=sc,solidcraft_measurements=raw,solidcraft_interference=result,commands=command_file)
        render = out/'TS01.png'
        subprocess.run([args.solidcraft_cli,'snapshot','--in',str(sc),'--out',str(render),'--view','iso',
                        '--width','1200','--height','900','--no-grid','--no-axes'],check=True,stdout=subprocess.DEVNULL)
        files['render'] = render
    if args.backend in {'freecad','both'}:
        fc = cad/'TS01.FCStd'; report = out/'freecad.json'
        subprocess.run([args.freecad_python,str(Path(__file__).resolve()),'--native-output',str(fc),'--native-report',str(report)],
                       env=freecad_environment(args.freecad_python),check=True)
        raw = json.loads(report.read_text())
        geometry['freecad'] = measurements(raw,source,backend='freecad'); checks['freecad'] = raw
        files.update(freecad=fc,freecad_validation=report)
    comparisons = compare(geometry['solidcraft'],geometry['freecad']) if args.backend=='both' else []
    passed = all(item['passed'] for item in checks.values()) and all(item['passed'] for item in comparisons)
    verify_pins(pins)
    report = {'format':'solidcraftbot.tapestation-build/1','source_sha256':model.digest(model.SOURCE),'source_files_sha256':pins,'passed':passed,
              'backends':args.backend,'cross_cad_checked':args.backend=='both','body_comparisons':comparisons,
              'checks':checks,'interfaces':model.interfaces(spec,p),'files':{key:relative(value) for key,value in files.items()},
              'artifact_sha256':{key:model.digest(value) for key,value in files.items()},'limitations':spec['limitations']}
    write(out/'build-report.json',report)
    if not passed:
        raise AssertionError('TS01 static geometry validation failed')
    write(model.ROOT/'cad/tapestation/shared-build-report.json',report)
    print(relative(out/'build-report.json'))


if __name__ == '__main__':
    import build_tapestation as adapter
    adapter.main()
