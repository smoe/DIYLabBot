"""Observed process time without a synthetic advance or inferred restart gap.

All helpers return detached JSON proposals. The caller commits the proposal with
its workflow event; a failed transaction must not install it as live state.
``lower_s`` is accumulated monotonic evidence, not a calibrated measurement.
An upper bound requires finite endpoint uncertainty and a provider explicitly
declaring suspend-inclusive continuity. The default provider makes neither claim.

``clock_id`` names a monotonic continuity domain independently of a writer
``process_id``. SystemClock intentionally chooses a fresh process-scoped domain
for each provider. A new provider therefore requires explicit gap evidence.
UTC records absolute observation time, and never supplies an elapsed-time gap.
"""

import copy
from datetime import datetime, timezone
import math
import time
import uuid

from manual_tasks import TaskError, encoded


FORMAT = 'solidcraftbot.clock-observation/1'
SAMPLE_FIELDS = {'format', 'source_kind', 'clock_id', 'process_id', 'utc',
                 'monotonic_ns', 'uncertainty_s', 'suspend_policy'}
CLOCK_FIELDS = {'lower_s', 'upper_s', 'last_sample', 'gap_required', 'gap_base',
                'anomalies', 'gap_resolution'}


def _require(condition, message):
    if not condition:
        raise TaskError(message)


def _number(value, name):
    try:
        valid = type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        valid = False
    _require(valid, 'Finite nonnegative ' + name + ' required')
    return value


def _text(value, name):
    _require(isinstance(value, str) and bool(value.strip()), 'Nonempty ' + name + ' required')
    return value


def _utc(value):
    _require(isinstance(value, str) and value.endswith('Z'), 'UTC time ending in Z required')
    try:
        result = datetime.fromisoformat(value[:-1] + '+00:00')
    except (ValueError, OverflowError) as error:
        raise TaskError('Valid aware UTC time required') from error
    _require(result.tzinfo is not None and result.utcoffset().total_seconds() == 0,
             'Valid aware UTC time required')
    return result


def validate_sample(sample):
    """Validate a closed provider record and return an independent copy."""
    _require(isinstance(sample, dict) and set(sample) == SAMPLE_FIELDS,
             'Closed clock-observation fields required')
    _require(sample['format'] == FORMAT, 'Unsupported clock observation format')
    _require(sample['source_kind'] in ('system_clock', 'test_clock'), 'Declared clock source kind required')
    _require(sample['suspend_policy'] in ('inclusive', 'unqualified'), 'Declared suspend policy required')
    _text(sample['clock_id'], 'clock continuity identity')
    _text(sample['process_id'], 'writer process identity')
    _utc(sample['utc'])
    _require(type(sample['monotonic_ns']) is int and sample['monotonic_ns'] >= 0,
             'Nonnegative integer monotonic nanoseconds required')
    if sample['uncertainty_s'] is not None:
        _number(sample['uncertainty_s'], 'clock uncertainty')
    # Reject numeric values too large to participate in finite elapsed seconds.
    try:
        _require(math.isfinite(sample['monotonic_ns'] / 1_000_000_000),
                 'Finite monotonic seconds required')
    except OverflowError as error:
        raise TaskError('Finite monotonic seconds required') from error
    return copy.deepcopy(sample)


class SystemClock:
    """UTC plus monotonic observations with explicitly unqualified continuity."""

    def __init__(self):
        self.clock_id = 'process-clock.' + uuid.uuid4().hex
        self.process_id = 'writer.' + uuid.uuid4().hex

    def sample(self):
        return validate_sample({
            'format': FORMAT, 'source_kind': 'system_clock',
            'clock_id': self.clock_id, 'process_id': self.process_id,
            'utc': datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z'),
            'monotonic_ns': time.monotonic_ns(), 'uncertainty_s': None,
            'suspend_policy': 'unqualified'})


def _bounded(sample):
    return sample['uncertainty_s'] is not None and sample['suspend_policy'] == 'inclusive'


def initial(sample):
    """Start the elapsed coordinate at this observation, without a prior gap."""
    sample = validate_sample(sample)
    return {'lower_s': 0.0, 'upper_s': 0.0 if _bounded(sample) else None,
            'last_sample': sample, 'gap_required': False, 'gap_base': None,
            'anomalies': [], 'gap_resolution': None}


def _clock(clock):
    _require(isinstance(clock, dict) and set(clock) == CLOCK_FIELDS, 'Closed observed-clock state required')
    _number(clock['lower_s'], 'elapsed lower bound')
    if clock['upper_s'] is not None:
        _number(clock['upper_s'], 'elapsed upper bound')
        _require(clock['upper_s'] >= clock['lower_s'], 'Reversed elapsed bounds')
    validate_sample(clock['last_sample'])
    _require(type(clock['gap_required']) is bool and isinstance(clock['anomalies'], list),
             'Explicit gap status and anomaly history required')
    base = clock['gap_base']
    _require(clock['gap_required'] == (base is not None), 'Gap status and base must agree')
    if base is not None:
        _require(isinstance(base, dict) and set(base) == {'lower_s', 'upper_s', 'last_sample'},
                 'Fixed clock gap base required')
        _number(base['lower_s'], 'gap lower bound')
        _require(base['lower_s'] <= clock['lower_s'], 'Gap base cannot follow accumulated time')
        if base['upper_s'] is not None:
            _number(base['upper_s'], 'gap upper bound')
            _require(base['upper_s'] >= base['lower_s'], 'Reversed gap base bounds')
        validate_sample(base['last_sample'])
    try:
        encoded(clock)
    except (TypeError, ValueError) as error:
        raise TaskError('Finite JSON clock state required') from error
    return copy.deepcopy(clock)


def _sum(left, right):
    value = left + right
    _require(math.isfinite(value), 'Finite accumulated elapsed seconds required')
    return value


def refresh(clock, sample):
    """Capture a sample; preserve fixed gap origin and all earlier anomalies.

    Same-domain deltas advance only from the last captured sample. A broken
    domain/counter contributes no inferred elapsed minimum. Clock discrepancies
    preserve valid monotonic lower evidence while opening a gap. Once unknown,
    an earlier upper bound cannot be restored by a later good sample.
    """
    proposed, sample = _clock(clock), validate_sample(sample)
    previous = proposed['last_sample']
    if sample == previous:
        return proposed
    codes = []
    same_domain = sample['clock_id'] == previous['clock_id']
    same_kind = sample['source_kind'] == previous['source_kind']
    same_policy = sample['suspend_policy'] == previous['suspend_policy']
    if not same_domain:
        codes.append('clock_domain_changed')
    if not same_kind:
        codes.append('clock_source_changed')
    if not same_policy:
        codes.append('suspend_policy_changed')
    comparable = same_domain and same_kind and same_policy
    delta = (sample['monotonic_ns'] - previous['monotonic_ns']) / 1_000_000_000
    if comparable and delta < 0:
        codes.append('monotonic_regressed')
        comparable = False
    utc_delta = (_utc(sample['utc']) - _utc(previous['utc'])).total_seconds()
    if utc_delta < 0:
        codes.append('utc_regressed')
    endpoint_uncertainty = sum(value for value in (previous['uncertainty_s'], sample['uncertainty_s'])
                               if value is not None)
    if (comparable and previous['uncertainty_s'] is not None and sample['uncertainty_s'] is not None
            and abs(utc_delta - delta) > endpoint_uncertainty + 1e-9):
        codes.append('utc_monotonic_disagreement')
    if codes and not proposed['gap_required']:
        proposed['gap_base'] = {name: copy.deepcopy(proposed[name])
                                for name in ('lower_s', 'upper_s', 'last_sample')}
        proposed['gap_required'] = True
        proposed['gap_resolution'] = None
    if comparable:
        proposed['lower_s'] = _sum(proposed['lower_s'], max(0.0, delta - endpoint_uncertainty))
        if proposed['upper_s'] is not None:
            proposed['upper_s'] = (_sum(proposed['upper_s'], delta + endpoint_uncertainty)
                                   if _bounded(previous) and _bounded(sample) else None)
    else:
        proposed['upper_s'] = None
    if proposed['gap_required']:
        proposed['upper_s'] = None
    for code in codes:
        proposed['anomalies'].append({'code': code, 'previous_sample': copy.deepcopy(previous),
                                     'sample': copy.deepcopy(sample)})
    proposed['last_sample'] = sample
    return _clock(proposed)


def reconcile_gap(clock, sample, minimum_s, maximum_s, reason, evidence_ref):
    """Apply explicit elapsed evidence from fixed gap_base through sample.

    A null maximum remains unbounded. A historical unbounded upper limit cannot
    be replaced by a finite one. Reconciliation closes the gap flag, preserves
    anomaly history and records its provenance; it resolves no process effect.
    """
    _number(minimum_s, 'minimum gap seconds')
    if maximum_s is not None:
        _number(maximum_s, 'maximum gap seconds')
        _require(maximum_s >= minimum_s, 'Reversed explicit gap interval')
    _text(reason, 'gap reconciliation reason')
    _text(evidence_ref, 'gap evidence reference')
    _require(_clock(clock)['gap_required'], 'No unresolved clock gap')
    proposed = refresh(clock, sample)
    base = proposed['gap_base']
    lower = max(proposed['lower_s'], _sum(base['lower_s'], minimum_s))
    if maximum_s is not None:
        _require(_sum(base['lower_s'], maximum_s) + 1e-9 >= lower,
                 'Explicit gap maximum contradicts accumulated monotonic evidence')
    upper = None if base['upper_s'] is None or maximum_s is None else _sum(base['upper_s'], maximum_s)
    _require(upper is None or upper + 1e-9 >= lower, 'Explicit gap maximum precedes elapsed lower bound')
    proposed.update(lower_s=lower, upper_s=upper, gap_required=False, gap_base=None,
                    gap_resolution={'minimum_s': minimum_s, 'maximum_s': maximum_s,
                        'reason': reason, 'evidence_ref': evidence_ref,
                        'from_sample': copy.deepcopy(base['last_sample']),
                        'through_sample': copy.deepcopy(proposed['last_sample'])})
    return _clock(proposed)
