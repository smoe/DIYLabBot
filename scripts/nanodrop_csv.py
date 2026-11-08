"""Narrow offline NanoDrop report adapter; qualification uses synthetic files only.

    The user-visible sample name is an explicit column, never a row number, date
    or device-internal UUID. All original cells remain in the result record.
"""
import csv
import io

from manual_tasks import TaskError
from manual_results import normalized, number, decode_report




METRICS = {
    'concentration': ('ng/uL', ('ng/uL',)),
    'a260_a280': ('1', ('A260/A280',)),
    'a260_a230': ('1', ('A260/A230',)),
    'a260': ('1', ('A260',)),
    'a280': ('1', ('A280',)),
    'a230': ('1', ('A230',)),
    'factor': (None, ('Factor',)),
}




def parse_report(content, identity_column='Sample Name'):
    """CSV/TSV with optional metadata before the report header.

    Only an ng/uL concentration column is supported in this first adapter.
    A column absent from the report is unknown, not a zero or a passed check.
    """
    text, encoding = decode_report(content)
    rows = None
    header_index = None
    delimiter = None
    for candidate in [',', ';', '\t']:
        try:
            trial = list(csv.reader(io.StringIO(text, newline=''), delimiter=candidate, strict=True))
        except csv.Error:
            continue
        for i, row in enumerate(trial):
            keys = [normalized(c) for c in row]
            if normalized(identity_column) in keys:
                if len(set(keys)) != len(keys):
                    raise TaskError('Duplicate report columns')
                if normalized('ng/uL') not in keys:
                    continue
                rows, header_index, delimiter = trial, i, candidate
                break
        if rows is not None:
            break
    if rows is None:
        raise TaskError('Expected explicit ' + identity_column + ' and ng/uL report columns')
    header = rows[header_index]
    index = {normalized(key): i for i, key in enumerate(header)}
    metadata = {}
    for row in rows[:header_index]:
        if len(row) == 2 and normalized(row[0]) in ('application', 'serialnumber'):
            key = normalized(row[0])
            if key in metadata and metadata[key] != row[1].strip():
                raise TaskError('Conflicting report metadata: ' + key)
            metadata[key] = row[1].strip()
    results = []
    for line, row in enumerate(rows[header_index + 1:], header_index + 2):
        if not row or not any(cell.strip() for cell in row):
            continue
        if len(row) != len(header):
            raise TaskError('Report column count mismatch at row ' + str(line))
        name = row[index[normalized(identity_column)]].strip()
        if not name:
            raise TaskError('Missing measurement name at row ' + str(line))
        metrics = {}
        for key, (unit, aliases) in METRICS.items():
            column = next((index[normalized(a)] for a in aliases if normalized(a) in index), None)
            value = number(row[column], delimiter != ',') if column is not None else None
            metrics[key] = {'value': value, 'unit': unit}
            if key in {'a260', 'a280', 'a230'}:
                metrics[key]['normalization'] = 'as reported; pathlength not established'
        if metrics['concentration']['value'] is None:
            raise TaskError('Missing concentration for ' + name)
        raw = dict(zip(header, row))
        warnings = {key: value for key, value in raw.items()
                    if normalized(key) in ('warning', 'warnings', 'flags', 'quality')}
        results.append({'measurement_id': name, 'metrics': metrics, 'raw_cells': raw,
                        'instrument_messages': warnings, 'source_row': line,
                        'metadata': {key: row[index[key]].strip()
                                     for key in ['application', 'serialnumber']
                                     if key in index and row[index[key]].strip()}})
    if not results:
        raise TaskError('Empty report')
    return {'rows': results, 'metadata': metadata, 'delimiter': delimiter,
            'identity_column': identity_column, 'encoding': encoding}
