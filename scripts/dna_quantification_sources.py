"""Pinned recipe for a rack-based, synthetic NanoDrop -> Qubit HS run."""
import copy
import json
from pathlib import Path

from manual_tasks import TaskError, encoded, digest
from manual_workflow import ROOT, keys, positive, text
import nanodrop_manual
import qubit_manual
import rack_slots

SOURCE = ROOT / 'model/dna-quantification.synthetic.json'
RUNTIME = ['dna_quantification.py', 'dna_quantification_sources.py',
           'dna_quantification_ledger.py', 'dna_quantification_stages.py',
           'dna_quantification_demo.py', 'run_dna_quantification.py']


def load(source=SOURCE):
    source = Path(source).resolve()
    if not source.is_relative_to(ROOT):
        raise TaskError('DNA run sources must stay in this project')
    hashes = {}

    def remember(path):
        hashes[str(path.relative_to(ROOT))] = digest(path.read_bytes())

    def read(ref):
        keys(ref, 'source source_sha256', 'DNA source reference')
        path = (ROOT / ref['source']).resolve()
        if not path.is_relative_to(ROOT / 'model') or not path.is_file():
            raise TaskError('DNA source reference must resolve inside model/')
        if digest(path.read_bytes()) != ref['source_sha256']:
            raise TaskError('Changed DNA source: ' + ref['source'])
        remember(path)
        return path, json.loads(path.read_text(encoding='utf-8'))

    remember(source)
    profile = json.loads(source.read_text(encoding='utf-8'))
    keys(profile, 'format id mode protocol device_profiles rack dilution_rack samples parameters diluent assumptions', 'DNA profile')
    if profile['format'] != 'solidcraftbot.dna-quantification-profile/1' or profile['mode'] != 'synthetic_only':
        raise TaskError('Synthetic DNA profile required')
    text(profile['id'], 'DNA profile id')
    _, protocol = read(profile['protocol'])
    keys(protocol, 'format id mode sequence dilution_presets repeat_policy assays limitations', 'DNA protocol')
    if (protocol['format'] != 'solidcraftbot.dna-quantification-protocol/1'
            or protocol['mode'] != 'synthetic_only' or protocol['sequence'] != ['nanodrop', 'qubit']):
        raise TaskError('Sequential synthetic NanoDrop -> Qubit contract required')
    expected = {'none': (1, 0, 1), '1+9': (1, 9, 10), '1+19': (1, 19, 20)}
    if not isinstance(protocol['dilution_presets'], dict) or set(protocol['dilution_presets']) != set(expected):
        raise TaskError('Only undiluted, 1+9 and 1+19 are supported')
    for name, values in expected.items():
        preset = protocol['dilution_presets'][name]
        keys(preset, 'sample_parts diluent_parts factor label_de', 'dilution preset')
        if (any(type(preset[k]) is not int for k in ['sample_parts', 'diluent_parts', 'factor'])
                or tuple(preset[k] for k in ['sample_parts', 'diluent_parts', 'factor']) != values):
            raise TaskError('Dilution parts and factor disagree')
        text(preset['label_de'], 'dilution label')
    policy = protocol['repeat_policy']
    if policy != {'source': 'fresh_original', 'new_pair_on_dilution': True,
                  'max_attempts_per_sample': 3, 'on_nanodrop_above_range': 'offer_dilution_before_qubit',
                  'on_nanodrop_below_range': 'continue_qubit_then_review',
                  'on_unknown_range': 'review_without_auto_accept', 'repeat_preset': False}:
        raise TaskError('Unsupported DNA repeat policy')
    if profile['assumptions'] != {'input_rack_delivered_on_table': True,
                                   'return_policy': 'original_rack_place',
                                   'new_dilutions_from_original_only': True}:
        raise TaskError('Explicit table-rack and fresh-original dilution assumptions required')
    keys(profile['device_profiles'], 'nanodrop qubit', 'DNA device profiles')
    devices = {}
    for name, loader in [('nanodrop', nanodrop_manual.load_profile), ('qubit', qubit_manual.load_profile)]:
        path, _ = read(profile['device_profiles'][name])
        devices[name] = loader(path)
        hashes.update(devices[name]['source_files_sha256'])
    if (devices['nanodrop']['profile']['instrument']['type'] != 'nanodrop_one_wifi'
            or devices['qubit']['profile']['instrument']['type'] != 'qubit_4'):
        raise TaskError('This target binds NanoDrop One pedestal and Qubit 4; qualify other range profiles separately')
    if devices['nanodrop']['profile']['workspace']['frame'] != devices['qubit']['profile']['workspace']['frame']:
        raise TaskError('Both device contexts must reference the same declared table frame')
    rack_places = {}
    for key in ['rack', 'dilution_rack']:
        rack = profile[key]
        keys(rack, 'id definition', key)
        text(rack['id'], 'rack instance')
        _, spec = read(rack['definition'])
        if rack['definition'] != devices['nanodrop']['profile']['rack']['definition']:
            raise TaskError('First DNA workflow uses the existing guided rack contract')
        if rack['definition'] != devices['qubit']['profile']['rack']['definition']:
            raise TaskError('Qubit source places must use that same guided rack contract')
        rack_places[key] = rack_slots.places(spec)
    if profile['rack']['id'] == profile['dilution_rack']['id']:
        raise TaskError('Original and dilution rack instances must differ')
    samples = profile['samples']
    if not isinstance(samples, list) or not 1 <= len(samples) <= len(rack_places['rack']):
        raise TaskError('A nonempty rack-bounded sample manifest is required')
    for sample in samples:
        keys(sample, 'id vessel_id rack_slot initial_volume_ul', 'DNA sample')
        text(sample['id'], 'sample id'); text(sample['vessel_id'], 'vessel id')
        if type(sample['rack_slot']) is not int or sample['rack_slot'] not in {p['slot'] for p in rack_places['rack']}:
            raise TaskError('Unknown original rack slot')
        if sample['initial_volume_ul'] is not None:
            positive(sample['initial_volume_ul'], 'initial sample volume', zero=True)
    for key in ['id', 'vessel_id', 'rack_slot']:
        if len({sample[key] for sample in samples}) != len(samples):
            raise TaskError('Duplicate DNA manifest ' + key)
    keys(profile['parameters'], 'nanodrop_sample_volume_ul qubit_sample_volume_ul dilution_sample_volume_ul task_deadline_s synthetic_calibration_validity_s', 'DNA parameters')
    for key, value in profile['parameters'].items(): positive(value, key)
    keys(profile['diluent'], 'id qualification', 'diluent')
    text(profile['diluent']['id'], 'diluent id'); text(profile['diluent']['qualification'], 'diluent qualification')
    keys(protocol['assays'], 'nanodrop qubit', 'assay targets')
    nd, qb = protocol['assays']['nanodrop'], protocol['assays']['qubit']
    keys(nd, 'id sample_volume_ul_min range reference', 'NanoDrop target')
    keys(qb, 'id catalog_numbers sample_volume_ul_min sample_volume_ul_max assay_total_volume_ul standard_volume_ul incubation_min_s range reference result_basis_reference', 'Qubit target')
    keys(nd['range'], 'basis unit lower upper lower_kind', 'NanoDrop range')
    keys(qb['range'], 'basis unit lower upper', 'Qubit range')
    if (nd['id'] != 'NanoDrop.One.dsDNA.Microvolume'
            or nd['range']['basis'] != 'selected_input_concentration'
            or nd['range']['unit'] != 'ng/uL'
            or nd['range']['lower_kind'] != 'limit_of_detection_not_lloq'):
        raise TaskError('Explicit NanoDrop One dsDNA pedestal target required')
    if (qb['id'] != 'Qubit.dsDNA.HS' or qb['range']['basis'] != 'assay_dna_mass'
            or qb['range']['unit'] != 'ng' or qb['assay_total_volume_ul'] != 200):
        raise TaskError('Explicit 200 uL dsDNA HS target required')
    for key in ['sample_volume_ul_min', 'sample_volume_ul_max', 'assay_total_volume_ul',
                'standard_volume_ul', 'incubation_min_s']:
        positive(qb[key], 'HS target ' + key)
    positive(nd['sample_volume_ul_min'], 'NanoDrop target sample volume')
    if (qb['sample_volume_ul_min'] > qb['sample_volume_ul_max']
            or qb['sample_volume_ul_max'] >= qb['assay_total_volume_ul']
            or qb['standard_volume_ul'] >= qb['assay_total_volume_ul']):
        raise TaskError('Inconsistent HS target volumes')
    for assay in [nd, qb]:
        rule = assay['range']
        for key in ['lower', 'upper']: positive(rule[key], 'assay range ' + key)
        if rule['lower'] >= rule['upper']: raise TaskError('Inconsistent assay range')
        if not isinstance(assay['reference'], dict) or not {'url', 'document', 'revision'} <= set(assay['reference']):
            raise TaskError('Explicit versioned assay reference required')
        for key in ['url', 'document', 'revision']: text(assay['reference'][key], 'assay reference ' + key)
    params = profile['parameters']
    if params['nanodrop_sample_volume_ul'] < nd['sample_volume_ul_min']:
        raise TaskError('NanoDrop sample volume below target minimum')
    if not qb['sample_volume_ul_min'] <= params['qubit_sample_volume_ul'] <= qb['sample_volume_ul_max']:
        raise TaskError('Qubit sample volume outside HS target interval')
    if params['synthetic_calibration_validity_s'] <= qb['incubation_min_s']:
        raise TaskError('Synthetic calibration window must cover sample incubation')
    # These are derived runtime contexts, not edits to the standalone fixtures.
    devices['nanodrop']['profile']['parameters']['sample_volume_ul'] = params['nanodrop_sample_volume_ul']
    devices['qubit']['profile']['parameters'].update(
        sample_volume_ul=params['qubit_sample_volume_ul'], assay_total_volume_ul=qb['assay_total_volume_ul'],
        standard_volume_ul=qb['standard_volume_ul'], incubation_min_s=qb['incubation_min_s'],
        incubation_max_s=None, calibration_validity_s=params['synthetic_calibration_validity_s'],
        task_deadline_s=params['task_deadline_s'])
    devices['qubit']['protocol']['assay'].update(id='SYN.DNA.HS', revision='1')
    for definition in devices.values():
        definition['profile']['parameters']['task_deadline_s'] = params['task_deadline_s']
        definition['effective_profile_sha256'] = digest(encoded(definition['profile']).encode())
    for filename in RUNTIME: remember(ROOT / 'scripts' / filename)
    remember(ROOT / 'model/dna-quantification.schema.json')
    return {'profile': profile, 'protocol': protocol, 'devices': devices, 'rack_places': rack_places,
            'work_area': copy.deepcopy(devices['nanodrop']['profile']['workspace']),
            'source_files_sha256': hashes, 'source_path': str(source.relative_to(ROOT)),
            'clock_mode': 'synthetic_events/1'}
