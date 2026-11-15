"""Build an inspectable replay of the checked continuous H02 arm program."""
import argparse
import base64
import gzip
import json
from pathlib import Path
import subprocess
import h02_arm_pickup as model
import build_extraction_kit_station as common
import tool_paths


def compact_numbers(value):
    """Preserve values exactly while avoiding redundant .0 in embedded meshes."""
    if isinstance(value,dict):return {k:compact_numbers(v) for k,v in value.items()}
    if isinstance(value,list):return [compact_numbers(v) for v in value]
    if isinstance(value,float) and value.is_integer():return int(value)
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__);tool_paths.add_tool_arguments(parser,solidcraft=False)
    parser.add_argument('--transfer',action='store_true')
    args=parser.parse_args();tool_paths.resolve_tool_arguments(parser,args)
    if args.transfer:
        from h02_rack_transfer import Program
        program=Program()
    else:program=model.Program()
    kind='h02-rack-transfer' if args.transfer else 'h02-arm-pickup'
    source=program.source_path if args.transfer else model.SOURCE
    report_path=model.ROOT/'cad'/kind/'shared-build-report.json';report=json.loads(report_path.read_text())
    if not report['passed'] or report['backends']!='both':raise ValueError('Checked full-arm geometry in both CADs required')
    common.verify_pins(report['source_files_sha256']);common.verify_pins(report['artifact_sha256'])
    case=next(c for c in report['cases'] if c['variant']=='V20');fc=json.loads((model.ROOT/case['freecad_report']).read_text())
    pose=next(p for p in fc['poses'] if p['state']=='grasp');native=model.ROOT/pose['file']
    stem=kind+'-animation-'+model.robot.digest(source)[:12];revision=stem;n=1
    while (model.ROOT/'exports/generated'/revision).exists():n+=1;revision=stem+'-r'+str(n)
    out=model.ROOT/'exports/generated'/revision;out.mkdir(parents=True)
    context={'transfer':args.transfer,'out':str(out),'native':str(native),'native_sha256':model.robot.digest(native),'validated_build':common.relative(report_path),'validated_build_sha256':model.robot.digest(report_path)}
    common.write(out/'context.json',context)
    subprocess.run([args.freecad_python,str(model.ROOT/'scripts/export_h02_arm_animation_mesh.py'),str(out/'context.json')],check=True,env=common.freecad_environment(args.freecad_python))
    mesh=json.loads((out/'mesh.json').read_text());reference=[]
    times={0.,program.total_duration};start=0.
    for phase,curve in program.curves.items():
        for t in curve.times:
            times.update(max(0.,min(program.total_duration,start+t+offset)) for offset in [-1e-6,0.,1e-6])
        for a,b in zip(curve.times,curve.times[1:]):times.add(start+(a+b)/2)
        start+=program.durations[phase]
    if args.transfer:
        loaded_start=program.durations['approach']+program.durations['closure']
        times.update(i*program.total_duration/256 for i in range(257))
        for boundary in [v[1] for v in program.route.pieces[:-1]]:
            lo=0.;hi=program.durations['extraction']
            for _ in range(48):
                middle=(lo+hi)/2;raw=model.motion.evaluate(program.curves['extraction'],middle)
                from h02_rack_transfer import J
                value=program.progress(J(*(raw[f][0] for f in model.motion.FIELDS))).d[0]
                if value<boundary:lo=middle
                else:hi=middle
            times.update(loaded_start+(lo+hi)/2+offset for offset in [-1e-6,0.,1e-6])
    for t in sorted(times):
        phase,u=program.at_time(t);state=program.state(phase,u)
        scalar=model.motion.evaluate(program.curves[phase],u*program.durations[phase])
        reference.append({'t':t,'state':state,'scalar':[scalar[f][0] for f in model.motion.FIELDS],'arm':program.kin.forward(state['joints_deg'])})
    data={**mesh,'scalar_limits':program.local_scene['motion_limits'],'motion_sha256':model.robot.digest(source),'total_duration':program.total_duration,'durations':program.durations,'z0':program.z0,'travel':program.travel,'jaw_travel':program.p['jaw_travel'],
        'closed_gap':2*program.spec['hp']['tube_radius'],'upper':program.upper,'fore':program.fore,'end':program.end,'radial':program.radial,'shoulder':program.shoulder,
        'base':program.kin.base,'frames':program.frames,'links':program.links,
        'curves':{k:{'times':v.times,'segments':[s[0] for s in v.segments]} for k,v in program.curves.items()}}
    if args.transfer:
        data['transfer']={'pieces':program.route.pieces,'length':program.route.length,'weight':program.metric_strength,'seat':program.seat,'yaw':program.transfer['route']['release_yaw_deg'],'base_y':program.definition['arm_fixture']['position_mm'][1]}
        data['scalar_limits']=program.loaded_caps
    packed=base64.b64encode(gzip.compress(json.dumps(compact_numbers(data),separators=(',',':'),allow_nan=False).encode(),mtime=0)).decode()
    template=model.ROOT/'scripts/templates/h02_arm_animation.html';runtime=model.ROOT/'scripts/h02_arm_animation.js'
    html=template.read_text()
    if args.transfer:html=html.replace('Gripper and H02','Follow gripper').replace('jaw closure and tube extraction','grasp, rack transfer, release and withdrawal').replace('Full-arm approach, grasp, and 60 mm extraction.','Full-arm transfer from H02 to the occupied rack.')
    html=html.replace('__DATA__',packed).replace('__RUNTIME__',runtime.read_text())
    if len(html.encode())>=1_000_000:raise ValueError('Animation exceeds inline size limit')
    (out/'h02-arm-pickup.html').write_text(html);common.write(out/'reference.json',reference)
    files=[Path(__file__),model.ROOT/'scripts/export_h02_arm_animation_mesh.py',template,runtime]
    result={'passed':True,'format':'solidcraftbot.h02-arm-animation/1','revision':revision,'context':context,
        'sources_sha256':{common.relative(p):model.robot.digest(p) for p in files},'checked_motion_sources':report['source_files_sha256'],
        'artifacts_sha256':{common.relative(out/name):model.robot.digest(out/name) for name in ['mesh.json','h02-arm-pickup.html','reference.json','native-replay-checks.json']},
        'duration_s':program.total_duration,'variant':'V20','visual_review':'Pending browser review',
        'limitations':['Display meshes only; vendor detail clustered at '+('2' if args.transfer else '1')+' mm','Exact source curves and analytic IK; no joint interpolation','Required grasp modeled as synthetic closure; no physical feedback','No hardware or new collision qualification; source-bound CAD audit retained']}
    common.write(out/'animation-report.json',result);common.write(model.ROOT/'cad'/kind/'animation-report.json',result)
    print(out,flush=True)


if __name__=='__main__':main()
