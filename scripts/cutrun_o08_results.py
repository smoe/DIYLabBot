"""Normalize explicit O08 fixture exports using a separately bound measurement plan."""

from collections import defaultdict
import math

from cutrun_preparation import parse_json, require
from manual_results import normalized
from manual_tasks import TaskError, digest
from manual_workflow import keys, positive, text
from qubit_csv import UNITS


PLAN = 'solidcraftbot.cutrun-o08-synthetic-plan/1'
RESULTS = {'qpcr': 'solidcraftbot.cutrun-qpcr-results/1',
           'fluorometry': 'solidcraftbot.cutrun-qubit-results/1'}
EXPORTS = {'qpcr': 'solidcraftbot.cutrun-synthetic-qpcr-export/1',
           'fluorometry': 'solidcraftbot.cutrun-synthetic-qubit-export/1'}
PRODUCT_ROLES = {'h3k4me3', 'igg', 'input'}
E4_STATUSES = {'quantified', 'below_loq', 'not_detected', 'invalid', 'unknown'}


def _fixture(raw, expected_fields, label):
    value = parse_json(raw)
    keys(value, 'format source_kind ' + expected_fields, label)
    require(value['source_kind'] == 'test_fixture', 'O08 requires explicit synthetic provenance')
    return value


def _identity_list(value, label):
    require(isinstance(value, list) and value, 'Nonempty ' + label + ' required')
    for item in value:
        text(item, label)
    require(len(set(value)) == len(value), 'Duplicate ' + label)


def _finite(value, label):
    if type(value) not in (float, int) or not math.isfinite(value):
        raise TaskError('Finite ' + label + ' required')


def _volumes(row, method):
    volumes = row['volumes']
    keys(volumes, 'eluate_ul prepared_ul used_ul' + (' assay_ul' if method == 'fluorometry' else ''),
         'fixture preparation volumes')
    for name, value in volumes.items():
        positive(value, name)
    require(volumes['eluate_ul'] <= volumes['prepared_ul'] and volumes['used_ul'] <= volumes['prepared_ul'],
            'Preparation volumes cannot exceed the prepared aliquot')
    if method == 'fluorometry':
        require(volumes['used_ul'] < volumes['assay_ul'], 'Qubit assay volume must include working solution')
    positive(volumes['prepared_ul'] / volumes['eluate_ul'], 'preparative dilution')


def read_plan(raw):
    plan = _fixture(raw, 'run_id attempt_id plan_id revision method qc_bindings acquisition positions',
                    'O08 measurement plan')
    method = text(plan['method'], 'method')
    require(plan['format'] == PLAN and method in EXPORTS, 'Unsupported O08 synthetic measurement plan')
    for name in ('run_id', 'attempt_id', 'plan_id', 'revision'):
        text(plan[name], name)
    acq = plan['acquisition']
    method_fields = 'primer_id master_mix_lot' if method == 'qpcr' else 'kit_lot standard_lot standard_ids'
    keys(acq, 'instrument_id instrument_run_id container_id software_version assay_id assay_revision '
              'calibration_ref ' + method_fields, 'O08 acquisition')
    for name, value in acq.items():
        if name == 'standard_ids':
            _identity_list(value, 'synthetic Qubit standard identities')
            require(len(value) == 2, 'Both synthetic Qubit standards must be planned')
        elif name != 'calibration_ref' or method == 'fluorometry' or value is not None:
            text(value, name)
    rows = plan['positions']
    require(isinstance(rows, list) and rows, 'Explicit planned measurement positions required')
    identifiers, replicates, preparations = set(), defaultdict(set), {}
    for row in rows:
        keys(row, 'id role replicate reaction_id material_id vessel_id withdrawal_intent_id '
                  'preparation_id volumes', 'planned O08 position')
        identity, role = text(row['id'], 'position identity'), text(row['role'], 'position role')
        require(identity not in identifiers, 'Duplicate planned position')
        identifiers.add(identity)
        require(role in PRODUCT_ROLES or (role == 'ntc' and method == 'qpcr'), 'Unexpected O08 role')
        repeat = row['replicate']
        require(type(repeat) is int and repeat > 0 and repeat not in replicates[role],
                'Positive unique technical replicate index required per role')
        replicates[role].add(repeat)
        subject_fields = ('reaction_id', 'material_id', 'vessel_id', 'withdrawal_intent_id', 'preparation_id')
        if role == 'ntc':
            require(all(row[name] is None for name in (*subject_fields, 'volumes')),
                    'PCR NTC cannot claim a sample, aliquot or withdrawal')
            continue
        subject = tuple(text(row[name], name) for name in subject_fields)
        _volumes(row, method)
        volumes = row['volumes']
        preparation = (*subject, volumes['eluate_ul'], volumes['prepared_ul'])
        stored, used = preparations.get(row['preparation_id'], (preparation, 0))
        used += volumes['used_ul']
        require(stored == preparation and used <= volumes['prepared_ul'] + 1e-9,
                'Inconsistent or overallocated synthetic preparation')
        preparations[row['preparation_id']] = (preparation, used)
    if method == 'qpcr':
        require(set(replicates) == PRODUCT_ROLES | {'ntc'} and all(
            sorted(group) in ([1, 2], [1, 2, 3]) for group in replicates.values()),
            'Each qPCR role requires two or three predeclared technical wells')
    bindings = plan['qc_bindings']
    require(isinstance(bindings, dict) and set(bindings) == set(replicates), 'Explicit E4 QC binding required per planned role')
    for binding in bindings.values():
        keys(binding, 'assay_id criteria_ref', 'E4 role binding')
        text(binding['assay_id'], 'E4 assay binding')
        text(binding['criteria_ref'], 'E4 criteria reference')
    return plan


def _curves(points, name):
    if points is None:
        return
    require(isinstance(points, list), 'Expected synthetic ' + name + ' curve points')
    for point in points:
        require(isinstance(point, list) and len(point) == 2, 'Expected coordinate pairs for ' + name)
        for value in point:
            _finite(value, name + ' coordinate')


def _qpcr(row):
    raw, status, melt = row['raw_cq'], row['cq_status'], row['melt_status']
    require(status in ('determined', 'undetermined', 'invalid', 'not_run'), 'Unsupported qPCR acquisition status')
    require(melt in ('target', 'other', 'ambiguous', 'not_observed'), 'Unsupported synthetic melt status')
    require(raw is None or type(raw) in (int, float, str), 'Invalid raw Cq entry')
    if type(raw) in (int, float):
        _finite(raw, 'raw Cq')
    cq = None
    if status == 'determined':
        try:
            cq = positive(float(raw), 'observed Cq')
        except (TypeError, ValueError) as error:
            raise TaskError('Determined qPCR well requires a numeric Cq') from error
    _curves(row['amplification_curve'], 'amplification')
    _curves(row['melt_curve'], 'melt')
    assessment = row['result_status']
    if assessment in ('quantified', 'below_loq'):
        require(cq is not None and melt == 'target', 'Quantified or below-LoQ qPCR requires observed target signal')
    if assessment == 'not_detected':
        require(status == 'undetermined' and melt in ('other', 'not_observed'),
                'Synthetic not-detected claim contradicts qPCR acquisition')
    return {'cq': cq, 'value': cq if assessment == 'quantified' else None, 'unit': 'Cq'}


def _fluorometry(row, planned):
    basis, value, unit = row['concentration_basis'], row['concentration'], row['concentration_unit']
    require(basis in ('assay_solution', 'prepared_sample', 'original_eluate'), 'Unknown Qubit concentration basis')
    if row['rfu'] is not None:
        _finite(row['rfu'], 'synthetic fluorescence signal')
    factors = None
    original = None
    if row['result_status'] == 'quantified':
        factor = UNITS.get(normalized(text(unit, 'Qubit concentration unit')))
        require(factor is not None, 'Unsupported synthetic Qubit concentration unit')
        volumes = planned['volumes']
        factors = {'unit_to_ng_ul': factor,
                   'assay_to_prepared': volumes['assay_ul'] / volumes['used_ul'] if basis == 'assay_solution' else 1,
                   'prepared_to_eluate': volumes['prepared_ul'] / volumes['eluate_ul'] if basis != 'original_eluate' else 1}
        original = positive(value, 'Qubit reported concentration') * math.prod(factors.values())
        _finite(original, 'original eluate concentration')
    else:
        require(value is None and unit is None, 'Censored Qubit results require an empty concentration and unit')
    return {'value': original, 'unit': 'ng/uL', 'original_eluate_factors': factors}


def normalize_export(raw, plan, plan_sha256):
    method = plan['method']
    qpcr = method == 'qpcr'
    details = 'baseline threshold' if qpcr else 'standards'
    export = _fixture(raw, 'plan_sha256 acquisition analysis_revision supersedes_sha256 rows ' + details,
                      'O08 export')
    require(export['format'] == EXPORTS[method], 'Unsupported O08 synthetic export format')
    require(export['plan_sha256'] == plan_sha256 and export['acquisition'] == plan['acquisition'],
            'O08 export does not match its bound plan or acquisition')
    revision = text(export['analysis_revision'], 'analysis revision')
    if qpcr:
        text(export['baseline'], 'synthetic baseline setting')
        positive(export['threshold'], 'synthetic threshold setting')
    else:
        standards = export['standards']
        require(isinstance(standards, dict) and set(standards) == set(plan['acquisition']['standard_ids']),
                'Qubit export requires both bound calibration standards')
        for result in standards.values():
            keys(result, 'rfu observed', 'synthetic Qubit standard')
            _finite(result['rfu'], 'synthetic standard fluorescence')
            require(result['observed'] is True, 'Qubit calibration standard observation missing')
    provided = export['rows']
    require(isinstance(provided, list), 'O08 export rows must be an array')
    positions = {item['id']: item for item in plan['positions']}
    rows, issues = {}, []
    method_row = ('raw_cq cq_status melt_status amplification_curve melt_curve' if qpcr else
                  'concentration concentration_unit concentration_basis rfu')
    for index, row in enumerate(provided):
        keys(row, 'id preparation_id result_status flags reason ' + method_row, 'O08 export row')
        identity = text(row['id'], 'export position')
        require(identity in positions and identity not in rows, 'Foreign or duplicate O08 export position ' + identity)
        position = positions[identity]
        require(row['preparation_id'] == position['preparation_id'], 'O08 export preparation identity mismatch')
        status = text(row['result_status'], 'synthetic assessment status')
        require(status in E4_STATUSES or (not qpcr and status == 'above_range'), 'Unsupported O08 assessment status')
        text(row['reason'], 'synthetic assessment reason')
        flags = row['flags']
        if flags != []:
            _identity_list(flags, 'synthetic instrument flags')
        result = _qpcr(row) if qpcr else _fluorometry(row, position)
        if status in {'invalid', 'unknown', 'above_range'}:
            issues.append({'id': identity, 'code': status})
        if position['role'] == 'ntc' and (row['melt_status'] in ('target', 'ambiguous') or status != 'not_detected'):
            issues.append({'id': identity, 'code': 'ntc_requires_clarification'})
        rows[identity] = {**position, **row, **result, 'locator': '/rows/' + str(index)}
    for identity in positions.keys() - rows.keys():
        missing = {'result_status': 'unknown', 'value': None, 'locator': None}
        if qpcr:
            missing.update(cq_status='missing', cq=None, raw_cq=None)
        rows[identity] = {**positions[identity], **missing}
        issues.append({'id': identity, 'code': 'missing_position'})
    source = {'sha256': digest(raw), 'byte_count': len(raw), 'format': export['format']}
    return {'format': RESULTS[method], 'source_kind': 'test_fixture', 'execution_ready': False, 'run_id': plan['run_id'],
            'attempt_id': plan['attempt_id'], 'plan_id': plan['plan_id'], 'plan_revision': plan['revision'],
            'plan_sha256': plan_sha256, 'acquisition': plan['acquisition'], 'original': source,
            'analysis_revision': revision, 'supersedes_sha256': export['supersedes_sha256'],
            'analysis_settings': {name: export[name] for name in details.split()},
            'qc_bindings': plan['qc_bindings'], 'issues': sorted(issues, key=lambda row: (row['id'], row['code'])),
            'complete': all(row['locator'] is not None for row in rows.values()), 'mapping_ready': not issues,
            'rows': [rows[identity] for identity in positions]}
