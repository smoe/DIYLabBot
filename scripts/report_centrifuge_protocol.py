"""Freeze CF01 protocol deliverables and executed offline evidence into a report."""
import json
import re
import shutil
import zipfile
from pathlib import Path
import centrifuge_model as model
import centrifuge_protocol as protocol


def main():
    context=json.loads((model.ROOT/'tmp/cf01-animation-context.json').read_text());out=Path(context['out']);cad=Path(context['cad']);renders=Path(context['renders'])
    assert context['geometry_source_sha256']==model.digest(model.SOURCE)
    assert context['protocol_source_sha256']==model.digest(protocol.SOURCE)
    assert context['baseline_report_sha256']==model.digest(model.ROOT/'cad/centrifuge-cf01/shared-build-report.json')
    motion=json.loads((out/'motion-validation.json').read_text());sila=json.loads((out/'sila-schema-validation.json').read_text())
    assert motion['passed'] and sila['passed']
    for name in ['ros2-mock-smoke.json','sila2-mock-smoke.json']:assert json.loads((out/name).read_text())['passed']
    log=model.ROOT/'tmp/cf01-protocol-tests-final.log';test_text=log.read_text(encoding='utf-8',errors='replace')
    assert test_text.rstrip().endswith('OK');count=int(re.search(r'Ran (\d+) tests',test_text).group(1))
    shutil.copy2(log,out/'offline-tests.log')
    with zipfile.ZipFile(cad/'Centrifuge_CF01_Animated.sc') as z:native=json.loads(z.read('document.json'))
    assert any(s['name']=='CF01RobotAccess' for s in native['assembly']['studies'])
    inputs=[model.SOURCE,protocol.SOURCE,*[model.ROOT/'scripts'/n for n in ['centrifuge_model.py','centrifuge_control.py','centrifuge_protocol.py',
        'build_centrifuge_animation.py','export_centrifuge_animation_mesh.py','build_centrifuge_visual.py','build_centrifuge_interfaces.py',
        'verify_centrifuge_protocol.py','verify_centrifuge_protocol.ps1','validate_centrifuge_fdl.ps1','report_centrifuge_protocol.py']],
        *[model.ROOT/'scripts/templates'/n for n in ['centrifuge_animation.html','centrifuge_playback.FCMacro']],
        model.ROOT/'tests/test_centrifuge_protocol.py',model.ROOT/'tests/test_centrifuge.py',
        *list((model.ROOT/'exports/research/sila2-schema').glob('*.xsd'))]
    outputs=list(cad.iterdir())+list(renders.iterdir())+list(out.iterdir())
    outputs+=list((model.ROOT/'ros2_ws/src/solidcraftbot_cf01_interfaces').rglob('*'))
    outputs+=[model.ROOT/'interfaces/centrifuge-cf01'/n for n in ['CentrifugeControl-v1_0.sila.xml','transport-contract.json','request.schema.json']]
    def relative(p):return str(p.relative_to(model.ROOT)).replace('\\','/')
    hashes={relative(p):model.digest(p) for p in outputs if p.is_file() and p.name!='protocol-build-report.json'}
    result={'format':'solidcraftbot.centrifuge-protocol-build/1',**context,'passed':True,
        'source_sha256':{relative(p):model.digest(p) for p in inputs},'artifact_sha256':hashes,
        'motion_validation':motion,'offline_tests':{'passed':True,'tests':count,'log':relative(out/'offline-tests.log')},
        'sila_schema':{'passed':True,'evidence':relative(out/'sila-schema-validation.json'),'live_conformance_tested':False},
        'files':{'animation':relative(renders/'robot-access-cycle.gif'),'interactive':relative(renders/'cf01-robot-access.html'),
            'solidcraft':relative(cad/'Centrifuge_CF01_Animated.sc'),'freecad':relative(cad/'Centrifuge_CF01.FCStd'),
            'freecad_playback':relative(cad/'CF01_RobotAccess.FCMacro'),'sila_feature':'interfaces/centrifuge-cf01/CentrifugeControl-v1_0.sila.xml',
            'ros_package':'ros2_ws/src/solidcraftbot_cf01_interfaces','contract':'interfaces/centrifuge-cf01/transport-contract.json'},
        'visual_checks':{'native_gif':{'passed':True,'frames':88,'loop':True,'dimensions_px':[1000,760],'observed_open_lid_and_raised_tube':True},
            'interactive':{'passed':True,'bytes':(renders/'cf01-robot-access.html').stat().st_size,
                'checked':['closed/open assembly fit','tilted tube/pusher close-up','16 mm axial / 13.1 mm vertical lift','playback advances','timeline scrub to closed/seated end','no browser warning/error logs','no horizontal overflow at 566 px'],
                'freecad_macro_gui_executed':False}},
        'runtime':{'ros_compiled':False,'ros_executed':False,'sila_server_implemented':False,'hardware_connected':False,'physics_validated':False},
        'limitations':['Geometry is reused from the checked native geometry revision; this report adds protocol/motion evidence.',
            'No physical robot grasp/removal is shown; the animation returns the same tube to its seat.',
            'Native frame comparison and pose constraints are sampled; no new continuous collision, gripper or dynamics validation.',
            'ROS interface definitions and SiLA FDL are generated; live network servers, TLS/discovery and device I/O remain unimplemented.',
            'Native SolidCraft GIF/study executed. FreeCAD macro is generated but its GUI has not been run.',
            'Mock speed/feedback/qualification never establish a physical 16000 x g capability.']}
    model.write(out/'protocol-build-report.json',result);model.write(model.ROOT/'cad/centrifuge-cf01/protocol-build-report.json',result)
    print(json.dumps({'passed':True,'revision':context['revision'],'tests':count,'native_pose_samples':motion['sampled_native_poses'],
        'artifact_count':len(hashes),'gif':result['files']['animation'],'interactive':result['files']['interactive']}))


if __name__=='__main__':main()
