"""Pure, bounded decoding of an explicitly synthetic TS01 gDNA report.

This is neither a native Agilent export decoder nor an instrument driver. The
owning workflow retains original bytes and books QC preparation in its ledger.
DIN, fragment size and concentration remain distinct reported observations.
"""
import copy
import json
import math
from pathlib import Path
import re

import assembly_model as assembly
from manual_tasks import TaskError, digest, encoded

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'model/tapestation-gdna.protocol.json'
SCHEMA = ROOT / 'model/tapestation-gdna.schema.json'
FORMAT = 'solidcraftbot.synthetic-tapestation-report/1'
PROTOCOL_FORMAT = 'solidcraftbot.tapestation-gdna-protocol/1'
TOP_FIELDS = ('workflow_run_id', 'instrument_run_id', 'analysis_id', 'instrument_id',
              'assay_id', 'assay_revision')
IDENTITY_FIELDS = ('measurement_id', 'lane_id', 'sample_id', 'product_material_id',
                   'product_vessel_id', 'product_content_revision', 'aliquot_material_id',
                   'aliquot_vessel_id', 'aliquot_content_revision')
REVISION_FIELDS = {'product_content_revision', 'aliquot_content_revision'}
METRIC_FIELDS = ('din', 'sample_concentration_ng_ul', 'fragment_size', 'flags', 'messages')


def _require(condition, message):
    if not condition:
        raise TaskError(message)


def _exact(value, fields, label):
    _require(isinstance(value, dict) and set(value) == set(fields), 'Exact ' + label + ' fields required')


def _identifier(value):
    _require(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,160}', value),
             'Explicit unambiguous TapeStation identity required')


def _numeric(value, label, minimum=None, maximum=None, nullable=False):
    if value is None and nullable:
        return
    _require(type(value) in (int, float) and math.isfinite(value), 'Finite ' + label + ' required')
    _require(minimum is None or value >= minimum, label + ' below supported range')
    _require(maximum is None or value <= maximum, label + ' above supported range')


def _json(content):
    def pairs(items):
        value = {}
        for key, item in items:
            _require(key not in value, 'Duplicate TapeStation JSON field')
            value[key] = item
        return value
    def invalid(_):
        raise TaskError('Nonfinite TapeStation JSON value')
    try:
        return json.loads(content, object_pairs_hook=pairs, parse_constant=invalid)
    except (UnicodeError, ValueError, TypeError, RecursionError) as error:
        raise TaskError('Malformed synthetic TapeStation JSON') from error


def _protocol(value):
    """Validate detached protocol values; existing Root pins supply revision trust."""
    value = copy.deepcopy(value)
    checksum = value.pop('source_sha256', None) if isinstance(value, dict) else None
    if checksum is not None:
        _require(isinstance(checksum, str) and re.fullmatch(r'[a-f0-9]{64}', checksum),
                 'TapeStation source checksum required')
    _exact(value, ('format', 'id', 'mode', 'instrument', 'assay', 'report_format', 'limits',
                   'known_flags', 'sources', 'limitations'), 'TapeStation protocol')
    _require(value['format'] == PROTOCOL_FORMAT and value['id'] == 'TS01.GenomicDNA.ScreenTape'
             and value['mode'] == 'synthetic_only' and value['report_format'] == FORMAT,
             'Explicit supported synthetic TapeStation protocol required')
    instrument = value['instrument']
    _exact(instrument, ('id', 'source', 'planning_reference', 'selected_model', 'handling'), 'TapeStation instrument')
    _exact(instrument['source'], ('source', 'source_sha256'), 'TapeStation source reference')
    _require(instrument['id'] == 'TS01' and instrument['source']['source'] == 'model/tapestation.shared.json'
             and instrument['planning_reference'] == '4200 TapeStation'
             and instrument['selected_model'] is None and instrument['handling'] == 'manual_only',
             'Existing unqualified manual TS01 planning model required')
    assay = value['assay']
    _exact(assay, ('id', 'revision', 'screentape_part_number', 'reagents_part_number', 'applicable_models',
                   'sample_volume_ul', 'sample_buffer_volume_ul', 'ladder_volume_ul', 'ladder_buffer_volume_ul',
                   'ladder_position', 'fixture_sample_position', 'ladder_fixture_scope', 'references', 'preparation'), 'gDNA assay')
    _require(assay['id'] == 'GenomicDNA.ScreenTape' and assay['revision'] == 'SYN.1'
             and assay['screentape_part_number'] == '5067-5365' and assay['reagents_part_number'] == '5067-5366'
             and assay['applicable_models'] == ['4150', '4200']
             and assay['ladder_fixture_scope'] == 'one_or_two_screentape_devices', 'Unsupported gDNA assay')
    for name in ('sample_volume_ul', 'sample_buffer_volume_ul', 'ladder_volume_ul', 'ladder_buffer_volume_ul'):
        _numeric(assay[name], name, minimum=0)
        _require(assay[name] > 0, 'Positive assay preparation volume required')
    _identifier(assay['ladder_position']); _identifier(assay['fixture_sample_position'])
    _require(assay['ladder_position'] != assay['fixture_sample_position'], 'Ladder and sample positions must differ')
    _exact(assay['preparation'], ('buffer_equilibration_s', 'mix_duration_s', 'mix_rpm', 'spin_duration_s'),
           'TapeStation preparation reference')
    for name, preparation_number in assay['preparation'].items():
        _numeric(preparation_number, name, minimum=0)
        _require(preparation_number > 0, 'Positive TapeStation preparation reference required')
    references = assay['references']
    _exact(references, ('sizing_lower_bp', 'sizing_upper_reference_bp', 'sizing_upper_open',
                       'sizing_accuracy_precision_lower_bp', 'sizing_accuracy_precision_upper_bp',
                       'quantitative_lower_ng_ul', 'quantitative_upper_ng_ul',
                       'din_functional_lower_ng_ul', 'din_functional_upper_ng_ul', 'din_min', 'din_max'), 'assay ranges')
    for name, number in references.items():
        if name == 'sizing_upper_open':
            _require(number is True, 'Sizing upper reference must remain explicitly open')
        else:
            _numeric(number, name, minimum=0)
    for low, high in [('sizing_lower_bp', 'sizing_upper_reference_bp'),
                      ('sizing_accuracy_precision_lower_bp', 'sizing_accuracy_precision_upper_bp'),
                      ('quantitative_lower_ng_ul', 'quantitative_upper_ng_ul'),
                      ('din_functional_lower_ng_ul', 'din_functional_upper_ng_ul'), ('din_min', 'din_max')]:
        _require(references[low] < references[high], 'Ordered assay reference range required')
    limits = value['limits']
    _exact(limits, ('max_report_bytes', 'max_rows', 'max_messages_per_row', 'max_message_characters'), 'TapeStation limits')
    for number in limits.values():
        _require(type(number) is int and number > 0, 'Positive integer TapeStation limit required')
    _require(limits['max_report_bytes'] <= 262144 and limits['max_rows'] <= 96
             and limits['max_messages_per_row'] <= 32 and limits['max_message_characters'] <= 2048,
             'TapeStation limits exceed implemented bounds')
    _require(isinstance(value['known_flags'], list) and value['known_flags']
             and len(value['known_flags']) == len(set(value['known_flags'])), 'Distinct known TapeStation flags required')
    for flag in value['known_flags']: _identifier(flag)
    for name in ('sources', 'limitations'):
        _require(isinstance(value[name], list) and value[name], 'TapeStation provenance and limits required')
    if checksum is not None: value['source_sha256'] = checksum
    return value


def load_protocol(source=SOURCE):
    try:
        raw = Path(source).read_bytes()
        protocol = _protocol(_json(raw))
        reference = assembly.validate_reference(protocol['instrument']['source'])
        instrument = _json(reference.read_bytes())
        _require(instrument.get('id') == protocol['instrument']['id']
                 and instrument.get('selected_model') is None
                 and instrument.get('planning_reference') == protocol['instrument']['planning_reference']
                 and instrument.get('handling') == 'manual_only', 'TS01 source binding mismatch')
        protocol['source_sha256'] = digest(raw)
        return protocol
    except TaskError:
        raise
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise TaskError('Invalid TapeStation protocol or TS01 source binding') from error


# One leading bound from the protocol, also usable before reading an input file.
MAX_REPORT_BYTES = load_protocol()['limits']['max_report_bytes']


def _identity(value):
    _exact(value, IDENTITY_FIELDS, 'TapeStation sample mapping')
    for name, item in value.items():
        if name in REVISION_FIELDS:
            _require(type(item) is int and item >= 0, 'Nonnegative integer material content revision required')
        else:
            _identifier(item)


def _expected(value, protocol):
    _exact(value, (*TOP_FIELDS, 'measurements'), 'TapeStation expected mapping')
    for name in TOP_FIELDS: _identifier(value[name])
    _require(value['instrument_id'] == protocol['instrument']['id']
             and value['assay_id'] == protocol['assay']['id']
             and value['assay_revision'] == protocol['assay']['revision'], 'Unexpected TapeStation instrument or assay')
    rows = value['measurements']
    _require(isinstance(rows, list) and 0 < len(rows) <= protocol['limits']['max_rows'], 'Bounded TapeStation mapping required')
    for row in rows: _identity(row)
    for name in ('measurement_id', 'lane_id', 'aliquot_material_id', 'aliquot_vessel_id'):
        _require(len({row[name] for row in rows}) == len(rows), 'Duplicate expected TapeStation ' + name)


def _row(value, protocol):
    _exact(value, (*IDENTITY_FIELDS, *METRIC_FIELDS), 'TapeStation result row')
    _identity({name: value[name] for name in IDENTITY_FIELDS})
    reference = protocol['assay']['references']
    _numeric(value['din'], 'DIN', reference['din_min'], reference['din_max'], nullable=True)
    _numeric(value['sample_concentration_ng_ul'], 'sample concentration', minimum=0, nullable=True)
    fragment = value['fragment_size']
    _exact(fragment, ('value', 'unit', 'method', 'qualifier'), 'fragment-size result')
    _require(fragment['unit'] == 'bp' and fragment['method'] in {'peak', 'smear_mean'}
             and fragment['qualifier'] in {'estimated', 'above_sizing_range', 'unavailable'}, 'Explicit fragment-size method and qualifier required')
    if fragment['qualifier'] == 'estimated':
        _numeric(fragment['value'], 'fragment-size estimate', minimum=0)
        _require(fragment['value'] > 0, 'Positive fragment-size estimate required')
    else:
        _require(fragment['value'] is None, 'Censored or unavailable size cannot carry a precise value')
    for name in ('flags', 'messages'):
        values = value[name]
        _require(isinstance(values, list) and len(values) <= protocol['limits']['max_messages_per_row'], 'Bounded instrument messages required')
        for message in values:
            _require(isinstance(message, str) and message.strip()
                     and len(message) <= protocol['limits']['max_message_characters']
                     and not any(ord(char) < 32 for char in message), 'Explicit single-line instrument message required')
    _require(len(set(value['flags'])) == len(value['flags']), 'Duplicate instrument flags')


def evaluate(row, policy=None, protocol=None):
    """Evaluate a declared synthetic policy, never analytical qualification."""
    protocol = load_protocol() if protocol is None else _protocol(protocol)
    _row(row, protocol)
    reference = protocol['assay']['references']
    issues = []
    if policy is None:
        issues.append('synthetic_review_policy_missing')
    else:
        _exact(policy, ('minimum_din', 'minimum_fragment_size_bp'), 'synthetic TapeStation review policy')
        _numeric(policy['minimum_din'], 'synthetic minimum DIN', reference['din_min'], reference['din_max'])
        _numeric(policy['minimum_fragment_size_bp'], 'synthetic minimum fragment size', minimum=0)
        _require(policy['minimum_fragment_size_bp'] > 0, 'Positive synthetic size threshold required')
    if row['din'] is None:
        issues.append('din_unavailable')
    elif policy is not None and row['din'] < policy['minimum_din']:
        issues.append('din_below_synthetic_policy')
    concentration = row['sample_concentration_ng_ul']
    if concentration is None:
        issues.append('din_functional_concentration_unknown')
    elif not reference['din_functional_lower_ng_ul'] <= concentration <= reference['din_functional_upper_ng_ul']:
        issues.append('din_functional_concentration_out_of_range')
    fragment = row['fragment_size']
    size = fragment['value']
    if fragment['qualifier'] != 'estimated':
        issues.append('fragment_size_' + fragment['qualifier'])
    elif not reference['sizing_lower_bp'] <= size <= reference['sizing_upper_reference_bp']:
        issues.append('fragment_size_out_of_reference_range')
    elif policy is not None and size < policy['minimum_fragment_size_bp']:
        issues.append('fragment_size_below_synthetic_policy')
    if row['flags']: issues.append('instrument_flags_present')
    if any(flag not in protocol['known_flags'] for flag in row['flags']): issues.append('unknown_instrument_flag')
    if row['messages']: issues.append('instrument_messages_present')
    accuracy_applicable = bool(fragment['qualifier'] == 'estimated'
        and reference['sizing_accuracy_precision_lower_bp'] <= size <= reference['sizing_accuracy_precision_upper_bp'])
    return {'synthetic_policy_passed': not issues, 'review_required': True, 'issues': issues,
            'sizing_accuracy_reference_applicable': accuracy_applicable,
            'concentration_quantitative_reference_applicable': bool(concentration is not None
                and reference['quantitative_lower_ng_ul'] <= concentration <= reference['quantitative_upper_ng_ul']),
            'analytical_qualified': False, 'hardware_executed': False,
            'reference_notes': ['Fragment size is a reported estimate; no electropherogram or DNA yield is derived.',
                'Assay reference specifications are not DIYLabBot analytical qualification.']}


def parse_report(content, expected, protocol=None):
    """Decode exact synthetic identity mappings; perform no stock or I/O effect."""
    protocol = load_protocol() if protocol is None else _protocol(protocol)
    _require(isinstance(content, bytes) and 0 < len(content) <= protocol['limits']['max_report_bytes'],
             'Bounded original TapeStation report bytes required')
    _expected(expected, protocol)
    value = _json(content)
    _exact(value, ('format', 'synthetic', *TOP_FIELDS, 'rows'), 'synthetic TapeStation report')
    _require(value['format'] == FORMAT and value['synthetic'] is True, 'Explicit synthetic TapeStation report required')
    for name in TOP_FIELDS:
        _identifier(value[name])
        _require(value[name] == expected[name], 'TapeStation ' + name + ' mapping mismatch')
    rows = value['rows']
    _require(isinstance(rows, list) and 0 < len(rows) <= protocol['limits']['max_rows'], 'Bounded TapeStation result rows required')
    for row in rows: _row(row, protocol)
    for name in ('measurement_id', 'lane_id', 'aliquot_material_id', 'aliquot_vessel_id'):
        _require(len({row[name] for row in rows}) == len(rows), 'Duplicate reported TapeStation ' + name)
    mapping = {row['measurement_id']: row for row in expected['measurements']}
    _require({row['measurement_id'] for row in rows} == set(mapping), 'Missing or foreign TapeStation measurements')
    for row in rows:
        _require({name: row[name] for name in IDENTITY_FIELDS} == mapping[row['measurement_id']],
                 'TapeStation sample, product, aliquot, revision or lane mapping mismatch')
    issues = []
    for row in rows:
        # No hidden default acceptance threshold is inferred during import.
        issues.extend(row['measurement_id'] + ':' + issue for issue in evaluate(row, protocol=protocol)['issues']
                      if issue != 'synthetic_review_policy_missing')
    return {'format': FORMAT, 'artifact_sha256': digest(content), 'synthetic': True,
            **{name: value[name] for name in TOP_FIELDS}, 'rows': copy.deepcopy(rows),
            'issues': issues, 'synthetic_policy_passed': False,
            'native_export_qualified': False, 'hardware_executed': False}


def synthetic_report(expected, *, din=8.0, fragment_size_bp=30000.0, size_method='peak',
                     size_qualifier='estimated', sample_concentration_ng_ul=50.0,
                     flags=None, messages=None):
    """Explicit fixture builder only; it never supplies a runtime observation."""
    protocol = load_protocol()
    _expected(expected, protocol)
    rows = [{**copy.deepcopy(identity), 'din': din,
             'sample_concentration_ng_ul': sample_concentration_ng_ul,
             'fragment_size': {'value': fragment_size_bp, 'unit': 'bp', 'method': size_method,
                               'qualifier': size_qualifier},
             'flags': copy.deepcopy([] if flags is None else flags),
             'messages': copy.deepcopy([] if messages is None else messages)}
            for identity in expected['measurements']]
    value = {'format': FORMAT, 'synthetic': True,
             **{name: expected[name] for name in TOP_FIELDS}, 'rows': rows}
    content = encoded(value).encode('utf-8')
    parse_report(content, expected, protocol)
    return content
