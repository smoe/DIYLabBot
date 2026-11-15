"""Separate water practice on the existing /3 material journal, no E4 binding.

Reuse the manual capture's observation/session plumbing, not its process rules.
Only explicit water declarations and the common material ledger hold quantities.
"""
import copy
import json
import math
from pathlib import Path
import uuid

from cutrun_manual_workflow import CutRunManualWorkflow
import manual_process_clock as clock
import material_ledger as ledger
from material_workflow import MaterialWorkflow
from material_workflow_sources import RUNTIME as COMMON_RUNTIME
from manual_tasks import TaskError, digest, encoded
from manual_workflow import ROOT, ObservationError, keys, text

PROTOCOL = 'model/water-transfer-practice.protocol.json'
FIXTURE = 'model/water-transfer-practice.fixture.json'
RUNTIME = tuple(dict.fromkeys((*COMMON_RUNTIME, 'scripts/cutrun_manual_workflow.py',
    'scripts/manual_process_clock.py', 'scripts/water_transfer_practice.py',
    'scripts/run_water_transfer_practice.py', PROTOCOL)))


def require(value, reason):
    if not value: raise TaskError(reason)


def volume(value):
    ledger.validate_quantity({'value': value, 'unit': 'uL'})
    require(value is not None, 'An explicit positive water quantity is required')
    return value


def protocol():
    value = json.loads((ROOT / PROTOCOL).read_text())
    keys(value, 'format engine medium paths steps scope', 'water protocol')
    require(value['format'] == 'solidcraftbot.water-transfer-practice/1'
            and value['engine'] == 'water_transfer_practice/1'
            and value['medium'] == 'water' and value['paths'] == list('ABC'), 'Closed water-only protocol required')
    require([(s['id'], s['path'], s['missing_receipt_exercise']) for s in value['steps']]
            == [('A1','A',False),('B1','B',False),('C1','C',False),('A2','A',True)], 'Three paths and the additional A2 documentation exercise required')
    for s in value['steps']:
        keys(s, 'id path missing_receipt_exercise', 'water step')
        require(type(s['missing_receipt_exercise']) is bool,'Explicit boolean fault requirement needed')
    return value


def definition(inventory, mode, inventory_bytes):
    source = protocol()
    keys(inventory, 'format medium actors paths', 'water inventory')
    require(inventory['format'] == 'solidcraftbot.water-transfer-inventory/1' and inventory['medium'] == 'water', 'Explicit water-only inventory required')
    require(mode in {'manual_observation', 'test_fixture'}, 'Explicit practice provenance required')
    actors = inventory['actors']
    require(isinstance(actors,list) and actors and all(isinstance(a,str) for a in actors) and len(set(actors))==len(actors), 'Distinct attributable actors required')
    for actor in actors: text(actor, 'practice actor')
    keys(inventory['paths'], 'A B C', 'three water paths')
    materials, vessels, used = [], [], set()
    for path, binding in inventory['paths'].items():
        keys(binding, 'source_material_id source_vessel_id target_vessel_id source_location target_location initial_volume_ul transfer_volume_ul', 'water path '+path)
        for name in ('source_material_id','source_vessel_id','target_vessel_id'):
            identity = text(binding[name], name)
            require(identity not in used, 'Water identities must be distinct across all paths');used.add(identity)
            require(identity.startswith('SYN.') if mode=='test_fixture' else not identity.startswith('SYN.'), 'Fixture and manual material identities must remain separate')
        initial, dose = volume(binding['initial_volume_ul']), volume(binding['transfer_volume_ul'])
        count = sum(s['path']==path for s in source['steps'])
        require(initial >= count*dose, 'Initial declared water cannot supply the planned transfers')
        materials.append({'id':binding['source_material_id'],'kind':'reagent','vessel_id':binding['source_vessel_id'],
                          'quantity':{'value':initial,'unit':'uL'},'origin_id':'water-only-practice'})
        for side in ('source','target'):
            vessels.append({'id':binding[side+'_vessel_id'],'location':binding[side+'_location']})
    ledger.initial_inventory(materials,vessels)
    require(math.isfinite(sum(m['quantity']['value'] for m in materials)),'Finite aggregate water quantity required')
    pins = {name:digest((ROOT/name).read_bytes()) for name in RUNTIME}
    if mode=='test_fixture':pins[FIXTURE]=digest((ROOT/FIXTURE).read_bytes())
    original = (ROOT/PROTOCOL).read_bytes()
    artifacts = {digest(original):original,digest(inventory_bytes):inventory_bytes}
    value = {'format':'solidcraftbot.material-workflow-definition/3','domain':'water_transfer_practice',
        'profile':{'type':source['engine'],'mode':mode,'parameters':{'task_deadline_s':None}},
        'clock_mode':'real_observations/1','clock_source_kind':'test_clock' if mode=='test_fixture' else 'system_clock',
        'practice_protocol':source,'water_inventory':copy.deepcopy(inventory),'manual_actors':copy.deepcopy(actors),
        'initial_materials':materials,'initial_vessels':vessels,'products':[],'protective_stop_bindings':{},
        'material_allocations':[{'material_id':m['id'],'vessel_id':m['vessel_id'],'declaration_sha256':digest(encoded(m).encode())} for m in materials],
        'source_files_sha256':pins,'runtime_source_files':list(pins),'initial_artifact_sha256':sorted(artifacts),
        'inventory_artifact_sha256':digest(inventory_bytes),'protocol_artifact_sha256':digest(original),
        'preparation_plan':{'execution_ready':False,'scope':source['scope']}}
    value['effective_profile_sha256']=digest(encoded(value).encode())
    return value, artifacts


class WaterPractice(CutRunManualWorkflow):
    ENGINE = 'water_transfer_practice/1'
    REPORT_FORMAT = 'solidcraftbot.water-transfer-practice-report/1'
    STEPS = ('accept_inventory','confirm_inventory','workspace_clear','claim','begin_transfer',
             'confirm_transfer','mark_unknown','resolve_transfer','set_disposition','close_practice')
    RECOVERY_COMMANDS = {'mark_unknown','resolve_transfer','reconcile','cancel','finish_cancel','set_disposition','confirm_inventory'}
    CANCELLING_COMMANDS = RECOVERY_COMMANDS

    @staticmethod
    def _verify_initial_artifacts(journal,state):
        d=state['definition']
        require(d.get('domain')=='water_transfer_practice','Separate water domain required')
        for checksum in d['initial_artifact_sha256']:journal.artifact(checksum)
        require(d['inventory_artifact_sha256'] in d['initial_artifact_sha256'] and d['protocol_artifact_sha256'] in d['initial_artifact_sha256'], 'Original water declarations missing')
        require(json.loads(journal.artifact(d['inventory_artifact_sha256']))==d['water_inventory'],'Initial water original differs from frozen declaration')
        require(json.loads(journal.artifact(d['protocol_artifact_sha256']))==d['practice_protocol'],'Protocol original differs from frozen source')

    @classmethod
    def create(cls,journal,inventory,run_id=None,*,mode='manual_observation',clock_provider=None,inventory_bytes=None):
        raw=encoded(inventory).encode() if inventory_bytes is None else inventory_bytes
        require(isinstance(raw,bytes) and json.loads(raw)==inventory,'Original inventory bytes do not match the declaration')
        d,artifacts=definition(inventory,mode,raw)
        provider=clock.SystemClock() if clock_provider is None else clock_provider
        sample=clock.validate_sample(provider.sample())
        require(sample['source_kind']==d['clock_source_kind'],'Real/test clock provenance cannot be mixed')
        identity=run_id or 'WATER.PRACTICE.'+uuid.uuid4().hex[:12]
        require(identity.startswith('SYN.') if mode=='test_fixture' else not identity.startswith('SYN.'),'Fixture and manual run identities must remain separate')
        flow=cls._create_definition(journal,d,run_id=identity,initial_artifacts=artifacts,extra_state={
            'clock':clock.initial(sample),'observation_context':None,'protective_operations':{},
            'manual':{'engine':cls.ENGINE,'observations':{}},
            'practice':{'attempts':{s['id']:[] for s in d['practice_protocol']['steps']},'uncertain_intents':[]}})
        flow.clock_provider=provider
        return flow

    def _before_transition(self,state):
        # No chemical deadlines or timing qualification in this water exercise.
        require(self._observation is not None,'Explicit observation required')
        sample=clock.validate_sample(self.clock_provider.sample())
        require(sample['source_kind']==state['definition']['clock_source_kind'],'Clock provenance changed')
        state['clock']=clock.refresh(state['clock'],sample)
        state['logical_time_s']=state['clock']['lower_s']
        state['observation_context']=copy.deepcopy(self._observation)

    def _claim(self,state,actor_id):
        require(state['status']=='ready' and state['workspace_clear'] and not state['actor_id'],'Accepted inventory and clear workplace required')
        state['actor_id'],state['status'],state['workspace_clear']=actor_id,'working',False
        self._assign_responsibility(state,actor_id)

    @staticmethod
    def _step(state,step_id):
        found=[s for s in state['definition']['practice_protocol']['steps'] if s['id']==step_id]
        require(len(found)==1,'Unknown water step')
        return found[0]

    @staticmethod
    def _done(state,step_id):
        ids=state['practice']['attempts'][step_id]
        return bool(ids and state['bookings'][ids[-1]]['outcome']=='performed')

    def _begin_transfer(self,state,actor_id,step_id,intent_id):
        self._claimed(state);text(intent_id,'water intent')
        step=self._step(state,step_id);attempts=state['practice']['attempts']
        if intent_id in state['bookings']:
            require(intent_id in attempts[step_id],'Intent belongs to another step');return False
        require(state['status']=='working' and not state['recovery_required'],'Reconcile before another transfer')
        steps=state['definition']['practice_protocol']['steps'];i=steps.index(step)
        require(all(self._done(state,s['id']) for s in steps[:i]) and not self._done(state,step_id),'Transfer sequence cannot be skipped or repeated')
        require(not attempts[step_id] or state['bookings'][attempts[step_id][-1]]['outcome']=='not_performed','Resolve the previous transfer; never redose after a missing receipt')
        b=state['definition']['water_inventory']['paths'][step['path']];dose=b['transfer_volume_ul']
        inputs=[{'material_id':b['source_material_id'],'quantity':{'value':dose,'unit':'uL'},'consume_all':False}]
        occupants=[m for m in state['inventory']['materials'].values() if m['vessel_id']==b['target_vessel_id']]
        for m in occupants:
            total=ledger.remaining(state,m['id'])['value'];volume(total)
            inputs.append({'material_id':m['id'],'quantity':{'value':total,'unit':'uL'},'consume_all':True})
        output={'material_id':self.run_id+'.'+step_id+'.Water.'+str(len(attempts[step_id])+1),
                'kind':'intermediate','vessel_id':b['target_vessel_id'],'role':'water_transfer_result'}
        ledger.begin_effect(state,actor_id,intent_id,'transformation',inputs,[output],'water_transfer_'+step_id)
        state['practice']['attempts'][step_id].append(intent_id)
        self._after_material_change(state,True)

    @staticmethod
    def _intent_step(state,intent_id):
        found=[s for s,ids in state['practice']['attempts'].items() if intent_id in ids]
        require(len(found)==1,'Unknown water transfer intent');return found[0]

    def _receipt(self,state,actor_id,intent_id,actual_volume_ul,target_total_ul,reason):
        step=self._step(state,self._intent_step(state,intent_id));request=state['bookings'][intent_id]['request'];volume(actual_volume_ul);volume(target_total_ul)
        prior=sum(i['quantity']['value'] for i in request['inputs'][1:])
        if not math.isclose(target_total_ul,prior+actual_volume_ul,rel_tol=0,abs_tol=1e-9):
            raise ObservationError('Observed water target total disagrees with source transfer and prior target amount')
        actual=[{'material_id':i['material_id'],'quantity':{'value':actual_volume_ul if n==0 else i['quantity']['value'],'unit':'uL'}} for n,i in enumerate(request['inputs'])]
        ledger.confirm_effect(state,actor_id,intent_id,actual,[{'material_id':request['outputs'][0]['material_id'],'quantity':{'value':target_total_ul,'unit':'uL'}}],reason)
        self._after_material_change(state,True)

    def _confirm_transfer(self,state,actor_id,intent_id,actual_volume_ul,target_total_ul,reason):
        self._claimed(state);step=self._step(state,self._intent_step(state,intent_id))
        require(not step['missing_receipt_exercise'],'The documentation exercise requires mark_unknown and explicit reconciliation')
        return self._receipt(state,actor_id,intent_id,actual_volume_ul,target_total_ul,reason)

    def _mark_unknown(self,state,actor_id,intent_id,reason):
        self._claimed(state);self._intent_step(state,intent_id)
        changed=ledger.mark_unknown(state,actor_id,intent_id,reason)
        if changed is False:return False
        if intent_id not in state['practice']['uncertain_intents']:state['practice']['uncertain_intents'].append(intent_id)
        state['recovery_required'],state['workspace_clear']='water_transfer_receipt_missing',False
        self._after_material_change(state,True)

    def _resolve_transfer(self,state,actor_id,intent_id,outcome,observations,workspace_clear,reason,actual_volume_ul=None,target_total_ul=None):
        self._claimed(state);self._intent_step(state,intent_id);text(reason,'reconciliation reason')
        require(state['recovery_required'],'No water reconciliation pending')
        if outcome=='unknown':
            require(actual_volume_ul is None and target_total_ul is None,'Unknown outcome cannot silently confirm quantities')
            return self._mark_unknown(state,actor_id,intent_id,reason)
        require(outcome in ('performed','not_performed'),'Explicit performed/not_performed/unknown outcome required')
        step=self._step(state,self._intent_step(state,intent_id))
        if outcome=='performed':
            require(not step['missing_receipt_exercise'] or intent_id in state['practice']['uncertain_intents'],'Record the missing-receipt exercise before resolving it')
            self._receipt(state,actor_id,intent_id,actual_volume_ul,target_total_ul,reason)
        else:
            require(actual_volume_ul is None and target_total_ul is None,'Nonperformance cannot invent actual quantities')
            ledger.not_performed(state,actor_id,intent_id,reason);self._after_material_change(state,True)
        self._reconcile(state,actor_id,observations,workspace_clear,reason)

    def _reconcile(self,state,actor_id,observations,workspace_clear,reason):
        text(reason,'water inventory reconciliation');require(type(workspace_clear)is bool,'Explicit workplace observation required')
        self._confirm_inventory(state,actor_id,observations)
        state['recovery_required']='unknown_water_effect' if state['pending_operation'] else None
        state['workspace_clear']=workspace_clear

    _set_disposition=MaterialWorkflow._set_disposition
    _restored=MaterialWorkflow._restored

    def _close_practice(self,state,actor_id,workspace_clear,reason):
        self._claimed(state);text(reason,'practice handover')
        require(not state['recovery_required'],'Resolve water effects before completion')
        require(all(self._done(state,s['id']) for s in state['definition']['practice_protocol']['steps']),'All three paths and the additional documentation exercise must complete')
        fault=state['practice']['attempts']['A2'][-1]
        require(fault in state['practice']['uncertain_intents'],'Missing-receipt exercise not evidenced')
        return MaterialWorkflow._release(self,state,actor_id,workspace_clear)

    def _report(self,state,trace):
        result=MaterialWorkflow._report(self,state,trace)
        steps=state['definition']['practice_protocol']['steps']
        amounts=[ledger.remaining(state,k)['value'] for k,m in state['inventory']['materials'].items() if m['disposition'] not in {'consumed','discarded'}]
        result.update(medium='water',recorded_current_water_total_ul=None if any(v is None for v in amounts) else sum(amounts),mode=state['definition']['profile']['mode'],practice_completed=state['status']=='completed',
            reference_success=False,e4_execution_ready=False,elapsed_time_qualified=False,physical_execution_verified=False,
            clock=copy.deepcopy(state['clock']),steps=[{**s,'completed':self._done(state,s['id']),'attempts':copy.deepcopy(state['practice']['attempts'][s['id']])} for s in steps],
            uncertain_intents=copy.deepcopy(state['practice']['uncertain_intents']),
            limitations=['Manual water observations or explicitly labelled software fixtures only; no hardware execution or E4 approval.',
                'The ledger transformation retires the former target-content identity and creates its combined water content; no water is consumed twice.',
                'Unknown elapsed time is retained; this practice has no timing acceptance criterion or chemical deadline.',
                'Recorded quantities do not qualify pipette accuracy, chemistry, temperature or biological performance.'])
        return result
