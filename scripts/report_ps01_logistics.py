"""Collect current native model, continuous-path and animation evidence."""
import argparse
import math
from pathlib import Path

import build_ps01_logistics as build

s=build.s


def coverage(report,program):
    s.require(report['passed'],'Native continuous audit did not pass')
    phases={row['phase'] for row in report['continuous_intervals']}
    s.require(phases==set(program.curves),'Native audit does not cover every phase')
    for phase in phases:
        last=0.
        for item in sorted((r for r in report['continuous_intervals'] if r['phase']==phase),key=lambda r:r['interval'][0]):
            a,b=item['interval']
            s.require(abs(a-last)<1e-12 and b>a and item['minimum_margin_beyond_required_mm']>=0,
                      'Gap, overlap or negative margin in continuous evidence')
            last=b
        s.require(last==1.,'Continuous evidence does not reach the endpoint')


def compare_models(freecad,solidcraft):
    s.require(freecad['passed'] and solidcraft['passed'],'A native construction report failed')
    s.require(freecad['solidcraft_construction_dependency'] is False and
              solidcraft['freecad_construction_dependency'] is False,'Independent native construction required')
    first={r['id']:r for r in freecad['records']};second={r['id']:r for r in solidcraft['records']}
    s.require(first.keys()==second.keys(),'Native semantic body sets differ')
    details=[]
    for key,a in first.items():
        b=second[key]
        # T01 is static and lowered in world coordinates by the SolidCraft
        # adapter. All other native bodies use their construction frames.
        left=freecad['bodies'][key] if a['instance'].endswith('PS01Waste') else a['local_metrics']
        right=b['local_metrics']
        volume=abs(left['volume_mm3']-right['volume_mm3'])/max(left['volume_mm3'],right['volume_mm3'])
        center=math.dist(left['center_of_mass_mm'],right['center_of_mass_mm'])
        bounds=max(abs(x-y) for edge in ('min','max') for x,y in zip(left['bbox'][edge],right['bbox'][edge]))
        details.append({'id':key,'relative_volume_error':volume,'center_error_mm':center,'bbox_error_mm':bounds,
                        'passed':volume<=.001 and center<=.02 and bounds<=.02})
    return {'passed':all(r['passed'] for r in details),'body_count':len(details),'bodies':details,
            'limits':{'relative_volume':.001,'center_mm':.02,'bbox_mm':.02}}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freecad',type=Path,required=True)
    parser.add_argument('--solidcraft',type=Path,required=True)
    parser.add_argument('--freecad-audit',type=Path,help='Earlier audit, only with exact BRep equivalence evidence')
    parser.add_argument('--animation',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();fc=args.freecad.resolve();sc=args.solidcraft.resolve()
    build.base.verify_pins(s.read(fc/'context.json')['source_files_sha256'])
    build.base.verify_pins(s.read(sc/'context.json')['source_files_sha256'])
    data=s.read(fc/'program.json');program=build.Program(data,build.geometry.Scene())
    s.require(data==s.read(sc/'program.json'),'Native models use different motion exports')
    digest=s.robot.digest(fc/'program.json')
    audit_dir=args.freecad_audit.resolve() if args.freecad_audit else fc
    files=[fc/'context.json',sc/'context.json',fc/'freecad-local-report.json',sc/'solidcraft-local-report.json',
           audit_dir/'freecad-continuous.json',sc/'solidcraft-continuous.json',args.animation/'animation-report.json']
    if audit_dir!=fc:
        equivalence=s.read(fc/'brep-equivalence.json')
        s.require(equivalence['passed'] and equivalence['previous_directory']==str(audit_dir) and
            equivalence['previous_artifact_sha256']==s.robot.digest(audit_dir/'Logistics-local.FCStd') and
            equivalence['current_artifact_sha256']==s.robot.digest(fc/'Logistics-local.FCStd'),'Invalid BRep equivalence')
        s.require(s.read(audit_dir/'freecad-local-report.json')['records']==s.read(fc/'freecad-local-report.json')['records'],
                  'Native body identities, frames or bounds changed')
        files.append(fc/'brep-equivalence.json')
    audits={}
    for backend,path in (('freecad',audit_dir),('solidcraft',sc)):
        report=s.read(path/(backend+'-continuous.json'));coverage(report,program)
        s.require(data==s.read(path/'program.json'),'Audit program differs')
        audit_digest=s.robot.digest(path/'program.json')
        if 'program_sha256' in report:s.require(report['program_sha256']==audit_digest,'Audit program checksum differs')
        audit_pins=dict(report['source_files_sha256'])
        if backend=='freecad' and audit_dir!=fc:
            # The old construction driver remains a historical source pin.
            # Exact native BReps and complete body/frame records were compared
            # above; collision mathematics and all other dependencies must
            # still match. The SolidCraft-only driver correction is not an
            # excuse to accept changed arm geometry or collision predicates.
            audit_pins.pop('scripts/build_ps01_logistics.py',None)
        build.base.verify_pins(audit_pins)
        if backend=='freecad' and 'program_sha256' not in report:
            # The first native run captured these during execution. Preserve
            # that provenance separately rather than rewriting its report.
            captured=s.read(path/'audit-execution-inputs.json')
            captured_pins=dict(captured['source_files_sha256'])
            if 'audit_source_snapshot' in captured:
                snapshot=Path(captured['audit_source_snapshot'])
                old_digest=captured_pins.pop('scripts/audit_ps01_logistics_freecad.py')
                s.require(s.robot.digest(snapshot)==old_digest,'Historical audit source changed')
                files.append(snapshot)
            build.base.verify_pins(captured_pins)
            s.require(captured['program_sha256']==audit_digest and
                      captured['artifact_sha256']==s.robot.digest(path/'Logistics-local.FCStd'),'FreeCAD execution inputs changed')
            files.append(path/'audit-execution-inputs.json')
        else:
            artifact='Logistics-local.FCStd' if backend=='freecad' else 'Logistics-local.solidcraft'
            s.require(report['artifact_sha256']==s.robot.digest(path/artifact),'Audited native artifact changed')
        audits[backend]={'native_pose_count':report['native_pose_count'],'continuous_intervals':len(report['continuous_intervals']),
                         'maximum_depth':report['maximum_depth'],'passed':True}
    comparison=compare_models(s.read(fc/'freecad-local-report.json'),s.read(sc/'solidcraft-local-report.json'))
    animation=s.read(args.animation/'animation-report.json')
    s.require(s.read(args.animation/'program.json')==data and
              animation['program_sha256']==s.robot.digest(args.animation/'program.json') and
              animation['html_sha256']==s.robot.digest(args.animation/'animation.html'),
              'Animation is stale')
    report={'format':'solidcraftbot.ps01-logistics-evidence/1','passed':comparison['passed'],
        'program_sha256':digest,'motion_duration_s':data['motion_duration_s'],'playback_factor':data['playback_factor'],
        'native_audits':audits,'model_comparison':comparison,
        'files_sha256':{str(p.resolve()):s.robot.digest(p) for p in files},
        'native_artifacts_sha256':{str((p/name).resolve()):s.robot.digest(p/name)
            for p,names in ((fc,('Logistics.FCStd','Logistics-local.FCStd')),(sc,('Logistics-local.solidcraft',))) for name in names},
        'scope':'Rack01 with two closed vessels: PS01.Outfeed to TR01 to RF02.InfeedRack, including empty approach/withdrawal',
        'source_files_sha256':{**build.pins(),str(Path(__file__).resolve().relative_to(s.ROOT)):s.robot.digest(Path(__file__))},
        'limitations':['Tip-box and plate transfer paths and local deck exchanges are not covered by this rack-motion evidence.',
            'Tip-box contours are unmeasured planning envelopes; the manual cover movement and observation duration are excluded.',
            'No hardware execution, biological/mechanical qualification or measured human-speed comparison.'],
        'hardware_executed':False,'human_speed_acceptance_proven':False}
    build.write(args.output,report)
    print({'passed':report['passed'],'body_count':comparison['body_count'],'report':str(args.output)},flush=True)


if __name__=='__main__':main()
