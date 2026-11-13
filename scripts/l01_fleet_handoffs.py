"""Source-referenced three-car loading, autonomous traffic, and unloading demo."""
import copy,hashlib,json,math
from pathlib import Path
import l01_opposing_traffic as traffic
import tr01_workcell as workcell
ROOT=traffic.ROOT;SOURCE=ROOT/'model/l01-fleet-handoffs.demo.json';F=traffic.F
mm=workcell.floor.robot.multiply;inverse=workcell.floor.robot.inverse

def placement(p,yaw=0):return workcell.pickup.placement(p,math.degrees(yaw))
def canonical_sha(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def derive():
    source=json.loads(SOURCE.read_text())
    if source['format']!='solidcraftbot.fleet-handoffs-demo/1' or source['mode']!='synthetic_display_only':raise ValueError('Synthetic fleet handoff contract required')
    for ref in source['sources'].values():workcell.floor.assembly.validate_reference(ref)
    if not all(source['guards'].values()):raise ValueError('Handoff guards must remain enabled')
    report=json.loads((ROOT/'cad/tr01-workcell/shared-build-report.json').read_text());opposing=traffic.validated_result();program=json.loads((ROOT/report['files']['program']).read_text())
    for key in ('program','arm_validation','floor_validation','vehicle','freecad'):
        if traffic.local.digest(ROOT/report['files'][key])!=report['artifact_sha256'][key]:raise ValueError('Workcell artifact changed: '+key)
    if not(report['floor_interval_check_passed'] and report['arm_dynamics_passed'] and report['arm_discrete_collision_passed']):raise ValueError('Complete original workcell checks required')
    missions=opposing['settings']['missions'];ids=[m['id'] for m in missions]
    if any(set(source[key])!=set(ids) or len(source[key])!=3 for key in ('loading_order','unloading_order')):raise ValueError('Each vehicle needs one load and unload')
    if set(source['cargo_ids'])!=set(ids) or len(set(source['cargo_ids'].values()))!=3:raise ValueError('Three distinct cargo identities required')
    definition=program['definition'];kin={name:workcell.actor_source(definition,name)[2] for name in program['actors']}
    initial=opposing['frames'][0];state={'cars':[v['pose_mm_rad'] for v in initial['vehicles']],'joints':{name:[math.radians(v) for v in data['park']] for name,data in program['actors'].items()},'covers':[True]*3,'owners':[{'type':'bench','station':m['from'],'matrix':placement(program['stations'][m['from']]['bench_grip_mm'])} for m in missions],'benches':{key:{'status':'closed','vehicle':None,'person_clear':False} for key in definition['work_areas']}}
    phases=[];events=[];clock=0.;gate_duration=source['gate_event_duration_s'];current_stage=None
    def tool(actor,q):return kin[actor].tool([math.degrees(v) for v in q])
    def cargo(i):
        owner=state['owners'][i]
        if owner['type']=='bench':return owner['matrix']
        if owner['type']=='car':return mm(placement([*state['cars'][i][:2],0],state['cars'][i][2]),owner['attachment'])
        return mm(tool(owner['actor'],state['joints'][owner['actor']]),owner['attachment'])
    def add(kind,duration=0,**values):
        nonlocal clock
        p={'kind':kind,'start_s':clock,'duration_s':duration,'state':copy.deepcopy(state),**values};phases.append(p);clock+=duration;return p
    def event(name,vehicle,station,before):
        # Wait ends only when the named synthetic observation is supplied.
        # The effect belongs to the next state, never to the waiting interval.
        phase=add('event',gate_duration,vehicle=vehicle,station=station,event=name,stage=current_stage)
        phase['state']=before
        events.append({'time_s':clock,'event':name,'vehicle':vehicle,'station':station,'work_area':definition['stations'][station]['work_area'],'evidence':'synthetic_demo_fixture'})
    def transfer(vehicle,station,direction):
        nonlocal current_stage
        i=ids.index(vehicle);data=program['stations'][station];actor=data['actor'];area=definition['stations'][station]['work_area'];current_stage=direction
        if data['kind']!='robot':raise ValueError('Stationary robot arm required')
        before=copy.deepcopy(state);state['benches'][area]={'status':'reserved','vehicle':vehicle,'person_clear':True};event('person_clear_and_exclusive_work_area_reserved',vehicle,station,before)
        approach=program['approaches'][station];a=approach['points'][0]['pose_mm_rad'];offset=2*math.pi*round((state['cars'][i][2]-a[2])/(2*math.pi))
        if math.dist(state['cars'][i][:2],a[:2])>1e-6:raise ValueError('Vehicle not at station aisle waiting position')
        add('dock',approach['duration_s'],vehicle=vehicle,station=station,curve_ref=station,reverse=False,yaw_offset=offset,stage=direction)
        end=approach['points'][-1]['pose_mm_rad'];state['cars'][i]=[end[0],end[1],end[2]+offset]
        before=copy.deepcopy(state);state['covers'][i]=False;event('cover_removed_and_person_outside_arm_envelope',vehicle,station,before)
        for part in ('empty_in','loaded','empty_out'):
            curve=data['transfers'][direction][part]
            if part=='loaded':
                before=copy.deepcopy(state);world=cargo(i);state['owners'][i]={'type':'arm','actor':actor,'attachment':mm(inverse(tool(actor,state['joints'][actor])),world)};event('grip_and_cargo_identity_confirmed',vehicle,station,before)
            add('arm',curve['duration_s'],vehicle=vehicle,station=station,actor=actor,direction=direction,part=part,stage=direction)
            state['joints'][actor]=curve['points'][-1][F[0]]
            if part=='loaded':
                before=copy.deepcopy(state);world=cargo(i)
                if direction=='load':state['owners'][i]={'type':'car','attachment':mm(inverse(placement([*state['cars'][i][:2],0],state['cars'][i][2])),world)}
                else:state['owners'][i]={'type':'bench','station':station,'matrix':world}
                event('placement_and_cargo_identity_confirmed',vehicle,station,before)
        before=copy.deepcopy(state);state['covers'][i]=True;event('arm_parked_cover_secured_and_departure_clear',vehicle,station,before)
        add('dock',approach['duration_s'],vehicle=vehicle,station=station,curve_ref=station,reverse=True,yaw_offset=offset,stage=direction)
        state['cars'][i]=[a[0],a[1],a[2]+offset];before=copy.deepcopy(state);state['benches'][area]={'status':'closed','vehicle':None,'person_clear':False};event('work_area_returned_and_vehicle_lease_revoked',vehicle,station,before)
    for vehicle in source['loading_order']:transfer(vehicle,missions[ids.index(vehicle)]['from'],'load')
    traffic_start=clock;add('traffic',opposing['duration_s'],stage='traffic');traffic_end=clock
    state['cars']=[v['pose_mm_rad'] for v in opposing['frames'][-1]['vehicles']]
    for vehicle in source['unloading_order']:transfer(vehicle,missions[ids.index(vehicle)]['to'],'unload')
    add('complete',0,stage='complete')
    source_pins={str(SOURCE.relative_to(ROOT)):traffic.local.digest(SOURCE),str(Path(__file__).relative_to(ROOT)):traffic.local.digest(__file__),**{r['source']:r['source_sha256'] for r in source['sources'].values()},report['files']['program']:report['artifact_sha256']['program'],report['files']['arm_validation']:report['artifact_sha256']['arm_validation'],report['files']['floor_validation']:report['artifact_sha256']['floor_validation'],**opposing['source_files_sha256']}
    result={'format':'solidcraftbot.fleet-handoffs-program/1','source_files_sha256':source_pins,'missions':missions,'cargo_ids':source['cargo_ids'],'phases':phases,'events':events,'duration_s':clock,'traffic_start_s':traffic_start,'traffic_end_s':traffic_end,'workcell_report':report,'original_arm_proof_scope':'discrete original workcell BRep checks and common PVA/FK dynamics; new additional vehicle/cargo obstacles need an independent certificate','limitations':source['limitations']}
    result['program_sha256']=canonical_sha(result)
    return result

def validated():
    result=derive();path=ROOT/'exports/tr01-workcell/fleet-handoffs-clearance.json';proof=json.loads(path.read_text())
    if not proof['passed'] or proof['program_sha256']!=result['program_sha256'] or proof['checker_sha256']!=traffic.local.digest(ROOT/'scripts/check_l01_fleet_handoffs_freecad.py'):raise ValueError('Current fleet handoff proof required')
    workcell.floor.verify(proof['native_inputs_sha256']);result['source_files_sha256'].update({str(path.relative_to(ROOT)):traffic.local.digest(path),'scripts/check_l01_fleet_handoffs_freecad.py':traffic.local.digest(ROOT/'scripts/check_l01_fleet_handoffs_freecad.py')});result['clearance_summary']=proof['summary'];result.pop('workcell_report');return result

def main():
    result=derive();(ROOT/'exports/tr01-workcell/fleet-handoffs.json').write_text(json.dumps(result,separators=(',',':'))+'\n');print(json.dumps({'duration_s':result['duration_s'],'phases':len(result['phases']),'events':len(result['events']),'traffic_start_s':result['traffic_start_s'],'program_sha256':result['program_sha256']}))
if __name__=='__main__':main()
