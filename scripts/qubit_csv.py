"""An explicit SYNTHETIC Qubit table contract, not a qualified native export."""
import csv
import io
import math

from manual_tasks import TaskError
from manual_results import decode_report, normalized, number

FORMAT = 'solidcraftbot.synthetic-qubit-report/1'
UNITS = {'ng/ul': 1.0, 'ng/ml': 0.001}


def concentration(value, unit, optional=False):
    if not value.strip():
        if optional and not unit.strip():
            return None
        raise TaskError('Missing concentration or unit')
    factor = UNITS.get(normalized(unit))
    if factor is None:
        raise TaskError('Unsupported concentration unit: ' + unit)
    numeric = number(value, decimal_comma=True)
    converted = numeric * factor
    if not math.isfinite(converted):
        raise TaskError('Non-finite converted concentration')
    return {'value': converted, 'unit': 'ng/uL', 'reported_value': numeric,
            'reported_unit': unit, 'unit_factor': factor}


def parse_report(content):
    text, encoding = decode_report(content)
    for delimiter in [',', ';', '\t']:
        try:
            rows = list(csv.reader(io.StringIO(text, newline=''), delimiter=delimiter, strict=True))
        except csv.Error:
            continue
        if len(rows) < 3 or rows[0] != ['Format', FORMAT]:
            continue
        header = rows[1]
        names = [normalized(key) for key in header]
        if len(set(names)) != len(names):
            raise TaskError('Duplicate report columns')
        required = {'measurementid', 'recordtype', 'tubeconcentration', 'tubeunit'}
        if not required <= set(names):
            raise TaskError('Missing synthetic Qubit report columns')
        index = dict(zip(names, range(len(names))))
        parsed = []
        for line, row in enumerate(rows[2:], 3):
            if not row or not any(cell.strip() for cell in row):
                continue
            if len(row) != len(header):
                raise TaskError('Report column count mismatch at row ' + str(line))
            cell = lambda key: row[index[key]].strip() if key in index else ''
            identity, kind = cell('measurementid'), cell('recordtype')
            if not identity or kind not in {'standard', 'sample'}:
                raise TaskError('Explicit measurement identity and standard/sample type required')
            volume = number(cell('samplevolumeul'), decimal_comma=delimiter != ',')
            if volume is not None and volume <= 0:
                raise TaskError('Positive reported sample volume required')
            raw = dict(zip(header, row))
            parsed.append({
                'measurement_id': identity, 'record_type': kind,
                'tube_concentration': concentration(cell('tubeconcentration'), cell('tubeunit')),
                'original_concentration': concentration(cell('originalconcentration'), cell('originalunit'), optional=True),
                'reported_sample_volume_ul': volume,
                'metadata': {key: cell(key) for key in ['assayid', 'assayrevision', 'kitlot',
                    'standardlot', 'instrumentserial', 'vesselid'] if cell(key)},
                'instrument_messages': {key: value for key, value in raw.items()
                                        if normalized(key) in {'warnings', 'flags', 'quality'}},
                'raw_cells': raw, 'source_row': line})
        if not parsed:
            raise TaskError('Empty synthetic Qubit report')
        return {'format': FORMAT, 'encoding': encoding, 'delimiter': delimiter, 'rows': parsed}
    raise TaskError('Expected explicitly marked synthetic Qubit report')
