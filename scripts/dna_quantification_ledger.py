"""One-run DNA consumption and explicit external-dilution result projections.

These functions mutate a caller's candidate root state, not the journal. The
coordinator persists the intent before an effect and commits its confirmation
atomically. Device values and their original cells are never rewritten here.
"""
import copy
import math

from manual_tasks import TaskError
from manual_workflow import ObservationError, text


UNRESOLVED = {'intent', 'unknown'}


def _finite(value, name, *, zero=False):
    try:
        valid = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid or (value < 0 if zero else value <= 0):
        raise TaskError('Finite ' + ('nonnegative ' if zero else 'positive ') + name + ' required')
    return value


def _vessel(state, vessel_id):
    text(vessel_id, 'source vessel id')
    vessel = state['inventory']['vessels'].get(vessel_id)
    if not isinstance(vessel, dict):
        raise TaskError('Unknown source vessel: ' + vessel_id)
    return vessel


def _records(state, vessel_id, exclude_intent=None):
    records = []
    for identity, record in state['bookings'].items():
        if identity == exclude_intent or record['source_vessel_id'] != vessel_id:
            continue
        if record['outcome'] not in UNRESOLVED | {'performed', 'not_performed'}:
            raise TaskError('Unknown withdrawal outcome')
        if record['outcome'] == 'performed':
            _finite(record['actual_volume_ul'], 'booked withdrawal in uL')
        records.append(record)
    return records


def remaining(state, vessel_id, exclude_intent=None):
    """Derive remaining stock; an unresolved transfer is not its planned amount."""
    vessel = _vessel(state, vessel_id)
    initial = vessel['initial_volume_ul']
    if initial is not None:
        _finite(initial, 'initial volume in uL', zero=True)
    records = _records(state, vessel_id, exclude_intent)
    if initial is None or any(row['outcome'] in UNRESOLVED for row in records):
        return None
    try:
        actual = math.fsum(row['actual_volume_ul'] for row in records if row['outcome'] == 'performed')
    except OverflowError as error:
        raise TaskError('Non-finite booked volume total') from error
    result = initial - actual
    if not math.isfinite(result) or result < 0:
        raise TaskError('Recorded consumption exceeds the initial volume')
    return result


def reserve_withdrawal(state, *, intent_id, source_vessel_id, planned_volume_ul,
                       stage_id, attempt_id, target, actor_id):
    """Record exactly one intent against the canonical source vessel."""
    for name, value in [('intent id', intent_id), ('stage id', stage_id),
                        ('attempt id', attempt_id), ('actor id', actor_id)]:
        text(value, name)
    planned = _finite(planned_volume_ul, 'planned withdrawal in uL')
    now = _finite(state['logical_time_s'], 'synthetic time in seconds', zero=True)
    if not isinstance(target, dict) or not target:
        raise TaskError('Explicit withdrawal target required')
    if intent_id in state['bookings']:
        raise TaskError('Withdrawal intent identity was already used')
    vessel = _vessel(state, source_vessel_id)
    if vessel.get('location', {}).get('kind') == 'discarded':
        raise TaskError('Discarded material cannot be withdrawn')
    if any(row['outcome'] in UNRESOLVED for row in _records(state, source_vessel_id)):
        raise TaskError('Resolve the previous source withdrawal before another intent')
    available = remaining(state, source_vessel_id)
    if available is not None and planned > available:
        raise TaskError('Insufficient recorded volume for the planned withdrawal')
    record = {'id': intent_id, 'run_id': state.get('run_id'), 'stage_id': stage_id,
              'attempt_id': attempt_id, 'sample_id': vessel.get('sample_id'),
              'source_vessel_id': source_vessel_id, 'target': copy.deepcopy(target),
              'planned_volume_ul': planned, 'actual_volume_ul': None, 'unit': 'uL',
              'outcome': 'intent', 'created_at_s': now, 'confirmed_at_s': None,
              'actor_id': actor_id, 'evidence': 'synthetic_input'}
    state['bookings'][intent_id] = record
    # A device handler may have set this flag already in this same transition.
    # The booking, rather than that compatibility flag, fences a second intent.
    vessel['volume_uncertain'] = True
    vessel['mass_confirmation_valid'] = False
    return copy.deepcopy(record)


def _open_record(state, intent_id):
    text(intent_id, 'withdrawal intent id')
    record = state['bookings'].get(intent_id)
    if not isinstance(record, dict):
        raise TaskError('Unknown withdrawal intent')
    if record['outcome'] not in UNRESOLVED:
        raise TaskError('Withdrawal intent is already resolved')
    return record, _vessel(state, record['source_vessel_id'])


def _uncertain(state, vessel_id):
    return any(row['outcome'] in UNRESOLVED for row in _records(state, vessel_id))


def confirm_withdrawal(state, intent_id, actual_volume_ul, reason=None):
    """Debit an observed transfer once, never its later measurement/disposal."""
    actual = _finite(actual_volume_ul, 'actual withdrawal in uL')
    record, vessel = _open_record(state, intent_id)
    if reason is not None:
        text(reason, 'withdrawal deviation reason')
    if not math.isclose(actual, record['planned_volume_ul'], rel_tol=0, abs_tol=1e-9) and reason is None:
        raise TaskError('Reason for withdrawal volume deviation required')
    available = remaining(state, record['source_vessel_id'], exclude_intent=intent_id)
    if available is not None and actual > available:
        raise ObservationError('Withdrawal exceeds remaining source volume')
    revision = vessel['content_revision']
    if type(revision) is not int or revision < 0:
        raise TaskError('Nonnegative integer content revision required')
    now = _finite(state['logical_time_s'], 'synthetic time in seconds', zero=True)
    record.update(outcome='performed', actual_volume_ul=actual, confirmed_at_s=now,
                  deviation_reason=reason)
    vessel['content_revision'] = revision + 1
    vessel['mass_confirmation_valid'] = False
    vessel['volume_uncertain'] = _uncertain(state, record['source_vessel_id'])
    return copy.deepcopy(record)


def resolve_not_performed(state, intent_id):
    """Retain an unperformed intent without a debit or restored mass evidence."""
    record, vessel = _open_record(state, intent_id)
    now = _finite(state['logical_time_s'], 'synthetic time in seconds', zero=True)
    record.update(outcome='not_performed', actual_volume_ul=0.0, confirmed_at_s=now)
    vessel['volume_uncertain'] = _uncertain(state, record['source_vessel_id'])
    vessel['mass_confirmation_valid'] = False
    return copy.deepcopy(record)


def dilution_factor(sample_ul, diluent_ul):
    """Use confirmed component volumes: one plus nine is factor ten."""
    sample = _finite(sample_ul, 'sample volume in uL')
    diluent = _finite(diluent_ul, 'diluent volume in uL')
    total = sample + diluent
    _finite(total, 'dilution total volume in uL')
    factor = total / sample
    _finite(factor, 'external dilution factor')
    return factor


def _concentration(metric, name):
    if not isinstance(metric, dict):
        raise TaskError('Missing ' + name)
    value = metric.get('value')
    try:
        valid = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        raise TaskError('Finite ' + name + ' required')
    unit = metric.get('unit')
    if not isinstance(unit, str) or unit not in {'ng/uL', 'ng/mL'}:
        raise TaskError('Unsupported ' + name + ' unit')
    result = value * (0.001 if unit == 'ng/mL' else 1.0)
    if not math.isfinite(result):
        raise TaskError('Non-finite converted ' + name)
    return {'value': result, 'unit': 'ng/uL', 'source_unit': unit,
            'source_basis': metric.get('basis', 'reported')}


def _flags(messages):
    """Only the explicit synthetic range tokens are machine interpretable."""
    if not isinstance(messages, dict):
        raise TaskError('Instrument messages must be an object')
    result = set()
    for value in messages.values():
        if value == '':
            continue
        if not isinstance(value, str) or value not in {'AboveRange', 'BelowRange'}:
            raise TaskError('Unqualified instrument flag requires review')
        result.add(value)
    if len(result) > 1:
        raise TaskError('Contradictory instrument range flags')
    return result


def classify_input(result, device, assay, sample_volume_ul=None, total_volume_ul=None,
                   external_factor=1):
    """Evaluate the measured basis before deriving the original-stock result.

    Qubit ``original_concentration`` is already corrected for its assay mixture.
    It describes the selected input, which may itself be a predilution. The new
    ``root_original_concentration`` applies only that external factor. NanoDrop's
    unrelated CSV Factor cell is never read.
    """
    messages = copy.deepcopy(result.get('instrument_messages')) if isinstance(result, dict) else None
    evaluation = {'status': 'unknown', 'measured_basis': None, 'measured_value': None,
                  'measured_unit': None, 'selected_input_concentration': None,
                  'root_original_concentration': None, 'external_factor': None,
                  'range': copy.deepcopy(assay.get('range')) if isinstance(assay, dict) else None,
                  'instrument_messages': messages, 'issues': [], 'quantifiable': False}
    try:
        factor = _finite(external_factor, 'external dilution factor')
        if factor < 1:
            raise TaskError('External dilution factor must be at least one')
        evaluation['external_factor'] = factor
        if not isinstance(result, dict) or not isinstance(result.get('metrics'), dict):
            raise TaskError('Explicit measurement metrics required')
        if not isinstance(assay, dict) or not isinstance(assay.get('range'), dict):
            raise TaskError('Declared assay range required')
        limits = assay['range']
        lower = _finite(limits.get('lower'), 'lower range limit', zero=True)
        upper = _finite(limits.get('upper'), 'upper range limit')
        if lower >= upper:
            raise TaskError('Increasing assay range limits required')
        metrics = result['metrics']
        if device == 'nanodrop':
            if limits.get('basis') != 'selected_input_concentration' or limits.get('unit') != 'ng/uL':
                raise TaskError('NanoDrop range must describe selected-input concentration in ng/uL')
            if 'sample_volume_ul_min' in assay:
                sample = _finite(sample_volume_ul, 'confirmed NanoDrop sample volume in uL')
                minimum = _finite(assay['sample_volume_ul_min'], 'NanoDrop sample-volume minimum')
                if sample < minimum:
                    raise TaskError('Confirmed NanoDrop sample volume is below the declared target minimum')
            selected = _concentration(metrics.get('concentration'), 'NanoDrop input concentration')
            measured, unit = selected['value'], 'ng/uL'
        elif device == 'qubit':
            if limits.get('basis') != 'assay_dna_mass' or limits.get('unit') != 'ng':
                raise TaskError('Qubit range must describe assay DNA mass in ng')
            sample = _finite(sample_volume_ul, 'confirmed Qubit sample volume in uL')
            total = _finite(total_volume_ul, 'confirmed Qubit total volume in uL')
            required_total = _finite(assay.get('assay_total_volume_ul'), 'declared Qubit total volume in uL')
            if total <= sample or not math.isclose(total, required_total, rel_tol=0, abs_tol=1e-9):
                raise TaskError('Confirmed Qubit volumes do not match the declared assay')
            for key, outside in [('sample_volume_ul_min', lambda bound: sample < bound),
                                 ('sample_volume_ul_max', lambda bound: sample > bound)]:
                if key in assay and outside(_finite(assay[key], 'Qubit sample-volume bound')):
                    raise TaskError('Confirmed Qubit sample volume is outside the declared assay')
            tube = _concentration(metrics.get('tube_concentration'), 'Qubit assay-tube concentration')
            selected = _concentration(metrics.get('original_concentration'), 'Qubit selected-input concentration')
            measured, unit = tube['value'] * total, 'ng'
            if not math.isfinite(measured):
                raise TaskError('Non-finite assay DNA mass')
        else:
            raise TaskError('Unsupported measurement device')
        original = selected['value'] * factor
        if not math.isfinite(original):
            raise TaskError('Non-finite original-stock concentration')
        evaluation.update(measured_basis=limits['basis'], measured_value=measured,
                          measured_unit=unit, selected_input_concentration=selected,
                          root_original_concentration={'value': original, 'unit': 'ng/uL',
                              'formula': 'selected_input_concentration_ng_ul * external_factor',
                              'external_factor': factor, 'source_basis': selected['source_basis']})
        status = 'below_range' if measured < lower else 'above_range' if measured > upper else 'in_range'
        flags = _flags(messages)
        flag_status = ('above_range' if 'AboveRange' in flags else
                       'below_range' if 'BelowRange' in flags else None)
        if flag_status:
            if status not in {'in_range', flag_status}:
                raise TaskError('Instrument range flag contradicts the numeric range')
            status = flag_status
        evaluation.update(status=status, quantifiable=status == 'in_range')
    except (TaskError, OverflowError) as error:
        evaluation['issues'].append(str(error))
    return evaluation
