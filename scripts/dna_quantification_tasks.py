"""Strict B0 task fields and a journal-independent synthetic claim worker.

The leading contract generates the ROS action shape and validates the same
structured fields locally. No ROS, network, motion or material effect is run.
"""
import copy
import json
from pathlib import Path
import re
import uuid

from manual_tasks import TaskError, digest, encoded
from manual_workflow import ROOT, keys, text

SOURCE = ROOT / 'model/dna-quantification-tasks.protocol.json'
RULE_TYPES = {'id': 'string', 'optional_id': 'string', 'sha256': 'string',
              'enum': 'string', 'uint64': 'uint64', 'false': 'bool'}


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise TaskError('Duplicate task field: ' + key)
            result[key] = value
        return result
    def constant(value):
        raise TaskError('Nonfinite task JSON number: ' + value)
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError, TypeError) as error:
        raise TaskError('Invalid task JSON: ' + str(error)) from error


def _field(field):
    expected = 'name ros_type rule description' + (' values' if isinstance(field, dict) and field.get('rule') == 'enum' else '')
    keys(field, expected, 'task field')
    if not isinstance(field['name'], str) or not re.fullmatch(r'[a-z][a-z0-9_]*', field['name']):
        raise TaskError('ROS task field name required')
    if (not isinstance(field['rule'], str) or field['rule'] not in RULE_TYPES
            or field['ros_type'] != RULE_TYPES[field['rule']]):
        raise TaskError('Unsupported task field type/rule')
    text(field['description'], 'task field description')
    if field['rule'] == 'enum':
        values = field['values']
        if not isinstance(values, list) or not values or any(not isinstance(v, str) or not v.strip() for v in values):
            raise TaskError('Nonempty string task enum required')
        if len(set(values)) != len(values):
            raise TaskError('Duplicate task enum value')
    return copy.deepcopy(field)


def fields(contract, section):
    """Return derived field definitions; goal bindings are defined only once."""
    protocol = contract['protocol']
    goal = protocol['goal_fields']
    if section == 'goal':
        return copy.deepcopy(goal)
    if section == 'result':
        return copy.deepcopy(goal + protocol['result']['claim_fields'])
    if section == 'feedback':
        by_name = {field['name']: field for field in goal}
        return [copy.deepcopy(by_name[field['goal_ref']] if 'goal_ref' in field else field)
                for field in protocol['feedback_fields']]
    raise TaskError('Unknown task field section')


def load_contract(source=SOURCE):
    source = Path(source).resolve()
    if not source.is_relative_to(ROOT):
        raise TaskError('Task contracts must stay in this project')
    raw = source.read_bytes(); protocol = _json(raw)
    keys(protocol, 'format id mode operation ros_package action_name goal_fields result feedback_fields limitations', 'task contract')
    if (protocol['format'] != 'solidcraftbot.dna-quantification-tasks/1'
            or protocol['mode'] != 'synthetic_only' or protocol['operation'] != 'transfer_vessel'):
        raise TaskError('Only the synthetic B0 vessel task contract is supported')
    text(protocol['id'], 'task contract id')
    if protocol['ros_package'] != 'solidcraftbot_dna_interfaces' or protocol['action_name'] != 'TransferVessel':
        raise TaskError('Unsupported generated task package/action')
    if not isinstance(protocol['goal_fields'], list) or not protocol['goal_fields']:
        raise TaskError('Task goal field declarations required')
    protocol['goal_fields'] = [_field(field) for field in protocol['goal_fields']]
    keys(protocol['result'], 'echo_goal_fields claim_fields', 'task result declaration')
    if protocol['result']['echo_goal_fields'] is not True or not isinstance(protocol['result']['claim_fields'], list):
        raise TaskError('Task result must echo exact goal bindings')
    protocol['result']['claim_fields'] = [_field(field) for field in protocol['result']['claim_fields']]
    if not isinstance(protocol['feedback_fields'], list) or not protocol['feedback_fields']:
        raise TaskError('Task feedback declarations required')
    goal_names = {field['name'] for field in protocol['goal_fields']}
    for index, field in enumerate(protocol['feedback_fields']):
        if isinstance(field, dict) and set(field) == {'goal_ref'}:
            if not isinstance(field['goal_ref'], str) or field['goal_ref'] not in goal_names:
                raise TaskError('Unknown feedback goal reference')
        else:
            protocol['feedback_fields'][index] = _field(field)
    if not isinstance(protocol['limitations'], list) or not protocol['limitations']:
        raise TaskError('Explicit B0 limitations required')
    for value in protocol['limitations']:
        text(value, 'task limitation')
    contract = {'protocol': protocol, 'source_sha256': digest(raw),
                'source_path': str(source.relative_to(ROOT))}
    for section in ['goal', 'result', 'feedback']:
        names = [field['name'] for field in fields(contract, section)]
        if len(set(names)) != len(names):
            raise TaskError('Duplicate generated task field in ' + section)
    # Semantic endpoint validation consumes these names and rules. A new wire
    # shape needs an explicitly supported contract version, not silent drift.
    expected = {name: 'id' for name in ['request_id', 'goal_id', 'run_id', 'attempt_id',
                'context_id', 'sample_id', 'vessel_id', 'executing_agent_id']}
    expected.update({name: 'sha256' for name in ['source_manifest_sha256', 'task_contract_sha256']})
    expected.update(content_revision='uint64', operation='enum', mode='enum')
    for side in ['source', 'target']:
        expected[side + '_kind'] = 'enum'
        expected.update({side + '_' + name: 'optional_id' for name in ['rack_id', 'place_id', 'agent_id']})
    if {field['name']: field['rule'] for field in fields(contract, 'goal')} != expected:
        raise TaskError('Unsupported B0 goal field contract')
    claims = protocol['result']['claim_fields']
    if {field['name']: field['rule'] for field in claims} != {
            'claim_id': 'id', 'worker_boot_id': 'id', 'outcome': 'enum',
            'evidence': 'enum', 'motion_executed': 'false'}:
        raise TaskError('Unsupported B0 worker claim contract')
    enum_values = {field['name']: field['values'] for field in fields(contract, 'result') if field['rule'] == 'enum'}
    if enum_values != {'operation': ['transfer_vessel'], 'mode': ['synthetic_only'],
            'source_kind': ['rack', 'agent'], 'target_kind': ['rack', 'agent'],
            'outcome': ['claimed_performed', 'claimed_not_performed', 'claimed_unknown'],
            'evidence': ['worker_claim']}:
        raise TaskError('Unsupported B0 task modes or evidence')
    if [(field['name'], field['rule'], field.get('values')) for field in fields(contract, 'feedback')] != [
            ('goal_id', 'id', None), ('phase', 'enum', ['claim_ready'])]:
        raise TaskError('Unsupported B0 task feedback contract')
    return contract


def _contract(contract):
    return load_contract() if contract is None else contract


def _identifier(value, name, optional=False):
    if optional and value == '':
        return
    if (not isinstance(value, str) or not value.strip() or value != value.strip()
            or any(ord(character) < 32 for character in value)):
        raise TaskError('Nonempty unambiguous task ' + name + ' required')


def _decode(raw, section, contract):
    value = _json(raw) if isinstance(raw, (str, bytes, bytearray)) else copy.deepcopy(raw)
    declarations = fields(contract, section)
    if not isinstance(value, dict) or set(value) != {field['name'] for field in declarations}:
        raise TaskError('Exact generated ' + section + ' fields required')
    for field in declarations:
        name = field['name']; item = value[name]; rule = field['rule']
        if rule in {'id', 'optional_id'}:
            _identifier(item, name, optional=rule == 'optional_id')
        elif rule == 'sha256':
            if not isinstance(item, str) or not re.fullmatch(r'[0-9a-f]{64}', item):
                raise TaskError('Lowercase SHA-256 task ' + name + ' required')
        elif rule == 'uint64':
            if type(item) is not int or not 0 <= item < 2**64:
                raise TaskError('Unsigned 64-bit task ' + name + ' required')
        elif rule == 'enum':
            if not isinstance(item, str) or item not in field['values']:
                raise TaskError('Unsupported task ' + name)
        elif rule == 'false' and item is not False:
            raise TaskError('B0 task motion_executed must be false')
    return value


def _endpoints(goal):
    for side in ['source', 'target']:
        rack, place, agent = (goal[side + '_' + name] for name in ['rack_id', 'place_id', 'agent_id'])
        if goal[side + '_kind'] == 'rack':
            if not rack or not place or agent:
                raise TaskError('Rack task endpoint needs rack/place and no agent')
        elif not agent or rack or place:
            raise TaskError('Agent task endpoint needs agent and empty rack/place')
        if agent and agent != goal['executing_agent_id']:
            raise TaskError('Task custodian must be the assigned executing agent')
    if {goal['source_kind'], goal['target_kind']} != {'rack', 'agent'}:
        raise TaskError('B0 supports only rack-to-agent or agent-to-rack transfer')


def decode_goal(raw, contract=None):
    contract = _contract(contract); goal = _decode(raw, 'goal', contract)
    if goal['task_contract_sha256'] != contract['source_sha256']:
        raise TaskError('Task contract digest mismatch')
    _endpoints(goal)
    return goal


def goal_fingerprint(goal, contract=None):
    return digest(encoded(decode_goal(goal, contract)).encode())


def decode_claim(raw, goal=None, contract=None):
    contract = _contract(contract); claim = _decode(raw, 'result', contract)
    decoded_goal = decode_goal({field['name']: claim[field['name']] for field in fields(contract, 'goal')}, contract)
    if goal is not None and decoded_goal != decode_goal(goal, contract):
        raise TaskError('Worker claim does not echo the exact task goal')
    return claim


def decode_feedback(raw, goal=None, contract=None):
    contract = _contract(contract); feedback = _decode(raw, 'feedback', contract)
    if goal is not None and feedback['goal_id'] != decode_goal(goal, contract)['goal_id']:
        raise TaskError('Feedback belongs to a different task goal')
    return feedback


class MockTaskWorker:
    """Within-boot idempotent claim producer; never an inventory authority."""
    def __init__(self, agent_id, boot_id=None, contract=None):
        _identifier(agent_id, 'executing_agent_id')
        self.agent_id = agent_id; self.boot_id = uuid.uuid4().hex if boot_id is None else boot_id
        _identifier(self.boot_id, 'worker_boot_id')
        self.contract = copy.deepcopy(_contract(contract))
        self._claims = {}

    def dispatch(self, goal):
        goal = decode_goal(goal, self.contract)
        if goal['executing_agent_id'] != self.agent_id:
            raise TaskError('Task is assigned to another executing agent')
        fingerprint = goal_fingerprint(goal, self.contract)
        existing = self._claims.get(goal['goal_id'])
        if existing is not None:
            if existing[0] != fingerprint:
                raise TaskError('Goal id was already used with different task arguments')
            return copy.deepcopy(existing[1])
        claim = {**goal, 'claim_id': uuid.uuid4().hex, 'worker_boot_id': self.boot_id,
                 'outcome': 'claimed_performed', 'evidence': 'worker_claim', 'motion_executed': False}
        claim = decode_claim(claim, goal, self.contract)
        self._claims[goal['goal_id']] = (fingerprint, copy.deepcopy(claim))
        return claim
