"""Build an interactive H03 animation from a pinned cycle and checked native CAD."""
import argparse
import tool_paths
import json
from pathlib import Path
import subprocess
import tube_cam_model as model
import tube_cam_cycle as cycle


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-only',action='store_true')
    tool_paths.add_tool_arguments(parser, freecad=True, solidcraft=False)
    args=parser.parse_args(); tool_paths.resolve_tool_arguments(parser, args);spec=model.load();p=model.parameters(spec);data=cycle.load()
    report_path=model.ROOT/'cad/tube-cam-h03/shared-build-report.json';build=json.loads(report_path.read_text())
    if not build['passed'] or build['source_sha256']!=model.digest(model.SOURCE):raise ValueError('Current checked H03 geometry required')
    case=build['cases'][0]
    for key in ['freecad','solidcraft']:
        if model.digest(model.ROOT/case['files'][key])!=case['artifact_sha256'][key]:raise ValueError('Native geometry artifact changed')
    stem='tube-cam-h03-cycle-'+model.digest(cycle.SOURCE)[:12];revision=stem;n=1
    while (model.ROOT/'exports/generated'/revision).exists():n+=1;revision=stem+'-r'+str(n)
    out=model.ROOT/'exports/generated'/revision;out.mkdir(parents=True)
    context={'out':str(out),'freecad':str(model.ROOT/case['files']['freecad']),'solidcraft':str(model.ROOT/case['files']['solidcraft']),
             'geometry_sha256':build['source_sha256'],'protocol_sha256':model.digest(cycle.SOURCE),'geometry_report_sha256':model.digest(report_path)}
    context_path=out/'context.json';context_path.write_text(json.dumps(context,indent=2)+'\n',encoding='utf-8')
    samples=cycle.samples(spec,p,data)
    (out/'timeline.json').write_text(json.dumps({'protocol':data,'samples':samples},separators=(',',':')),encoding='utf-8')
    if args.prepare_only:print(context_path);return
    subprocess.run([args.freecad_python,str(model.ROOT/'scripts/export_tube_cam_animation_mesh.py'),str(context_path)],check=True,cwd=model.ROOT)
    mesh=json.loads((out/'animation-mesh.json').read_text());variant=data['variant']
    columns=[k for k in samples[0]['values'] if k.endswith(variant)]
    packed={'duration':data['keyframes'][-1]['time_s'],'columns':columns,
            'frames':[[s['time_s']]+[round(s['values'][k],9) for k in columns] for s in samples],
            'phases':[{k:s[k] for k in ['time_s','phase','label','detail']} for s in data['keyframes']],
            'presentation':data['presentation']}
    template=model.ROOT/'scripts/templates/tube_cam_animation.html'
    html=template.read_text(encoding='utf-8').replace('__MESH__',json.dumps(mesh,separators=(',',':'))).replace('__TIMELINE__',json.dumps(packed,separators=(',',':')))
    fragment=out/'transfer-reset.html';fragment.write_text(html,encoding='utf-8')
    if fragment.stat().st_size>=1000000:raise ValueError('Inline animation exceeds 1 MB')
    native=json.loads((out/'native-cycle-checks.json').read_text());initial=samples[0]['values'];final=samples[-1]['values']
    closed=max(abs(initial[k]-final[k]) for k in initial)<1e-10
    sources=[cycle.SOURCE,model.SOURCE,Path(model.__file__),Path(cycle.__file__),Path(__file__),model.ROOT/'scripts/export_tube_cam_animation_mesh.py',template,model.ROOT/'scripts/verify_tube_cam_freecad.py']
    result={'format':'solidcraftbot.tube-cam-animation/1','passed':native['passed'] and closed,'geometry_sha256':model.digest(model.SOURCE),
            'protocol_sha256':model.digest(cycle.SOURCE),'geometry_report_sha256':context['geometry_report_sha256'],
            'source_files_sha256':{str(f.relative_to(model.ROOT)).replace('\\','/'):model.digest(f) for f in sources},
            'artifact_sha256':{name:model.digest(out/name) for name in ['transfer-reset.html','timeline.json','animation-mesh.json','native-cycle-checks.json']},
            'native_models':{key:{'path':case['files'][key],'sha256':case['artifact_sha256'][key]} for key in ['freecad','solidcraft']},
            'cycle_samples':len(samples),'final_equals_initial':closed,'bodies':len(mesh['bodies']),'variant':variant,
            'files':{'fragment':str(fragment.relative_to(model.ROOT)).replace('\\','/'),'directory':str(out.relative_to(model.ROOT)).replace('\\','/')},
            'visual_review':'Pending browser inspection','limitations':data['limitations']+[data['timing_status'],'Native CAD geometry is unchanged; the new output is a mesh animation and a source-derived replay timeline']}
    for path in [out/'animation-report.json',model.ROOT/'cad/tube-cam-h03/animation-report.json']:
        path.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'passed':result['passed'],'fragment':str(fragment),'bytes':fragment.stat().st_size,'samples':len(samples)},indent=2),flush=True)


if __name__=='__main__':main()
