"""Compose the pinned E1 preflight with the local SOP draft and CST reference."""

from pathlib import Path

import cutrun_manual_sources as manual
import cutrun_preparation as legacy
from manual_tasks import digest, encoded
from manual_workflow import keys, text


ROOT = legacy.ROOT
SOURCE = ROOT / 'model/cutrun-automation-v3.preparation.json'
FORMAT = 'solidcraftbot.cutrun-preparation/3'
RUNTIME = ('scripts/cutrun_preparation_v3.py', 'scripts/prepare_cutrun_automation_v3.py',
           'model/cutrun-automation-v3.schema.json')


def compile_plan(source=SOURCE, *, original_pdf=None):
    path = Path(source).resolve()
    content = path.read_bytes()
    profile = legacy.parse_json(content)
    keys(profile, 'format id base_preflight source_binding', 'CUT&RUN preflight /3')
    legacy.require(profile['format'] == FORMAT, 'Explicit CUT&RUN preflight /3 required')
    text(profile['id'], 'preflight identity')
    pins = {}
    base = legacy.read_reference(profile['base_preflight'], pins)
    legacy.require(base['format'] == 'solidcraftbot.cutrun-preparation/2', 'Preflight /3 requires the pinned /2 planning contract')
    plan = legacy.compile_plan(base)
    pins.update(plan['source_files_sha256'])
    binding = profile['source_binding']
    keys(binding, 'sop_draft manual_reference manufacturer confirmation', 'draft source binding')
    draft = binding['sop_draft']
    keys(draft, 'source source_sha256 id revision', 'machine-readable SOP draft')
    protocol = legacy.read_reference({key: draft[key] for key in ('source', 'source_sha256')}, pins)
    identity = {'id': 'SOP-CR-SKM29-H3K4me3', 'revision': '0.1'}
    legacy.require({key: draft[key] for key in identity} == protocol.get('sop') == identity
                   and protocol.get('format') == 'solidcraftbot.cutrun-manual-sop-protocol/1',
                   'The machine-readable source must identify the local SOP draft 0.1')
    reference = legacy.read_reference(binding['manual_reference'], pins)
    checked = manual.compile_profile(reference, original_pdf=original_pdf)
    legacy.require(all(reference['sources']['sop'][key] == expected for key, expected in identity.items())
                   and binding['manufacturer'] == {'kit': 'CST #86652', **reference['sources']['manufacturer']},
                   'SOP draft and manufacturer reference must agree')
    legacy.require(binding['confirmation'] == {'decision_id': 'O11', 'status': 'open', 'evidence_ref': None}
                   and any(item['id'] == 'O11' for item in checked['open_requirements']),
                   'E1 /3 cannot confer O11 approval')
    for name, checksum in checked['source_files_sha256'].items():
        legacy.require(pins.get(name, checksum) == checksum, 'Inconsistent source pin: ' + name)
        pins[name] = checksum
    if path.is_relative_to(ROOT):
        pins[str(path.relative_to(ROOT))] = digest(content)
    pins.update({name: digest((ROOT / name).read_bytes()) for name in RUNTIME})
    legacy.verify_source_pins(pins)

    blockers = [item for item in plan['execution_blockers'] if item != 'historical_sop_and_original_source_unbound']
    blockers.append('O11_local_sop_confirmation_open')
    verified = checked['original_pdf_verified']
    if not verified:
        blockers.append('manufacturer_original_bytes_not_verified')
    return {**plan, 'format': 'solidcraftbot.cutrun-preparation-plan/3', 'id': profile['id'],
            'source_binding': binding, 'manufacturer_original_verified': verified,
            'open_requirements': [*plan['open_requirements'],
                {'path': 'source_binding.confirmation', 'kind': 'local_decision_open', 'decision_id': 'O11'}],
            'planning_complete': False, 'execution_ready': False, 'execution_blockers': blockers,
            'source_files_sha256': pins,
            'effective_preparation_sha256': digest(encoded({
                'profile': profile, 'base': plan['effective_preparation_sha256']}).encode())}
