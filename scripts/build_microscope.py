"""Build MI01 independently in either CAD, compare both, and render its detail view."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

import microscope_model as model
import tool_paths
from build_instrument_concepts import freecad_environment
from build_tube_carrier import compare


def write(path, value):
    Path(path).write_text(json.dumps(value,indent=2)+'\n')


def freecad_build(output, report, step=None):
    import FreeCAD as App
    import Part
    import build_tube_carrier_freecad as native
    native.model=model
    spec=model.load();p=model.parameters(spec);source=model.expanded(spec,p)
    doc=native.build(spec,p,Path(output));geometry=native.measurements(doc)
    shapes={obj.SourceBody:native.motion.world_shape(obj) for obj in native.objects(doc)}
    checks=[]
    for name in ['StageLower','StageUpper','SlideCarrier']:
        witness=Part.makeCylinder(10,50,App.Vector(0,-45,p['stage_z']-35))
        overlap=shapes[name].common(witness).Volume
        checks.append({'id':name+'_OpticalOpening','passed':overlap<1e-6,'intersection_mm3':overlap})
    for obj in spec['objectives']:
        tip=shapes['Objective_'+obj['id']+'_Lens'].BoundBox.ZMin
        gap=tip-(p['stage_z']+3)
        checks.append({'id':obj['id']+'_StageGap','passed':gap>=1-1e-6,'gap_mm':gap})
    feet=[shapes['Foot'+str(i)].BoundBox.ZMin for i in range(1,5)]
    checks.append({'id':'FourSupportedFeet','passed':all(abs(v)<1e-7 for v in feet),'z_mm':feet})
    exact=native.step_check(doc,Path(step)) if step else []
    doc.save();App.closeDocument(doc.Name);doc=App.openDocument(str(Path(output)));doc.recompute()
    reopened=native.measurements(doc);App.closeDocument(doc.Name)
    sys.path.insert(0,str(model.ROOT/'scripts/freecad'))
    from persist_station_view import persist
    view=persist(output,source,geometry)
    passed=(len(geometry)==len(source['bodies'])==len(reopened)
            and all(b['valid'] and b['solid_count']==1 for b in geometry+reopened)
            and all(c['passed'] for c in checks+exact) and view['passed'])
    write(report,{'passed':passed,'geometry':geometry,'geometric_checks':checks,
                  'step_comparison':exact,'presentation':view,'freecad_version':App.Version(),
                  'scope':'Static solids, optical openings, objective/stage gaps and support feet; not optical qualification'})
    if not passed:raise AssertionError('Microscope native geometry check failed')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend',choices=['both','solidcraft','freecad'],default='both')
    parser.add_argument('--no-render',action='store_true')
    tool_paths.add_tool_arguments(parser)
    args=parser.parse_args();required={'solidcraft_cli','freecad_python'} if args.backend=='both' else {args.backend+'_python' if args.backend=='freecad' else 'solidcraft_cli'}
    tool_paths.resolve_tool_arguments(parser,args,required=required)
    spec=model.load();p=model.parameters(spec);source=model.expanded(spec,p)
    dependencies=[model.SOURCE,Path(__file__),model.ROOT/'scripts/microscope_model.py',
        model.ROOT/'model/microscope-mi01.schema.json',model.ROOT/'scripts/tube_carrier_model.py',
        model.ROOT/'scripts/robot_spec.py',model.ROOT/'scripts/build_tube_carrier_freecad.py',
        model.ROOT/'scripts/freecad/persist_station_view.py']
    pins={str(path.relative_to(model.ROOT)):model.digest(path) for path in dependencies}
    stem='microscope-mi01-'+model.digest(model.SOURCE)[:12];revision=stem;number=1
    while (model.ROOT/'cad/generated'/revision).exists():number+=1;revision=stem+'-r'+str(number)
    cad=model.ROOT/'cad/generated'/revision;out=model.ROOT/'exports/generated'/revision;render=model.ROOT/'renders'/revision
    for folder in (cad,out,render):folder.mkdir(parents=True)
    files={};sc=fc=None
    if args.backend in ('both','solidcraft'):
        files.update(commands=out/'commands.json',solidcraft=cad/'MicroscopeMI01.sc',solidcraft_geometry=out/'solidcraft.json',step=out/'microscope.step')
        write(files['commands'],{'commands':model.solidcraft_commands(spec,p)})
        subprocess.run([args.solidcraft_cli,'run',str(files['commands']),'--save',str(files['solidcraft']),
            '--out',str(files['step']),'--json-out',str(files['solidcraft_geometry']),'--quiet'],check=True)
        sc=json.loads(files['solidcraft_geometry'].read_text())
        if len(sc['bodies'])!=len(source['bodies']) or not all(b['closed'] and b['volume_mm3']>0 for b in sc['bodies']):
            raise AssertionError('SolidCraft microscope body coverage failed')
    if args.backend in ('both','freecad'):
        files.update(freecad=cad/'MicroscopeMI01.FCStd',freecad_geometry=out/'freecad.json')
        cmd=[args.freecad_python,str(Path(__file__)),'--native-freecad',str(files['freecad']),str(files['freecad_geometry'])]
        if sc is not None:cmd.append(str(files['step']))
        subprocess.run(cmd,check=True,env=freecad_environment(args.freecad_python))
        fc=json.loads(files['freecad_geometry'].read_text())
    cross=compare(sc,fc['geometry']) if sc is not None and fc is not None else []
    if not all(c['passed'] for c in cross):raise AssertionError('Independent microscope CADs differ')
    if sc is not None and not args.no_render:
        files['view_commands']=out/'view.json';write(files['view_commands'],{'commands':[]})
        files['preview']=render/'microscope.png'
        camera={'target':[0,0,290],'distance':1250,'yaw':-2.2,'pitch':.3,'fov':.65}
        subprocess.run([args.solidcraft_cli,'snapshot',str(files['view_commands']),'--in',str(files['solidcraft']),
            '--out',str(files['preview']),'--width','1500','--height','1500','--camera',json.dumps(camera),
            '--no-grid','--no-axes','--quality','fine'],check=True)
    if any(model.digest(model.ROOT/name)!=sha for name,sha in pins.items()):raise ValueError('Microscope sources changed during build')
    report={'passed':True,'revision':revision,'source_files_sha256':pins,'backends':args.backend,
        'body_count':len(source['bodies']),'body_comparisons':cross,
        'files':{key:str(path.relative_to(model.ROOT)) for key,path in files.items()},
        'artifact_sha256':{key:model.digest(path) for key,path in files.items()},'limitations':spec['limitations']}
    write(out/'build-report.json',report)
    print('Microscope passed: '+str(out/'build-report.json'),flush=True)


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--native-freecad':freecad_build(*sys.argv[2:])
    else:main()
