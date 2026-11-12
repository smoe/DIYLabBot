"""Versioned receipt provenance; real observations never relabel old fixtures."""
import copy

from manual_tasks import MATERIAL_DEFINITION_V3, MATERIAL_STATE_V3, TaskError, encoded

SOURCE_KINDS = {'human_observation', 'device_export', 'external_record', 'test_fixture'}
CONTEXT_FIELDS = {'observation_id', 'source_kind', 'observed_at', 'source_ref', 'artifact_sha256'}


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise TaskError('Nonempty ' + label + ' required')
    return value


def provenance(state):
    """Return stable provenance fields, without a changing capture timestamp.

    The manual runtime validates actor permissions, absolute times and source
    associations. This shared layer requires an explicit detached context and
    never manufactures one from a synthetic value or a journal timestamp.
    """
    if state.get('format') != MATERIAL_STATE_V3:
        return {'evidence': 'synthetic_input'}
    if state.get('definition', {}).get('format') != MATERIAL_DEFINITION_V3:
        raise TaskError('Manual observations require the matching version-3 definition')
    context = state.get('observation_context')
    if not isinstance(context, dict) or set(context) != CONTEXT_FIELDS:
        raise TaskError('Explicit manual observation context required')
    _text(context['observation_id'], 'observation identity')
    if not isinstance(context['source_kind'], str) or context['source_kind'] not in SOURCE_KINDS:
        raise TaskError('Explicit supported observation source kind required')
    observed = context['observed_at']
    if observed is not None and (not isinstance(observed, dict)
                                or set(observed) != {'earliest_utc', 'latest_utc'}):
        raise TaskError('Explicit observed UTC interval or unknown time required')
    checksum = context['artifact_sha256']
    if checksum is not None and (not isinstance(checksum, str) or len(checksum) != 64
            or any(character not in '0123456789abcdef' for character in checksum)):
        raise TaskError('Observation artifact reference must be a SHA-256 or null')
    try:
        encoded(context)
    except (TypeError, ValueError) as error:
        raise TaskError('Observation context must contain finite JSON values') from error
    return {'evidence': 'test_fixture' if context['source_kind'] == 'test_fixture' else 'manual_observation',
            'observation': copy.deepcopy(context)}


def receipt(state, actor_id, reason, **extra):
    _text(actor_id, 'synthetic actor identity' if state.get('format') != MATERIAL_STATE_V3 else 'actor identity')
    _text(reason, 'evidence reason')
    return {'actor_id': actor_id, 'reason': reason, **provenance(state), **extra}


def inventory_receipt(state, actor_id, inventory_sha256):
    _text(actor_id, 'inventory actor identity')
    return {'actor_id': actor_id, **provenance(state), 'inventory_sha256': inventory_sha256}
