"""Compile generic liquid-handling requests into a checked, ideal planning projection.

This module neither dispatches commands nor books material in a workflow ledger.
"""
import copy
from decimal import Decimal, localcontext
import math
from pathlib import Path

import pipetting_station as station

ROOT=station.ROOT
SOURCE=ROOT/'model/pipetting-matrix-96.protocol.json'
require=station.require
exact=station.exact


def quantity(value, positive=False):
    if isinstance(value,Decimal):
        require(value.is_finite() and (value>0 if positive else value>=0),'Finite nonnegative quantity required')
        return value
    station.number(value, positive=positive)
    return Decimal(str(value))


def total(components):
    return sum(components.values(), Decimal(0))


def location(value):
    exact(value,'labware well','liquid location')
    require(all(isinstance(v,str) and v for v in value.values()),'Named labware and well required')
    return value['labware']+'.'+value['well']


def json_quantities(value):
    if isinstance(value,Decimal):return float(value)
    if isinstance(value,dict):return {k:json_quantities(v) for k,v in value.items()}
    if isinstance(value,list):return [json_quantities(v) for v in value]
    return value


class Planner:
    def __init__(self, protocol, context, demand_only=False):
        self.protocol=protocol;self.context=context
        self.demand_only=demand_only
        self.contents={key:{} for key in context['locations']}
        self.dead={key:Decimal(0) for key in self.contents}
        self.homogeneous={key:True for key in self.contents}
        self.actions=[];self.transfers=[];self.skipped=[];self.tool=None
        self.stock={};self.used={};self.step=''
        for variant in context['tip_source']['variants']:
            self.stock[variant]=[];self.used[variant]=0
        for rack in context['tip_racks']:
            for slot in rack['slots']:
                if slot['occupied']:
                    self.stock[rack['variant']].append({'id':slot['tip_id'],'rack':rack['id'],'slot':slot['id'],
                                                       'mouth_world_mm':slot['mouth_world_mm']})
        self.capacities={variant:quantity(station.tips.parameters(context['tip_source'],variant)['capacity']) for variant in self.stock}
        self.initial_tip_count={v:len(stock) for v,stock in self.stock.items()}
        seen=set()
        for seed in protocol['initial_liquids']:
            exact(seed,'location components_ul dead_volume_ul','initial liquid')
            key=self.known(seed['location']);require(key not in seen,'Duplicate initial liquid location');seen.add(key)
            require(isinstance(seed['components_ul'],dict) and seed['components_ul'],'Explicit initial components required')
            for name,value in seed['components_ul'].items():
                require(name in protocol['materials'],'Unknown initial material')
                self.contents[key][name]=quantity(value,positive=True)
            self.dead[key]=quantity(seed['dead_volume_ul'])
            require(self.dead[key] < total(self.contents[key]) <= self.capacity(key),'Initial volume or dead volume invalid')
        self.initial=copy.deepcopy(self.contents)

    def known(self, target):
        key=location(target);require(key in self.contents,'Unknown labware/well: '+key);return key

    def capacity(self,key):
        return quantity(self.context['locations'][key]['capacity_ul'])

    def destinations(self,selector):
        exact(selector,'labware wells','target selection')
        require(selector['labware'] in self.context['labware'],'Unknown target labware')
        definition=self.context['labware'][selector['labware']]
        wells=list(definition['wells']) if selector['wells']=='all' else selector['wells']
        require(isinstance(wells,list) and wells and all(isinstance(w,str) for w in wells) and len(set(wells))==len(wells),'Unique nonempty target wells required')
        return [self.known({'labware':selector['labware'],'well':w}) for w in wells]

    def action(self,operation,**fields):
        record={'id':'P%05d'%(len(self.actions)+1),'step_id':self.step,'operation':operation,
                'after':self.actions[-1]['id'] if self.actions else None,**fields}
        self.actions.append(record);return record

    def fresh_tip(self,minimum):
        possible=sorted((cap,variant) for variant,cap in self.capacities.items() if cap>=minimum)
        require(possible,'Requested volume exceeds every declared tip capacity')
        cap,variant=possible[0]
        require(self.demand_only or self.stock[variant],'Fresh tips exhausted for '+variant+'; no automatic oversized-tip substitution')
        if self.tool!=variant:
            self.action('select_tool',variant=variant,nominal_capacity_ul=cap,
                        required_feedback='identified_tool_with_current_volume_calibration')
            self.tool=variant
        if self.demand_only:
            tip={'id':'UnboundNeed.'+variant+'.'+str(self.used[variant]+1),'rack':None,'slot':None,'mouth_world_mm':None}
        else:
            tip=self.stock[variant].pop(0)
        self.used[variant]+=1
        self.action('pick_tip',tip=tip,variant=variant,required_feedback='correct_unused_tip_attached')
        return tip,variant

    def discard(self,tip,variant):
        fit=station.tips.fit_check(self.context['tip_source'],variant)
        self.action('discard_tip',tip_id=tip['id'],destination='PS01Waste',groove=fit['groove_id'],
                    fit_status=fit['status'],required_feedback='tip_detached_and_in_waste')

    def mix(self,key,spec,attached=None):
        exact(spec,'volume_ul cycles','mix request')
        volume=quantity(spec['volume_ul'],positive=True)
        require(type(spec['cycles']) is int and 1<=spec['cycles']<=100,'Mix cycles must be an integer in 1..100')
        require(volume <= total(self.contents[key])-self.dead[key], 'Mix volume exceeds available liquid above dead volume')
        tip,variant=attached if attached else self.fresh_tip(volume)
        require(volume<=self.capacities[variant],'Attached tip too small for mixing')
        self.action('mix',location=key,volume_ul=volume,cycles=spec['cycles'],tip_id=tip['id'],
                    mouth_world_mm=self.context['locations'][key]['mouth_world_mm'],
                    required_feedback='mix_cycles_completed_with_liquid_detection')
        # Perfect homogeneity is a stated forecast assumption, not a sensor result.
        self.homogeneous[key]=True
        if not attached:self.discard(tip,variant)

    def transfer(self,source,target,volume,mix_after=None):
        volume=quantity(volume)
        require(source!=target,'Use mix for a same-well operation')
        if volume==0:
            self.skipped.append({'step_id':self.step,'source':source,'target':target,'reason':'zero_volume'})
            if mix_after:self.mix(target,mix_after)
            return
        require(self.homogeneous[source] or len(self.contents[source])<=1,'Mix a multi-component source before withdrawing an aliquot')
        require(total(self.contents[source])-volume >= self.dead[source], 'Source exhausted or below dead volume: '+source)
        require(total(self.contents[target])+volume <= self.capacity(target), 'Target well would overflow: '+target)
        largest=max(self.capacities.values());remaining=volume
        while remaining>0:
            chunk=min(remaining,largest);last=chunk==remaining
            mix_volume=quantity(mix_after['volume_ul'],positive=True) if last and mix_after else Decimal(0)
            tip,variant=self.fresh_tip(max(chunk,mix_volume))
            self.action('aspirate',location=source,volume_ul=chunk,tip_id=tip['id'],
                        mouth_world_mm=self.context['locations'][source]['mouth_world_mm'],
                        required_feedback='aspiration_volume_and_liquid_presence_confirmed')
            before=total(self.contents[source]);portions={};allocated=Decimal(0)
            positive=[(k,v) for k,v in self.contents[source].items() if v>0]
            for index,(name,value) in enumerate(positive):
                amount=chunk-allocated if index==len(positive)-1 else chunk*value/before
                allocated+=amount;portions[name]=amount
                self.contents[source][name]-=amount
                self.contents[target][name]=self.contents[target].get(name,Decimal(0))+amount
            self.homogeneous[target]=len([v for v in self.contents[target].values() if v>0])<=1
            self.action('dispense',location=target,volume_ul=chunk,tip_id=tip['id'],
                        mouth_world_mm=self.context['locations'][target]['mouth_world_mm'],
                        required_feedback='dispense_completed_without_unintended_contact')
            self.transfers.append({'step_id':self.step,'source':source,'target':target,'volume_ul':chunk,
                                   'components_ul':portions,'tip_id':tip['id'],'variant':variant})
            if last and mix_after:self.mix(target,mix_after,(tip,variant))
            self.discard(tip,variant);remaining-=chunk

    def run_step(self,step):
        require(isinstance(step,dict) and isinstance(step.get('id'),str) and step['id'],'Named protocol step required')
        self.step=step['id'];op=step.get('operation')
        allowed={'transfer':{'id','operation','source','target','volume_ul'},
                 'distribute':{'id','operation','source','target','volumes'},
                 'consolidate':{'id','operation','sources','target','volumes_ul'},
                 'fill_to':{'id','operation','source','target','total_volume_ul'},
                 'mix':{'id','operation','target','volume_ul','cycles'}}
        require(op in allowed and allowed[op]<=set(step) and set(step)<=allowed[op]|({'mix_after'} if op!='mix' else set()),'Unsupported step or fields')
        mix=step.get('mix_after')
        if 'mix_after' in step:
            exact(mix,'volume_ul cycles','mix request');quantity(mix['volume_ul'],positive=True)
            require(type(mix['cycles']) is int and 1<=mix['cycles']<=100,'Invalid mix cycle count')
        if op=='transfer':
            self.transfer(self.known(step['source']),self.known(step['target']),step['volume_ul'],mix)
        elif op=='mix':
            for target in self.destinations(step['target']):self.mix(target,{'volume_ul':step['volume_ul'],'cycles':step['cycles']})
        elif op=='consolidate':
            require(isinstance(step['sources'],list) and step['sources'] and len(step['sources'])==len(step['volumes_ul']),'Consolidation needs matching sources and volumes')
            source_keys=[self.known(s) for s in step['sources']]
            require(len(set(source_keys))==len(source_keys),'Duplicate consolidation source')
            target=self.known(step['target'])
            for index,(source,volume) in enumerate(zip(source_keys,step['volumes_ul'])):
                self.transfer(source,target,volume,mix if index==len(source_keys)-1 else None)
        else:
            source=self.known(step['source']);targets=self.destinations(step['target'])
            if op=='fill_to':
                final=quantity(step['total_volume_ul'],positive=True)
                for target in targets:
                    volume=final-total(self.contents[target]);require(volume>=0,'Fill target is below current well volume')
                    self.transfer(source,target,volume,mix)
            else:
                volumes=step['volumes'];require(isinstance(volumes,dict),'Volume schedule required')
                if set(volumes)=={'constant_ul'}:
                    amounts=[quantity(volumes['constant_ul'])]*len(targets)
                elif set(volumes)=={'per_target_ul'}:
                    require(len(volumes['per_target_ul'])==len(targets),'One volume per target required')
                    amounts=[quantity(v) for v in volumes['per_target_ul']]
                else:
                    exact(volumes,'axis values_ul','axis volumes');axis=volumes['axis']
                    require(axis in {'row','column'},'Row or column volume axis required')
                    plate=self.context['labware'][step['target']['labware']]
                    require(len(volumes['values_ul'])==plate['rows' if axis=='row' else 'columns'],'Volume axis does not match labware')
                    values=[quantity(v) for v in volumes['values_ul']]
                    targets.sort(key=lambda target: (self.context['locations'][target][axis], self.context['locations'][target]['column' if axis=='row' else 'row']))
                    amounts=[values[self.context['locations'][target][axis]] for target in targets]
                for target,amount in zip(targets,amounts):self.transfer(source,target,amount,mix)

    def report(self):
        totals={name:sum((values.get(name,Decimal(0)) for values in self.contents.values()),Decimal(0)) for name in self.protocol['materials']}
        initial={name:sum((values.get(name,Decimal(0)) for values in self.initial.values()),Decimal(0)) for name in self.protocol['materials']}
        require(all(abs(totals[name]-value)<Decimal('1e-20') for name,value in initial.items()),'Component mass/volume balance failed')
        expected=self.protocol['expectations'];checks=[]
        if expected:
            exact(expected,'target_labware per_well_total_ul axis_components homogeneous','expected plate')
            require(expected['homogeneous'] is True,'Supported expectation is homogeneous output')
            require(expected['target_labware'] in self.context['labware'],'Unknown expected plate')
            require(set(expected['axis_components'])=={'row','column'},'Two independent expected axes required')
            plate=self.context['labware'][expected['target_labware']]
            for identity,w in plate['wells'].items():
                key=expected['target_labware']+'.'+identity
                require(total(self.contents[key])==quantity(expected['per_well_total_ul']) and self.homogeneous[key],'Final total or mixing expectation failed: '+key)
            for axis,component in expected['axis_components'].items():
                require(component in self.protocol['materials'],'Unknown axis component')
                groups={}
                for identity,w in plate['wells'].items():
                    groups.setdefault(w[axis],set()).add(self.contents[expected['target_labware']+'.'+identity].get(component,Decimal(0)))
                require(all(len(v)==1 for v in groups.values()),'Component does not remain constant along its orthogonal axis')
                checks.append({'id':component+'_'+axis,'passed':True,'values_ul':[next(iter(groups[k])) for k in sorted(groups)]})
        if self.demand_only:
            return {'format':'solidcraftbot.pipetting-tip-demand/1','protocol_id':self.protocol['id'],
                    'required_tips':copy.deepcopy(self.used),'mode':'demand_forecast_only',
                    'inventory_reserved':False,'hardware_ready':False,
                    'scope':'Validated liquid plan and nominal tip counts; no tip identities allocated or execution actions exported.'}
        result={'format':'solidcraftbot.pipetting-plan/1','protocol_id':self.protocol['id'],'passed':True,
                'mode':'planning_only','hardware_ready':False,'planned_actions':self.actions,'transfers':self.transfers,
                'skipped_zero_transfers':self.skipped,'initial_components_ul':self.initial,
                'final_wells':{key:{'total_ul':total(values),'components_ul':values,'homogeneous_assumed':self.homogeneous[key],
                                    'capacity_ul':self.context['locations'][key]['capacity_ul'],'dead_volume_ul':self.dead[key]}
                               for key,values in self.contents.items()},
                'tip_usage':{v:{'capacity_ul':self.capacities[v],'available':self.initial_tip_count[v],'used':self.used[v],'remaining':len(self.stock[v])} for v in self.stock},
                'component_balance':{'initial_ul':initial,'final_ul':totals,'passed':True},'expectation_checks':checks,
                'physical_readiness':{'t01_fit':{v:station.tips.fit_check(self.context['tip_source'],v)['status'] for v in self.stock},
                                      'qualified_minimum_dose_ul':None,'actual_tip_residual_ul':None,'actual_dose_error_ul':None,
                                      'robot_trajectory':None,'duration_s':None,'human_speed_comparison':None},
                'scope':'Ideal local quantity and consumable forecast. Actions are requests with required feedback, not observed execution, sensor acknowledgements or material-ledger transactions.',
                'limitations':self.protocol['limitations']}
        return json_quantities(result)


def compile_protocol(path=SOURCE, *, protocol=None, context=None, demand_only=False):
    spec=copy.deepcopy(protocol) if protocol is not None else station.read(path)
    exact(spec,'format id revision mode units setup materials initial_liquids tip_policy steps expectations limitations','pipetting protocol')
    require(spec['format']=='solidcraftbot.pipetting-protocol/1' and spec['mode']=='planning_only' and spec['units']=={'volume':'uL'},'Planning-only pipetting contract required')
    require(isinstance(spec['id'],str) and spec['id'] and type(spec['revision']) is int and spec['revision']>0,'Named protocol revision required')
    require(spec['tip_policy']=='fresh_per_transfer_chunk_or_mix','Unsupported contamination policy')
    require(isinstance(spec['materials'],dict) and spec['materials'],'Named materials required')
    for name,material in spec['materials'].items():
        require(isinstance(name,str) and name,'Material identity required');exact(material,'label basis','material')
        require(isinstance(material['label'],str) and material['label'] and material['basis']=='synthetic_example','Explicit synthetic material basis required')
    require(isinstance(spec['steps'],list) and spec['steps'],'Nonempty ordered protocol required')
    require(isinstance(spec['expectations'],dict),'Expected results must be an object')
    require(isinstance(spec['initial_liquids'],list) and spec['initial_liquids'],'Initial liquid declarations required')
    require(isinstance(spec['limitations'],list) and spec['limitations'] and all(isinstance(v,str) and v for v in spec['limitations']),'Explicit planning limitations required')
    require(len({s.get('id') for s in spec['steps']})==len(spec['steps']),'Unique step IDs required')
    setup_path=station.assembly.validate_reference(spec['setup'])
    context=context or station.compile_setup(setup_path)
    require(context['setup']==station.read(setup_path),'Setup context differs from its pinned source')
    with localcontext() as decimal_context:
        decimal_context.prec=40
        require(type(demand_only) is bool,'Explicit forecast mode required')
        planner=Planner(spec,context,demand_only=demand_only)
        for step in spec['steps']:planner.run_step(step)
        return planner.report()
