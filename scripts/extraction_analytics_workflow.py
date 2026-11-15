"""Opt-in extracted-DNA NanoDrop/Qubit/TapeStation composition on one Root."""
import copy
import inspect

import material_ledger as ledger
from extraction_workflow import ExtractionWorkflow, require
from manual_tasks import TaskError
from manual_workflow import ObservationError
from extraction_analytics_stages import (contract, stage, initial_stage, build_adapter,
                                         DeviceHandle)


class ExtractionAnalyticsWorkflow(ExtractionWorkflow):
    REPORT_FORMAT = 'solidcraftbot.extraction-analytics-report/1'
    ENGINE = 'extraction_analytics_synthetic/1'
    SOURCE_MODULE = 'extraction_analytics_sources'
    RUN_PREFIX = 'SYN.EXTQC.'
    EFFECT_PREFIX = 'extraction_analytics'
    RECOVERY_PREFIX = 'extraction_analytics'
    WORK_AREA = 'SYN.ExtractionAnalytics.WorkArea'
    STEPS = ExtractionWorkflow.STEPS + ('start_device', 'device_action', 'resolve_device')
    RECOVERY_COMMANDS = ExtractionWorkflow.RECOVERY_COMMANDS | {'resolve_device', 'device_action'}
    CANCELLING_COMMANDS = RECOVERY_COMMANDS
    LIMITATIONS = ('Synthetic extraction and NanoDrop/Qubit/TapeStation observations only.',
                  'No real biochemical, hardware, network, robot, native-export, local-SOP or safety qualification.',
                  'One source sample, one measurement attempt per device, no automatic retry or old-journal migration.',
                  'Concentration observations do not prove fragment size or extraction yield; TapeStation limits remain explicit.')

    @classmethod
    def _prepare_create_state(cls, state, creation_context):
        require(creation_context is None, 'No external inventory handoff is supported')
        from extraction_analytics_sources import bind_run
        state['definition'] = bind_run(state['definition'], state['run_id'])
        state['inventory'] = ledger.initial_inventory(state['definition']['initial_materials'], state['definition']['initial_vessels'])
        state['analytics'] = {'active_device': None, 'stages': {}}
        state['resources'] = cls._resources(state)

    @classmethod
    def _resources(cls, state):
        result = set(super()._resources(state))
        for definition in contract(state)['devices'].values():
            result.add('instrument:' + definition['profile']['instrument']['id'])
            result.add('workspace:' + definition['profile']['workspace']['id'])
        return sorted(result)

    def device(self, device):
        stage(self.state, device)
        return DeviceHandle(self, device)

    def _analytics_ready(self, state):
        return all(state['analytics']['stages'].get(device, {}).get('local', {}).get('status') == 'completed'
                   for device in contract(state)['sequence'])

    def _start_device(self, state, actor_id, device):
        self._normal(state); self._extraction_complete(state)
        spec = contract(state)
        require(device in spec['sequence'], 'Unknown extraction measurement device')
        require(state['analytics']['active_device'] is None and device not in state['analytics']['stages'],
                'A device can start once and only after the previous device finishes')
        index = spec['sequence'].index(device)
        require(all(state['analytics']['stages'].get(name, {}).get('local', {}).get('status') == 'completed'
                    for name in spec['sequence'][:index]), 'NanoDrop must complete before Qubit')
        material = state['inventory']['materials'][spec['product_material_id']]
        require(material['vessel_id'] == spec['product_vessel_id'] and material['disposition'] not in {'discarded','consumed','quarantined'},
                'Identified retained extraction product required')
        require(state['inventory']['vessels'][spec['product_vessel_id']]['location'] == spec['product_home'],
                'Observe the DNA product at its declared home before starting a device')
        require(state['process']['qc']['request'] is None and not state['process']['qc']['preparations'],
                'NanoDrop and Qubit precede TapeStation preparation')
        state['analytics']['stages'][device] = initial_stage(state, device)
        state['analytics']['active_device'] = device

    def _pending(self, state):
        result = super()._pending(state)
        if result: return result
        analytics = state.get('analytics', {})
        active = analytics.get('active_device')
        if active:
            local = analytics['stages'][active]['local']
            return local.get('pending_measurement') or local.get('pending_operation')
        return None

    @staticmethod
    def _analytics_deviation(state, intent_id, reason):
        state['process']['deviations'].append({'command':'analytics_effect', 'intent_id':intent_id,
            'reason':reason, 'requires_abort':True, 'evidence':'synthetic_input'})
        state['recovery_required'], state['workspace_clear'] = 'analytics_process_deviation', False

    def _check_active(self, state, device):
        require(state['analytics']['active_device'] == device, 'Only the active device context accepts commands')
        return build_adapter(self, state, device)

    def _reserve(self, state, actor_id, device, adapter, pending):
        spec = contract(state); view = adapter.state
        if device == 'nanodrop':
            source = spec['product_material_id']; output = None
            inputs = [{'material_id':source, 'quantity':{'value':view['definition']['profile']['parameters']['sample_volume_ul'],'unit':'uL'},'consume_all':False}]
        elif pending['kind'] == 'preparation':
            prep = view['preparations'][pending['preparation_id']]
            params = view['definition']['profile']['parameters']
            source = (spec['product_material_id'] if prep['kind']=='sample' else spec['reagent_bindings']['standards'][prep['target_id']])
            volume = params['sample_volume_ul' if prep['kind']=='sample' else 'standard_volume_ul']
            inputs = [{'material_id':source,'quantity':{'value':volume,'unit':'uL'},'consume_all':False},
                      {'material_id':spec['reagent_bindings']['working_solution'],'quantity':{'value':params['assay_total_volume_ul']-volume,'unit':'uL'},'consume_all':False}]
            output = {'material_id':pending['vessel_id']+'.Assay','kind':'intermediate', 'vessel_id':pending['vessel_id'],'role':'qubit_'+prep['kind']}
        else:
            return
        binding = {'sample_id':spec['sample_id'],'product_material_id':spec['product_material_id'],
                   'product_vessel_id':spec['product_vessel_id'], 'inputs':[]}
        for item in inputs:
            material = state['inventory']['materials'][item['material_id']]
            require(material['vessel_id'] is not None, 'A live source material is required')
            vessel_id = material['vessel_id']
            binding['inputs'].append({'material_id':material['id'],'vessel_id':vessel_id,
                'content_revision':state['inventory']['vessels'][vessel_id]['content_revision']})
        if output:
            binding.update(output_material_id=output['material_id'],preparation_id=pending['preparation_id'])
        ledger.begin_effect(state, actor_id, pending['intent_id'], 'transformation' if output else 'withdrawal',
            inputs, [output] if output else [], 'extraction_analytics:'+device)
        adapter.context['bindings'][pending['intent_id']] = binding
        state['inventory_confirmation'] = None

    def _device_action(self, state, actor_id, device, operation, arguments):
        command=operation
        adapter = self._check_active(state, device); view = adapter.state
        require(isinstance(arguments, dict), 'Explicit device arguments required')
        allowed = set(view['definition']['protocol']['steps']) | {'take','discard_import'}
        require(command in allowed - {'rack_ready','advance_time','import_results','reconcile','cancel','finish_cancel'},
                'Use the extraction root lifecycle and artifact commands')
        if state['status']=='cancelling' or state['recovery_required']:
            require(command in {'place','dispose_vessel','discard_import'}, 'Resolve and reconcile before normal device work')
        else:
            require(not state['process']['deviations'] and not state['process']['aborted_phase'], 'Process deviations require controlled abort')
        require(view['actor_id'] in (None,actor_id), 'Wrong device actor')
        require(adapter.context['reconciled_session']==state['session'] or command in {'place','dispose_vessel','discard_import'},
                'Observe device validity after resume before continuing')
        deadline=view['deadline_s']
        if deadline is not None and state['logical_time_s']>=deadline and command not in {'place','dispose_vessel','discard_import'}:
            raise ObservationError('The active device context deadline expired')
        before = copy.deepcopy(adapter._pending(view))
        handler = getattr(adapter,'_'+command)
        try: inspect.signature(handler).bind(view,actor_id=actor_id,**arguments)
        except TypeError as error: raise TaskError('Invalid device arguments: '+str(error)) from error
        handler(view,actor_id=actor_id,**arguments)
        pending = adapter._pending(view)
        if pending and not before: self._reserve(state,actor_id,device,adapter,pending)
        if command=='release':
            state['analytics']['active_device'] = None
        state['inventory_confirmation'] = None

    def _import_results(self, state, artifact, file_name, origin='synthetic_export', device=None):
        if device is None:
            require(self._analytics_ready(state), 'Complete and accept NanoDrop and Qubit before TapeStation')
            return super()._import_results(state,artifact,file_name,origin)
        adapter = self._check_active(state,device)
        require(not state['recovery_required'] and state['status']=='working', 'Reconciled analytics context required')
        adapter._import_results(adapter.state,artifact,file_name,origin)
        spec = contract(state)
        for result in adapter.state['results'].values():
            if result.get('sample_id')==spec['sample_id']:
                result['extraction_source'] = {'sample_id':spec['sample_id'], 'product_material_id':spec['product_material_id'],
                    'product_vessel_id':spec['product_vessel_id'], 'context_id':adapter.context['id'],
                    'bindings':copy.deepcopy(adapter.context['bindings'])}

    def _confirm_tapestation_ready(self,state,actor_id,observations,reason):
        require(self._analytics_ready(state), 'Complete accepted NanoDrop and Qubit contexts before TapeStation')
        return super()._confirm_tapestation_ready(state,actor_id,observations,reason)

    def _begin_qc_preparation(self,state,actor_id,role,intent_id):
        require(self._analytics_ready(state), 'Complete NanoDrop and Qubit before TapeStation aliquot preparation')
        return super()._begin_qc_preparation(state,actor_id,role,intent_id)

    def _resolve_device(self,state,actor_id,device,pending_resolution,device_valid,reason):
        require(state['recovery_required'] or state['status']=='cancelling','Explicit device recovery required')
        require(type(device_valid) is bool,'Explicit blank/calibration validity observation required')
        require(pending_resolution is None or isinstance(pending_resolution,dict),'Device pending resolution must be an object or explicit null')
        require(isinstance(reason,str) and reason.strip(),'Device recovery reason required')
        adapter = self._check_active(state,device); view=adapter.state
        pending=copy.deepcopy(adapter._pending(view))
        outcome = None if pending_resolution is None else pending_resolution.get('outcome')
        if pending and outcome=='unknown' and state['pending_operation'] is not None:
            ledger.mark_unknown(state,actor_id,pending['intent_id'],reason)
        if pending and outcome=='not_performed' and state['pending_operation'] is not None:
            ledger.not_performed(state,actor_id,pending['intent_id'],reason)
        resolved = adapter._reconcile_device(view,actor_id,
            **({'blank_still_valid':device_valid} if device=='nanodrop' else {'calibration_still_valid':device_valid}),
            pending_resolution=pending_resolution)
        if outcome=='not_performed': self._analytics_deviation(state,pending['intent_id'],'Explicit nonperformed analytics operation; no automatic retry')
        if resolved is not False:
            adapter.context['reconciled_session']=state['session']
            if view['actor_id'] is not None:
                view['deadline_s']=state['logical_time_s']+view['definition']['profile']['parameters']['task_deadline_s']
                view['recovery_required']=None
        state['recovery_required'],state['workspace_clear']='analytics_inventory_reconciliation_required',False
        state['inventory_confirmation']=None

    def _reconcile(self,state,actor_id,observations,workspace_clear,reason=None):
        active=state['analytics']['active_device']
        if active:
            context=stage(state,active)
            require(context['reconciled_session']==state['session'],'Observe device validity before full inventory reconciliation')
            require(build_adapter(self,state,active)._pending(build_adapter(self,state,active).state) is None,
                    'Resolve the pending device operation before inventory reconciliation')
        result=super()._reconcile(state,actor_id,observations,workspace_clear,reason)
        if active:
            vessel=state['inventory']['vessels'][contract(state)['product_vessel_id']]
            if vessel['location']==contract(state)['product_home']:
                vessel['return_confirmation']={'actor_id':actor_id,'evidence':'synthetic_input',**vessel['location']}
                state['inventory_confirmation']=None
        return result

    def _advance_time(self,state,actor_id,seconds):
        super()._advance_time(state,actor_id,seconds)
        active=state['analytics']['active_device']
        if active:
            local=stage(state,active)['local'];deadline=local['deadline_s']
            if deadline is not None and state['logical_time_s']>=deadline:
                local['recovery_required']='device_deadline_exceeded'
                state['recovery_required'],state['workspace_clear']='analytics_device_deadline_exceeded',False

    def _cancel(self,state,actor_id,reason):
        result=super()._cancel(state,actor_id,reason)
        active=state['analytics']['active_device']
        if active: stage(state,active)['local']['status']='cancelling'
        return result

    def _set_disposition(self,state,actor_id,material_id,disposition,reason):
        spec=contract(state)
        require(not self._pending(state),'Resolve pending analytics and material work before dispositions')
        if state['status']!='cancelling':
            require(material_id!=spec['product_material_id'] or self._analytics_ready(state),
                    'Keep the DNA product through NanoDrop and Qubit')
            for context in state['analytics']['stages'].values():
                require(not any(meta.get('material_id')==material_id for meta in context['derived'].values())
                        or context['local']['status']=='completed','Dispose active Qubit assays through their device context')
        return super()._set_disposition(state,actor_id,material_id,disposition,reason)

    def _restored(self,state):
        spec=contract(state)
        require(state['inventory']['vessels'][spec['product_vessel_id']]['location']==spec['product_home'],
                'Return the retained DNA product vessel to its declared home before handover')
        active=state['analytics']['active_device']
        if active:
            adapter=build_adapter(self,state,active)
            adapter._restored(adapter.state)
        for device,context in state['analytics']['stages'].items():
            build_adapter(self,state,device)._verify_artifacts(build_adapter(self,state,device).state)
        return super()._restored(state)

    def _release(self,state,actor_id,workspace_clear):
        require(self._analytics_ready(state),'Accepted NanoDrop and Qubit completions required')
        return super()._release(state,actor_id,workspace_clear)

    def _report(self,state,trace):
        result=super()._report(state,trace)
        result['analytics']=copy.deepcopy(state['analytics'])
        result['nanodrop_hardware_executed']=False;result['qubit_hardware_executed']=False
        result['passed']=bool(result['passed'] and self._analytics_ready(state))
        return result
