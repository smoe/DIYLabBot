"""Compile and check a smooth three-sample CF01 preview using checked geometry.

No construction is copied. A new trajectory gets new native motion evidence;
historical media and historical motion reports remain immutable.
"""
import argparse
import base64
import copy
import gzip
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

import cf01_unload_geometry as geometry
import cf01_unload_motion as compiler
import cf01_unload_validation as dynamics
from build_instrument_concepts import freecad_environment
import tool_paths

ROOT=geometry.ROOT
AUDIT_CODE=('scripts/cf01_unload_geometry.py','scripts/check_cf01_unload_motion.py',
            'scripts/lab_transfer_model.py')
_DYNAMICS_CACHE={}


def write(path,value):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    Path(path).write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')


def verify_program(program):
    if program.get('format')!=compiler.FORMAT:raise ValueError('Compiled unloading program required')
    scene=compiler.pickup.load();definition=compiler.load()
    if program.get('source_files_sha256')!=compiler._hashes(scene):raise ValueError('Compiled program source bindings changed or incomplete')
    if program['source_sha256']!=geometry.sha(compiler.SOURCE):raise ValueError('Motion definition changed')
    definition_sha=hashlib.sha256(json.dumps(definition,sort_keys=True).encode()).hexdigest()
    if (program.get('scene')!=scene or program.get('definition')!=definition
            or program.get('definition_sha256')!=definition_sha):raise ValueError('Compiled scene or definition changed')
    if program['verification'].get('qualified') is not False:raise ValueError('Unqualified synthetic program required')
    # Before/after guards repeat in one process. Reuse only an identical full
    # payload with identical current implementation/source bytes, never a saved
    # summary supplied by the program or an earlier process.
    def cache_key():
        payload=hashlib.sha256(json.dumps(program,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        code={name:geometry.sha(ROOT/name) for name in geometry.GEOMETRY_CODE}
        return (payload,geometry.sha(dynamics.__file__),tuple(sorted(code.items())),
                tuple(sorted(program['source_files_sha256'].items())))
    key=cache_key()
    if key not in _DYNAMICS_CACHE:
        validation=dynamics.validate_program(program,definition=definition)
        if cache_key()!=key:raise ValueError('Dynamics validation inputs changed during checking')
        _DYNAMICS_CACHE[key]=copy.deepcopy(validation)
    return copy.deepcopy(_DYNAMICS_CACHE[key])


def verify_native_context(context,program,native,audit_sources):
    """Check the same immutable inputs before and after native work or rendering."""
    validation=verify_program(program)
    if geometry.sha(context['program'])!=context['program_sha256']:raise ValueError('Checked program artifact changed')
    if native.get('passed') is not True:raise ValueError('Passed native evidence required')
    if native['program']['sha256']!=context['program_sha256']:raise ValueError('Native evidence is for another program')
    for name in AUDIT_CODE:
        if geometry.sha(ROOT/name)!=audit_sources.get(name):raise ValueError('Native audit implementation changed: '+name)
    for model in native['posed_models']:
        if geometry.sha(ROOT/model['path'])!=model['sha256']:raise ValueError('Checked posed model changed')
    bundle=geometry.load_bundle(context['geometry_report']);instruments=geometry.load_instruments()
    if bundle['evidence']!=native['geometry'] or context['geometry']!=native['geometry']:
        raise ValueError('Native geometry evidence changed')
    if instruments['evidence']!=native['instruments']:raise ValueError('Native instrument evidence changed')
    bundle['dynamics_validation']=validation
    return bundle


def preview_samples(program):
    """Bounds/framing samples only: actual playback evaluates PVA polynomials."""
    times={0.,program['duration_s']}
    for channel in ['arm','station','jaw']:
        times.update(point['time_s'] for point in program[channel]['points'])
    times.update(event['time_s'] for event in program['events'])
    count=math.ceil(program['duration_s']/.1)
    times.update(program['duration_s']*i/count for i in range(count+1))
    evaluate=compiler.ProgramEvaluator(program)
    return [{key:sample[key] for key in ['time_s','joints_deg','station','jaw_gap_mm','owners',
                                        'active_sample_id','phase_key','phase','workspace_clear']}
            for time in sorted(times) for sample in [evaluate(time)]]


def render_html(program,bundle,target):
    # State restoration identifies the complete derived program, not just one
    # source file which could be unchanged after a generator improvement.
    program_id=hashlib.sha256(json.dumps(program,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    display={**program,'preview_samples':preview_samples(program)}
    mesh=geometry.mesh_for_program(bundle,display);mesh['trajectory']['scene_sha256']=program_id
    packed=base64.b64encode(gzip.compress(json.dumps(mesh,separators=(',',':'),allow_nan=False).encode(),compresslevel=9,mtime=0)).decode()
    template=(ROOT/'scripts/templates/centrifuge_robot_pickup.html').read_text()
    header=(ROOT/'scripts/templates/robot_demo_header.html').read_text()
    curves=(ROOT/'scripts/templates/quintic_motion.js').read_text()
    target.write_text(header+'<script>\n'+curves+'\n</script>\n'+template.replace('__MESH__',packed)+'\n</html>\n',encoding='utf-8')
    if target.stat().st_size>2_000_000:raise ValueError('Inline preview exceeds the 2 MB budget')
    return {'path':str(target.relative_to(ROOT)),'sha256':geometry.sha(target),'bytes':target.stat().st_size,
            'program_id':program_id,'body_count':len(mesh['bodies']),'framing_samples':len(display['preview_samples']),
            'interpolation':'Actual quintic PVA evaluation; framing samples are not linearly replayed',
            'vendor_display_cluster_mm':1,'native_geometry_simplified':False}


def dynamics_report(program,validation):
    """Publish mixed-unit station axes without the math engine's radian labels."""
    result=copy.deepcopy(validation)
    for channel in ['station','jaw']:
        bounds=result[channel+'_bounds']
        result[channel+'_bounds']={'joint_names':program[channel]['joint_names'],
            'units':program[channel]['units'],
            **{generic:bounds[field] for generic,field in zip(('p','v','a','j'),compiler.FIELDS)}}
    return result


def publish_report(context,program,visual,native,validation):
    out=Path(context['out'])
    report={'format':'solidcraftbot.cf01-unload-build/1','passed':native['passed'],**context,
            'source_files_sha256':{**program['source_files_sha256'],**{str(Path(p).relative_to(ROOT)):geometry.sha(p)
                for p in [Path(__file__),*[ROOT/name for name in AUDIT_CODE],
                          ROOT/'scripts/templates/quintic_motion.js',ROOT/'scripts/templates/centrifuge_robot_pickup.html',
                          ROOT/'scripts/templates/robot_demo_header.html',
                          ROOT/'scripts/cf01_unload_validation.py',
                          ROOT/'scripts/build_centrifuge_robot_pickup_visual.py']}},
            'visualization':visual,'native_report':{'path':str((out/'native-motion-validation.json').relative_to(ROOT)),
                                                   'sha256':geometry.sha(out/'native-motion-validation.json')},
            'curve_limits':program['limits'],'segments':program['segment_audits'],
            'dynamics_validation':dynamics_report(program,validation),
            'validation_scope':'New native discrete motion check and conservative numerical kinematic bounds. Browser, media review and ROS execution are separate.',
            'verification':program['verification'],'limitations':program['definition']['limitations']}
    write(out/'build-report.json',report)
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--program',type=Path,help='Reuse a source-current compiled program instead of compiling twice')
    parser.add_argument('--geometry-report',type=Path,default=geometry.DEFAULT_REPORT)
    parser.add_argument('--prepare-only',action='store_true',help='Prepare program/HTML only; no native check is claimed')
    parser.add_argument('--finish-existing',type=Path,help='Rebuild only the HTML/report for a source-current, immutable native-checked context')
    tool_paths.add_tool_arguments(parser,freecad=True,solidcraft=False)
    args=parser.parse_args(argv);tool_paths.resolve_tool_arguments(parser,args,required=not(args.prepare_only or args.finish_existing))
    if args.finish_existing:
        if args.program or args.prepare_only:parser.error('--finish-existing cannot be combined with --program/--prepare-only')
        context=geometry.read(args.finish_existing);out=Path(context['out'])
        program=geometry.read(context['program']);verify_program(program)
        if geometry.sha(context['program'])!=context['program_sha256']:raise ValueError('Checked program artifact changed')
        previous=geometry.read(out/'build-report.json');native=geometry.read(out/'native-motion-validation.json')
        if previous.get('passed') is not True or native.get('passed') is not True:raise ValueError('Passed native evidence required')
        if geometry.sha(out/'native-motion-validation.json')!=previous['native_report']['sha256']:raise ValueError('Native evidence changed')
        bundle=verify_native_context(context,program,native,previous['source_files_sha256'])
        visual=render_html(program,bundle,Path(context['renders'])/'cf01-unload-demo.html')
        checked=verify_native_context(context,program,native,previous['source_files_sha256'])
        if geometry.sha(out/'native-motion-validation.json')!=previous['native_report']['sha256']:raise ValueError('Native evidence changed during rendering')
        write(out/'visualization.json',visual);publish_report(context,program,visual,native,checked['dynamics_validation'])
        print(json.dumps({'passed':True,'revision':context['revision'],'native_evidence_retained':True,'interactive':visual['path']}))
        return
    program=geometry.read(args.program) if args.program else compiler.compile()
    verify_program(program);bundle=geometry.load_bundle(args.geometry_report)
    stem='cf01-unload-smooth-'+program['source_sha256'][:12];revision=stem;index=1
    while (ROOT/'exports/generated'/revision).exists():
        index+=1;revision=stem+'-r'+str(index)
    out,cad,renders=[ROOT/folder/revision for folder in ['exports/generated','cad/generated','renders']]
    for folder in [out,cad,renders]:folder.mkdir(parents=True)
    program_path=out/'program.json';write(program_path,program)
    context={'revision':revision,'out':str(out),'cad':str(cad),'renders':str(renders),
             'program':str(program_path),'geometry_report':str(args.geometry_report.resolve()),
             'program_sha256':geometry.sha(program_path),'geometry':bundle['evidence']}
    audit_sources={name:geometry.sha(ROOT/name) for name in AUDIT_CODE}
    write(out/'context.json',context);write(ROOT/'tmp/cf01-unload-context.json',context)
    visual=render_html(program,bundle,renders/'cf01-unload-demo.html');write(out/'visualization.json',visual)
    print(json.dumps({'revision':revision,'program':str(program_path),'duration_s':program['duration_s'],
                      'interactive':visual['path'],'prepare_only':args.prepare_only}),flush=True)
    if args.prepare_only:return
    subprocess.run([args.freecad_python,str(ROOT/'scripts/check_cf01_unload_motion.py'),
                    '--context',str(out/'context.json')],check=True,cwd=ROOT,env=freecad_environment(args.freecad_python))
    native=geometry.read(out/'native-motion-validation.json')
    checked=verify_native_context(context,program,native,audit_sources)
    publish_report(context,program,visual,native,checked['dynamics_validation'])
    print(json.dumps({'passed':True,'revision':revision,'report':str((out/'build-report.json').relative_to(ROOT))}),flush=True)


if __name__=='__main__':main()
