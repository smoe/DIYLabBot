"""Resolve checked immutable geometry for a new CF01 motion, never old motion QA.

The cache contains construction-local geometry. Its old world snapshot must be
normalized with the *old* trajectory before applying the new program transforms.
"""
import copy
import hashlib
import json
from pathlib import Path

import centrifuge_robot_pickup as pickup

ROOT=pickup.ROOT
DEFAULT_REPORT=ROOT/'cad/centrifuge-cf01/robot-pickup-build-report.json'
GEOMETRY_CODE={
    'scripts/build_centrifuge_robot_pickup_freecad.py','scripts/build_centrifuge_freecad.py','scripts/centrifuge_robot_pickup.py',
    'scripts/centrifuge_model.py','scripts/centrifuge_mechanisms.py','scripts/robot_spec.py',
    'scripts/robot_components.py','scripts/robot_cameras.py','scripts/servo_mounting_design.py',
    'scripts/synthetic_workspace.py','scripts/furniture_model.py','scripts/rack_slots.py',
    'scripts/freecad/solidcraftbot_freecad.py','scripts/assembly_model.py'}


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def project(path):
    path=Path(path)
    path=(ROOT/path).resolve()
    if not path.is_relative_to(ROOT):raise ValueError('Geometry inputs must stay in the project')
    return path


def load_bundle(report_path=DEFAULT_REPORT):
    path=project(report_path);report=read(path)
    if report.get('format')!='solidcraftbot.centrifuge-robot-pickup-build/1' or report.get('passed') is not True:
        raise ValueError('A passed source-bound pickup geometry build is required')
    # The combined build predates its mechanism-helper pin. Resolve that pin
    # from the original station build, linked through the exact native input.
    station_native=project(report['centrifuge_native'])
    station_path=project(Path('exports/generated')/station_native.parent.name/'build-report.json')
    station=read(station_path)
    station_sha=report['native_input_sha256'].get(str(station_native))
    cases=[case for case in station.get('cases',[]) if project(case['files']['freecad'])==station_native]
    if (station.get('format')!='solidcraftbot.centrifuge-build/1' or station.get('passed') is not True
            or len(cases)!=1 or cases[0].get('passed') is not True
            or not station_sha or cases[0]['artifact_sha256']['freecad']!=station_sha
            or sha(station_native)!=station_sha):
        raise ValueError('Source-bound original station geometry evidence required')
    hashes={**report['source_files_sha256']}
    for sources in [report['solidcraft_snapshots']['source_files_sha256'],station['source_files_sha256']]:
        for key,value in sources.items():
            if key in hashes and hashes[key]!=value:raise ValueError('Inconsistent geometry source pin: '+key)
            hashes[key]=value
    selected={name:digest for name,digest in hashes.items()
              if name.startswith(('model/','cad/vendor/')) or name in GEOMETRY_CODE}
    required=GEOMETRY_CODE|{'model/robot.json','model/centrifuge-cf01.shared.json',
              'model/centrifuge-cf01.robot-pickup.shared.json'}
    if not required<=selected.keys():raise ValueError('Incomplete geometry source evidence')
    for name,digest in selected.items():
        if sha(project(name))!=digest:raise ValueError('Geometry source changed; rebuild the base: '+name)
    out=project(report['out']);cad=project(report['cad'])
    files={'mesh':out/'scene-mesh.json','old_scene':out/'scene-source.json',
           'old_trajectory':out/'trajectory.json','native':cad/'CF01_Robot_Closed.FCStd'}
    for name,file in files.items():
        relative=str(file.relative_to(ROOT))
        if report['artifact_sha256'].get(relative)!=sha(file):raise ValueError('Frozen geometry artifact changed: '+name)
    mesh=read(files['mesh']);old_scene=read(files['old_scene']);old_data=read(files['old_trajectory'])
    if old_data['scene_sha256']!=selected[str(pickup.SOURCE.relative_to(ROOT))]:
        raise ValueError('Old normalization trajectory does not match its geometry source')
    return {'files':files,'mesh':mesh,'old_scene':old_scene,'old_trajectory':old_data,
            'evidence':{'report':str(path.relative_to(ROOT)),'report_sha256':sha(path),
                'station_report':str(station_path.relative_to(ROOT)),'station_report_sha256':sha(station_path),
                'station_native':str(station_native.relative_to(ROOT)),'station_native_sha256':station_sha,
                'geometry_sources_sha256':selected,
                'artifacts':{name:{'path':str(file.relative_to(ROOT)),'sha256':sha(file)} for name,file in files.items()},
                'scope':'Reuse of unchanged source-bound construction geometry only. Old trajectory, clearance and motion reports are not evidence for the new program.'}}


def sample_body_slot(identity):
    for prefix in ('Tube','ClosedCap'):
        tail=identity[len(prefix):] if identity.startswith(prefix) else ''
        if len(tail)==2 and tail.isdigit() and 1<=int(tail)<=12:return int(tail)
    return None


def load_instruments(report_path='cad/synthetic-lab-scene/shared-build-report.json'):
    """Resolve only unchanged instrument geometry, not historical path evidence.

    The selected native snapshot contains world-placed, source-selected instrument
    poses. It is deliberately separate from the old CF01 normalization snapshot.
    """
    import instrument_concept as instruments
    import synthetic_lab_scene as layout
    path=project(report_path);report=read(path)
    if report.get('format')!='solidcraftbot.synthetic-lab-scene/1' or report.get('passed') is not True:
        raise ValueError('A passed synthetic laboratory geometry build is required')
    code={'scripts/synthetic_lab_scene.py','scripts/build_synthetic_lab_scene_freecad.py',
          'scripts/instrument_concept.py','scripts/assembly_model.py',
          'scripts/synthetic_workspace.py','scripts/furniture_model.py',
          'scripts/freecad/solidcraftbot_freecad.py'}
    selected={name:digest for name,digest in report['source_files_sha256'].items()
              if name.startswith('model/') or name in code}
    required=code|{'model/nanodrop-concept.shared.json','model/qubit-4-concept.shared.json'}
    if not required<=selected.keys():raise ValueError('Incomplete instrument geometry source evidence')
    for name,digest in selected.items():
        if sha(project(name))!=digest:raise ValueError('Instrument geometry source changed: '+name)
    snapshot=next((item for item in report['snapshots'] if item['id']=='Grasp'),None)
    if not snapshot or snapshot.get('passed') is not True:
        raise ValueError('Passed Grasp instrument snapshot required')
    native=project(snapshot['files']['freecad'])
    if sha(native)!=snapshot['artifact_sha256']['freecad']:
        raise ValueError('Frozen instrument native artifact changed')
    entries=layout.instrument_instances();manifest={};poses={}
    for entry in entries:
        item=entry['instance'];identity=item['id'];source=report['source_bindings'].get(identity)
        if source!={'source':item['source']['source'],
                    'source_sha256':sha(project(item['source']['source']))}:
            raise ValueError('Instrument instance/source binding changed: '+identity)
        if item['matrix']!=report['instance_poses'].get(identity):
            raise ValueError('Instrument placement changed: '+identity)
        for body in instruments.expanded(entry['spec'],entry['parameters'])['bodies']:
            key=identity+'.'+body['id']
            manifest[key]={'instance':identity,'component':body['component'],
                           'role':body['role'],'appearance':body['appearance']}
        poses[identity]={'hinge_deg':instruments.pose(entry['spec'],entry['parameters'])['Hinge'],
                         'hinge_limits_deg':[0.,entry['parameters']['max_open']],
                         'asset':item['asset']}
    recorded={item['instance']+'.'+item['source_body'] for item in report['body_manifest']
              if item['instance'] in poses}
    if recorded!=set(manifest):raise ValueError('Incomplete instrument body manifest')
    return {'native':native,'entries':entries,'manifest':manifest,
            'evidence':{'report':str(path.relative_to(ROOT)),'report_sha256':sha(path),
                'geometry_sources_sha256':selected,'native':str(native.relative_to(ROOT)),
                'native_sha256':sha(native),'body_count':len(manifest),'poses':poses,
                'scope':'Unchanged native instrument geometry and placements only; old reachability and motion results do not validate the new unloading path.'}}


def mesh_for_program(bundle,program):
    """Regroup the twelve existing bodies, keeping every vertex and identity."""
    mesh=copy.deepcopy(bundle['mesh']);samples={sample['rotor_slot']:sample for sample in program['samples']}
    for body in mesh['bodies']:
        slot=sample_body_slot(body['id'])
        if slot is not None:
            body['group']='Tube%02d'%slot
            body['sample_id']=samples[slot]['id']
    mesh['unload_program']=program
    mesh['trajectory']={'scene_sha256':program['source_sha256'],'duration_s':program['duration_s'],
                        'samples':program['preview_samples']}
    mesh['scene']=program['scene']
    mesh['rack_batch']=None
    old=pickup.SceneEvaluator(bundle['old_scene'],bundle['old_trajectory'])
    # Matrices used by the legacy renderer are still required for arm frames.
    mesh['robot_frames']=old.kin.frames;mesh['arm_base']=old.kin.base
    mesh['tube_attachment_from_tool']=old.attachment;mesh['tube_seated_matrix']=old.seated_tube
    scene=program['scene'];spec=pickup.cf.load();parameters=pickup.cf.parameters(spec)
    mesh['rack_frame']=pickup.rack_geometry(scene,parameters)['frame']
    mesh['rack_slots']=pickup.rack_geometry(scene,parameters)['slots']
    mesh['tube_grip_references']={}
    for slot in range(1,13):
        bottom,axis=pickup.cf.pocket(spec,parameters,slot)
        mesh['tube_grip_references']['Tube%02d'%slot]=pickup.cf.plus(bottom,axis,parameters['tube_length']-8)
    mesh['pickup_axis']=pickup.cf.pocket(spec,parameters,1)[1]
    mesh['grip_reference']=mesh['tube_grip_references']['Tube01']
    from build_centrifuge_robot_pickup_visual import compact_mesh
    return compact_mesh(mesh)
