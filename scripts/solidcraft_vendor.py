"""SolidCraft-only preparation of vendor cases affected by its STEP importer.

Read the archived manufacturer STEP, retain the shared exterior partition and
keep its closed case pieces as a rigid assembly. No hole patches, mesh fallback,
FreeCAD runtime or modification of the registered library is involved.
"""
import copy
import json
import math
from pathlib import Path
import subprocess
import robot_components as components
import robot_spec as robot

ROOT=robot.ROOT
AFFECTED={"RMD-X2-P28-7-E","RMD-X4-P36-36-E-L","RMD-X6-P20-60-E"}


def run(cli,commands,script,measurement,**options):
    script=Path(script);script.parent.mkdir(parents=True,exist_ok=True)
    script.write_text(json.dumps({'commands':commands},indent=2)+'\n',encoding='utf-8')
    args=[str(cli),'run',str(script),'--json-out',str(measurement),'--quiet']
    for key,value in options.items():args.extend(['--'+key,str(value)])
    with script.with_suffix('.log').open('w') as log:
        subprocess.run(args,check=True,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    return json.loads(Path(measurement).read_text(encoding='utf-8'))


def prepare(spec,cli,directory):
    """Return registered-STEP replacements and an auditable native round trip."""
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=True)
    library=components.library(spec)
    manifest_path=ROOT/'cad/vendor/myactuator/manifest.json'
    check_path=ROOT/'cad/vendor/myactuator/geometry-check.json'
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    checks=json.loads(check_path.read_text(encoding='utf-8'))
    used={op['part'] for link in spec['links'] for op in link['recipe'] if op['action']=='vendor_component' and op['section']=='housing'}
    replacements={};reports=[]
    for name in sorted(used&AFFECTED):
        part=library['parts'][name];folder=directory/name;folder.mkdir()
        source=next(f for m in manifest['models'] if m['part']==name for f in m['files'] if f['kind']=='step')
        evidence=next(c for c in checks['models'] if c['part']==name)
        if (source['path']!=evidence['source'] or source['sha256']!=evidence['source_sha256']
            or part['source']!=evidence['cad_reference'] or part['source_sha256']!=evidence['cad_reference_sha256']
            or robot.digest(ROOT/source['path'])!=source['sha256']):raise ValueError('Vendor provenance mismatch: '+name)
        insert={'command':'file.insert_step','params':{'path':str(ROOT/source['path']),
                'name':'OriginalVendor','matrix':part['vendor_to_output_frame']}}
        measured=run(cli,[insert],folder/'import.commands.json',folder/'import.json')
        partition=components.exterior_sections(part,measured['bodies']);selected=partition['housing']
        selected_bodies=[next(b for b in measured['bodies'] if b['name']==n) for n in selected]
        body_names=['VendorHousingPart%02d'%(i+1) for i in range(len(selected))]
        target=folder/'housing.step'
        # A repeated manufacturer part shares one definition (X6 sleeves).
        # Export each selected world body separately before assigning identities;
        # renaming the original would rename all its occurrences. A native
        # single-body STEP also avoids copy_bodies' placement error on this file.
        pieces=[folder/(body_name+'.step') for body_name in body_names]
        run(cli,[insert]+[{'command':'file.export_step','params':{'path':str(path),'bodies':[body]}}
                         for path,body in zip(pieces,selected)],folder/'select.commands.json',folder/'select.json')
        commands=[];piece_reports=[]
        for path,body_name in zip(pieces,body_names):
            imported=run(cli,[{'command':'file.insert_step','params':{'path':str(path)}}],
                         folder/(body_name+'.commands.json'),folder/(body_name+'.json'))['bodies']
            if len(imported)!=1:raise ValueError('Expected one isolated vendor body: '+str(path))
            commands.extend([{'command':'file.insert_step','params':{'path':str(path),'name':body_name}},
                             {'command':'body.rename','params':{'body':imported[0]['name'],'name':body_name}}])
            piece_reports.append({'step':str(path),'sha256':robot.digest(path),'import_body_name':imported[0]['name']})
        commands.append({'command':'file.export_step','params':{'path':str(target),'bodies':body_names}})
        run(cli,commands,folder/'exterior.commands.json',folder/'exterior.json')
        roundtrip=run(cli,[{'command':'file.insert_step','params':{'path':str(target)}}],folder/'roundtrip.commands.json',folder/'roundtrip.json')
        actual={b['name']:b for b in roundtrip['bodies']};comparisons=[]
        if set(actual)!=set(body_names):raise ValueError('Vendor exterior part identities changed: '+name)
        for source_body,body_name in zip(selected_bodies,body_names):
            body=actual[body_name]
            volume=body.get('volume_mm3')
            if not body.get('closed') or volume is None or volume<=0:raise ValueError('Open vendor exterior: '+body_name)
            ve=abs(volume-source_body['volume_mm3'])/source_body['volume_mm3']
            ce=math.dist(body['center_of_mass'],source_body['center_of_mass'])
            be=max(abs(a-b) for key in ['min','max'] for a,b in zip(body['bbox'][key],source_body['bbox'][key]))
            passed=ve<1e-4 and ce<.01 and be<.001
            comparisons.append({'part':body_name,'original_body':source_body['name'],'passed':passed,
                                'relative_volume_error':ve,'center_error_mm':ce,'bbox_error_mm':be})
        sum_volume=sum(b['volume_mm3'] for b in actual.values())
        # Separate case pieces can overlap at their original assembly seams.
        # This is a summed piece volume, not a claim of a Boolean union volume.
        ve=abs(sum_volume-part['sections']['housing']['volume_mm3'])/part['sections']['housing']['volume_mm3']
        if not all(c['passed'] for c in comparisons) or ve>=.001:raise ValueError('Vendor exterior round trip changed geometry: '+name)
        entry={'step':str(target),'body_names':body_names,'sha256':robot.digest(target)}
        replacements[str(ROOT/part['sections']['housing']['step'])]=entry
        reports.append({'part':name,'passed':True,'original':source,'registration':part['vendor_to_output_frame'],
                        'selected_original_bodies':selected,'isolated_parts':piece_reports,'output':entry,'comparisons':comparisons,
                        'summed_volume_difference_from_registered_union':ve,
                        'representation':'Separate original closed case pieces; rigid together, not Boolean-unioned'})
    report={'passed':True,'freecad_required':False,'vendor_originals_modified':False,'parts':reports,
            'source_sha256':{str(p.relative_to(ROOT)):robot.digest(p) for p in [manifest_path,check_path,ROOT/spec['vendor_library']['path']]}}
    (directory/'vendor-build-report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return replacements,report


def replace_imports(commands,replacements):
    """Adapt the existing robot command stream; expand its body references once."""
    result=[];aliases={};pending=None
    for original in commands:
        command=copy.deepcopy(original);name=command['command'];params=command['params']
        if name=='file.insert_step' and params['path'] in replacements:
            pending=replacements[params['path']]
            if robot.digest(pending['step'])!=pending['sha256']:raise ValueError('Prepared vendor STEP changed')
            params['path']=pending['step'];result.append(command);continue
        if pending:
            if name!='body.rename':raise ValueError('Expected vendor body naming after import')
            target=params['name'];aliases[target]=[target+'_Part%02d'%(i+1) for i in range(len(pending['body_names']))]
            result += [{'command':'body.rename','params':{'body':source,'name':dest}} for source,dest in zip(pending['body_names'],aliases[target])]
            pending=None;continue
        for field in ['bodies','targets']:
            if field in params:params[field]=[alias for body in params[field] for alias in aliases.get(body,[body])]
        result.append(command)
    if pending:raise ValueError('Unfinished vendor import')
    return result,aliases


def aggregate(bodies,names):
    selected=[bodies[n] for n in names]
    if not selected or any(not b.get('closed') or not isinstance(b.get('volume_mm3'),(int,float))
                          or not math.isfinite(b['volume_mm3']) or b['volume_mm3']<=0 for b in selected):
        raise ValueError('Cannot measure open or invalid bodies: '+str(names))
    for body in selected:
        center=body.get('center_of_mass')
        if not isinstance(center,list) or len(center)!=3 or any(not isinstance(v,(int,float)) or not math.isfinite(v) for v in center):
            raise ValueError('Missing or invalid center_of_mass: '+body['name'])
    volume=sum(b['volume_mm3'] for b in selected)
    return {'volume_mm3':volume,'center_of_mass':[sum(b['center_of_mass'][i]*b['volume_mm3'] for b in selected)/volume for i in range(3)]}


def semantic_bodies(measured,expected_names,aliases):
    """Measure each semantic body, retaining every closed native case piece.

    Case-piece volumes are summed (including original seam overlaps), not
    claimed to be Boolean-union volumes. Cross-CAD tolerances remain unchanged.
    Reject missing, duplicate and unexpected native bodies before aggregation.
    """
    expected_names=list(expected_names)
    names=[n for name in expected_names for n in aliases.get(name,[name])]
    actual={b['name']:b for b in measured}
    if (len(set(expected_names))!=len(expected_names) or len(set(names))!=len(names)
        or len(actual)!=len(measured) or set(actual)!=set(names) or set(aliases)-set(expected_names)):
        raise ValueError('SolidCraft body identities/count mismatch')
    result={}
    for name in expected_names:
        parts=aliases.get(name,[name]);metrics=aggregate(actual,parts)
        boxes=[actual[n]['bbox'] for n in parts]
        result[name]={'name':name,'closed':True,**metrics,'native_bodies':parts,
                      'bbox':{key:[op(box[key][i] for box in boxes) for i in range(3)]
                              for key,op in [('min',min),('max',max)]}}
    return result
