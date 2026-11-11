"""Build native analytical balance/cold-storage models and checked access poses."""
import argparse
import json
import math
from pathlib import Path
import subprocess
import sys
import time

from build_instrument_concepts import freecad_environment
from build_tube_carrier import compare
import lab_equipment as model
import tool_paths
import tube_carrier_model as portable


def write(path,value):
    Path(path).write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')


def relative(path):
    return str(Path(path).relative_to(model.ROOT)).replace('\\','/')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile',action='append',help='Build selected equipment profile(s)')
    parser.add_argument('--backend',choices=['both','freecad','solidcraft'],default='both')
    tool_paths.add_tool_arguments(parser,freecad=True,solidcraft=True)
    args=parser.parse_args()
    needed={'freecad_python','solidcraft_cli'} if args.backend=='both' else {'freecad_python' if args.backend=='freecad' else 'solidcraft_cli'}
    tool_paths.resolve_tool_arguments(parser,args,required=needed)
    catalog=model.load()
    selected=set(args.profile or catalog['profiles'])
    if selected-set(catalog['profiles']):
        parser.error('Unknown equipment profile')
    started=time.monotonic()
    stem='lab-equipment-'+model.digest(model.SOURCE)[:12]
    revision,index=stem,1
    while (model.ROOT/'cad/generated'/revision).exists():
        index+=1;revision=stem+'-r'+str(index)
    cad,out,renders=(model.ROOT/folder/revision for folder in ('cad/generated','exports/generated','renders'))
    for directory in (cad,out,renders):
        directory.mkdir(parents=True)
    cases=[{'kind':'device','id':name+'_default','profile':name,'overrides':{}}
           for name in catalog['profiles'] if name in selected]
    if 'freezer_minus20' in selected:
        cases.append({'kind':'device','id':'freezer_minus20_wide','profile':'freezer_minus20',
                      'overrides':{'width':640,'inner_width':490}})
    if 'analytical_balance' in selected:
        cases.append({'kind':'device','id':'analytical_balance_raised','profile':'analytical_balance',
                      'overrides':{'base_height':90}})
    full=selected==set(catalog['profiles'])
    if full:
        cases.append({'kind':'overview','id':'storage_overview'})
    sys.path.insert(0,str(model.ROOT/'scripts/freecad'))
    from persist_station_view import persist
    results=[]
    for case in cases:
        if case['kind']=='overview':
            spec,source,placements=model.overview(catalog)
            p={}
            class Provider:
                SOURCE=model.SOURCE
                expanded=staticmethod(lambda spec,p:source)
                pose=staticmethod(lambda spec,p:{})
                samples=staticmethod(lambda spec,p:[])
            commands=portable.solidcraft_commands(spec,p,Provider)
        else:
            spec=model.materialize(catalog,case['profile'],case['overrides'])
            p=model.parameters(spec)
            source=model.expanded(spec,p)
            placements=None
            commands=model.solidcraft_commands(spec,p)
        identity=case['id']
        print('Equipment: '+identity,flush=True)
        case_path,command_path=out/(identity+'.case.json'),out/(identity+'.commands.json')
        write(case_path,case);write(command_path,{'source_sha256':model.digest(model.SOURCE),'commands':commands})
        files={'case':case_path,'commands':command_path}
        sc,fc,step=cad/(identity+'.sc'),cad/(identity+'.FCStd'),out/(identity+'.step')
        scm,fcm,presentation=None,None,None
        if args.backend in {'both','solidcraft'}:
            measurement=out/(identity+'.solidcraft.json')
            subprocess.run([args.solidcraft_cli,'run',str(command_path),'--save',str(sc),'--out',str(step),
                            '--json-out',str(measurement),'--quiet'],check=True,cwd=model.ROOT,stdout=subprocess.DEVNULL)
            scm=json.loads(measurement.read_text())
            files.update(solidcraft=sc,step=step,solidcraft_measurements=measurement)
        if args.backend in {'both','freecad'}:
            validation=out/(identity+'.freecad.json')
            command=[args.freecad_python,str(model.ROOT/'scripts/build_lab_equipment_freecad.py'),
                     str(case_path),str(fc),str(validation)]
            if scm is not None:
                command+=['--compare-step',str(step)]
            subprocess.run(command,check=True,cwd=model.ROOT,env=freecad_environment(args.freecad_python))
            fcm=json.loads(validation.read_text())
            presentation=persist(fc,source,fcm['geometry'])
            files.update(freecad=fc,freecad_validation=validation)
        cross=compare(scm,fcm['geometry']) if scm is not None and fcm is not None else None
        closed_cross=None
        if case['kind']=='device' and scm is not None and fcm is not None:
            closed_command,closed_measure=out/(identity+'.closed.commands.json'),out/(identity+'.closed.solidcraft.json')
            write(closed_command,{'commands':[{'command':'joint.drive','params':{'joint':name,'value':value,'quiet':True}}
                                             for name,value in model.pose(spec,p,'closed').items()]+[{'command':'joint.solve','params':{}}]})
            subprocess.run([args.solidcraft_cli,'eval',str(closed_command),'--in',str(sc),'--json-out',str(closed_measure)],
                           check=True,cwd=model.ROOT,stdout=subprocess.DEVNULL)
            closed_cross=compare(json.loads(closed_measure.read_text()),fcm['closed_geometry'])
            files['closed_solidcraft_measurements']=closed_measure
        passed=(fcm is None or fcm['passed']) and (scm is None or all(b['closed'] and b['volume_mm3']>0 for b in scm['bodies']))
        passed=passed and (cross is None or all(c['passed'] for c in cross)) and (closed_cross is None or all(c['passed'] for c in closed_cross))
        result={'id':identity,'profile':case.get('profile'),'overrides':case.get('overrides'),'passed':passed,
                'body_comparisons':cross,'closed_pose_comparisons':closed_cross,
                'interfaces':None if case['kind']=='overview' else model.interfaces(spec,p),
                'handling':None if case['kind']=='overview' else spec['profile']['handling'],
                'motion_samples':None if fcm is None else len(fcm['motion_samples']),
                'access_checks':None if fcm is None else fcm['access_checks'],
                'freecad_presentation':presentation,'placements':placements,
                'files':{key:relative(path) for key,path in files.items()},
                'artifact_sha256':{key:model.digest(path) for key,path in files.items() if key in {'solidcraft','freecad','step'}}}
        results.append(result);write(out/'cases-progress.json',results)
        if not passed:
            raise AssertionError('Equipment comparison failed: '+identity)
    views={}
    if args.backend in {'both','solidcraft'}:
        empty=out/'view.commands.json';write(empty,{'commands':[]})
        targets=(['storage_overview','analytical_balance_default'] if full else [results[0]['id']])
        for target in targets:
            image=renders/(target+'.png')
            entry=next(c for c in results if c['id']==target)
            bodies=json.loads((model.ROOT/entry['files']['solidcraft_measurements']).read_text())['bodies']
            lo=[min(b['bbox']['min'][i] for b in bodies) for i in range(3)]
            hi=[max(b['bbox']['max'][i] for b in bodies) for i in range(3)]
            width,depth,height=[b-a for a,b in zip(lo,hi)]
            pixels=[1800,1100] if target=='storage_overview' else [1200,1000]
            pitch,fov=.13 if target=='storage_overview' else .45,.6
            distance=max(width/(pixels[0]/pixels[1]),height*math.cos(pitch)+depth*math.sin(pitch))
            camera={'target':[(a+b)/2 for a,b in zip(lo,hi)],'yaw':0 if target=='storage_overview' else -.5,
                    'pitch':pitch,'distance':distance*1.15/(2*math.tan(fov/2))+depth/2,'fov':fov}
            subprocess.run([args.solidcraft_cli,'snapshot',str(empty),'--in',str(model.ROOT/entry['files']['solidcraft']),
                            '--out',str(image),'--width',str(pixels[0]),'--height',str(pixels[1]),'--camera',json.dumps(camera),
                            '--no-grid','--no-axes','--quality','fine'],check=True,cwd=model.ROOT,stdout=subprocess.DEVNULL)
            views[target]={'path':relative(image),'sha256':model.digest(image),'camera':camera,'source':'native SolidCraft model'}
    dependencies=[model.SOURCE,model.ROOT/'model/lab-equipment.schema.json',Path(__file__),Path(model.__file__),
        model.ROOT/'scripts/build_lab_equipment_freecad.py',model.ROOT/'scripts/build_instrument_concepts.py',
        model.ROOT/'scripts/tube_carrier_model.py',model.ROOT/'scripts/build_tube_carrier.py',
        model.ROOT/'scripts/build_tube_carrier_freecad.py',model.ROOT/'scripts/tube_cam_model.py',
        model.ROOT/'scripts/robot_spec.py',model.ROOT/'scripts/assembly_model.py',model.ROOT/'scripts/tool_paths.py',
        model.ROOT/'scripts/build_neutral_freecad.py',model.ROOT/'scripts/freecad/solidcraftbot_freecad.py',
        model.ROOT/'scripts/freecad/persist_station_view.py',model.ROOT/'scripts/freecad/persist_view.py']
    dependencies += [model.ROOT/'scripts/furniture_model.py',model.ROOT/'model/furniture/laboratory.catalog.json']
    report={'format':'solidcraftbot.lab-equipment-build/1','source':relative(model.SOURCE),
            'source_sha256':model.digest(model.SOURCE),'source_files_sha256':{relative(p):model.digest(p) for p in dependencies},
            'passed':all(c['passed'] for c in results),'complete_catalog':full,'backends':args.backend,
            'cross_cad_checked':args.backend=='both','cases':results,'renders':views,'elapsed_s':time.monotonic()-started,
            'limitations':catalog['limitations']+['Native dimension edits require regeneration of saved access metadata.',
                'FreeCAD saved presentation metadata checked; GUI rendering not verified.',
                'The combined storage view is a derived contact sheet, not the measured cellar or an L01 placement.']}
    write(out/'build-report.json',report)
    latest=model.ROOT/'cad/lab-equipment';latest.mkdir(exist_ok=True)
    write(latest/'shared-build-report.json',report)
    print('Equipment passed: '+relative(out/'build-report.json'),flush=True)


if __name__=='__main__':
    main()
