"""Manual NanoDrop/Qubit operation views over one typed extraction inventory.

These views do not persist balances. Every withdrawal and assay preparation is
an ordinary material-ledger effect in the extraction Root's transaction.
"""
from collections.abc import MutableMapping
import copy
import math

import material_ledger as ledger
from manual_tasks import TaskError
from manual_workflow import ObservationError, text
from nanodrop_manual import NanoDropOperations
from qubit_manual import QubitOperations


def require(condition, message):
    if not condition:
        raise TaskError(message)


def contract(root):
    return root['definition']['execution']['analytics']


def stage(root, device):
    require(device in {'nanodrop', 'qubit'}, 'Unknown extraction analytics device')
    require(device in root['analytics']['stages'], 'Start this device explicitly first')
    return root['analytics']['stages'][device]


def initial_stage(root, device):
    spec = contract(root); identity = spec['context_ids'][device]
    definition = copy.deepcopy(spec['devices'][device])
    definition['profile']['id'] = identity
    adapter = ADAPTERS[device]
    local = {'status': 'ready', 'actor_id': None, 'attempt_id': identity + '.A01',
             'deadline_s': None, 'rack_ready': True, 'workspace_clear': False,
             'recovery_required': None, 'session': root['session'],
             'planned_measurements': {}, 'measurements': {}, 'imports': {},
             'results': {}, 'result_review': None, **adapter._initial_extra(identity, definition)}
    local.pop('logical_time_s', None)
    local.pop('derived_vessels', None)
    if device == 'nanodrop':
        local['planned_measurements'][spec['sample_id']] = identity + '.A01.M001'
    return {'id': identity, 'device': device, 'definition': definition, 'local': local,
            'derived': {}, 'bindings': {}, 'reconciled_session': root['session']}


class SourceView(MutableMapping):
    def __init__(self, root, context):
        self.root, self.device = root, context['device']
    @property
    def context(self): return stage(self.root,self.device)
    @property
    def spec(self): return contract(self.root)
    @property
    def vessel(self): return self.root['inventory']['vessels'][self.spec['product_vessel_id']]
    @property
    def material(self): return self.root['inventory']['materials'][self.spec['product_material_id']]

    def __getitem__(self, key):
        home = self.spec['product_home']
        fixed = {'id': self.spec['sample_id'], 'sample_id': self.spec['sample_id'],
                 'vessel_id': self.spec['product_vessel_id'], 'material_id': self.spec['product_material_id'],
                 'rack_slot': 1, 'original_place_id': home['place_id'],
                 'initial_volume_ul': self.material['initial_quantity']['value']}
        if key in fixed: return fixed[key]
        if key in {'remaining_volume_ul', 'volume_uncertain'}:
            amount = ledger.remaining(self.root, self.spec['product_material_id'])
            return (amount['value'] if key == 'remaining_volume_ul' else
                    amount['knowledge'] in {'unresolved_operation', 'confirmed_quantity_unknown'})
        if key == 'return_confirmation': return self.vessel.get('return_confirmation')
        return self.vessel[key]

    def __setitem__(self, key, value):
        if key in {'id', 'sample_id', 'vessel_id', 'material_id', 'rack_slot',
                   'original_place_id', 'initial_volume_ul', 'remaining_volume_ul'}:
            raise TaskError('Analytics identities and quantity projections are read only')
        if key == 'volume_uncertain':
            require(type(value) is bool, 'Explicit uncertainty flag required')
            # The persisted canonical intent, not a compatibility flag, owns uncertainty.
            return
        self.vessel[key] = copy.deepcopy(value)
        self.root['inventory_confirmation'] = None

    def __iter__(self):
        return iter(set(self.vessel) | {'id', 'sample_id', 'vessel_id', 'material_id', 'rack_slot',
                    'original_place_id', 'initial_volume_ul', 'remaining_volume_ul',
                    'volume_uncertain', 'return_confirmation'})

    def __len__(self): return sum(1 for _ in self)
    def __delitem__(self, key): raise TaskError('Source history cannot be deleted')


class SamplesView(MutableMapping):
    def __init__(self, root, context): self.root, self.device = root, context['device']
    @property
    def context(self): return stage(self.root,self.device)
    def __getitem__(self, key):
        if key != contract(self.root)['sample_id']: raise KeyError(key)
        return SourceView(self.root, self.context)
    def __iter__(self): return iter([contract(self.root)['sample_id']])
    def __len__(self): return 1
    def __setitem__(self, key, value): raise TaskError('Source bindings are immutable')
    def __delitem__(self, key): raise TaskError('Source bindings are immutable')


class VesselView(MutableMapping):
    def __init__(self, root, context, identity):
        self.root, self.device, self.identity = root, context['device'], identity
    @property
    def meta(self): return stage(self.root,self.device)['derived'][self.identity]
    @property
    def vessel(self): return self.root['inventory']['vessels'][self.identity]
    def __getitem__(self, key):
        return self.vessel['location'] if key == 'location' else self.meta[key]
    def __setitem__(self, key, value):
        if key == 'location':
            self.vessel['location'] = ledger.location(value)
            self.root['inventory_confirmation'] = None
        else: self.meta[key] = copy.deepcopy(value)
    def __delitem__(self, key): raise TaskError('Assay history cannot be deleted')
    def __iter__(self): return iter(set(self.meta) | {'location'})
    def __len__(self): return len(set(self.meta) | {'location'})


class DerivedView(MutableMapping):
    def __init__(self, root, context): self.root, self.device = root, context['device']
    @property
    def context(self): return stage(self.root,self.device)
    def __getitem__(self, key):
        if key not in self.context['derived']: raise KeyError(key)
        return VesselView(self.root, self.context, key)
    def __setitem__(self, key, value):
        require(key not in self.context['derived'] and value.get('id') == key,
                'New matching assay tube identity required')
        require(key in contract(self.root)['qubit_tubes'].values(), 'Predeclared physical Qubit tube required')
        vessel = self.root['inventory']['vessels'][key]
        require(vessel['location']['kind'] != 'discarded', 'A discarded tube cannot be reused')
        location = ledger.location(value['location'])
        require(not any(identity != key and v['location'] == location
                        for identity, v in self.root['inventory']['vessels'].items()), 'Physical holder is occupied')
        require(not any(m['vessel_id'] == key for m in self.root['inventory']['materials'].values()),
                'Assay tube is not empty')
        vessel['location'] = location
        vessel['responsibility'] = {'kind': 'actor', 'actor_id': self.root['actor_id']}
        self.context['derived'][key] = {k: copy.deepcopy(v) for k, v in value.items() if k != 'location'}
        self.root['inventory_confirmation'] = None
    def __delitem__(self, key): raise TaskError('Assay history cannot be deleted')
    def __iter__(self): return iter(self.context['derived'])
    def __len__(self): return len(self.context['derived'])


class DeviceState(MutableMapping):
    def __init__(self, root, device):
        self.root, self.device = root, device
    @property
    def context(self): return stage(self.root,self.device)
    @property
    def local(self): return self.context['local']
    def __getitem__(self, key):
        if key == 'samples': return SamplesView(self.root, self.context)
        if key == 'derived_vessels': return DerivedView(self.root, self.context)
        if key == 'definition': return self.context['definition']
        if key == 'resources': return self.root['resources']
        if key == 'logical_time_s': return self.root['logical_time_s']
        if key == 'run_id': return self.context['id']
        return self.local[key]
    def __setitem__(self, key, value):
        if key in {'samples', 'derived_vessels', 'definition', 'run_id'}:
            raise TaskError('Device projections are immutable')
        if key in {'resources', 'logical_time_s'}: self.root[key] = value
        else: self.local[key] = value
    def __delitem__(self, key):
        require(key in self.local, 'Device projections cannot be deleted'); del self.local[key]
    def __iter__(self):
        return iter(set(self.local) | {'samples', 'derived_vessels', 'definition', 'resources', 'logical_time_s', 'run_id'})
    def __len__(self): return sum(1 for _ in self)


class Adapter:
    EVENT_CLOCK = True
    DEADLINE_FIELD = 'deadline_s'
    def __init__(self, flow, root, device):
        self.flow, self.root, self.device = flow, root, device
        self.state = DeviceState(root, device)
        self.journal, self.run_id = flow.journal, self.context['id']
    @property
    def context(self): return stage(self.root,self.device)
    def _now(self, state): return self.root['logical_time_s']
    def _check_withdrawal(self, state, sample_id):
        amount = ledger.remaining(self.root, contract(self.root)['product_material_id'])
        require(amount['knowledge'] not in {'unresolved_operation', 'confirmed_quantity_unknown'},
                'Resolve the previous DNA withdrawal before another intent')
        return super()._check_withdrawal(state, sample_id)
    def _verify_artifacts(self, state):
        return super()._verify_artifacts(state)
    def _scientific_ready(self,state):
        super()._scientific_ready(state)
        from dna_quantification_ledger import classify_input
        spec=contract(self.root)
        results=[r for r in state['results'].values() if r.get('sample_id')==spec['sample_id']]
        require(len(results)==1,'Exactly one identified extracted-DNA result required')
        result=results[0]
        if self.device=='qubit' and any(any(value for value in row.get('instrument_messages',{}).values())
                for row in state['results'].values() if row.get('standard_id') is not None):
            raise ObservationError('Qubit calibration-standard flags need explicit review; normal acceptance is blocked')
        if self.device=='nanodrop':
            volume=state['measurements'][result['measurement_id']]['withdrawn_volume']['value'];total=None
        else:
            prep=state['preparations'][result['preparation_id']]
            volume,total=prep['sample_volume_ul'],prep['assay_total_volume_ul']
        evaluation=classify_input(result,self.device,spec['assays'][self.device],
            sample_volume_ul=volume,total_volume_ul=total,external_factor=1)
        self.context['evaluation']=evaluation
        if evaluation['status']!='in_range' or not evaluation['quantifiable']:
            raise ObservationError('The explicitly synthetic assay range/flag policy does not permit acceptance')
    @staticmethod
    def _finish_lifecycle(state, status):
        state.local.update(status=status, workspace_clear=True, session=None)
    def _live_binding(self, intent_id):
        binding = self.context['bindings'].get(intent_id)
        require(binding is not None, 'Persisted analytics material binding required')
        for row in binding['inputs']:
            material = self.root['inventory']['materials'][row['material_id']]
            vessel = self.root['inventory']['vessels'][row['vessel_id']]
            if material['vessel_id'] != row['vessel_id'] or vessel['content_revision'] != row['content_revision']:
                raise ObservationError('Analytics source identity or content revision changed')
        return binding
    def _consume(self, state, sample_id, volume_ul, deviation_reason=None):
        require(sample_id == contract(self.root)['sample_id'], 'Matching extracted sample required')
        if self.device == 'qubit': return  # one complete sample+buffer transformation below
        pending = self._pending(state); binding = self._live_binding(pending['intent_id'])
        ledger.confirm_effect(self.root, self.root['actor_id'], pending['intent_id'],
            [{'material_id': binding['inputs'][0]['material_id'], 'quantity': {'value': volume_ul, 'unit': 'uL'}}],
            [], deviation_reason or 'Explicit synthetic NanoDrop withdrawal and cleanup')
        self.root['inventory_confirmation'] = None
        planned = state['definition']['profile']['parameters']['sample_volume_ul']
        if not math.isclose(volume_ul, planned, rel_tol=0, abs_tol=1e-9):
            text(deviation_reason, 'dose deviation reason')
            self.flow._analytics_deviation(self.root, pending['intent_id'], 'Observed NanoDrop withdrawal differs from recipe')


class NanoDropAdapter(Adapter, NanoDropOperations):
    @staticmethod
    def _pending(state): return state['pending_measurement']


class QubitAdapter(Adapter, QubitOperations):
    def _begin_preparation(self, state, actor_id, kind, target_id, vessel_id,
                           observed_vessel_id, holder_id, place_id, empty_tube_confirmed):
        expected = contract(self.root)['qubit_tubes'].get(kind + ':' + target_id)
        require(vessel_id == expected, 'The selected source role has a predeclared Qubit tube')
        require(holder_id != state['definition']['profile']['instrument']['id'],
                'The Qubit measurement chamber is not a preparation holder')
        return super()._begin_preparation(state, actor_id, kind, target_id, vessel_id,
            observed_vessel_id, holder_id, place_id, empty_tube_confirmed)
    def _finish_preparation(self, state, intent_id, observed_vessel_id, volume_ul,
                            assay_total_volume_ul, mixed, observed_sample_id=None, deviation_reason=None):
        binding = self._live_binding(intent_id)
        super()._finish_preparation(state, intent_id, observed_vessel_id, volume_ul,
            assay_total_volume_ul, mixed, observed_sample_id, deviation_reason)
        inputs = [{'material_id': binding['inputs'][0]['material_id'], 'quantity': {'value': volume_ul, 'unit': 'uL'}},
                  {'material_id': binding['inputs'][1]['material_id'], 'quantity': {'value': assay_total_volume_ul-volume_ul, 'unit': 'uL'}}]
        ledger.confirm_effect(self.root, self.root['actor_id'], intent_id, inputs,
            [{'material_id': binding['output_material_id'], 'quantity': {'value': assay_total_volume_ul, 'unit': 'uL'}}],
            deviation_reason or 'Explicit synthetic Qubit source and working-solution preparation')
        self.context['derived'][observed_vessel_id]['material_id'] = binding['output_material_id']
        self.root['inventory_confirmation'] = None
        params = state['definition']['profile']['parameters']
        preparation = state['preparations'][binding['preparation_id']]
        wanted = params['sample_volume_ul' if preparation['kind'] == 'sample' else 'standard_volume_ul']
        if not math.isclose(volume_ul, wanted, abs_tol=1e-9, rel_tol=0) or not math.isclose(assay_total_volume_ul, params['assay_total_volume_ul'],abs_tol=1e-9,rel_tol=0):
            self.flow._analytics_deviation(self.root, intent_id, 'Observed Qubit preparation differs from recipe')
    def _begin_measurement(self, state, actor_id, preparation_id, measurement_id, observed_vessel_id, calibration_id=None):
        meta = self.context['derived'].get(observed_vessel_id)
        require(meta is not None and meta.get('material_id') is not None, 'Canonical prepared assay material required')
        material = self.root['inventory']['materials'][meta['material_id']]
        vessel = self.root['inventory']['vessels'][observed_vessel_id]
        require(material['vessel_id'] == observed_vessel_id and material['disposition'] not in {'discarded','consumed','quarantined'},
                'Prepared Qubit assay must remain in its physical tube')
        require(vessel['location']['kind'] == 'logical' and vessel['location']['holder_id'] != state['definition']['profile']['instrument']['id'],
                'Observe the prepared Qubit tube at its holder')
        super()._begin_measurement(state, actor_id, preparation_id, measurement_id, observed_vessel_id, calibration_id)
        pending = state['pending_operation']
        pending.update(material_id=material['id'], content_revision=vessel['content_revision'], return_place=copy.deepcopy(vessel['location']))
    def _finish_measurement(self, state, intent_id, observed_vessel_id, returned_to_holder):
        pending = state['pending_operation']
        require(pending and pending['intent_id'] == intent_id, 'Current Qubit measurement intent required')
        material = self.root['inventory']['materials'][pending['material_id']]
        vessel = self.root['inventory']['vessels'][pending['vessel_id']]
        if (material['vessel_id'] != pending['vessel_id'] or vessel['content_revision'] != pending['content_revision']
                or vessel['location'] != pending['return_place']):
            raise ObservationError('Qubit assay identity, content revision or return holder changed')
        return super()._finish_measurement(state, intent_id, observed_vessel_id, returned_to_holder)
    def _dispose_vessel(self, state, actor_id, vessel_id, observed_vessel_id, reason):
        meta = self.context['derived'].get(vessel_id)
        require(meta is not None, 'Known context tube required')
        prep = state['preparations'][meta['preparation_id']]
        if self.root['status'] != 'cancelling':
            require(prep['status'] == 'measured', 'Measure the prepared Qubit tube before disposing it')
            if prep['kind'] == 'standard': require(state['calibration']['status'] == 'approved', 'Approve calibration before disposing standards')
        super()._dispose_vessel(state, actor_id, vessel_id, observed_vessel_id, reason)
        material_id = meta.get('material_id')
        if material_id is not None:
            ledger.set_disposition(self.root, actor_id, material_id, 'discarded', reason)
        self.root['inventory_confirmation'] = None


ADAPTERS = {'nanodrop': NanoDropAdapter, 'qubit': QubitAdapter}

def build_adapter(flow, root, device): return ADAPTERS[device](flow, root, device)


class DeviceHandle:
    """Commands return the familiar ephemeral manual state view."""
    def __init__(self, flow, device): self.flow, self.device = flow, device
    @property
    def state(self): return DeviceState(self.flow.state, self.device)
    def act(self, command, actor_id, **data):
        if command == 'advance_time':
            self.flow.act('advance_time', actor_id, **data)
        else:
            self.flow.act('device_action', actor_id, device=self.device, operation=command, arguments=data)
        return self.state
    def import_content(self, content, actor_id, file_name='synthetic-report.csv'):
        self.flow.act('import_results', actor_id, artifact=content, device=self.device,
                      file_name=file_name, origin='synthetic_export')
        return self.state
