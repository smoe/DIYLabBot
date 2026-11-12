"""Pure interval checks for manual SOP evidence; never invent laboratory values.

Time is expressed in an explicitly identified, prospectively qualified domain.
Occurrence bounds are supplied observations, not differences between capture UTC
timestamps. These checks validate declared evidence, not physical qualification
or authenticity of a device, operator or original artifact.
"""
import copy
import math

from manual_tasks import TaskError, encoded


IDENTITY_FIELDS = {'stage_run_id', 'phase_id', 'reaction_id', 'material_id', 'vessel_id'}
SOURCE_KINDS = {'human_observation', 'device_export', 'external_record', 'test_fixture'}
COMMON_FIELDS = IDENTITY_FIELDS | {'evidence_id', 'time_basis_id', 'qualification_ref',
                                  'source_kind', 'artifact_sha256'}
TIME_FIELDS = COMMON_FIELDS | {'start_earliest_s', 'start_latest_s', 'end_earliest_s', 'end_latest_s'}
TEMPERATURE_FIELDS = COMMON_FIELDS | {'source_id', 'time_qualification_ref', 'from_earliest_s',
    'from_latest_s', 'to_earliest_s', 'to_latest_s', 'minimum_deg_c', 'maximum_deg_c', 'uncertainty_deg_c'}
REQUIREMENT_FIELDS = {'duration_min_s', 'duration_max_s', 'temperature_min_deg_c',
    'temperature_max_deg_c', 'time_qualification_ref', 'temperature_qualification_ref', 'evidence_ref'}
QUALIFICATION_FIELDS = {'kind', 'source_id', 'relationship', 'evidence_ref'}


def _require(condition, message):
    if not condition:
        raise TaskError(message)


def _text(value, name, *, nullable=False):
    if value is None and nullable:
        return value
    _require(isinstance(value, str) and bool(value.strip()), 'Nonempty ' + name + ' required')
    return value


def _number(value, name, *, nonnegative=False):
    if value is None:
        return value
    try:
        valid = type(value) in (int, float) and math.isfinite(value) and (not nonnegative or value >= 0)
    except OverflowError:
        valid = False
    _require(valid, 'Finite ' + ('nonnegative ' if nonnegative else '') + name + ' or null required')
    return value


def _interval(record, earliest, latest):
    left = _number(record[earliest], earliest, nonnegative=True)
    right = _number(record[latest], latest, nonnegative=True)
    _require(left is None or right is None or left <= right, 'Reversed occurrence interval')


def _qualifications(qualifications):
    _require(isinstance(qualifications, dict), 'Prospective qualification registry required')
    for identity, item in qualifications.items():
        _text(identity, 'qualification identity')
        _require(isinstance(item, dict) and set(item) == QUALIFICATION_FIELDS, 'Closed qualification fields required')
        _require(item['kind'] in {'time', 'temperature'}, 'Declared qualification kind required')
        _text(item['source_id'], 'qualified source identity')
        _text(item['evidence_ref'], 'qualification evidence reference')
        if item['kind'] == 'time':
            _require(item['relationship'] is None, 'A time qualification has no specimen temperature relationship')
        else:
            _require(item['relationship'] in {None, 'sample_measurement', 'qualified_proxy', 'device_setpoint'},
                     'Declared specimen temperature relationship required')


def _common(record, expected_identity, fields, qualifications):
    _require(isinstance(record, dict) and set(record) == fields, 'Closed SOP evidence fields required')
    _require(isinstance(expected_identity, dict) and set(expected_identity) == IDENTITY_FIELDS,
             'Complete stage/phase/reaction/material/vessel identity required')
    for name in IDENTITY_FIELDS:
        _text(record[name], name)
        _require(record[name] == expected_identity[name], 'SOP evidence identity mismatch: ' + name)
    _text(record['evidence_id'], 'SOP evidence identity')
    _text(record['time_basis_id'], 'occurrence time basis')
    _text(record['qualification_ref'], 'qualification reference', nullable=True)
    _require(record['source_kind'] in SOURCE_KINDS, 'Explicit SOP evidence source kind required')
    checksum = record['artifact_sha256']
    _require(isinstance(checksum, str) and len(checksum) == 64
             and all(character in '0123456789abcdef' for character in checksum),
             'Original evidence SHA-256 required')
    _qualifications(qualifications)
    try:
        encoded(record)
    except (TypeError, ValueError) as error:
        raise TaskError('Finite JSON SOP evidence required') from error


def validate_time(record, expected_identity, qualifications):
    """Validate an occurrence record; null/unqualified data remain archivable."""
    _common(record, expected_identity, TIME_FIELDS, qualifications)
    _interval(record, 'start_earliest_s', 'start_latest_s')
    _interval(record, 'end_earliest_s', 'end_latest_s')
    _require(record['start_earliest_s'] is None or record['end_latest_s'] is None
             or record['start_earliest_s'] <= record['end_latest_s'], 'Phase end precedes every possible start')
    return copy.deepcopy(record)


def validate_temperature(record, expected_identity, qualifications):
    """Validate a temperature observation without treating setpoints as samples."""
    _common(record, expected_identity, TEMPERATURE_FIELDS, qualifications)
    _text(record['source_id'], 'temperature source identity')
    _text(record['time_qualification_ref'], 'temperature time qualification reference', nullable=True)
    _interval(record, 'from_earliest_s', 'from_latest_s')
    _interval(record, 'to_earliest_s', 'to_latest_s')
    _require(record['from_earliest_s'] is None or record['to_latest_s'] is None
             or record['from_earliest_s'] <= record['to_latest_s'], 'Temperature interval end precedes every possible start')
    lower = _number(record['minimum_deg_c'], 'minimum temperature')
    upper = _number(record['maximum_deg_c'], 'maximum temperature')
    _number(record['uncertainty_deg_c'], 'temperature uncertainty', nonnegative=True)
    _require(lower is None or upper is None or lower <= upper, 'Reversed temperature bounds')
    return copy.deepcopy(record)


def _requirements(requirements):
    _require(isinstance(requirements, dict) and set(requirements) == REQUIREMENT_FIELDS,
             'Closed prospective phase requirements required')
    for name in ('duration_min_s', 'duration_max_s'):
        _number(requirements[name], name, nonnegative=True)
    for name in ('temperature_min_deg_c', 'temperature_max_deg_c'):
        _number(requirements[name], name)
    for name in ('time_qualification_ref', 'temperature_qualification_ref', 'evidence_ref'):
        _text(requirements[name], name, nullable=True)
    for lower, upper in [('duration_min_s', 'duration_max_s'), ('temperature_min_deg_c', 'temperature_max_deg_c')]:
        _require(requirements[lower] is None or requirements[upper] is None
                 or requirements[lower] <= requirements[upper], 'Reversed prospective phase requirements')


def _qualified_time(reference, basis, qualifications):
    item = qualifications.get(reference) if reference is not None else None
    return bool(item and item['kind'] == 'time' and item['source_id'] == basis)


def evaluate_phase(time_record, temperature_records, requirements, qualifications):
    """Assess declared occurrences and complete specimen-temperature coverage.

    Temperature intervals guarantee coverage only from their latest possible
    start through their earliest possible end. The required coverage includes
    every possible phase occurrence: earliest start through latest end. Point
    readings, unqualified proxies and setpoints never fill interval gaps.
    Contradictory qualifying observations remain issues even if good intervals
    cover the same region. Unknown inputs remain unknown, never numerical zero.
    """
    _requirements(requirements)
    _qualifications(qualifications)
    _require(isinstance(time_record, dict), 'Phase time evidence required')
    identity = {name: time_record.get(name) for name in IDENTITY_FIELDS}
    timed = validate_time(time_record, identity, qualifications)
    _require(isinstance(temperature_records, list), 'Explicit temperature evidence list required')
    records = [validate_temperature(record, identity, qualifications) for record in temperature_records]
    ids = [timed['evidence_id']] + [record['evidence_id'] for record in records]
    _require(len(ids) == len(set(ids)), 'SOP evidence identities must be unique')
    issues = []

    def issue(code):
        if code not in issues:
            issues.append(code)

    if any(value is None for value in requirements.values()):
        issue('requirements_open')
    start_lower, start_upper = timed['start_earliest_s'], timed['start_latest_s']
    end_lower, end_upper = timed['end_earliest_s'], timed['end_latest_s']
    duration_lower = None if end_lower is None or start_upper is None else max(0, end_lower - start_upper)
    duration_upper = None if end_upper is None or start_lower is None else max(0, end_upper - start_lower)
    if duration_lower is None or duration_upper is None:
        issue('duration_unknown')
    time_qualified = (_qualified_time(timed['qualification_ref'], timed['time_basis_id'], qualifications)
                      and timed['qualification_ref'] == requirements['time_qualification_ref'])
    if not time_qualified:
        issue('time_unqualified')
    if duration_lower is not None and requirements['duration_min_s'] is not None and duration_lower < requirements['duration_min_s']:
        issue('duration_below_minimum')
    if duration_upper is not None and requirements['duration_max_s'] is not None and duration_upper > requirements['duration_max_s']:
        issue('duration_above_maximum')
    if start_upper is not None and end_lower is not None and end_lower < start_upper:
        issue('occurrence_order_uncertain')
    required_from, required_to = start_lower, end_upper
    if required_from is None or required_to is None:
        issue('temperature_window_unknown')
    qualifying_intervals = []
    for record in records:
        suffix = ':' + record['evidence_id']
        if (timed['source_kind'] == 'test_fixture') != (record['source_kind'] == 'test_fixture'):
            issue('fixture_evidence_mismatch' + suffix)
            continue
        if (record['time_basis_id'] != timed['time_basis_id']
                or record['time_qualification_ref'] != timed['qualification_ref']
                or not _qualified_time(record['time_qualification_ref'], record['time_basis_id'], qualifications)):
            issue('temperature_time_unqualified' + suffix)
            continue
        qualifier = qualifications.get(record['qualification_ref'])
        if (qualifier is None or qualifier['kind'] != 'temperature'
                or qualifier['source_id'] != record['source_id']
                or qualifier['relationship'] not in {'sample_measurement', 'qualified_proxy'}
                or record['qualification_ref'] != requirements['temperature_qualification_ref']):
            issue('temperature_unqualified' + suffix)
            continue
        possible_from, possible_to = record['from_earliest_s'], record['to_latest_s']
        if (possible_from is not None and possible_to is not None
                and required_from is not None and required_to is not None
                and (possible_to < required_from or possible_from > required_to)):
            continue
        if (record['minimum_deg_c'] is None or record['maximum_deg_c'] is None or record['uncertainty_deg_c'] is None):
            issue('temperature_unknown' + suffix)
            continue
        lower = record['minimum_deg_c'] - record['uncertainty_deg_c']
        upper = record['maximum_deg_c'] + record['uncertainty_deg_c']
        if (requirements['temperature_min_deg_c'] is not None and lower < requirements['temperature_min_deg_c']
                or requirements['temperature_max_deg_c'] is not None and upper > requirements['temperature_max_deg_c']):
            issue('temperature_out_of_range' + suffix)
        guaranteed_from, guaranteed_to = record['from_latest_s'], record['to_earliest_s']
        if guaranteed_from is None or guaranteed_to is None:
            issue('temperature_interval_unknown' + suffix)
        elif guaranteed_to > guaranteed_from:
            qualifying_intervals.append((guaranteed_from, guaranteed_to))
    cursor = required_from
    coverage_complete = False
    if cursor is not None and required_to is not None:
        for left, right in sorted(qualifying_intervals):
            if left <= cursor:
                cursor = max(cursor, right)
        coverage_complete = bool(qualifying_intervals) and cursor >= required_to
    if not coverage_complete:
        issue('temperature_coverage_missing')
    return {'complete': not issues, 'conformant': not issues,
            'duration_bounds': {'min_s': duration_lower, 'max_s': duration_upper},
            'coverage': {'required_from_s': required_from, 'required_to_s': required_to,
                         'covered_through_s': cursor, 'complete': coverage_complete},
            'issues': issues}
