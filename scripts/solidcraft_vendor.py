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
AFFECTED={"RMD-X2-P28-7-E","RMD-X4-P36-36-E-L"}


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
        commands=[insert,{'command':'solid.remove','params':{'bodies':[b['name'] for b in measured['bodies'] if b['name'] not in selected]}}]
        commands += [{'command':'body.rename','params':{'body':old,'name':new}} for old,new in zip(selected,body_names)]
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
                        'selected_original_bodies':selected,'output':entry,'comparisons':comparisons,
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
    if any(not b.get('closed') or b.get('volume_mm3') is None or b['volume_mm3']<=0 for b in selected):
        raise ValueError('Cannot measure open bodies: '+str(names))
    volume=sum(b['volume_mm3'] for b in selected)
    return {'volume_mm3':volume,'center_of_mass':[sum(b['center_of_mass'][i]*b['volume_mm3'] for b in selected)/volume for i in range(3)]}
