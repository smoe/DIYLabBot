"""Independent native CAD construction of the PS01/TR01 logistics composition."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import ps01_logistics_geometry as geometry
import ps01_logistics_motion as motion
from ps01_logistics_validation import Program
import build_pipetting_station as base
import tip_collector_model as collector
import solidcraft_vendor as vendor
import tool_paths

s=geometry.s
write=base.write


def pins():
    result=base.source_pins()
    for source in (geometry.SOURCE,motion.SOURCE):
        result[str(source.relative_to(s.ROOT))]=s.robot.digest(source)
        spec=s.read(source)
        refs=spec['sources'].values() if source==geometry.SOURCE else (spec[k] for k in ('logistics','arm_limits','sample_limits','vehicle_limits'))
        # Only the selected limit tables are imported from historical motion
        # profiles, not those profiles' old scenes or revision-bound robot arms.
        for ref in refs:
            path=s.assembly.validate_reference(ref);result[str(path.relative_to(s.ROOT))]=s.robot.digest(path)
    for name in ('build_ps01_logistics.py','build_ps01_logistics_freecad.py','ps01_logistics_geometry.py',
                 'ps01_logistics_motion.py','ps01_logistics_validation.py','sample_motion.py','cf01_unload_path.py',
                 'h02_arm_pickup.py','h02_native_pose_boxes.py','solidcraft_audit_session.py'):
        path=s.ROOT/'scripts'/name
        if path.exists():result[str(path.relative_to(s.ROOT))]=s.robot.digest(path)
    return result


def definitions(scene,program):
    """Semantic bodies/rigid frames; each adapter constructs its own geometry."""
    result=[]
    for identity,entry in scene.arms.items():
        arm=entry['arm'];station=identity.split('.')[0];moving=identity.endswith('TransferArm')
        home=s.robot.forward(arm)
        for link in s.robot.expanded(arm)['links']:
            for op in link['recipe']:
                if op['action']!='create' or op['role']=='viewing_cone':continue
                result.append({'id':identity+'.'+op['body'],'instance':identity,'source_body':op['body'],
                    'group':identity+'.'+link['id'],'kind':'arm' if moving else 'fixture',
                    'station':station,'link':link['id'],'home':home[link['id']],
                    'matrix':home[link['id']] if moving else entry['state']['world_links'][link['id']]})
    for group in scene.groups(cover_on=True):
        for part in group['parts']:
            identity=group['id'];kind='fixture';extra={}
            if identity==program.cid:kind='sample'
            elif identity=='TR01':kind='vehicle'
            elif identity.endswith('LabwareGripper'):
                kind='tool';extra={'station':identity.split('.')[0],
                    'jaw_sign':-1 if part['id'].startswith('Left') else 1 if part['id'].startswith('Right') else 0}
            result.append({'id':identity+'.'+part['id'],'instance':identity,'source_body':part['id'],
                'group':identity,'kind':kind,'part':part,'matrix':group['matrix'],**extra})
    for item in scene.waste:
        spec=collector.load(s.assembly.validate_reference(item['source']));p=collector.parameters(spec)
        for body in collector.expanded(spec,p)['bodies']:
            result.append({'id':item['id']+'.'+body['id'],'instance':item['id'],'source_body':body['id'],
                           'group':item['id'],'kind':'fixture','matrix':item['matrix']})
    return result


def grouped(records):
    """Compound only rigid arm links; fixtures and intentional contacts stay named."""
    groups={}
    for record in records:
        key=record['group'] if 'link' in record else record['id']
        if key not in groups:groups[key]={**record,'id':key,'members':[]}
        groups[key]['members'].append(record['id'])
    for group in groups.values():
        members=[r for r in records if r['id'] in group['members']]
        group['local_bbox']={edge:[fn(r['local_bbox'][edge][i] for r in members) for i in range(3)]
                             for edge,fn in (('min',min),('max',max))}
    return list(groups.values())


def solidcraft(scene,program,cli,dest,vendor_cache=None,reuse_geometry=None):
    if vendor_cache:
        from types import SimpleNamespace
        from build_h02_arm_pickup import vendor_cache as checked_vendor_cache
        replacements,vendor_report=checked_vendor_cache(SimpleNamespace(arm=scene.context['arm']),vendor_cache)
    else:replacements,vendor_report=vendor.prepare(scene.context['arm'],cli,dest/'vendor')
    records=definitions(scene,program);byid={r['id']:r for r in records};commands=[];manifest=[]
    for identity,entry in scene.arms.items():
        # arm_commands removes the source joints/drives when creating scene
        # instances. Its solids are already in their zero construction frames;
        # applying inverse(home) here would rotate them a second time.
        state={'world_links':{key:s.robot.identity() for key in s.robot.forward(entry['arm'])}}
        extra,mapping=s.tools.arm_commands(entry['item'],state,replacements)
        commands.extend(extra);manifest.extend(mapping)
        prefix=s.tools.re.sub(r'[^A-Za-z0-9_]','_',identity)+'_'
        for record in records:
            if record['instance']==identity:record['occurrence']=prefix+record['link']+':1'
    rigid={}
    for record in records:
        if 'part' not in record:continue
        key=record['group']
        if record['kind']=='tool':key+='.Jaw'+str(record['jaw_sign'])
        if record['source_body']=='LT01TransportCover':key+='.Cover'
        rigid.setdefault(key,[]).append(record)
    for identity,members in rigid.items():
        extra,mapping=s.tools.primitive_commands(identity,[record['part'] for record in members],s.robot.identity())
        commands.extend(extra)
        for item in mapping:item.update(instance=members[0]['instance'])
        manifest.extend(mapping)
        occurrence=next(c['params']['occurrence'] for c in extra if c['command']=='occurrence.move')
        for record in members:record['occurrence']=occurrence
    for item in scene.waste:
        spec=collector.load(s.assembly.validate_reference(item['source']));p=collector.parameters(spec);expanded=collector.expanded(spec,p)
        extra,names=s.tools.namespace(collector.solidcraft_commands(spec,p),item['id'],spec['parameters'],
            [b['id'] for b in expanded['bodies']]+[c['id'] for c in expanded['components']])
        commands.extend(extra)
        for body in expanded['bodies']:
            manifest.append({'instance':item['id'],'source_body':body['id'],'names':[names[body['id']]]})
        for component in expanded['components']:
            # Waste is static; lower it directly at the source-defined world pose.
            commands.append({'command':'occurrence.move','params':{'occurrence':names[component['id']]+':1',
                'matrix':item['matrix'],'space':'world','move_grounded':True}})
        for record in records:
            if record['instance']==item['id']:record['matrix']=s.robot.identity()
    output=dest/'Logistics-local.solidcraft'
    reused=None
    if reuse_geometry:
        old=Path(reuse_geometry).resolve();prior=s.read(old/'solidcraft.commands.json')['commands']
        s.require(s.read(old/'solidcraft-local-report.json')['passed'],'Cannot reuse invalid native solids')
        without_moves=lambda values:[c for c in values if c['command']!='occurrence.move']
        s.require(without_moves(prior)==without_moves(commands),
                  'Native construction commands differ; full rebuild required')
        def poses(values):
            result={}
            for c in values:
                if c['command']!='occurrence.move':continue
                p=c['params'];s.require(p['space']=='world' and p['move_grounded'] and 'matrix' in p,'Unsupported cached move')
                key=p['occurrence'];result[key]=s.robot.multiply(p['matrix'],result.get(key,s.robot.identity()))
            return result
        before,after=poses(prior),poses(commands)
        s.require(before.keys()==after.keys(),'Native occurrence identities differ')
        correction=[{'command':'occurrence.move','params':{'occurrence':key,'space':'world','move_grounded':True,
                    'matrix':s.robot.multiply(value,s.robot.inverse(before[key]))}} for key,value in after.items() if value!=before[key]]
        originals={name:s.robot.digest(old/name) for name in ('Logistics-local.solidcraft','solidcraft.commands.json','solidcraft-local-report.json')}
        measured=vendor.run(cli,correction,dest/'solidcraft-reframe.commands.json',dest/'solidcraft-local.json',
                            **{'in':old/'Logistics-local.solidcraft','save':output})
        s.require(originals=={name:s.robot.digest(old/name) for name in originals},'Cached geometry changed during reuse')
        write(dest/'solidcraft.commands.json',{'commands':commands})
        reused={'source_directory':str(old),'artifacts_sha256':originals,'geometry_commands_identical':True,
                'occurrence_corrections':len(correction),'scope':'Reused native BReps; current source-derived occurrence frames reapplied natively'}
    else:
        measured=vendor.run(cli,commands,dest/'solidcraft.commands.json',dest/'solidcraft-local.json',save=output)
    actual={body['name']:body for body in measured['bodies']}
    s.require(set(actual)=={n for item in manifest for n in item['names']},'Native semantic body set differs')
    for item in manifest:
        record=byid[item['instance']+'.'+item['source_body']];record['names']=item['names']
        metrics=s.tools.scene_model.instance_metrics([actual[name] for name in item['names']])
        record['local_bbox']=metrics['bbox'];record['local_metrics']=metrics
    report={'passed':all(b['closed'] and b['volume_mm3']>0 for b in actual.values()),
            'freecad_construction_dependency':False,'vendor':vendor_report,'records':records,'manifest':manifest}
    if reused:report['reused_geometry']=reused
    write(dest/'solidcraft-local-report.json',report)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend',choices=['freecad','solidcraft','both'],default='both')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--program',type=Path)
    parser.add_argument('--vendor-cache',type=Path,help='Source/artifact-verified independent SolidCraft vendor report')
    parser.add_argument('--reuse-solidcraft',type=Path,help='Reuse native solids only when all non-placement construction commands are identical')
    tool_paths.add_tool_arguments(parser);args=parser.parse_args()
    tool_paths.resolve_tool_arguments(parser,args,required={'freecad_python','solidcraft_cli'} if args.backend=='both' else
        {'freecad_python' if args.backend=='freecad' else 'solidcraft_cli'})
    dest=args.output.resolve();dest.mkdir(parents=True,exist_ok=True)
    scene=geometry.Scene();data=s.read(args.program) if args.program else motion.compile_demo(scene)
    s.require(data['definition']==motion.load(),'Motion program definition is stale')
    s.require(data.get('compiler_sources_sha256')==motion.compiler_pins(),'Motion compiler source pins are stale')
    write(dest/'program.json',data);write(dest/'context.json',{'source_files_sha256':pins()})
    program=Program(data,scene)
    if args.backend in ('freecad','both'):
        from build_instrument_concepts import freecad_environment
        with (dest/'freecad.log').open('w') as log:
            subprocess.run([args.freecad_python,str(s.ROOT/'scripts/build_ps01_logistics_freecad.py'),str(dest)],
                cwd=s.ROOT,env=freecad_environment(args.freecad_python),check=True,stdout=log,stderr=subprocess.STDOUT)
    if args.backend in ('solidcraft','both'):solidcraft(scene,program,args.solidcraft_cli,dest,args.vendor_cache,args.reuse_solidcraft)
    base.verify_pins(s.read(dest/'context.json')['source_files_sha256'])
    print(json.dumps({'directory':str(dest),'backend':args.backend}),flush=True)


if __name__=='__main__':main()
