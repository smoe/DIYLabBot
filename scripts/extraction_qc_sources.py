"""One TapeStation binding compiler for synthetic extraction compositions."""
import copy
import math

from manual_tasks import TaskError


def require(condition, message):
    if not condition:
        raise TaskError(message)


def positive(value, label):
    require(type(value) in (int, float) and math.isfinite(value) and value > 0,
            'Finite positive ' + label + ' required')
    return value


def build_tapestation_qc(profile, instrument, ts_protocol, verified_ts, lineage,
                        reagent_bindings, material_by_id, output_identities,
                        fixture, dose_totals):
    """Build the same separated sample/ladder contract without stock effects.

    The caller owns the canonical declarations and output-identity set. This
    helper only extends their detached compiler proposal; no runtime state or
    material quantities are introduced by importing this module.
    """
    policy = profile['qc_policy']
    require(isinstance(policy, dict) and set(policy) == {'minimum_din', 'minimum_fragment_size_bp'},
            'Explicit synthetic QC policy required')
    require(1 <= positive(policy['minimum_din'], 'synthetic DIN threshold') <= 10,
            'DIN fixture threshold outside 1..10')
    positive(policy['minimum_fragment_size_bp'], 'synthetic fragment-size threshold')
    assay = ts_protocol['assay']
    qc = {'instrument_id': instrument['id'], 'planning_reference': instrument['planning_reference'],
          'selected_model': instrument['selected_model'], 'assay_id': assay['id'],
          'screen_tape_id': profile['id'] + '.ScreenTape01',
          'assay_revision': assay['revision'], 'protocol': copy.deepcopy(verified_ts),
          'policy': copy.deepcopy(policy), 'policy_scope': 'synthetic_fixture_only_not_manufacturer_or_biological_acceptance',
          'parameters': copy.deepcopy(assay['preparation']),
          'required_checks': ['assay_and_reagent_identity_confirmed', 'separate_ladder_preparation_confirmed',
                              'instrument_and_manual_operator_confirmed', 'sample_mapping_confirmed']}
    # Independent effects deliberately prevent a false DNA ancestry on ladder.
    for role, source_id, token, volume, buffer_volume, lane, vessel in [
        ('sample', lineage['product_id'], 'ts_sample', assay['sample_volume_ul'], assay['sample_buffer_volume_ul'],
         assay['fixture_sample_position'], profile['extra_vessels']['qc_sample']),
        ('ladder', reagent_bindings['TSLadder'], 'ts_ladder', assay['ladder_volume_ul'], assay['ladder_buffer_volume_ul'],
         assay['ladder_position'], profile['extra_vessels']['qc_ladder'])]:
        material_id = profile['sample_id'] + ('.TS.SampleAliquot' if role == 'sample' else '.TS.LadderMix')
        require(material_id not in output_identities, 'QC material aliases an existing process object')
        output_identities.add(material_id)
        output = {'material_id': material_id, 'kind': 'intermediate', 'vessel_id': vessel, 'role': 'tapestation_' + role}
        qc[role] = {'lane_id': lane, 'effect': {
            'inputs': [{'material_id': source_id, 'quantity': {'value': volume, 'unit': 'uL'}, 'consume_all': False},
                       {'material_id': reagent_bindings['TSBuffer'], 'quantity': {'value': buffer_volume, 'unit': 'uL'}, 'consume_all': False}],
            'outputs': [output], 'fixture_actual_outputs': [{'material_id': material_id, 'quantity': copy.deepcopy(fixture[token])}]}}
        for declaration in qc[role]['effect']['inputs']:
            if declaration['material_id'] in material_by_id and material_by_id[declaration['material_id']]['kind'] == 'reagent':
                identity = declaration['material_id']
                dose_totals[identity] = dose_totals.get(identity, 0) + declaration['quantity']['value']
    require(fixture['product']['value'] is not None and fixture['product']['value'] >= assay['sample_volume_ul'],
            'Synthetic DNA product receipt cannot supply its declared QC aliquot')
    return qc
