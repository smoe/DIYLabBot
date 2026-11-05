"""Offline CF01 native-frame/typed-contract audit; no ROS/SiLA server is started."""
import json
import math
from pathlib import Path
import sys
import centrifuge_model as model
import centrifuge_protocol as protocol
from centrifuge_control import Simulator


def motion(context):
    native=json.loads((Path(context['out'])/'native-motion.json').read_text())
    spec=model.load();p=model.parameters(spec);source=model.expanded(spec,p);keys=protocol.frames(spec,p);maximum=0
    for sample in native['samples']:
        values=protocol.at_time(keys,sample['step']/10)['values'];model.validate_pose(source,values)
        assert sample['stopped_by_contact'] is None and sample['stopped_by_loop'] is None
        for occurrence in sample['positions']:
            group=occurrence['occurrence'].rsplit(':',1)[0];frame=occurrence['pose']
            for point in ([0,0,0],[17,0,0],[0,23,0],[0,0,31]):
                actual=[frame['origin'][i]+sum(frame[axis][i]*point[k] for k,axis in enumerate(['x','y','z'])) for i in range(3)]
                maximum=max(maximum,math.dist(actual,model.transform(source,group,list(point),values)))
    assert maximum<1e-5
    return {'passed':True,'sampled_native_poses':len(native['samples']),'rigid_groups':len(source['components']),
        'maximum_frame_error_mm':maximum,'tube_axis_travel_mm':p['lift_travel'],
        'vertical_travel_mm':p['lift_travel']*model.pocket(spec,p,1)[1][2],
        'scope':'Native joint frames versus independent shared transforms; sampled kinematics, not continuous collision/dynamic checking.'}


def smoke(transport):
    sim=Simulator();bridge=protocol.MockProtocol(sim);commands={c['id']:c for c in protocol.load()['commands']};trace=[];token=None
    for step in protocol.load()['robot_pickup_sequence']:
        if 'external' in step:
            sim.robot_clear=not ('grasps' in step['external'])
            trace.append({'external_simulated_feedback':step['external'],'robot_clear':sim.robot_clear});continue
        c=commands[step['command']];args=dict(step.get('arguments',{}))
        if c['id'] not in protocol.PUBLIC:args['control_token']=token
        name=c['id'] if transport=='ros2' else c['name']
        if transport=='sila2':args={''.join(s[:1].upper()+s[1:] for s in k.split('_')):v for k,v in args.items()}
        result=bridge.dispatch(transport,name,args)
        if c['id']=='acquire':token=result['control_token']
        if c['observable']:assert result['phase']=='succeeded'
        trace.append({'command':name,'state':result['state']})
    return {'transport':transport,'passed':True,'trace':trace,'mode':'local SDK-independent mock, no network transport'}


def main():
    context=json.loads((model.ROOT/'tmp/cf01-animation-context.json').read_text());out=Path(context['out'])
    assert context['geometry_source_sha256']==model.digest(model.SOURCE)
    assert context['protocol_source_sha256']==model.digest(protocol.SOURCE)
    result=motion(context);model.write(out/'motion-validation.json',result)
    for transport in ('ros2','sila2'):model.write(out/(transport+'-mock-smoke.json'),smoke(transport))
    print(json.dumps({'motion':result,'typed_ros_mock':True,'typed_sila_mock':True,'sila_xsd':'Run validate_centrifuge_fdl.ps1 separately, or verify_centrifuge_protocol.ps1 for the recorded combined check.'}))


if __name__=='__main__':main()
