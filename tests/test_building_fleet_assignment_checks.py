"""Original mission identity and observed booking lifecycle, without CAD."""
import copy
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import building_fleet_assignment_checks as checks
import building_fleet_comm as comm
import tr01_floor_motion as floor


def fixture():
    home={'level':'EG','area':'H','slot':0,'pose_mm_rad':[0,0,0]}
    target={'kind':'inspection_pass','level':'OG1','area':'R','basis':'fixture','weight':1,'minimum_visits':1}
    source={'missions':{'seed':20261120,'targets':[target],'minimum_duration_s':1.,'maximum_duration_s':5.},
            'communication':{'latency_s':[.1,.1]}}
    assignments=[{'mission_id':'mission-1','vehicle_id':'BF01','assigned_s':0.,'goal':target,
                  'source_level':'EG','booking_id':'booking-1'},
                 {'mission_id':'mission-2','vehicle_id':'BF01','assigned_s':1.,'goal':{'kind':'home',**home},
                  'source_level':'OG1','booking_id':'booking-2'}]
    def snapshot(number,start,end,created,state='active'):
        return {'booking_id':'booking-'+str(number),'vehicle_id':'BF01','mission_id':'mission-'+str(number),
                'from_level':start,'to_level':end,'source_role':'start','start':{'level':start,'slot':0},
                'destination':{'level':end,'slot':0},'state':state,'created_s':created,'activated_s':created}
    first=snapshot(1,'EG','OG1',0.);second=snapshot(2,'OG1','EG',1.)
    events=[]
    for booking,board,arrival in((first,.3,.7),(second,1.3,1.8)):
        for name,t,state in(('booking_fenced',booking['created_s'],'active'),
                             ('booking_boarded',board,'boarded'),('booking_arrived',arrival,'arrived')):
            events.append({'event':name,'time_s':t,**{**copy.deepcopy(booking),'state':state}})
    final=[{**copy.deepcopy(b),'state':'arrived'}for b in(first,second)]
    channel=comm.Channel([.1,.1],20261120,.1);messages=[]
    blackouts={.4:False,.6:True,1.4:False,1.6:True}
    for step in range(42):
        now=round(step*.05,3)
        if now in blackouts:channel.set_connected('BF01',blackouts[now],now)
        for mission,receipt in zip(assignments,(.1,1.1)):
            if now==receipt:
                channel.emit('BF01','event',{'event':'mission_assigned','details':{
                    'mission_id':mission['mission_id'],'goal':mission['goal'],'source_level':mission['source_level'],
                    'booking_id':mission['booking_id'],'acknowledged':True}},now)
        if now==.8:channel.emit('BF01','event',{'event':'inspection_completed',
            'details':{'mission_id':'mission-1','level':'OG1','area':'R'}},now)
        if now==1.9:channel.emit('BF01','event',{'event':'home_reached',
            'details':{'mission_id':'mission-2','level':'EG','slot':0}},now)
        messages.extend(channel.deliver(now))
    ack_records=[{'vehicle_id':'BF01','mission_id':m['payload']['details']['mission_id'],
                  'received_s':checks._tick(m['received_s'])}for m in messages
                 if m['kind']=='event'and m['payload']['event']=='mission_assigned']
    waiting=[]
    for booking,board,arrival in((first,.3,.7),(second,1.3,1.8)):
        for name,t,role,place in(
            ('waiting_granted'if booking is first else'waiting_bound',booking['created_s'],'start',booking['start']),
            ('waiting_granted',booking['created_s'],'destination',booking['destination']),
            ('waiting_released',board,'start',booking['start']),('waiting_promoted',arrival,'start',booking['destination'])):
            waiting.append({'event':name,'time_s':t,'role':role,**place,'vehicle_id':'BF01',
                'mission_id':booking['mission_id'],'booking_id':booking['booking_id']})
    waiting.append({'event':'waiting_released','time_s':1.9,'role':'start','level':'EG','slot':0,
                    'vehicle_id':'BF01','mission_id':'mission-2','booking_id':'booking-2'})
    program={'duration_s':2.05,'mission_assignments':assignments,'waiting_events':waiting,
        'mission_receipts':[{'vehicle_id':'BF01','mission_id':'mission-'+str(i),'received_s':t}for i,t in((1,.1),(2,1.1))],
        'mission_acknowledgements':ack_records,'received_messages':messages,
        'inspection_witnesses':[{'vehicle_id':'BF01','mission_id':'mission-1','level':'OG1','area':'R','time_s':.8}],
        'booking_events':events,'mission_bookings':final,
        'lift_requests':[{'vehicle_id':'BF01','mission_id':'mission-'+str(i),'booking_id':'booking-'+str(i),
            'start_port':a,'destination_port':b,'requested_s':r,'assigned_s':r,'exited_s':exit_time}
            for i,a,b,r,exit_time in((1,'E','O',.2,.7),(2,'O','E',1.2,1.8))],
        'lift_events':[{'vehicle_id':'BF01','event':name,'time_s':t}for name,t in(
            ('lift_boarded',.3),('lift_exited',.7),('lift_boarded',1.3),('lift_exited',1.8))]}
    nav=NS(homes={'BF01':home},level_z={'EG':0,'OG1':1000},waits={'EG':[[0,0,0]],'OG1':[[0,0,0]]},
           mesh=NS(manifest={'elevator':{'ports':[{'id':'E','active':True,'level_id':'EG'},
                                                 {'id':'O','active':True,'level_id':'OG1'}]}}))
    curve=floor.motion.Curve([{'time_s':t,floor.F[0]:[0,0,0],floor.F[1]:[0,0,0],floor.F[2]:[0,0,0]}for t in(0,2.05)])
    def episode(t):return {'level_id':'EG'if t<.7 or t>=1.8 else'OG1','attached_cabin':False,'curve':curve,
                           'mode':'hold','hold_reason':'home'if t>=1.9 else'resource_wait'}
    trajectories=[NS(identity='BF01',episode=episode)]
    return program,trajectories,nav,source


class AssignmentTests(unittest.TestCase):
    def test_original_assignment_receipt_ack_completion_and_two_actual_trips(self):
        result=checks.check_assignments(*fixture())
        self.assertTrue(result['passed']);self.assertEqual(result['foreign_bookings'],2)
        self.assertEqual(result['identity_bound_completions'],2)

    def test_ack_cannot_change_goal_or_booking(self):
        for field,value in(('booking_id','foreign-booking'),('goal',{'kind':'home'})):
            p,tr,n,s=fixture()
            message=next(m for m in p['received_messages']if m['payload'].get('event')=='mission_assigned')
            message['payload']['details'][field]=value
            with self.assertRaisesRegex(ValueError,'acknowledgment'):checks.check_assignments(p,tr,n,s)

    def test_receipt_cannot_be_invented_before_real_downlink(self):
        p,tr,n,s=fixture();p['mission_receipts'][0]['received_s']=.05
        with self.assertRaisesRegex(ValueError,'downlink replay'):checks.check_assignments(p,tr,n,s)

    def test_completion_cannot_use_a_different_original_mission_id(self):
        p,tr,n,s=fixture();p['inspection_witnesses'][0]['mission_id']='mission-2'
        with self.assertRaisesRegex(ValueError,'same issued mission ID'):checks.check_assignments(p,tr,n,s)

    def test_foreign_booking_must_exist_before_assignment(self):
        p,tr,n,s=fixture();p['booking_events'][0]['created_s']=.05;p['booking_events'][0]['time_s']=.05
        with self.assertRaisesRegex(ValueError,'before issuance'):checks.check_assignments(p,tr,n,s)

    def test_body_clear_arrival_needs_actual_lift_observation(self):
        p,tr,n,s=fixture();p['lift_events'][1]['time_s']=.75
        with self.assertRaisesRegex(ValueError,'lift observation'):checks.check_assignments(p,tr,n,s)

    def test_conditional_source_cannot_be_inferred_without_boarding(self):
        p,tr,n,s=fixture();event=p['booking_events'][0]
        event.update(source_role='arrival',state='conditional',activated_s=None)
        with self.assertRaisesRegex(ValueError,'already-boarded'):checks.check_assignments(p,tr,n,s)

    def test_final_bookings_cannot_stay_active(self):
        p,tr,n,s=fixture();p['mission_bookings'][0]['state']='active'
        with self.assertRaisesRegex(ValueError,'unfinished'):checks.check_assignments(p,tr,n,s)

    def test_home_completion_is_not_a_provisional_capacity_stop(self):
        p,tr,n,s=fixture();n.homes['BF01']['pose_mm_rad']=[1,0,0]
        p['mission_assignments'][1]['goal']['pose_mm_rad']=[1,0,0]
        for message in p['received_messages']:
            if message['payload'].get('event')=='mission_assigned'and message['payload']['details']['mission_id']=='mission-2':
                message['payload']['details']['goal']['pose_mm_rad']=[1,0,0]
        with self.assertRaisesRegex(ValueError,'source home rest'):checks.check_assignments(p,tr,n,s)

    def test_bay_event_cannot_borrow_another_mission_binding(self):
        p,tr,n,s=fixture();p['waiting_events'][0]['mission_id']='mission-2'
        with self.assertRaisesRegex(ValueError,'immutable mission booking'):checks.check_assignments(p,tr,n,s)

    def test_arrival_cannot_be_promoted_from_a_different_bay(self):
        p,tr,n,s=fixture();p['waiting_events'][3]['level']='EG'
        with self.assertRaisesRegex(ValueError,'endpoint observation'):checks.check_assignments(p,tr,n,s)

    def test_lift_call_must_follow_local_receipt_and_activation(self):
        p,tr,n,s=fixture();p['lift_requests'][0]['requested_s']=.05
        with self.assertRaisesRegex(ValueError,'immutable issued mission booking'):checks.check_assignments(p,tr,n,s)

    def test_capacity_home_cannot_be_reported_as_final_home(self):
        p,tr,n,s=fixture();old=tr[0].episode
        tr[0].episode=lambda t:{**old(t),'hold_reason':'capacity_home'}
        with self.assertRaisesRegex(ValueError,'source home rest'):checks.check_assignments(p,tr,n,s)

    def test_conditional_fence_activates_only_with_its_observed_incoming_source(self):
        p,tr,n,s=fixture()
        # This two-phase fixture fences the return before issuing it. Only
        # observed arrival activates the capacity promise; no pose is inferred.
        second=[r for r in p['booking_events']if r['booking_id']=='booking-2']
        for row in second:
            row.update(source_role='arrival',created_s=.4,activated_s=.7)
        second[0].update(time_s=.4,state='conditional',activated_s=None)
        activated={**copy.deepcopy(second[0]),'event':'booking_activated','time_s':.7,'state':'active','activated_s':.7}
        p['booking_events'].append(activated);p['booking_events'].sort(key=lambda r:r['time_s'])
        p['mission_bookings'][1].update(source_role='arrival',created_s=.4,activated_s=.7)
        for row in p['waiting_events']:
            if row['booking_id']!='booking-2':continue
            if row['event']=='waiting_bound':row['time_s']=.7
            elif row['event']=='waiting_granted':row.update(time_s=.4,role='lookahead_destination')
        activation={'event':'waiting_role_activated','time_s':.7,'role':'destination','level':'EG','slot':0,
                    'vehicle_id':'BF01','mission_id':'mission-2','booking_id':'booking-2'}
        p['waiting_events'].append(activation)
        order={'waiting_promoted':0,'waiting_role_activated':1,'waiting_bound':2}
        p['waiting_events'].sort(key=lambda r:(r['time_s'],order.get(r['event'],0)))
        self.assertTrue(checks.check_assignments(p,tr,n,s)['passed'])
        activated['time_s']=.65
        p['booking_events'].sort(key=lambda r:r['time_s'])
        with self.assertRaisesRegex(ValueError,'body-clear arrival'):checks.check_assignments(p,tr,n,s)


if __name__=='__main__':unittest.main()
