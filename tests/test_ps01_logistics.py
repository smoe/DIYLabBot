"""Identity, atomicity, restart and consumable scheduling for PS01/TR01."""
import copy
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import ps01_logistics as logistics
import async_transport_domain as domain
from manual_tasks import Journal, TaskError
from run_ps01_logistics import clear_stations, complete_mock


class LogisticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.definition = logistics.definition()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Path(self.temp.name) / 'journal.sqlite'
        self.journal = Journal(self.store); self.addCleanup(self.journal.close)
        with patch.object(logistics, 'definition', return_value=copy.deepcopy(self.definition)):
            self.flow = logistics.Logistics.create(self.journal, 'Test')
        self.flow.act('admit', 'Admit', evidence='test_fixture')
        clear_stations(self.flow, 'Clear')

    def rack(self, job='Rack', target='RF02.InfeedRack'):
        self.flow.act('transfer', 'Prepare.' + job, carrier_id='Carrier.Rack01', target=target, job_id=job, mobile=True)

    def request(self, demand='Demand', variant='tip_200_ul', boxes=1):
        return self.flow.act('request_tips', 'Request.' + demand, demand_id=demand, station='PS01',
                             variant=variant, boxes=boxes, reason='Test demand')

    def supply(self, demand='Demand', variant='tip_200_ul', target='PS01.S07'):
        self.request(demand, variant)
        for stage in ('Stage', 'Deliver'):
            result = self.flow.act('serve', demand + '.' + stage, demand_id=demand, job_id=demand + '.' + stage)
            self.assertIsNotNone(result['job_id']); complete_mock(self.flow, result['job_id'])
        cid = logistics.demand_status(self.flow.state, self.flow.state['demands'][demand])['delivered'][0]
        if target:
            self.flow.act('transfer', demand + '.Seat', carrier_id=cid, target=target, job_id=demand + '.Seat', mobile=False)
            complete_mock(self.flow, demand + '.Seat')
        return cid

    def test_typed_rack_roundtrip_preserves_original_vessels_slots_and_contents(self):
        original = copy.deepcopy(self.flow.state['cargo']['Carrier.Rack01'])
        self.rack(); complete_mock(self.flow, 'Rack')
        self.flow.act('transfer', 'StageBack', carrier_id='Carrier.Rack01', target='RF02.Outfeed', job_id='StageBack', mobile=False)
        complete_mock(self.flow, 'StageBack')
        self.flow.act('transfer', 'Return', carrier_id='Carrier.Rack01', target='PS01.InfeedRack', job_id='Return', mobile=True)
        complete_mock(self.flow, 'Return')
        state = self.flow.state
        self.assertEqual(original, state['cargo']['Carrier.Rack01'])
        self.assertEqual(state['transport']['rack_placements']['Carrier.Rack01'], {'kind': 'endpoint', 'endpoint_id': 'PS01.InfeedRack'})
        self.assertEqual(len(state['transport']['jobs']['Return']['receipts']), 4)
        self.assertIn('vessel:Logistics.Tube01', state['resources'])

    def test_all_three_box_classes_reach_deck_without_creating_tips(self):
        initial = {k: copy.deepcopy(v['manifest']) for k, v in self.flow.state['cargo'].items()}
        for n, variant in enumerate(logistics.VARIANTS):
            self.supply('D' + str(n), variant, 'PS01.S%02d' % (4 + n if n < 2 else 7))
        state = self.flow.state
        self.assertEqual(initial, logistics.manifests(state))
        self.assertEqual(logistics.available_tips(state, 'PS01'), {'tip_10_ul': 164, 'tip_200_ul': 144, 'tip_1000_ul': 192})
        self.assertTrue(all(logistics.demand_status(state, d)['status'] == 'ready' for d in state['demands'].values()))

    def test_forecast_two_boxes_and_outstanding_request_is_not_available_inventory(self):
        first = logistics.forecast(self.flow.state, 'PS01')
        self.assertEqual(first['variants']['tip_200_ul']['additional_full_boxes'], 2)
        self.request(boxes=2)
        next_value = logistics.forecast(self.flow.state, 'PS01')['variants']['tip_200_ul']
        self.assertEqual(next_value['additional_full_boxes'], 0)
        self.assertEqual(next_value['available_on_deck'], 48)

    def test_fixed_labware_hosts_are_not_transport_endpoints(self):
        # Reservoir occupancy comes from the shared PS01 setup, including its
        # second instance. A failed move cannot create a job or free the rack.
        state=self.flow.state
        endpoints={r['id'] for r in state['definition']['topology']['endpoints']}
        self.assertNotIn('PS01.S06',endpoints)
        self.assertNotIn('RF02.S06',endpoints)
        with self.assertRaises(TaskError):
            self.flow.act('transfer','ReservoirCollision',carrier_id='Carrier.Rack01',
                          target='PS01.S06',job_id='ReservoirCollision',mobile=False)
        self.assertEqual(self.flow.state,state)

    def test_two_matrix_supply_boxes_wait_for_the_single_infeed_then_cover_the_deficit(self):
        self.request(boxes=2)
        delivered=[]
        for index in range(2):
            for stage in ('Stage','Deliver'):
                job=str(index)+stage
                result=self.flow.act('serve','Schedule'+job,demand_id='Demand',job_id=job)
                if index==1 and stage=='Deliver':
                    self.assertIsNone(result['job_id'])
                    self.assertNotIn(job,self.flow.state['transport']['jobs'])
                    self.flow.act('transfer','SeatFirst',carrier_id=delivered[0],target='PS01.S05',job_id='SeatFirst',mobile=False)
                    complete_mock(self.flow,'SeatFirst')
                    result=self.flow.act('serve','Retry'+job,demand_id='Demand',job_id=job)
                self.assertIsNotNone(result['job_id']);complete_mock(self.flow,result['job_id'])
            delivered.append(result['carrier_id'])
        self.flow.act('transfer','SeatSecond',carrier_id=delivered[1],target='PS01.S09',job_id='SeatSecond',mobile=False)
        complete_mock(self.flow,'SeatSecond')
        self.assertEqual(len(set(delivered)),2)
        self.assertEqual(logistics.available_tips(self.flow.state,'PS01')['tip_200_ul'],240)
        self.assertEqual(logistics.forecast(self.flow.state,'PS01')['variants']['tip_200_ul']['additional_full_boxes'],0)
        self.assertEqual(logistics.demand_status(self.flow.state,self.flow.state['demands']['Demand'])['status'],'ready')

    def test_stock_shortage_waits_and_never_substitutes_another_variant(self):
        self.request(variant='tip_10_ul', boxes=2)
        result = self.flow.act('serve', 'Serve', demand_id='Demand', job_id='Supply')
        self.assertIsNotNone(result['job_id'])
        demand = self.flow.state['demands']['Demand']
        self.assertEqual(list(demand['allocations']), ['Carrier.Fresh10'])
        self.assertEqual(logistics.demand_status(self.flow.state, demand)['unallocated_boxes'], 1)

    def test_request_replay_conflict_cancellation_and_allocation_holds(self):
        self.request(); state = self.flow.state
        self.request(); self.assertEqual(state, self.flow.state)
        with self.assertRaises(TaskError):
            self.request(boxes=2)
        self.flow.act('serve', 'Serve', demand_id='Demand', job_id='Supply')
        with self.assertRaises(TaskError):
            self.flow.act('transfer', 'Steal', carrier_id='Carrier.Fresh200A', target='RF02.S09', job_id='Steal', mobile=False)
        self.flow.act('cancel_demand', 'Cancel', demand_id='Demand', reason='No longer needed')
        self.assertEqual(logistics.demand_status(self.flow.state, self.flow.state['demands']['Demand'])['status'], 'cancelled')
        with self.assertRaises(TaskError):
            self.flow.act('serve', 'ServeAgain', demand_id='Demand', job_id='Another')

    def test_no_partial_job_or_allocation_when_target_occupied(self):
        self.rack(); complete_mock(self.flow, 'Rack')
        before = self.flow.state
        with self.assertRaises(TaskError):
            self.flow.act('transfer', 'Bad', carrier_id='Carrier.Plate01', target='RF02.InfeedRack', job_id='Bad', mobile=True)
        self.assertEqual(before, self.flow.state)
        self.assertNotIn('Bad', self.flow.state['transport']['jobs'])

    def test_missing_receipt_claim_and_out_of_order_receipts_do_not_fake_delivery(self):
        self.rack()
        batch = self.flow.dispatch_mock('Rack', 'Dispatch', order=['delivery_accept', 'delivery_release', 'pickup_accept', 'pickup_release'])
        self.flow.ingest_mock(batch[:-1])
        self.assertEqual(self.flow.state['transport']['rack_placements']['Carrier.Rack01']['endpoint_id'], 'PS01.Outfeed')
        self.assertNotEqual(self.flow.state['transport']['jobs']['Rack']['phase'], 'completed')
        self.flow.ingest_mock(batch[-1:])
        self.assertEqual(self.flow.state['transport']['jobs']['Rack']['phase'], 'completed')
        self.assertEqual(self.flow.dispatch_mock('Rack', 'Dispatch'), [])

    def test_restart_at_each_handover_cut_preserves_claims_and_fences_writer(self):
        # Separate fixtures model process termination after each committed receipt.
        self.rack(); batch = self.flow.dispatch_mock('Rack', 'Dispatch')
        for cut in range(1, 5):
            with self.subTest(cut=cut), tempfile.TemporaryDirectory() as folder:
                target = Path(folder) / 'copy.sqlite'
                other = sqlite3.connect(target); self.journal.connection.backup(other); other.close()
                with Journal(target) as journal:
                    old = logistics.Logistics(journal, 'Test', self.flow.session)
                    old.ingest_mock(batch[:cut])
                    snapshot = old.state
                    resumed = logistics.Logistics.open(journal, 'Test', resume=True)
                    self.assertEqual(snapshot['cargo'], resumed.state['cargo'])
                    self.assertEqual(snapshot['resources'], resumed.state['resources'])
                    self.assertEqual(resumed.state['transport']['jobs']['Rack']['control'], 'held')
                    with self.assertRaises(TaskError):
                        old.act('cancel', 'Old', job_id='Rack', reason='Old session')
                    with self.assertRaises(TaskError):
                        resumed.dispatch_mock('Rack', 'Redispatch')

    def test_failed_grip_observation_holds_without_moving_inventory(self):
        self.rack(); batch = self.flow.dispatch_mock('Rack', 'Dispatch')
        observation = batch[1]; observation['args']['checks']['supported'] = False
        self.flow.ingest_mock([observation])
        state = self.flow.state
        self.assertEqual(state['transport']['jobs']['Rack']['control'], 'held')
        self.assertEqual(state['transport']['rack_placements']['Carrier.Rack01']['endpoint_id'], 'PS01.Outfeed')

    def test_late_wrong_manifest_blocks_following_transfer(self):
        self.rack(); batch = self.flow.dispatch_mock('Rack', 'Dispatch'); self.flow.ingest_mock(batch)
        self.flow.act('transfer', 'Next', carrier_id='Carrier.Rack01', target='RF02.Outfeed', job_id='Next', mobile=False)
        bad = copy.deepcopy(batch[-1]); bad['request_id'] = 'LateBad'
        bad['args']['observation']['observation_id'] = 'LateBad'
        bad['args']['observation']['manifest_sha256'] = '0' * 64
        self.flow.ingest_mock([bad])
        with self.assertRaises(TaskError):
            self.flow.dispatch_mock('Next', 'NextDispatch')
        self.assertEqual(self.flow.state['transport']['jobs']['Rack']['control'], 'held')

    def test_late_failed_retention_preserves_evidence_and_holds_following_job(self):
        self.rack();batch=self.flow.dispatch_mock('Rack','Dispatch');self.flow.ingest_mock(batch)
        self.flow.act('transfer','Next',carrier_id='Carrier.Rack01',target='RF02.Outfeed',job_id='Next',mobile=False)
        bad=copy.deepcopy(batch[-1]);bad['request_id']='LateRetention'
        bad['args']['observation']['observation_id']='LateRetention'
        bad['args']['checks']['load_secured']=False
        self.flow.ingest_mock([bad])
        state=self.flow.state
        self.assertFalse(state['requests']['LateRetention']['arguments']['checks']['load_secured'])
        self.assertEqual(state['transport']['jobs']['Rack']['phase'],'completed')
        with self.assertRaises(TaskError):self.flow.dispatch_mock('Next','NextDispatch')

    def test_mobile_job_holds_both_station_zones_against_another_carrier(self):
        self.rack()
        with self.assertRaisesRegex(TaskError,'zone already held'):
            self.flow.act('transfer','Other',carrier_id='Carrier.Plate01',target='PS01.S09',job_id='Other',mobile=False)
        self.assertIn('zone:PS01.TR01.Logistics:PS01',self.flow.state['resources'])
        self.assertIn('zone:PS01.TR01.Logistics:RF02',self.flow.state['resources'])

    def test_tip_consumption_intent_survives_restart_and_cannot_reset_or_double_debit(self):
        cid = 'Carrier.Stock10'
        self.flow.act('condition', 'OpenBox', carrier_id=cid, closure='open', quality='usable', evidence='test_fixture')
        tip_ids = [t['tip_id'] for t in self.flow.state['cargo'][cid]['manifest']['tips'] if t['state'] == 'unused'][:2]
        self.flow.act('begin_tip_use', 'UseIntent', use_id='Use01', carrier_id=cid, station='PS01', tip_ids=tip_ids)
        with self.assertRaises(TaskError):
            self.flow.act('transfer', 'MoveHeld', carrier_id=cid, target='PS01.S09', job_id='MoveHeld', mobile=False)
        resumed = logistics.Logistics.open(self.journal, 'Test', resume=True)
        self.assertEqual(resumed.state['tip_uses']['Use01']['status'], 'intended')
        resumed.act('confirm_tip_use', 'ConfirmUse', use_id='Use01', outcome='performed', tip_ids=tip_ids, evidence='test_fixture')
        resumed.act('confirm_tip_use', 'ConfirmUse', use_id='Use01', outcome='performed', tip_ids=tip_ids, evidence='test_fixture')
        self.assertEqual(logistics.available_tips(resumed.state, 'PS01')['tip_10_ul'], 66)
        with self.assertRaises(TaskError):
            resumed.act('confirm_tip_use', 'DoubleUse', use_id='Use01', outcome='performed', tip_ids=tip_ids, evidence='test_fixture')
        with self.assertRaises(TaskError):
            resumed.act('admit', 'Reset', evidence='test_fixture')

    def test_unknown_access_wrong_class_and_typed_contract_fail_closed(self):
        self.flow.act('access', 'Blocked', station='PS01', workspace_clear=False, pipetting_parked=True, transfer_parked=True, evidence='test_fixture')
        with self.assertRaises(TaskError):
            self.rack()
        clear_stations(self.flow, 'ClearAgain'); self.rack()
        env = domain.embedded_envelope(self.flow.state['transport'], 'Rack', self.definition['topology'])
        env['contract_sha256'] = domain.CONTRACT_SHA256
        with self.assertRaises(TaskError):
            domain.decode_envelope(env)
        with self.assertRaises(TaskError):
            self.request(variant='tip_20_ul')

    def test_second_owner_cannot_admit_same_fixture_and_failed_commit_rolls_back(self):
        with patch.object(logistics, 'definition', return_value=copy.deepcopy(self.definition)):
            second = logistics.Logistics.create(self.journal, 'Second')
        with self.assertRaises(TaskError):
            second.act('admit', 'SecondAdmit', evidence='test_fixture')
        self.assertFalse(second.state['admitted'])
        before, revision = self.journal.get_current('Test')
        self.request()
        with self.assertRaises(TaskError):
            self.journal.append('Test', revision, 'stale', {}, before)
        self.assertIn('Demand', self.flow.state['demands'])


class ContractTests(unittest.TestCase):
    def test_schema_and_runtime_reject_wrong_cargo_variant_and_unsupported_pose(self):
        try:
            import jsonschema
            from referencing import Registry,Resource
        except ImportError:self.skipTest('jsonschema is not installed')
        resources=[]
        for name in ('assembly-reference.schema.json','ps01-logistics.schema.json'):
            path=ROOT/'model'/name;schema=json.loads(path.read_text());schema['$id']=path.as_uri()
            resources.append((schema['$id'],Resource.from_contents(schema)))
        validator=jsonschema.Draft202012Validator(schema,registry=Registry().with_resources(resources))
        source=json.loads(logistics.SOURCE.read_text());validator.validate(source)
        for field,value in [('used_tip_count',97),('variant','tip_20_ul'),('physical_width_mm',123)]:
            bad=copy.deepcopy(source);bad['fixture'][2][field]=value
            with self.assertRaises(jsonschema.ValidationError):validator.validate(bad)

    def test_malformed_tip_slot_and_well_material_fail_closed(self):
        definition=logistics.definition()
        tip=copy.deepcopy(definition['initial_cargo']['Carrier.Stock10']['manifest'])
        tip['tips'][0]['place_id']=[]
        with self.assertRaises(TaskError):domain._manifest(tip)
        plate=copy.deepcopy(definition['initial_cargo']['Carrier.Plate01']['manifest'])
        plate['wells'][0]['materials']=[{}]
        with self.assertRaises(TaskError):domain._manifest(plate)


if __name__ == '__main__':
    unittest.main()
