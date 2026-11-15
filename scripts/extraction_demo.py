"""Explicit fictional observations shared by synthetic extraction/TapeStation demos.

Nothing in this driver operates an instrument or predicts extraction yield.
The workflow validator never calls these positive-observation helpers.
"""
import copy
import uuid

import material_ledger as ledger
from manual_tasks import TaskError, digest
from tapestation_results import synthetic_report

REASON = 'Explicitly invented fixture observation; no extraction, physical measurement or hardware execution.'


def actual_inputs(state, intent_id):
    """Invent full known consumption only in this opt-in test driver."""
    result = []
    for item in state['bookings'][intent_id]['request']['inputs']:
        quantity = copy.deepcopy(item['quantity'])
        if item['consume_all']:
            quantity = {key: value for key, value in ledger.remaining(
                state, item['material_id'], exclude_intent=intent_id).items() if key in {'value', 'unit'}}
        result.append({'material_id': item['material_id'], 'quantity': quantity})
    return result


def phase_observations(step):
    result = {key: True for key in step['required_checks']}
    params = step['parameters']
    if 'duration_s' in params:
        result['duration_s'] = params['duration_s']
    if 'temperature_min_deg_c' in params:
        result['temperature_deg_c'] = (params['temperature_min_deg_c'] + params['temperature_max_deg_c']) / 2
    if 'rcf_min_x_g' in params:
        result['rcf_x_g'] = params['rcf_min_x_g']
    if 'inversion_count' in params:
        result['inversion_count'] = params['inversion_count']
    return result


def perform_phase(flow, sample_id, step, *, actor_id, pause_before_confirmation=False):
    intent = flow.run_id + '.Phase.' + step['id']
    flow.act('begin_phase', actor_id, sample_id=sample_id, phase_id=step['id'], intent_id=intent)
    if pause_before_confirmation:
        return False
    if step['parameters'].get('duration_s'):
        flow.act('advance_time', actor_id, seconds=step['parameters']['duration_s'])
    state = flow.state
    flow.act('confirm_phase', actor_id, intent_id=intent,
             actual_inputs=actual_inputs(state, intent) if intent in state['bookings'] else [],
             actual_outputs=copy.deepcopy(step.get('fixture_actual_outputs', [])),
             observations=phase_observations(step), reason=REASON)
    return True


def run_tapestation(flow, definition, *, actor_id, pause_after=None):
    """Supply explicit fictional TapeStation observations on an existing Root."""
    identity = flow.run_id
    qc = definition['execution']['qc']
    equilibration_s = qc['parameters']['buffer_equilibration_s']
    flow.act('advance_time', actor_id, seconds=equilibration_s)
    flow.act('confirm_tapestation_ready', actor_id,
             observations={**{key: True for key in qc['required_checks']}, 'buffer_equilibration_s': equilibration_s},
             reason=REASON)
    for role in ('ladder', 'sample'):
        intent = flow.run_id + '.QC.' + role
        flow.act('begin_qc_preparation', actor_id, role=role, intent_id=intent)
        duration = qc['parameters']['mix_duration_s'] + qc['parameters']['spin_duration_s']
        flow.act('advance_time', actor_id, seconds=duration)
        flow.act('confirm_qc_preparation', actor_id, intent_id=intent,
                 actual_inputs=actual_inputs(flow.state, intent),
                 actual_outputs=copy.deepcopy(qc[role]['effect']['fixture_actual_outputs']),
                 observations={'capped': True, 'mixed': True, 'spun_down': True,
                               'mix_duration_s': qc['parameters']['mix_duration_s'],
                               'mix_rpm': qc['parameters']['mix_rpm'],
                               'spin_duration_s': qc['parameters']['spin_duration_s']}, reason=REASON)
    flow.act('begin_tapestation', actor_id,
             instrument_run_id=identity + '.TS.Run', analysis_id=identity + '.TS.Analysis',
             measurement_id=identity + '.TS.Measurement', screen_tape_id=qc['screen_tape_id'],
             lane_id=qc['sample']['lane_id'], ladder_lane_id=qc['ladder']['lane_id'])
    flow.act('confirm_tapestation_loaded', actor_id,
             observations={**flow.expected_tapestation_loading(), 'sample_loaded': True,
                           'ladder_loaded': True, 'identities_confirmed': True}, reason=REASON)
    if pause_after == 'tapestation_loaded':
        return flow.report()
    flow.act('confirm_tapestation_run_complete', actor_id,
             observations={'run_complete': True, 'ladder_accepted': True,
                           'instrument_run_id': identity + '.TS.Run',
                           'analysis_id': identity + '.TS.Analysis'}, reason=REASON)
    artifact = synthetic_report(flow.expected_tapestation(), din=8.0, fragment_size_bp=30000.0)
    flow.act('import_results', actor_id, artifact=artifact,
             file_name='synthetic-tapestation.json', origin='synthetic_export')
    flow.act('review_tapestation', actor_id, decision='accept', artifact_sha256=digest(artifact), reason=REASON)
    for material_id, item in flow.state['inventory']['materials'].items():
        if item['disposition'] not in {'consumed', 'discarded'}:
            disposition = 'retained' if item['kind'] in {'product', 'reagent'} else 'discarded'
            flow.act('set_disposition', actor_id, material_id=material_id, disposition=disposition, reason=REASON)
    flow.act('confirm_inventory', actor_id, observations=flow.inventory_observations())
    flow.act('release', actor_id, workspace_clear=True)
    return flow.report()


def run_demo(journal, *, workflow_class, definition_loader, run_prefix, actor_id,
             run_id=None, source=None, pause_after=None):
    """Create a fresh synthetic fixture, never resume or reset an existing run."""
    definition = definition_loader(source)
    steps = definition['execution']['steps']
    markers = {step['id'] for step in steps}
    markers.update('before_confirm:' + step['id'] for step in steps)
    markers.update({'extracted', 'tapestation_loaded'})
    if pause_after is not None and pause_after not in markers:
        raise TaskError('Unknown demo pause marker; use a declared phase or TapeStation boundary')
    identity = run_id or run_prefix + uuid.uuid4().hex[:12]
    flow = workflow_class.create(journal, source=source, run_id=identity)
    try:
        flow.act('accept_inventory', actor_id, observations=flow.inventory_observations())
        flow.act('workspace_clear', actor_id, confirmed=True)
        flow.act('claim', actor_id)
        for sample_id in definition['execution']['samples']:
            for step in steps:
                if not perform_phase(flow, sample_id, step,
                                     pause_before_confirmation=pause_after == 'before_confirm:' + step['id'], actor_id=actor_id):
                    return flow.report()
                if pause_after == step['id']:
                    return flow.report()
        if pause_after == 'extracted':
            return flow.report()
        return run_tapestation(flow, definition, actor_id=actor_id, pause_after=pause_after)
    finally:
        flow.close()
