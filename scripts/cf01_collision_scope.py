"""Bind standalone CF01 collision reports to their actual workspace coverage."""
import hashlib
import json
from pathlib import Path

import assembly_model as assembly
import centrifuge_model as cf
import synthetic_workspace as workspace

ROOT=cf.ROOT
OVERALL_REPORT='cad/synthetic-lab-scene/shared-build-report.json'


def trajectory_signature(data):
    return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def collision_scope(scene,data,overall_report=OVERALL_REPORT):
    spatial=workspace.load(assembly.validate_reference(scene['environment']))
    included=['Arm','CF01','Rack']
    excluded=[{'instance_id':identity,'source':device['source']} for identity,device in sorted(spatial['devices'].items()) if identity not in included]
    reference={'path':str(overall_report),'status':'missing','current_trajectory_checked':False}
    signature=trajectory_signature(data)
    report_path=(ROOT/overall_report).resolve()
    try:
        if not report_path.is_relative_to(ROOT):raise ValueError('Overall report must stay in the project')
        if report_path.is_file():
            raw=report_path.read_bytes();report=json.loads(raw)
            reference['sha256']=hashlib.sha256(raw).hexdigest()
            if report.get('format')!='solidcraftbot.synthetic-lab-scene/1' or report.get('passed') is not True:
                raise ValueError('A passed overall scene report is required')
            if report.get('instrument_motion_validation',{}).get('passed') is not True:
                raise ValueError('Overall instrument-motion check is absent or failed')
            sources=report['source_files_sha256']
            for path in workspace.source_dependencies(spatial):
                key=str(path.relative_to(ROOT))
                if sources.get(key)!=cf.digest(path):raise ValueError('Overall workspace source is stale: '+key)
            for name,checksum in sources.items():
                path=(ROOT/name).resolve()
                if not path.is_relative_to(ROOT) or not path.is_file() or cf.digest(path)!=checksum:
                    raise ValueError('Overall report source changed: '+name)
            if not {device['instance_id'] for device in excluded}<=set(report['source_bindings']):
                raise ValueError('Overall report does not cover every excluded workspace device')
            trajectory=report['cf01_trajectory'];path=(ROOT/trajectory['path']).resolve()
            if not path.is_relative_to(ROOT):raise ValueError('Trajectory must stay in the project')
            raw=path.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=trajectory['sha256']:
                raise ValueError('Overall checked trajectory artifact changed')
            if trajectory['semantic_sha256']!=signature or trajectory_signature(json.loads(raw))!=signature:
                raise ValueError('Overall report checked a different CF01 trajectory')
            if report['instrument_motion_validation']['cf01_path_samples']!=len(data['samples']):
                raise ValueError('Overall report trajectory sample coverage differs')
            reference.update(status='current',current_trajectory_checked=True)
    except (OSError,ValueError,KeyError,TypeError) as error:
        reference.update(status='unverified',reason=str(error))
    return {'modeled_core_workspace_devices':included,'modeled_reference_surface':True,
            'excluded_workspace_devices':excluded,'trajectory_semantic_sha256':signature,
            'standalone_models_all_workspace_devices':not excluded,'overall_report':reference,
            'overall_workspace_validation_required':bool(excluded) and not reference['current_trajectory_checked'],
            'limits':'The standalone scene contains the listed core devices and reference surface. Each subreport scope/coverage states its actual checked pairs; modeled bodies do not imply every pair was checked. Additional devices require a source-current overall report for this exact trajectory; discrete checks are not continuous swept-volume certification.'}
