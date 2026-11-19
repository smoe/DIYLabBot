"""Typed carrier manifests; identity/claims only, no transport state machine."""
import copy
import re

from manual_tasks import TaskError

FORMAT = 'solidcraftbot.transport-cargo-manifest/1'
KINDS = ('tube_rack', 'well_plate', 'tip_box')


def require(ok, message):
    if not ok:
        raise TaskError(message)


def identity(value):
    require(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,160}', value),
            'Explicit cargo identity required')


def validate(value, validate_vessels):
    require(isinstance(value, dict) and set(value) == {
        'format', 'carrier_id', 'payload_id', 'payload_kind', 'content_revision',
        'variant', 'vessels', 'wells', 'tips'}, 'Exact typed cargo manifest required')
    require(value['format'] == FORMAT and value['payload_kind'] in KINDS,
            'Unsupported cargo manifest version/kind')
    identity(value['carrier_id']); identity(value['payload_id'])
    require(type(value['content_revision']) is int and value['content_revision'] >= 0,
            'Cargo content revision required')
    for key in ('vessels', 'wells', 'tips'):
        require(isinstance(value[key], list), 'Cargo members must be lists')
    kind = value['payload_kind']
    require((kind == 'tip_box') == (value['variant'] in ('tip_10_ul', 'tip_200_ul', 'tip_1000_ul')),
            'A tip box needs its explicit supported variant')
    if kind != 'tip_box':
        require(value['variant'] is None and not value['tips'], 'Only tip boxes contain tips')
    if kind != 'tube_rack':
        require(not value['vessels'], 'Only tube racks contain these vessel records')
    elif value['vessels']:
        validate_vessels(value['vessels'])
    if kind != 'well_plate':
        require(not value['wells'], 'Only plates contain wells')
    slots, ids = set(), set()
    for tip in value['tips']:
        require(isinstance(tip, dict) and set(tip) == {'place_id', 'tip_id', 'state'},
                'Exact tip member required')
        identity(tip['tip_id'])
        require(isinstance(tip['place_id'], str) and re.fullmatch(r'[A-H](0[1-9]|1[0-2])', tip['place_id']) is not None,
                'Local 96-tip slot required')
        require(tip['state'] in ('unused', 'used', 'unknown') and tip['place_id'] not in slots
                and tip['tip_id'] not in ids, 'Duplicate or invalid tip member')
        slots.add(tip['place_id']); ids.add(tip['tip_id'])
    if kind == 'tip_box':
        require(len(slots) == 96, 'All tip identities, including consumed/unknown slots, must remain present')
    slots = set()
    for well in value['wells']:
        require(isinstance(well, dict) and set(well) == {'place_id', 'content_revision', 'materials'},
                'Exact well member required')
        identity(well['place_id'])
        require(well['place_id'] not in slots and type(well['content_revision']) is int
                and well['content_revision'] >= 0 and isinstance(well['materials'], list),
                'Unique well and content revision required')
        slots.add(well['place_id'])
        for material in well['materials']:
            identity(material)
        require(len(well['materials']) == len(set(well['materials'])), 'Duplicate well material')
    if kind == 'well_plate':
        require(bool(slots), 'Plate well identities required')
    require(len(claims(value)) == len(set(claims(value))), 'Duplicate cargo content identity')


def claims(value):
    result = ['carrier:' + value['carrier_id'], 'labware:' + value['payload_id']]
    for vessel in value['vessels']:
        result.append('vessel:' + vessel['vessel_id'])
        result.extend('material:' + material['material_id'] for material in vessel['materials'])
    for well in value['wells']:
        result.append('well:' + value['payload_id'] + '.' + well['place_id'])
        result.extend('material:' + material for material in well['materials'])
    result.extend('tip:' + tip['tip_id'] for tip in value['tips'])
    return result


def identities(value):
    """Historical transfers retain immutable identity while current usage evolves."""
    result = copy.deepcopy(value)
    result.pop('content_revision')
    for item in result['vessels'] + result['wells']:
        item.pop('content_revision')
    for tip in result['tips']:
        tip.pop('state')
    return result


def normalize(value):
    result = copy.deepcopy(value)
    for name in ('vessels', 'wells', 'tips'):
        result[name].sort(key=lambda item: item['place_id'])
    for vessel in result['vessels']:
        vessel['materials'].sort(key=lambda item: item['material_id'])
    for well in result['wells']:
        well['materials'].sort()
    return result
