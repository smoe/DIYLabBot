"""Synthetic NanoDrop adapter on the common manual workflow core."""
import uuid
from pathlib import Path

from manual_tasks import Journal, TaskError, digest, encoded
from manual_workflow import (ManualWorkflow, ObservationError, text, positive, keys,
                             original_location, inventory_observations, compile_profile)
from nanodrop_csv import parse_report

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'model/nanodrop-manual.synthetic.json'
TERMINAL = {'completed', 'cancelled'}
STEPS = ['rack_ready', 'workspace_clear', 'claim', 'blank', 'begin_measurement',
         'confirm_measurement', 'place', 'import_results', 'review_results', 'release']


def load_profile(source=SOURCE):
    definition = compile_profile(source, 'solidcraftbot.nanodrop-manual-profile/1', [
        'scripts/nanodrop_manual.py', 'scripts/nanodrop_csv.py', 'scripts/manual_results.py',
        'scripts/run_nanodrop_manual.py', 'scripts/manual_workflow_cli.py', 'model/nanodrop-manual.schema.json'])
    protocol = definition['protocol']
    if (protocol['format'] != 'solidcraftbot.nanodrop-manual-protocol/1'
            or protocol['method'] != 'dsDNA' or protocol['capability'] != 'microvolume_absorbance'
            or protocol['steps'] != STEPS or protocol['return_policy'] != 'original_place'):
        raise TaskError('Unsupported NanoDrop protocol contract')
    if protocol['parameters'] != {
            'sample_volume_ul': {'unit': 'uL', 'exclusive_minimum': 0},
            'task_deadline_s': {'unit': 's', 'exclusive_minimum': 0}}:
        raise TaskError('Unsupported parameter contract')
    if definition['instrument_type']['identity_column'] != 'Sample Name':
        raise TaskError('Unsupported report identity column')
    return definition


class Workflow(ManualWorkflow):
    STATE_FORMAT = 'solidcraftbot.nanodrop-manual-state/1'
    REPORT_FORMAT = 'solidcraftbot.nanodrop-manual-report/1'
    STEPS = STEPS
    SOURCE = SOURCE
    RUN_PREFIX = 'SYN-ND-'
    PREPLAN_MEASUREMENTS = True
    load_profile = staticmethod(load_profile)
    @staticmethod
    def _initial_extra(run_id, definition):
        return {'blanks': {}, 'active_blank': None, 'pending_measurement': None}

    @staticmethod
    def card_extra(state):
        return {'active_blank': state['active_blank'], 'pending_measurement': state['pending_measurement']}

    def _blank(self, state, actor_id, reference_id, cleaned):
        self._claimed(state)
        if state['pending_measurement']:
            raise TaskError('Resolve pending measurement before a new blank')
        text(reference_id, 'synthetic blank reference')
        self._require(cleaned, 'Blank cleanup confirmation missing')
        blank_id = state['run_id'] + '.A01.B%03d' % (len(state['blanks']) + 1)
        state['blanks'][blank_id] = {'reference_id': reference_id,
                                     'actor_id': actor_id, 'evidence': 'synthetic_input'}
        state['active_blank'] = blank_id

    def _begin_measurement(self, state, actor_id, sample_id, measurement_id):
        self._claimed(state)
        sample = self._sample(state, sample_id)
        if (state['pending_measurement'] or not state['active_blank']
                or sample['location'] != {'kind': 'operator', 'actor_id': actor_id}):
            raise TaskError('Blank, held original vessel and no pending measurement required')
        if measurement_id != state['planned_measurements'][sample_id] or measurement_id in state['measurements']:
            raise TaskError('Unexpected or already completed measurement id')
        self._check_withdrawal(state, sample_id)
        state['pending_measurement'] = {'intent_id': uuid.uuid4().hex, 'sample_id': sample_id,
                                        'measurement_id': measurement_id,
                                        'blank_id': state['active_blank']}
        sample['volume_uncertain'] = True

    def _finish_measurement(self, state, intent_id, observed_sample_id, volume_ul, cleaned,
                            deviation_reason=None):
        pending = state['pending_measurement']
        if not pending or pending['intent_id'] != intent_id:
            raise TaskError('Stale or unknown measurement intent')
        if observed_sample_id != pending['sample_id']:
            raise ObservationError('Measurement sample identity mismatch')
        self._require(cleaned, 'Measurement cleanup confirmation missing')
        sample = state['samples'][pending['sample_id']]
        self._consume(state, pending['sample_id'], volume_ul, deviation_reason)
        measurement_id = pending['measurement_id']
        state['measurements'][measurement_id] = {
            **pending, 'parent_sample_id': pending['sample_id'],
            'source_vessel_id': sample['vessel_id'], 'aliquot_id': measurement_id + '.Aliquot',
            'withdrawn_volume': {'value': volume_ul, 'unit': 'uL'},
            'disposition': 'discarded_after_synthetic_cleanup',
            'sop': state['definition']['protocol']['sop'], 'deviation_reason': deviation_reason,
            'actor_id': state['actor_id'], 'evidence': 'synthetic_input'}
        state['pending_measurement'] = None

    def _confirm_measurement(self, state, actor_id, intent_id, observed_sample_id,
                             volume_ul, cleaned, deviation_reason=None):
        self._claimed(state)
        self._finish_measurement(state, intent_id, observed_sample_id, volume_ul, cleaned, deviation_reason)

    def _before_import(self, state):
        if state['pending_measurement'] or set(state['measurements']) != set(state['planned_measurements'].values()):
            raise TaskError('Confirm all planned measurements before importing the batch')

    def _parse_import(self, state, artifact, origin):
        issues, report = [], None
        try:
            report = parse_report(artifact, state['definition']['instrument_type']['identity_column'])
            expected = set(state['planned_measurements'].values())
            names = [row['measurement_id'] for row in report['rows']]
            sample_names = [name for name in names if name not in state['blanks']]
            if len(set(names)) != len(names):
                issues.append('duplicate_measurement')
            if set(sample_names) - expected:
                issues.append('foreign_measurement')
            if expected - set(sample_names):
                issues.append('missing_measurement')
            metadata = report['metadata']
            if metadata.get('application', state['definition']['protocol']['method']) != state['definition']['protocol']['method']:
                issues.append('method_mismatch')
            serial = state['definition']['profile']['instrument']['serial_number']
            if metadata.get('serialnumber', serial) != serial:
                issues.append('instrument_serial_mismatch')
            for row in report['rows']:
                if row['metadata'].get('application', state['definition']['protocol']['method']) != state['definition']['protocol']['method']:
                    issues.append('method_mismatch')
                if row['metadata'].get('serialnumber', serial) != serial:
                    issues.append('instrument_serial_mismatch')
        except TaskError as error:
            issues.append(str(error))
        results = {}
        if not issues:
            for row in report['rows']:
                if row['measurement_id'] in state['blanks']:
                    continue
                measurement = state['measurements'][row['measurement_id']]
                results[row['measurement_id']] = {
                    **row, 'sample_id': measurement['sample_id'], 'aliquot_id': measurement['aliquot_id'],
                    'blank_id': measurement['blank_id'], 'artifact_sha256': digest(artifact),
                    'origin': origin, 'method': state['definition']['protocol']['method'],
                    'method_source': 'report' if 'application' in report['metadata'] or 'application' in row['metadata'] else 'profile_declaration',
                    'instrument': state['definition']['profile']['instrument'],
                    'serial_source': 'report' if 'serialnumber' in report['metadata'] or 'serialnumber' in row['metadata'] else 'profile_declaration',
                    'concentration_basis': 'reported; no additional dilution or purity correction applied'}
        return report, issues, results

    def _reconcile_device(self, state, actor_id, blank_still_valid, pending_resolution=None):
        if type(blank_still_valid) is not bool:
            raise TaskError('Explicit blank observation required')
        pending = state['pending_measurement']
        if pending:
            if not isinstance(pending_resolution, dict):
                raise TaskError('Explicit pending measurement outcome required')
            outcome = pending_resolution.get('outcome')
            if pending_resolution.get('intent_id') != pending['intent_id']:
                raise TaskError('Pending measurement intent mismatch')
            if outcome == 'unknown':
                state['samples'][pending['sample_id']]['volume_uncertain'] = True
                state['recovery_required'] = 'measurement_outcome_unknown'
                return False
            if outcome == 'performed':
                self._finish_measurement(state, **{k: v for k, v in pending_resolution.items() if k != 'outcome'})
            elif outcome == 'not_performed':
                keys(pending_resolution, 'intent_id outcome', 'pending measurement resolution')
                state['samples'][pending['sample_id']]['volume_uncertain'] = False
                state['pending_measurement'] = None
            else:
                raise TaskError('Unknown pending measurement outcome')
        elif pending_resolution is not None:
            raise TaskError('No measurement intent to resolve')
        if not blank_still_valid:
            state['active_blank'] = None
        return True
