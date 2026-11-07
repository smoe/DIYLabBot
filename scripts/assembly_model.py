"""Shared source references and parameterized instances; no CAD dependencies."""
import ast
import copy
import json
from pathlib import Path
import re
import robot_spec as robot

ROOT = robot.ROOT


def project_path(value, root=ROOT):
    path = (root / value).resolve()
    if Path(value).is_absolute() or not path.is_relative_to(root.resolve()):
        raise ValueError('Assembly path must remain relative to project: '+str(value))
    return path


def validate_reference(ref, root=ROOT):
    if not isinstance(ref,dict): raise ValueError('Expected assembly reference object')
    if not isinstance(ref.get('source'),str): raise ValueError('Expected assembly source path')
    if set(ref)-{'source','source_sha256','report','case'} or 'source' not in ref:
        raise ValueError('Unsupported assembly reference fields')
    path = project_path(ref['source'], root)
    if not path.is_relative_to((root/'model').resolve()) or path.suffix != '.json':
        raise ValueError('Assembly source must be a model JSON file')
    if 'source_sha256' in ref:
        if not re.fullmatch('[0-9a-f]{64}',ref['source_sha256']) or robot.digest(path)!=ref['source_sha256']:
            raise ValueError('Pinned assembly source changed: '+ref['source'])
    if 'report' in ref: project_path(ref['report'], root)
    if 'case' in ref and (not isinstance(ref['case'],str) or not ref['case']):
        raise ValueError('Assembly case must be a nonempty name')
    return path


def parameter_variant(spec, overrides=None, context=None):
    """Materialize driving parameters in their declared units; keep derived expressions."""
    result = copy.deepcopy(spec)
    definitions = result['parameters']
    for name, expression in (overrides or {}).items():
        if name not in definitions: raise ValueError('Unknown parameter override: '+name)
        definition = definitions[name]
        if 'unit' not in definition: raise ValueError('Instance parameter needs an explicit unit: '+name)
        if any(isinstance(n,ast.Name) for n in ast.walk(ast.parse(str(definition['expression']),mode='eval'))):
            raise ValueError('Override driving parameter, not derived '+name)
        if type(expression) not in (str,int,float): raise ValueError('Expected numeric parameter or expression: '+name)
        try: value = robot.evaluate(expression, context or {})
        except KeyError as error: raise ValueError('Undefined instance parameter expression: '+name) from error
        for key in ['range','range_mm']:
            if key in definition and not definition[key][0]<=value<=definition[key][1]:
                raise ValueError('Override outside declared range: '+name)
        definition['expression'] = value
    robot.parameters(result)  # Check coupled expressions, finite values and cycles.
    return result


def load_instance(provider, ref, overrides=None, context=None):
    path = validate_reference(ref)
    variant = parameter_variant(provider.load(path), overrides, context)
    if provider is robot: return robot.validate(variant)
    provider.parameters(variant)  # Apply assembly-specific geometric constraints.
    return variant


def resolve_artifact(ref, root=ROOT):
    """Resolve a named case via its current checked report, then verify artifact bytes."""
    source = validate_reference(ref, root)
    report = json.loads(project_path(ref['report'],root).read_text(encoding='utf-8'))
    if not report.get('passed') or report.get('source_sha256',report.get('spec_sha256')) != robot.digest(source):
        raise ValueError('Assembly build report is missing, failed or stale: '+ref['source'])
    if 'cases' in report:
        cases = [c for c in report['cases'] if c['id']==ref.get('case','default')]
        if len(cases)!=1 or not cases[0].get('passed'): raise ValueError('Checked assembly case not found')
        case = cases[0]
        path, digest = case['files']['freecad'],case['artifact_sha256']['freecad']
    else:
        if ref.get('case','default')!='default': raise ValueError('Arm build has only a default case')
        path, digest = report['artifacts']['freecad'],report['artifact_sha256']['freecad']
    artifact = project_path(path,root)
    if robot.digest(artifact)!=digest: raise ValueError('Assembly artifact changed after validation')
    return artifact


def validate_instance(item, context=None):
    allowed = {'id','asset','host','xyz','yaw_deg','overrides','pose','variant','joints_deg','exclude_bodies','riser_height'}
    if set(item)-allowed or not {'id','asset','xyz','yaw_deg'}<=set(item):
        raise ValueError('Unsupported assembly instance fields')
    if any(not isinstance(item[k],str) or not item[k] for k in ['id','asset']):
        raise ValueError('Instance needs stable ID and asset reference')
    if not isinstance(item['xyz'],list) or len(item['xyz'])!=3:
        raise ValueError('Instance requires three position coordinates in mm')
    for value in item['xyz']:
        if type(value) not in (int,float,str): raise ValueError('Invalid position coordinate')
        robot.evaluate(value,context or {})
    if type(item['yaw_deg']) not in (int,float): raise ValueError('Instance yaw must be numeric degrees')
    robot.evaluate(item['yaw_deg'],{})
    if not isinstance(item.get('overrides',{}),dict): raise ValueError('Expected instance parameter overrides')
    if 'joints_deg' in item:
        q=item['joints_deg']
        if not isinstance(q,list) or len(q)!=6 or any(type(v) not in (int,float) for v in q):
            raise ValueError('Arm instance requires six numeric joint angles in degrees')
        for value in q: robot.evaluate(value,{})
    for field in ['host','pose','variant']:
        if field in item and (not isinstance(item[field],str) or not item[field]):
            raise ValueError('Expected nonempty instance '+field)
    if 'exclude_bodies' in item and (not isinstance(item['exclude_bodies'],list) or any(not isinstance(v,str) for v in item['exclude_bodies'])):
        raise ValueError('Expected body IDs to exclude')
    return item
