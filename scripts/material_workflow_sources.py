"""Freeze existing preparation plans for the common synthetic material lifecycle.

Preparation recipes remain in their existing sources. Initial fixture quantities
are explicit declarations; abstract phase volumes never become reagent stocks.
"""

import copy
from pathlib import Path

import cutrun_preparation
import extraction_preparation
from manual_tasks import TaskError, digest, encoded
from manual_workflow import positive, text
import material_ledger


ROOT = Path(__file__).resolve().parents[1]
FORMAT = 'solidcraftbot.material-workflow-definition/1'
RUNTIME = (
    'scripts/material_workflow.py',
    'scripts/material_workflow_sources.py',
    'scripts/material_ledger.py',
    'scripts/run_material_lifecycle.py',
    'scripts/manual_workflow.py',
    'scripts/manual_tasks.py',
    'scripts/assembly_model.py',
    'scripts/robot_spec.py',
)
PREPARATIONS = {'cutrun': cutrun_preparation, 'extraction': extraction_preparation}


def require(condition, message):
    if not condition:
        raise TaskError(message)


def _bindings(domain, plan):
    inputs, products = [], []
    if domain == 'cutrun':
        branches = {branch['id']: branch for branch in plan['branches']}
        for edge in plan['lineage']:
            branch = branches[edge['id']]
            inputs.append({'material_id': edge['input_material_id'], 'vessel_id': edge['input_vessel_id'],
                           'role': branch['role'], 'origin_id': None})
            products.append({'material_id': edge['product_material_id'], 'vessel_id': edge['product_vessel_id'],
                             'role': branch['role'], 'parent_material_id': edge['input_material_id']})
    else:
        for edge in plan['lineage']:
            inputs.append({'material_id': edge['input_id'], 'vessel_id': edge['input_vessel_id'],
                           'role': edge['analyte'], 'origin_id': edge['origin_id']})
            products.append({'material_id': edge['product_id'], 'vessel_id': edge['product_vessel_id'],
                             'role': edge['analyte'], 'parent_material_id': edge['input_id']})
    return inputs, products


def load(domain, source=None, *, materials, vessels, task_deadline_s=3600):
    """Return a detached, source-bound definition for material primitives only.

    ``source`` is an existing E1 preparation profile, never a caller-supplied
    compiled plan whose provenance could be self-reported. An incomplete E1
    recipe may still supply material bindings for an explicitly synthetic E2
    fixture; the frozen plan keeps all its blockers and execution prohibition.
    """
    require(isinstance(domain, str) and domain in PREPARATIONS, 'Explicit cutrun or extraction domain required')
    positive(task_deadline_s, 'synthetic material task deadline')
    module = PREPARATIONS[domain]
    plan = module.compile_plan() if source is None else module.compile_plan(source)
    require(plan['mode'] == 'preparation_only' and plan['synthetic'] is True
            and plan['execution_ready'] is False, 'Effect-free synthetic preparation plan required')
    initial_materials, initial_vessels = copy.deepcopy(materials), copy.deepcopy(vessels)
    inventory = material_ledger.initial_inventory(initial_materials, initial_vessels)
    inputs, products = _bindings(domain, plan)
    declared = {item['material_id']: item for item in inputs}
    present = inventory['materials']
    require(set(declared) <= set(present), 'Every declared preparation input must be provided explicitly')
    for identity, binding in declared.items():
        material = present[identity]
        require(material['kind'] in {'sample', 'control'} and material['vessel_id'] == binding['vessel_id'],
                'Preparation input identity/vessel binding mismatch: ' + identity)
        if binding['origin_id'] is not None:
            require(material['origin_id'] == binding['origin_id'], 'Preparation origin binding mismatch: ' + identity)
    require(all(present[identity]['kind'] == 'reagent' for identity in set(present) - set(declared)),
            'Additional initial materials must be explicitly issued reagent aliquots')
    for product in products:
        require(product['material_id'] not in present, 'A planned product cannot be introduced as an initial stock')
        require(product['vessel_id'] in inventory['vessels'], 'Declared product vessel must be provided explicitly')
        require(not any(material['vessel_id'] == product['vessel_id'] for material in present.values()),
                'Declared product vessel must initially be empty')
    require(len({item['material_id'] for item in inputs + products}) == len(inputs) + len(products),
            'Preparation inputs and products must have distinct material identities')

    allocations = [{'material_id': item['id'], 'vessel_id': item['vessel_id'],
                    'declaration_sha256': digest(encoded(item).encode())}
                   for item in initial_materials if item['kind'] == 'reagent']
    pins = copy.deepcopy(plan['source_files_sha256'])
    for name in RUNTIME:
        path = ROOT / name
        require(path.is_file(), 'Missing material lifecycle runtime source: ' + name)
        pins[name] = digest(path.read_bytes())
    for name, checksum in pins.items():
        path = (ROOT / name).resolve()
        require(path.is_relative_to(ROOT.resolve()) and path.is_file()
                and digest(path.read_bytes()) == checksum, 'Material preparation source changed: ' + name)
    profile = {'id': 'SYN.Material.' + plan['id'], 'mode': 'synthetic_only',
               'parameters': {'task_deadline_s': task_deadline_s}}
    definition = {'format': FORMAT, 'domain': domain, 'profile': profile,
                  'clock_mode': 'synthetic_events/1', 'preparation_plan': copy.deepcopy(plan),
                  'declared_inputs': inputs, 'products': products,
                  'initial_materials': initial_materials, 'initial_vessels': initial_vessels,
                  'material_allocations': allocations, 'runtime_source_files': list(RUNTIME),
                  'source_files_sha256': pins}
    definition['effective_profile_sha256'] = digest(encoded({
        'domain': domain, 'profile': profile, 'preparation_sha256': plan['effective_preparation_sha256'],
        'materials': initial_materials, 'vessels': initial_vessels}).encode())
    return definition
