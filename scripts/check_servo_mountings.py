"""Save calculated servo fits/stacks with current generated-model evidence."""
import argparse,hashlib,json,zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
import robot_spec as model
from robot_components import library
from servo_mounting_design import analyse

def assembly_bindings(spec,lib,native,solidcraft,ros):
    """Trace the selected hardware into actual CAD bodies and RViz link contents."""
    from robot_components import audit
    audit(spec)
    rows=[]
    for actuator in spec['services']['actuators']:
        row={'actuator':actuator['id'],'joint':actuator['joint'],'servo':actuator['part'],'plates':[]}
        for link in spec['links']:
            for op in link['recipe']:
                if op['action']!='mount_plate' or op['actuator']!=actuator['id']:continue
                vendor=actuator['id']+'_'+op['section'];plate=op['body'];part=lib['parts'][op['part']]
                interface=part['interfaces'][op['section']]
                pins=[plate+'_pin_'+suffix for suffix in ['round','relieved']] if 'plate_locating_pins' in interface else []
                for body in [vendor,plate]+pins:
                    if body not in native or body not in solidcraft:raise ValueError('Selected part missing from CAD: '+body)
                    if native[body]['RigidLink']!=link['id']:raise ValueError('CAD part on wrong link: '+body)
                if native[vendor].get('VendorPart')!=op['part'] or native[vendor].get('VendorSHA256')!=part['sections'][op['section']]['sha256']:
                    raise ValueError('Actual FreeCAD vendor part/revision mismatch: '+vendor)
                mesh=set(ros['links'][link['id']]['mesh_bodies'])
                if not set([plate]+pins)<=mesh:raise ValueError('RViz missing selected plate or pins: '+plate)
                if vendor in mesh:raise ValueError('RViz contains duplicate detailed servo: '+vendor)
                if vendor not in {b['body'] for b in ros['links'][link['id']]['collision_boxes']}:raise ValueError('RViz missing servo collision proxy: '+vendor)
                if op['section']=='housing':
                    boxes=[b for b in ros['links'][link['id']]['servo_visual_boxes'] if b['body']==vendor]
                    if len(boxes)!=1 or boxes[0]['part']!=op['part']:raise ValueError('RViz uses wrong servo box: '+vendor)
                row['plates'].append({'section':op['section'],'body':plate,'rigid_link':link['id'],'locating_pin_bodies':pins,
                    'screw':interface['fastener_design']['designation'],'screw_quantity':len(interface['hole_centres_mm'])})
        rows.append(row)
    return {'passed':True,'joints':rows,'screw_representation':'Assembly specification and checked head envelopes; full screw/thread solids omitted',
            'counts':{'servos':len(rows),'motor_plates':sum(len(r['plates']) for r in rows),
                'own_locating_pins':sum(len(p['locating_pin_bodies']) for r in rows for p in r['plates']),
                'specified_screws':sum(p['screw_quantity'] for r in rows for p in r['plates'])}}

def native_part_metadata(path):
    with zipfile.ZipFile(path) as archive:doc=ET.fromstring(archive.read('Document.xml'))
    result={}
    for obj in doc.findall('ObjectData/Object'):
        props={p.get('name'):p.find('String').get('value') for p in obj.findall('Properties/Property') if p.find('String') is not None}
        if 'SourceBody' in props:result[props['SourceBody']]=props
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path,default=model.ROOT/'exports/x2-x4-fits-fasteners/design-validation.json')
    args=parser.parse_args();target=args.report.resolve()
    if not target.is_relative_to(model.ROOT):raise ValueError('Keep report inside project')
    spec=model.load();lib=library(spec);build_path=model.ROOT/'exports/generated/build-report.json'
    build=json.loads(build_path.read_text(encoding='utf-8'))
    if build['spec_sha256']!=model.digest(model.SPEC) or not build['passed']:raise ValueError('Build current model first')
    native=json.loads((model.ROOT/build['artifacts']['freecad_report']).read_text(encoding='utf-8'))
    for key,digest in build['artifact_sha256'].items():
        if model.digest(model.ROOT/build['artifacts'][key])!=digest:raise ValueError('Generated CAD artifact changed: '+key)
    ros_path=model.ROOT/'ros2_ws/src/solidcraftbot_ros/config/geometry.json'
    ros=json.loads(ros_path.read_text(encoding='utf-8'))
    if ros['spec_sha256']!=model.digest(model.SPEC):raise ValueError('RViz robot source is stale')
    sc=json.loads((model.ROOT/build['artifacts']['solidcraft_measurements']).read_text(encoding='utf-8'))
    integration=assembly_bindings(spec,lib,native_part_metadata(model.ROOT/build['artifacts']['freecad']),{b['name'] for b in sc['bodies']},ros)
    urdf_path=model.ROOT/'ros2_ws/src/solidcraftbot_ros/urdf/robot.urdf'
    urdf=ET.parse(urdf_path).getroot()
    boxes={v.get('name','').removesuffix('_servo_box') for v in urdf.findall('link/visual') if v.get('name','').endswith('_servo_box') and v.find('geometry/box') is not None}
    if boxes!={a['id']+'_housing' for a in spec['services']['actuators']}:raise ValueError('Actual RViz URDF uses wrong servo boxes')
    result={'spec_sha256':model.digest(model.SPEC),'interfaces':{},'manufacturing_released':False,'physical_sample_verified':False,
            'artifacts':build['artifacts'],'artifact_sha256':build['artifact_sha256'],'cross_cad_body_count':len(build['body_comparisons']),
            'head_clearance':native['screw_head_clearance'],'retained_pin_clearance':native['retained_pin_clearance'],'assembly_integration':integration,'ros2_runtime_tested':False}
    sources={model.SPEC,Path(__file__),model.ROOT/'model/robot.schema.json',model.ROOT/'scripts/servo_mounting_design.py',
             model.ROOT/'scripts/x6_mounting_design.py',model.ROOT/'scripts/robot_components.py',model.ROOT/'scripts/prepare_servo_components.py',
             model.ROOT/spec['vendor_library']['path'],ros_path,urdf_path}
    sources.update(model.ROOT/p for p in build['generator_sha256'])
    for link in ros['links'].values():
        mesh=model.ROOT/'ros2_ws/src/solidcraftbot_ros/meshes'/link['mesh']
        if not mesh.is_file():raise ValueError('RViz robot mesh is missing')
        sources.add(mesh)
    dependencies={}
    if spec.get('mobile_base'):
        path=model.ROOT/'cad/mobile-base-mb01/shared-build-report.json';mobile=json.loads(path.read_text(encoding='utf-8'))
        if not mobile['passed'] or mobile['arm_sha256']!=build['spec_sha256']:raise ValueError('Mobile arm parts are stale')
        for state in mobile['states']:
            for key in ['freecad','solidcraft']:
                if model.digest(model.ROOT/state[key])!=state['sha256'][key]:raise ValueError('Mobile CAD changed')
            metadata=native_part_metadata(model.ROOT/state['freecad'])
            for row in integration['joints']:
                for plate in row['plates']:
                    for body in [plate['body']]+plate['locating_pin_bodies']:
                        if body not in metadata:raise ValueError('Mobile arm missing hardware: '+body)
        dependencies['mobile_base']={'report':path.relative_to(model.ROOT).as_posix(),'passed':True,'arm_sha256':mobile['arm_sha256'],'states':[s['id'] for s in mobile['states']]}
        sources.add(path)
    path=model.ROOT/'cad/lab-layout-l01/shared-build-report.json'
    if path.is_file():
        layout=json.loads(path.read_text(encoding='utf-8'));arm=layout['asset_sources']['arm']
        if arm['source_sha256']!=build['spec_sha256'] or arm['native_sha256']!=build['artifact_sha256']['freecad']:
            raise ValueError('Laboratory layout uses an older arm parts set')
        dependencies['laboratory_layout_arm']={'report':path.relative_to(model.ROOT).as_posix(),'arm_source_sha256':arm['source_sha256'],
            'native_sha256':arm['native_sha256'],'instances':[k for k in layout['layout_validation']['instance_metrics'] if k.startswith('Arm')]}
        sources.add(path)
    result['referencing_assemblies']=dependencies
    for name,part in lib['parts'].items():
        path=model.ROOT/part['interface_spec']['path'];source=json.loads(path.read_text(encoding='utf-8'));calculation=analyse(source)
        if calculation!=part['assembly_design_analysis']:raise ValueError('Library calculation stale: '+name)
        result['interfaces'][name]={'source':part['interface_spec'],'geometry_evidence':part['interface_check'],'analysis':calculation}
        sources.update([path,model.ROOT/part['interface_check']['path'],model.ROOT/source['drawing']])
    schedule={};pin_schedule={'custom_round_pins':0,'custom_diamond_pins':0}
    for link in spec['links']:
        for op in link['recipe']:
            if op['action']=='mount_plate':
                source=json.loads((model.ROOT/lib['parts'][op['part']]['interface_spec']['path']).read_text(encoding='utf-8'))
                analyse(source,model.evaluate(op['thickness_mm'],model.parameters(spec)))
                definition=source[op['section']];key=definition['fastener_design']['designation']
                schedule[key]=schedule.get(key,0)+definition['fastener_count']
                if 'plate_locating_pins' in definition:
                    pin_schedule['custom_round_pins']+=1;pin_schedule['custom_diamond_pins']+=1
    result['nominal_hardware_schedule']={'fasteners':schedule,'own_locating_pins':pin_schedule,'procurement_or_manufacturing_released':False}
    result['source_files_sha256']={p.relative_to(model.ROOT).as_posix():model.digest(p) for p in sorted(sources)}
    result['passed']=build['passed'] and result['head_clearance']['passed'] and result['retained_pin_clearance']['passed']
    target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print('Servo mounting design checks:',result['passed'],str(target))

if __name__=='__main__':main()
