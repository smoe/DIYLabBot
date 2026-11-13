"""Read-only front view of a checked building; source photos stay private."""
import argparse
import json
import math
from pathlib import Path
import subprocess
import building_stack as model
import render_building_stack_highlight as checked
import tool_paths

ROOT=Path(__file__).resolve().parents[1]


def render(args):
    report_path=Path(args.build_report).resolve();report,native,bindings=checked.checked_build(report_path)
    bindings[str(Path(__file__).relative_to(ROOT))]=checked.digest(__file__)
    spec=model.load(ROOT/report['source']);d=model.interfaces(spec,model.parameters(spec));ext=d['exterior']
    geometry=json.loads((ROOT/report['files']['freecad_validation']).read_text())['geometry']
    hidden=set(ext['terrain_body_ids'])|{v['body'] for v in geometry if v['bbox']['max'][2]<=ext['grade_z_mm']}
    hidden.update(v['body'] for v in geometry if v['body'].startswith('KG__') or '_KG_EG' in v['body'])
    hidden.update(v['body'] for v in geometry if v['body'] in d['circulation']['elevator']['shaft_body_ids'] and v['bbox']['min'][2] < ext['grade_z_mm'])
    focus=[v for v in geometry if v['body']==ext['frame_body_id']]
    cam=checked.camera(focus,1800,1400,-math.pi/2,.15)
    commands=[{'command':'browser.visibility','params':{'items':sorted(hidden),'visible':False}}]
    out=Path(args.output_dir).resolve()
    if not out.is_relative_to(ROOT) or out.exists():raise ValueError('New output directory inside the project required')
    out.mkdir(parents=True);script=out/'front.commands.json';script.write_text(json.dumps({'commands':commands},indent=2)+'\n');image=out/'front.png'
    cmd=[args.solidcraft_cli,'snapshot',str(script),'--in',str(native),'--out',str(image),'--width','1800','--height','1400','--camera',json.dumps(cam),'--no-grid','--no-axes','--quality','fine']
    checked.verify(bindings);subprocess.run(cmd,cwd=ROOT,check=True,stdout=subprocess.DEVNULL);checked.verify(bindings)
    result={'format':'solidcraftbot.building-exterior-view/1','native_model':str(native.relative_to(ROOT)),'native_model_sha256':checked.digest(native),'source_files_sha256':bindings,'image':str(image.relative_to(ROOT)),'image_sha256':checked.digest(image),'pixels':[1800,1400],'view_script':str(script.relative_to(ROOT)),'view_script_sha256':checked.digest(script),'view_commands':commands,'camera':cam,'command_line':cmd,'native_model_unchanged':True,'original_photograph_included':False,'metric_scale_known':False,'visually_reviewed':False}
    path=out/'front-report.json';path.write_text(json.dumps(result,indent=2)+'\n');print(str(path.relative_to(ROOT)))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--build-report',default=str(ROOT/'cad/building-stack/shared-build-report.json'));parser.add_argument('--output-dir',required=True);parser.add_argument('--solidcraft-cli');args=parser.parse_args();tool_paths.resolve_tool_arguments(parser,args,required=('solidcraft_cli',));render(args)

if __name__=='__main__':main()
