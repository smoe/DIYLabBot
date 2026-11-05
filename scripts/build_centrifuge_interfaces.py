"""Generate ROS 2 interfaces and SiLA 2 FDL from the CF01 shared contract."""
import json
import xml.etree.ElementTree as ET
import centrifuge_model as model
import centrifuge_protocol as protocol
from centrifuge_control import request_schema

NS='http://www.sila-standard.org'
# A common SI snapshot: both wire contracts expose the same values/validity bits.
FIELDS=[
 ('string','boot_id','Controller boot UUID; invalidates all old coordination tokens.'),
 ('uint64','sequence','Event sequence within this boot; not a UTC timestamp.'),
 ('bool','simulation_only','Always true in this implementation.'),
 ('bool','hardware_qualified','Always false; no device qualification.'),
 ('string','fault_code','Empty or latched project error identifier.'),
 ('bool','lid_open','Confirmed open state in the mock.'),('bool','lid_closed','Confirmed closed state in the mock.'),
 ('bool','lid_locked','Both locking pins confirmed engaged.'),('float64','lid_angle_rad','Lid hinge angle, radians.'),
 ('bool','standstill_confirmed','Separate standstill input; a stop request never proves this.'),
 ('bool','parking_brake_held','Parking brake held feedback.'),('bool','robot_clear','Independent workspace-clear input; never a remote override.'),
 ('float64','feedback_age_s','Age of mechanism feedback, seconds.'),('bool','encoder_healthy','Encoder health including age.'),
 ('float64','encoder_age_s','Encoder feedback age, seconds.'),('float64','speed_rad_s','Spindle angular speed, radians/second; ignore unless speed_valid.'),
 ('bool','speed_valid','Validity of speed_rad_s.'),('float64','rotor_angle_rad','Spindle angle, radians; ignore unless rotor_angle_valid.'),
 ('bool','rotor_angle_valid','Validity of rotor_angle_rad.'),('uint8','indexed_slot','1..12; zero means no confirmed selected slot.'),
 ('bool','index_confirmed','Indexed orientation confirmed within the source tolerance.'),('float64','lift_m','Tube axial lift, meters; excludes pusher park gap.'),
 ('float64[3]','pickup_position_m','Uncalibrated pickup position XYZ, meters, relative to pickup_frame_id.'),
 ('float64[3]','pickup_axis','Unit tube-axis vector in pickup_frame_id; roll is not calibrated.'),
 ('string','pickup_frame_id','cf01_station; integration must calibrate this frame against the robot.'),
 ('bool','pickup_valid','False unless presentation, index, standstill, lid hold and fresh feedback all agree.'),
 ('bool','lid_open_limit','Open-limit feedback.'),('bool','lid_closed_limit','Closed-limit feedback.'),
 ('bool','lid_holding_brake_held','Lid drive holding brake feedback.'),
 ('float64[2]','locking_pin_retraction_m','Left/right pin retraction, meters, in that order.')]
TYPES={'string':('string','String'),'integer':('int32','Integer'),'number':('float64','Real'),'boolean':('bool','Boolean')}


def camel(name): return ''.join(w[:1].upper()+w[1:] for w in name.split('_'))


def write(path,text):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text,encoding='utf-8')


def feature(data):
    ET.register_namespace('',NS)
    def el(parent,tag,text=None):
        node=ET.SubElement(parent,'{'+NS+'}'+tag)
        if text is not None:node.text=str(text)
        return node
    def header(parent,name,description):
        for k,v in [('Identifier',name),('DisplayName',name),('Description',description)]:el(parent,k,v)
    def value(parent,tag,name,basic,description):
        node=el(parent,tag);header(node,name,description);dt=el(node,'DataType')
        if '[' in basic:
            dt=el(el(dt,'List'),'DataType');basic=basic.split('[')[0]
        if basic=='State':el(dt,'DataTypeIdentifier','State')
        else:el(dt,'Basic',{'string':'String','bool':'Boolean','uint64':'Integer','uint8':'Integer','float64':'Real'}.get(basic,basic))
        return node
    t=data['transport']
    root=ET.Element('{'+NS+'}Feature',{'SiLA2Version':t['sila_version'],'FeatureVersion':t['feature_version'],
        'MaturityLevel':'Draft','Originator':t['sila_originator'],'Category':t['sila_category'],'Locale':'en-us'})
    header(root,t['sila_identifier'],'CF01 custom centrifuge feature draft. Generated contract plus local mock adapter only; no SiLA gRPC server, authentication, TLS or discovery is implemented. No qualified hardware. Observable commands require confirmed terminal state, not just an accepted setpoint. Send Heartbeat during long executions. Use Stop for controlled cancellation; observe State until standstill and held brake. Provisional project namespace, not a registered standard feature.')
    for c in data['commands']:
        if c.get('local_only'):continue
        command=el(root,'Command');header(command,c['name'],c['description']);el(command,'Observable','Yes' if c['observable'] else 'No')
        if c['id'] not in protocol.PUBLIC:value(command,'Parameter','ControlToken','String','Exclusive coordination token for the current boot; not an authentication credential.')
        for name,kind in c['arguments'].items():
            value(command,'Parameter',camel(name),TYPES[kind][1],'Required '+name+'; units and range are stated in the command description and shared contract. RcfXG is relative centrifugal acceleration in multiples of g; DurationS is seconds; MassG is measured grams.')
        if c['id']=='acquire':
            value(command,'Response','ControlToken','String','Exclusive boot-scoped coordination token.')
            value(command,'Response','HeartbeatWithinS','Real','Heartbeat deadline, seconds.')
        value(command,'Response','State','State','Coherent SI snapshot at command completion; examine all validity fields.')
        if c['observable']:value(command,'IntermediateResponse','State','State','Execution snapshot; Stop requests cancellation but does not itself prove physical standstill.')
        errors=el(command,'DefinedExecutionErrors')
        for error in data['errors']:el(errors,'Identifier',error)
    prop=el(root,'Property');header(prop,'Status','Coherent SI snapshot. Publish on change and at least every 0.1 seconds in a future server; clients also check local receipt age. Synthetic in the local adapter.');el(prop,'Observable','Yes');el(el(prop,'DataType'),'DataTypeIdentifier','State')
    state=el(root,'DataTypeDefinition');header(state,'State','Project-specific SI state shared with the ROS State message. No frame calibration or safety integrity is implied.')
    structure=el(el(state,'DataType'),'Structure')
    for kind,name,desc in FIELDS:value(structure,'Element',camel(name),kind,desc)
    for error in data['errors']:
        node=el(root,'DefinedExecutionError');header(node,error,'Command refused or execution interrupted: '+error+'. Inspect Status and command details; do not automatically resume motion.')
    ET.indent(root);return ET.tostring(root,encoding='unicode',xml_declaration=True)+'\n'


def build():
    data=protocol.load();pkg=model.ROOT/'ros2_ws/src'/data['transport']['ros_package'];interface=model.ROOT/'interfaces/centrifuge-cf01'
    entries=['msg/State.msg']; write(pkg/'msg/State.msg','# Generated from the shared CF01 contract; all numbers SI unless explicitly named.\n'+'\n'.join('# '+desc+'\n'+kind+' '+name for kind,name,desc in FIELDS)+'\n')
    mapping=[]
    for c in data['commands']:
        if c.get('local_only'):continue
        args=[] if c['id'] in protocol.PUBLIC else ['string control_token']
        args += [TYPES[kind][0]+' '+name for name,kind in c['arguments'].items()]
        result=['bool success','string error_code','string message','State state']
        if c['id']=='acquire':result+=['string control_token','float64 heartbeat_within_s']
        body='# '+c['description']+'\n'+'\n'.join(args)+'\n---\n'+'\n'.join(result)+'\n'
        if c['observable']:body+='---\n# -1 means no defensible completion estimate.\nfloat32 progress\nstring phase\nState state\n'
        suffix='action' if c['observable'] else 'srv';entry=suffix+'/'+c['name']+'.'+suffix; entries.append(entry);write(pkg/entry,body)
        mapping.append({'command':c['id'],'sila_command':c['name'],'ros_type':data['transport']['ros_package']+'/'+suffix+'/'+c['name'],
                        'ros_endpoint':data['transport']['ros_namespace']+'/'+c['id'],'kind':suffix})
    write(pkg/'CMakeLists.txt','cmake_minimum_required(VERSION 3.8)\nproject('+pkg.name+')\nfind_package(ament_cmake REQUIRED)\nfind_package(rosidl_default_generators REQUIRED)\nrosidl_generate_interfaces(${PROJECT_NAME}\n'+''.join('  "'+e+'"\n' for e in entries)+')\nament_export_dependencies(rosidl_default_runtime)\nament_package()\n')
    write(pkg/'package.xml','<?xml version="1.0"?>\n<package format="3">\n  <name>'+pkg.name+'</name>\n  <version>0.1.0</version>\n  <description>Generated CF01 station interfaces; no ROS server or hardware driver.</description>\n  <maintainer email="maintainers@example.invalid">SolidCraftBot contributors</maintainer>\n  <license>UNLICENSED</license>\n  <buildtool_depend>ament_cmake</buildtool_depend>\n  <build_depend>rosidl_default_generators</build_depend>\n  <exec_depend>rosidl_default_runtime</exec_depend>\n  <member_of_group>rosidl_interface_packages</member_of_group>\n  <export><build_type>ament_cmake</build_type></export>\n</package>\n')
    write(interface/'CentrifugeControl-v1_0.sila.xml',feature(data))
    model.write(interface/'request.schema.json',request_schema())
    manifest={'format':'solidcraftbot.centrifuge-interfaces/1','geometry_sha256':model.digest(model.SOURCE),'protocol_sha256':model.digest(protocol.SOURCE),
        'mapping':mapping,'state_fields':[{'name':n,'ros_type':t,'description':d} for t,n,d in FIELDS],
        'execution_rules':data['execution_rules'],'robot_pickup_sequence':data['robot_pickup_sequence'],
        'runtime':{'ros2_built':False,'ros2_executed':False,'sila_server_implemented':False,'hardware_connected':False}}
    model.write(interface/'transport-contract.json',manifest)
    print(json.dumps({'ros_definitions':len(entries),'actions':sum(c['observable'] for c in data['commands']),
        'sila_commands':len(mapping),'protocol_sha256':manifest['protocol_sha256']}))


if __name__=='__main__':build()
