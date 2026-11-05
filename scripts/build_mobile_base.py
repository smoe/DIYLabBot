"""Build MB01 working/parking assemblies from one source and the referenced arm."""
from pathlib import Path
import argparse
import json
import math
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
import mobile_base_model as model
import robot_spec as robot


def write(path,value):
    Path(path).write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')


def compare(actual,expected):
    refs={b['body']:b for b in expected}
    if set(refs)!={b['name'] for b in actual['bodies']}: raise AssertionError('MB01 body names/count mismatch')
    result=[]
    for b in actual['bodies']:
        ref=refs[b['name']]; vol=abs(b['volume_mm3']-ref['volume_mm3'])/ref['volume_mm3']
        com=math.dist(b['center_of_mass'],ref['world_center_of_mass_mm'])
        box=max(abs(a-c) for key in ['min','max'] for a,c in zip(b['bbox'][key],ref['bbox'][key]))
        result.append({'body':b['name'],'relative_volume_error':vol,'com_error_mm':com,'bbox_error_mm':box,
                       'passed':b['closed'] and vol<0.001 and com<0.01 and box<0.02})
    return result


def presentation(spec,arm,p):
    styles=robot.appearances(arm)['appearances']; bodies=[]
    for link in robot.expanded(arm)['links']:
        for op in link['recipe']:
            if op['action']!='create': continue
            look=styles['bodies'].get(op['body'],styles['components'][link['id']])
            bodies.append({'id':op['body'],'appearance':{'color':'#'+''.join(f'{v:02x}' for v in look['color']),'opacity':look['opacity']}})
    for body in model.expanded(spec,p)['bodies']:
        look=body['appearance']; bodies.append({'id':body['id'],'appearance':{'color':'#'+''.join(f'{v:02x}' for v in look['color']),'opacity':look['opacity']}})
    return {'bodies':bodies}


def pose_commands(arm,pose):
    commands=model.solidcraft_pose(pose)
    commands += [{'command':'joint.drive','params':{'joint':j['id'],'value':v,'quiet':True}} for j,v in zip(arm['joints'],pose['arm_deg'])]
    commands.append({'command':'joint.solve','params':{}})
    return commands


def mobile_urdf(spec,arm,p,name,destination):
    """Static manual-base state plus the unchanged six controlled arm axes.

    No powered mobile joints/controller or dynamic contact model is implied.
    Cut bores are omitted from mobile visual/collision primitives.
    """
    base=model.expanded(spec,p); pose=model.state(spec,arm,p,name)
    path=model.ROOT/'ros2_ws/src/solidcraftbot_ros/urdf/robot.urdf'
    root=ET.parse(path).getroot(); root.set('name','solidcraftbot_mb01_'+name)
    for joint,angle in zip(arm['joints'],pose['arm_deg']):
        initial=root.find("ros2_control/joint[@name='%s']/state_interface[@name='position']/param[@name='initial_value']"%joint['id'].lower())
        if initial is not None: initial.text=str(math.radians(angle))
    ET.SubElement(root,'link',name='mb01_bench_reference')
    groups={'MB01_Chassis':'mb01_chassis',**{s['component']:s['component'].lower() for s in base['supports']}}
    for link in groups.values(): ET.SubElement(root,'link',name=link)
    def fixed(name,parent,child,xyz,rpy=[0,0,0]):
        joint=ET.SubElement(root,'joint',name=name,type='fixed')
        ET.SubElement(joint,'parent',link=parent); ET.SubElement(joint,'child',link=child)
        ET.SubElement(joint,'origin',xyz=' '.join(str(v/1000) for v in xyz),rpy=' '.join(map(str,rpy)))
    x,y,heading=pose['manual_xy_yaw']
    fixed('mb01_manual_location','mb01_bench_reference','mb01_chassis',[x,y,pose['chassis_lift_mm']],[0,0,math.radians(heading)])
    fixed('mb01_arm_mount','mb01_chassis','base_link',[0,0,p['mb_mount_z']])
    for support in base['supports']: fixed(support['joint'].lower(),'mb01_chassis',groups[support['component']],[0,0,-pose['support_extension_mm']])
    for body in base['bodies']:
        shape=model.station.primitive(body['geometry'],p); parent=root.find("link[@name='%s']"%groups[body['component']])
        o=shape['origin']; rpy=[0,0,0]
        if shape['type']=='box': center=[a+b/2 for a,b in zip(o,shape['size'])]
        else:
            center=[a+b*shape['height']/2 for a,b in zip(o,shape['axis'])]
            if shape['axis']==[0,1,0]: rpy=[-math.pi/2,0,0]
        for tag in ['visual','collision']:
            element=ET.SubElement(parent,tag,name=body['id']+('_conservative' if tag=='collision' else ''))
            ET.SubElement(element,'origin',xyz=' '.join(str(v/1000) for v in center),rpy=' '.join(map(str,rpy)))
            geo=ET.SubElement(element,'geometry')
            if shape['type']=='box': ET.SubElement(geo,'box',size=' '.join(str(v/1000) for v in shape['size']))
            else: ET.SubElement(geo,'cylinder',radius=str(shape['radius']/1000),length=str(shape['height']/1000))
            if tag=='visual':
                material=ET.SubElement(element,'material',name=body['id']+'_material')
                ET.SubElement(material,'color',rgba=' '.join(str(v/255) for v in body['appearance']['color'])+' 1')
    # Preserve a parent-before-child traversal for simple consumers as well as URDF.
    links=root.findall('link'); joints=root.findall('joint'); others=[e for e in root if e.tag not in {'link','joint'}]
    for e in list(root): root.remove(e)
    root.extend(links); remaining=joints[:]; known={'mb01_bench_reference'}
    while remaining:
        ready=[j for j in remaining if j.find('parent').get('link') in known]
        if not ready: raise AssertionError('Mobile URDF contains disconnected/cyclic joints')
        for j in ready: root.append(j); known.add(j.find('child').get('link')); remaining.remove(j)
    root.extend(others); ET.indent(root)
    ET.ElementTree(root).write(destination,encoding='utf-8',xml_declaration=True)
    return {'path':str(Path(destination).relative_to(model.ROOT)).replace('\\','/'),'revolute_arm_joints':len(root.findall("joint[@type='revolute']")),
        'base_state':name,'base_joints':'fixed manual state; no mobile hardware controller','runtime_tested':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freecad-python',default=str(Path.home()/'AppData/Local/Programs/FreeCAD 27.1/bin/python.exe'))
    parser.add_argument('--solidcraft-cli',default=shutil.which('solidcraft-cli') or 'solidcraft-cli')
    parser.add_argument('--ros2',action='store_true')
    parser.add_argument('--reuse-freecad-report',help='Reuse passed native files with identical source snapshots in a fresh revision')
    args=parser.parse_args(); started=time.monotonic(); spec=model.load(); arm=robot.load(model.ROOT/spec['arm_source']); p=model.parameters(spec)
    source_hash=model.digest(model.SOURCE); arm_hash=model.digest(model.ROOT/spec['arm_source'])
    import hashlib
    signature=hashlib.sha256((source_hash+arm_hash).encode()).hexdigest()
    stem='mobile-base-mb01-'+signature[:12]; revision=stem; count=1
    while (model.ROOT/'cad/generated'/revision).exists(): count+=1; revision=stem+'-r'+str(count)
    cad=model.ROOT/'cad/generated'/revision; out=model.ROOT/'exports/generated'/revision
    cad.mkdir(parents=True); out.mkdir(parents=True); (model.ROOT/'cad/mobile-base-mb01').mkdir(exist_ok=True)
    write(out/'mobile-source.json',spec); write(out/'arm-source.json',arm)
    sc=cad/(spec['id']+'.sc'); fc=cad/(spec['id']+'.FCStd')
    commands=out/'working.commands.json'; measurements=out/'working.solidcraft.json'; freport=out/'freecad-validation.json'
    write(commands,{'commands':model.solidcraft_commands(spec,arm,p)})
    print('MB01: building SolidCraft working assembly',flush=True)
    subprocess.run([args.solidcraft_cli,'run',str(commands),'--save',str(sc),'--out',str(out/'working.step'),'--json-out',str(measurements),'--quiet'],check=True,cwd=model.ROOT)
    print('MB01: building FreeCAD; checking fold, support transfer and parameter variants',flush=True)
    if args.reuse_freecad_report:
        prior=Path(args.reuse_freecad_report).resolve()
        if not prior.is_relative_to((model.ROOT/'exports/generated').resolve()): raise ValueError('Native report must be inside project generated outputs')
        prior_cad=model.ROOT/'cad/generated'/prior.parent.name
        if json.loads((prior.parent/'mobile-source.json').read_text())!=spec or json.loads((prior.parent/'arm-source.json').read_text())!=arm:
            raise ValueError('Native report source snapshots differ from current source')
        for name in ['', '_manual_reposition', '_parked_aside']:
            shutil.copyfile(prior_cad/(spec['id']+name+'.FCStd'),fc.with_name(fc.stem+name+'.FCStd'))
        subprocess.run([args.freecad_python,str(model.ROOT/'scripts/recheck_mobile_geometry.py'),str(fc),str(freport),str(prior)],check=True,cwd=model.ROOT)
    else:
        subprocess.run([args.freecad_python,str(model.ROOT/'scripts/build_mobile_base_freecad.py'),str(fc),str(freport)],check=True,cwd=model.ROOT)
    fcr=json.loads(freport.read_text()); results=[]
    sys.path.insert(0,str(model.ROOT/'scripts/freecad')); from persist_station_view import persist
    styles=presentation(spec,arm,p)
    for name in ['working','manual_reposition','parked_aside']:
        target=sc if name=='working' else sc.with_name(sc.stem+'_'+name+'.sc')
        ftarget=fc if name=='working' else fc.with_name(fc.stem+'_'+name+'.FCStd')
        measured=measurements if name=='working' else out/(name+'.solidcraft.json')
        if name!='working':
            script=out/(name+'.commands.json'); write(script,{'commands':pose_commands(arm,model.state(spec,arm,p,name))})
            subprocess.run([args.solidcraft_cli,'run',str(script),'--in',str(sc),'--save',str(target),'--json-out',str(measured),'--quiet'],check=True,cwd=model.ROOT)
        checks=compare(json.loads(measured.read_text()),fcr['state_geometry'][name])
        view=persist(ftarget,styles,fcr['state_geometry'][name])
        results.append({'id':name,'passed':all(c['passed'] for c in checks) and view['passed'],'body_comparisons':checks,'presentation':view,
            'solidcraft':str(target.relative_to(model.ROOT)).replace('\\','/'),'freecad':str(ftarget.relative_to(model.ROOT)).replace('\\','/'),
            'sha256':{'solidcraft':model.digest(target),'freecad':model.digest(ftarget)}})
        subprocess.run([args.solidcraft_cli,'snapshot',str(target),'--out',str(cad/(name+'.png')),'--width','1200','--height','900','--no-grid','--no-axes'],check=True,cwd=model.ROOT)
        print('MB01 cross-CAD state '+name+': '+str(results[-1]['passed']),flush=True)
    # Check the same actual joint solver that the saved SolidCraft files expose.
    script=out/'joint-check.commands.json'; write(script,{'commands':[{'command':'joint.inspect','params':{}}]})
    jointfile=out/'solidcraft-joints.json'
    subprocess.run([args.solidcraft_cli,'run',str(script),'--in',str(sc),'--results','--json-out',str(jointfile),'--quiet'],check=True,cwd=model.ROOT)
    joints=json.loads(jointfile.read_text())[0]['joints']
    joint_pass=len(joints)==12 and all(j['a']['resolves'] and j['b']['resolves'] and not j['errors'] and not j['conflicts'] for j in joints)
    variants=[]
    for case in fcr['native_parameter_changes']:
        overrides={case['parameter']:case['value_mm']}; changed=model.parameters(spec,overrides)
        script=out/('variant-'+case['parameter']+'.commands.json'); measured=out/('variant-'+case['parameter']+'.solidcraft.json')
        write(script,{'commands':model.solidcraft_commands(spec,arm,changed)})
        subprocess.run([args.solidcraft_cli,'run',str(script),'--json-out',str(measured),'--quiet'],check=True,cwd=model.ROOT)
        checks=compare(json.loads(measured.read_text()),case['geometry'])
        variants.append({'overrides':overrides,'passed':all(c['passed'] for c in checks),'body_comparisons':checks})
    ros=[]
    if args.ros2:
        package=model.ROOT/'ros2_ws/src/solidcraftbot_ros'
        for name in ['working','manual_reposition']:
            ros.append(mobile_urdf(spec,arm,p,name,package/'urdf'/('robot_mb01_'+name+'.urdf')))
        write(package/'config/mobile-base.json',{'source_sha256':model.digest(model.SOURCE),'arm_sha256':model.digest(model.ROOT/spec['arm_source']),
            'protocol':spec['protocol'],'vision':spec['vision'],'states':ros,'runtime_tested':False})
    source_paths=[model.SOURCE,model.ROOT/spec['arm_source'],model.ROOT/'model/mobile-base.schema.json',Path(__file__),model.ROOT/'scripts/mobile_base_model.py',
        model.ROOT/'scripts/build_mobile_base_freecad.py',model.ROOT/'scripts/recheck_mobile_geometry.py',model.ROOT/'scripts/robot_spec.py',model.ROOT/'scripts/build_neutral_freecad.py',
        model.ROOT/'scripts/robot_components.py',model.ROOT/'scripts/robot_cameras.py',model.ROOT/'scripts/station_model.py',
        model.ROOT/'scripts/freecad/solidcraftbot_freecad.py',model.ROOT/'scripts/freecad/persist_station_view.py']
    if source_hash!=model.digest(model.SOURCE) or arm_hash!=model.digest(model.ROOT/spec['arm_source']):
        raise RuntimeError('Shared source changed during MB01 build; preserve outputs and rebuild before publishing')
    report={'format':'solidcraftbot.mobile-arm-build/1','source':'model/mobile-base-mb01.shared.json','source_sha256':source_hash,
        'arm_source':spec['arm_source'],'arm_sha256':arm_hash,
        'source_files_sha256':{str(path.relative_to(model.ROOT)).replace('\\','/'):model.digest(path) for path in source_paths},
        'passed':fcr['passed'] and joint_pass and all(r['passed'] for r in results+variants),'states':results,'parameter_variants':variants,
        'freecad_validation':str(freport.relative_to(model.ROOT)).replace('\\','/'),'solidcraft_joints_resolve':joint_pass,
        'solidcraft_joint_count':len(joints),'sample_count':len(fcr['samples']),'native_parameter_changes':[{k:v for k,v in c.items() if k!='geometry'} for c in fcr['native_parameter_changes']],
        'reused_collision_evidence':fcr.get('reused_collision_evidence'),
        'envelopes':fcr['envelopes'],'ros_descriptions':ros,'ros_runtime_tested':False,'elapsed_s':time.monotonic()-started,
        'solidcraft_execution':'Reproducible CLI; MCP import refused by server allowed-folder configuration',
        'renderings_visually_inspected':False,'limitations':spec['limitations']+['BRep collisions checked at sampled poses; no continuous swept-volume proof',
            'Support contact geometry is not physical load/stiffness/stability qualification','FreeCAD native placements; interactive GUI controls not separately validated']}
    write(out/'build-report.json',report)
    if not report['passed']: raise AssertionError('MB01 validation failed: '+str(out/'build-report.json'))
    write(model.ROOT/'cad/mobile-base-mb01/shared-build-report.json',report)
    arm_report_path=model.ROOT/'exports/generated/build-report.json'
    if arm_report_path.exists():
        arm_report=json.loads(arm_report_path.read_text())
        if arm_report.get('spec_sha256')==arm_hash:
            arm_report['mobile_base_report']='cad/mobile-base-mb01/shared-build-report.json'; write(arm_report_path,arm_report)
    print('MB01 passed: '+str(out/'build-report.json'),flush=True)


if __name__=='__main__': main()
