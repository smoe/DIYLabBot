"""Build TR01 + awareness kit independently in FreeCAD and SolidCraft."""
from pathlib import Path
import argparse
import json
import subprocess
import time
import tr01_camera_model as model
import tool_paths
from build_instrument_concepts import freecad_environment
from build_tube_carrier import compare


def build(args):
    start=time.monotonic();spec=model.load();source=model.expanded(spec)
    source_paths=[model.SOURCE,model.SCHEMA,model.ROOT/spec['transport']['source'],model.ROOT/'model/camera.schema.json']
    source_paths += [model.ROOT/'scripts'/n for n in ['tr01_camera_model.py','build_tr01_awareness.py','build_tr01_awareness_freecad.py','sample_transport_model.py','robot_spec.py','build_tube_carrier.py','build_tube_carrier_freecad.py','build_instrument_concepts.py','robot_components.py','robot_cameras.py','freecad/solidcraftbot_freecad.py','tool_paths.py','build_neutral_freecad.py','tube_carrier_model.py']]
    pins={str(p.relative_to(model.ROOT)):model.digest(p)for p in source_paths}
    stem='tr01-awareness-'+model.digest(model.SOURCE)[:12];revision=stem;i=1
    while (model.ROOT/'exports/generated'/revision).exists():i+=1;revision=stem+'-r'+str(i)
    out=model.ROOT/'exports/generated'/revision;cad=model.ROOT/'cad/generated'/revision;out.mkdir(parents=True);cad.mkdir(parents=True)
    files={'freecad':cad/'TR01_Awareness.FCStd','solidcraft':cad/'TR01_Awareness.sc','commands':out/'commands.json','solidcraft_measurements':out/'solidcraft.json','freecad_report':out/'freecad.json'}
    files['commands'].write_text(json.dumps({'commands':model.solidcraft_commands(source)},indent=2)+'\n')
    subprocess.run([args.solidcraft_cli,'run',str(files['commands']),'--save',str(files['solidcraft']),'--json-out',str(files['solidcraft_measurements']),'--quiet'],check=True,cwd=model.ROOT)
    subprocess.run([args.freecad_python,str(model.ROOT/'scripts/build_tr01_awareness_freecad.py'),str(files['freecad']),str(files['freecad_report'])],check=True,cwd=model.ROOT,env=freecad_environment(args.freecad_python))
    native=json.loads(files['freecad_report'].read_text());sc=json.loads(files['solidcraft_measurements'].read_text());comparison=compare(sc,native['geometry'])
    for p,h in pins.items():
        if model.digest(model.ROOT/p)!=h:raise ValueError('Source changed during build: '+p)
    passed=native['passed'] and all(c['passed']for c in comparison)
    report={'format':'solidcraftbot.tr01-awareness-cross-cad/1','revision':revision,'passed':passed,'source_files_sha256':pins,'files':{k:str(p.relative_to(model.ROOT))for k,p in files.items()},'artifact_sha256':{k:model.digest(p)for k,p in files.items()},'camera_frame':source['camera_frame'],'body_count':len(source['bodies']),'omitted_load_bodies':source['omitted_load_bodies'],'cross_kernel_comparisons':comparison,'native_kit_checks':native,'elapsed_s':time.monotonic()-start,'qualification':spec['qualification'],'limitations':spec['limitations']+['No robot motion, navigation, dynamics or visibility qualification.','Native camera geometry is a presentation envelope; manufacturing and hardware unselected.']}
    (out/'build-report.json').write_text(json.dumps(report,indent=2)+'\n')
    if not passed:raise AssertionError('Cross-CAD mismatch; see '+str(out/'build-report.json'))
    print('Camera kit passed: '+str(out/'build-report.json'),flush=True)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__);tool_paths.add_tool_arguments(parser);args=parser.parse_args();tool_paths.resolve_tool_arguments(parser,args);build(args)


if __name__=='__main__':main()
