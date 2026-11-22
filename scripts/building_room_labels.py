"""Resolve known room names from the existing, pinned building assignments.

Lower storeys reuse F03 geometry, not its third-floor room numbers.  Only an
explicit assignment may supply a lower-storey number or use.  Furniture recipes
are not general room-use classifiers; the existing PhD identities are the
documented exception naming the doctoral writing rooms.
"""
import json
from pathlib import Path
import re

import assembly_model as assembly

ROOT = Path(__file__).resolve().parents[1]
USES = {'office': 'Büro', 'storage': 'Lager', 'secretariat': 'Sekretariat',
        'kitchen': 'Küche', 'non_laboratory': ''}
PHD_IDS = frozenset({'PhD1002', 'PhD2002', 'PhD3002'})
NUMBER = re.compile(r'^(\d+\.\d+[A-Za-z]?(?:/[A-Za-z])?|\d+[A-Za-z]?)\b')


def read(ref):
    """Verify source pins before resolving an editorial room label."""
    return json.loads(assembly.validate_reference(ref, root=ROOT).read_text())


def dependencies(spec):
    """List the direct semantic sources and nested room assignments used here."""
    raw = spec.get('_stack', spec)
    paths = [Path(__file__)]
    for key in ('laboratories', 'furnishings', 'microscopy', 'kitchenette'):
        ref = raw['sources'].get(key)
        if ref is None:
            continue
        source = read(ref)
        paths.append(ROOT/ref['source'])
        if key in {'microscopy', 'kitchenette'}:
            read(source['furnishings'])
            paths.append(ROOT/source['furnishings']['source'])
    return paths


def _source_label(area):
    """Remove presentation provenance, but never turn an open assignment into fact."""
    text = area.get('label')
    if not isinstance(text, str) or not text.strip() or '?' in text:
        return None
    if 'Zuordnung offen' in text or 'Aufteilung ungeklärt' in text:
        return None
    # These are explicitly qualified geometry descriptions, not part of a name.
    return text.split(' · registrierter Konzeptbezug', 1)[0].split(' (rear facade strip)', 1)[0].strip()


def _assigned_number(area, level):
    """An owner-confirmed area assignment authorizes its level-scoped number."""
    text = area.get('label') or ''
    found = NUMBER.match(text)
    if found is None:
        raise ValueError('A confirmed room use needs an existing room-number token')
    number = found.group(0)
    if level.startswith('OG'):
        if not number.startswith('3.'):
            raise ValueError('Upper-storey room assignment needs an F03 room token')
        return level[-1]+number[1:]
    return number


def labels(spec, plans):
    """Return known labels keyed by (level, area); absent knowledge stays absent.

    Records describe naming provenance, not the existence of a corridor door.
    The placement adapter must separately report named rooms without such a door.
    The supplied plans must be the effective per-level plans after variants.
    """
    raw = spec.get('_stack', spec)
    areas = {(level, area['id']): area for level, plan in plans.items()
             for area in plan['areas'] if area['kind'] not in {'corridor', 'void'}}
    result = {}

    def assign(key, text, basis, source, **extra):
        if key not in areas:
            return
        if not isinstance(text, str) or not text.strip():
            raise ValueError('A known room label needs explicit nonempty text')
        result[key] = {'text': text, 'basis': basis, 'source': source, **extra}

    for (level, identity), area in areas.items():
        if level not in {'KG', 'EG', 'OG3'}:
            continue
        text = _source_label(area)
        if text is not None:
            source = raw['sources']['basement' if level == 'KG' else
                                    'ground_floor' if level == 'EG' else 'floorplan']['source']
            assign((level, identity), text, 'effective_level_source_label', source,
                   source_label=area['label'])

    ref = raw['sources'].get('laboratories')
    if ref is not None:
        labs = read(ref)
        for item in labs.get('laboratories', [])+labs.get('basic_laboratories', []):
            assign((item['level'], item['area']), item['room']+' Labor',
                   item['basis'], ref['source'])
        for item in labs.get('excluded_rooms', []):
            key = (item['level'], item['area'])
            if key not in areas:
                continue
            if item['basis'] != 'owner_confirmed' or item['usage'] not in USES:
                raise ValueError('Only confirmed supported room uses may supply a sign')
            number = _assigned_number(areas[key], item['level'])
            suffix = USES[item['usage']]
            assign(key, number+(' '+suffix if suffix else ''), item['basis'], ref['source'],
                   usage=item['usage'])

    ref = raw['sources'].get('furnishings')
    if ref is not None:
        social = read(ref)
        for item in social['rooms']:
            for area_id in item['template_areas']:
                key = (item['level'], area_id)
                if key not in areas:
                    continue
                # Preserve confirmed uses while taking the current composite
                # room number from the furnishing binding, including Office3009.
                if item['id'] in PHD_IDS:
                    suffix = 'Doktorandenraum'
                elif item['recipe'] == 'kitchen':
                    suffix = 'Küche'
                else:
                    suffix = USES.get(result.get(key, {}).get('usage'), '')
                assign(key, item['room']+(' '+suffix if suffix else ''),
                       'explicit_furnishing_room_binding', ref['source'],
                       room_binding_id=item['id'])

    for key, name, expected in [('microscopy', 'Mikroskop', 'solidcraftbot.microscopy-furnishings/1'),
                                ('kitchenette', 'Küche', 'solidcraftbot.kitchenette-furnishings/1')]:
        ref = raw['sources'].get(key)
        if ref is None:
            continue
        equipment = read(ref)
        furnishing = read(equipment['furnishings'])
        if furnishing.get('format') != expected:
            raise ValueError('Room naming needs the supported equipment furnishing binding')
        identity = (furnishing['level'], furnishing['area'])
        if identity not in areas:
            continue
        number = furnishing.get('room') or _assigned_number(areas[identity], furnishing['level'])
        assign(identity, number+' '+name, 'explicit_equipment_room_binding',
               equipment['furnishings']['source'], equipment_source=ref['source'])
    return result
