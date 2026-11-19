import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import pipetting_protocol as protocol
import pipetting_station as station
import run_pipetting_protocol as run


def loc(labware,well):return {'labware':labware,'well':well}
def targets(*wells):return {'labware':'Plate01','wells':list(wells)}


class ProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=station.read(protocol.SOURCE)
        cls.context=station.compile_setup()
        cls.plan=protocol.compile_protocol()

    def custom(self,steps,**changes):
        source=copy.deepcopy(self.source);source.update(expectations={},steps=steps,**changes)
        return source

    def compile(self,source,context=None):
        return protocol.compile_protocol(protocol=source,context=context or self.context)

    def test_matrix_every_well_and_component_conservation(self):
        plan=self.plan
        for r in range(8):
            for c in range(12):
                well=plan['final_wells'][f'Plate01.{chr(65+r)}{c+1:02d}']
                self.assertEqual(well['total_ul'],200)
                self.assertEqual(well['components_ul'].get('A',0),c*5)
                self.assertEqual(well['components_ul'].get('B',0),r*10)
                self.assertEqual(well['components_ul']['Buffer'],200-c*5-r*10)
                self.assertTrue(well['homogeneous_assumed'])
        self.assertEqual(plan['component_balance']['initial_ul'],plan['component_balance']['final_ul'])
        for well,remaining in [('A01',1360),('A02',1640),('A03',1800)]:
            self.assertEqual(plan['final_wells']['Sources.'+well]['total_ul'],remaining)
        self.assertFalse(plan['hardware_ready'])
        self.assertIsNone(plan['physical_readiness']['duration_s'])

    def test_tip_usage_zero_controls_feedback_and_order(self):
        plan=self.plan
        self.assertEqual(len(plan['transfers']),268)
        self.assertEqual(len(plan['skipped_zero_transfers']),20)
        self.assertEqual({k:v['used'] for k,v in plan['tip_usage'].items()},{'tip_10_ul':28,'tip_200_ul':240,'tip_1000_ul':0})
        self.assertEqual(len({t['tip_id'] for t in plan['transfers']}),268)
        actions=plan['planned_actions']
        self.assertEqual(sum(a['operation']=='select_tool' for a in actions),4)
        self.assertEqual(sum(a['operation']=='mix' for a in actions),96)
        for i,action in enumerate(actions):
            self.assertEqual(action['after'],actions[i-1]['id'] if i else None)
            self.assertTrue(action['required_feedback'])
        self.assertEqual(set(plan['physical_readiness']['t01_fit'].values()),{'open'})

    def test_large_transfer_splits_into_nominal_1000_ul_strokes(self):
        source=self.custom([{'id':'Large','operation':'transfer','source':loc('Sources','A01'),'target':loc('Sources','A02'),'volume_ul':1500}])
        plan=self.compile(source)
        self.assertEqual([t['volume_ul'] for t in plan['transfers']],[1000,500])
        self.assertEqual(plan['tip_usage']['tip_1000_ul']['used'],2)
        self.assertEqual(plan['final_wells']['Sources.A02']['components_ul'],{'B':5000,'A':1500})

    def test_generic_distribution_consolidation_and_mix(self):
        plan=self.compile(self.custom([
            {'id':'Distribute','operation':'distribute','source':loc('Sources','A01'),'target':targets('A01','A02'),'volumes':{'per_target_ul':[10,20]}},
            {'id':'Pool','operation':'consolidate','sources':[loc('Plate01','A01'),loc('Plate01','A02')],'target':loc('Plate01','B01'),'volumes_ul':[5,10]},
            {'id':'Mix','operation':'mix','target':targets('B01'),'volume_ul':10,'cycles':2}]))
        self.assertEqual(plan['final_wells']['Plate01.B01']['total_ul'],15)
        self.assertEqual(plan['final_wells']['Plate01.A01']['total_ul'],5)
        self.assertEqual(plan['final_wells']['Plate01.A02']['total_ul'],10)

    def test_fractional_aliquots_and_fill_preserve_component_balance(self):
        plan=self.compile(self.custom([
            {'id':'A','operation':'transfer','source':loc('Sources','A01'),'target':loc('Plate01','A01'),'volume_ul':0.1},
            {'id':'B','operation':'transfer','source':loc('Sources','A02'),'target':loc('Plate01','A01'),'volume_ul':0.2,'mix_after':{'volume_ul':0.2,'cycles':2}},
            {'id':'Aliquot','operation':'transfer','source':loc('Plate01','A01'),'target':loc('Plate01','A02'),'volume_ul':0.1},
            {'id':'Fill','operation':'fill_to','source':loc('Sources','A03'),'target':targets('A01','A02'),'total_volume_ul':1,'mix_after':{'volume_ul':0.5,'cycles':2}}]))
        self.assertEqual(plan['final_wells']['Plate01.A01']['total_ul'],1)
        self.assertEqual(plan['final_wells']['Plate01.A02']['total_ul'],1)
        self.assertAlmostEqual(plan['final_wells']['Plate01.A02']['components_ul']['A'],1/30)
        self.assertAlmostEqual(plan['final_wells']['Plate01.A02']['components_ul']['B'],1/15)
        self.assertEqual(plan['component_balance']['initial_ul'],plan['component_balance']['final_ul'])
        # Arithmetic support is not a qualified sub-microlitre dosing claim.
        self.assertIsNone(plan['physical_readiness']['qualified_minimum_dose_ul'])

    def test_serial_dilution_tracks_mixture_provenance(self):
        source=self.custom([
            {'id':'Diluent','operation':'distribute','source':loc('Sources','A03'),'target':targets('A01','A02'),'volumes':{'constant_ul':100}},
            {'id':'First','operation':'transfer','source':loc('Sources','A01'),'target':loc('Plate01','A01'),'volume_ul':100,'mix_after':{'volume_ul':100,'cycles':3}},
            {'id':'Next','operation':'transfer','source':loc('Plate01','A01'),'target':loc('Plate01','A02'),'volume_ul':100,'mix_after':{'volume_ul':100,'cycles':3}}])
        plan=self.compile(source)
        self.assertEqual(plan['final_wells']['Plate01.A02']['components_ul'],{'Buffer':150,'A':50})
        self.assertEqual(plan['final_wells']['Plate01.A01']['components_ul'],{'Buffer':50,'A':50})
        del source['steps'][1]['mix_after']
        with self.assertRaisesRegex(ValueError,'Mix a multi-component source'):self.compile(source)

    def test_fail_closed_volume_bounds_and_unknown_locations(self):
        base={'id':'Bad','operation':'transfer','source':loc('Sources','A01'),'target':loc('Plate01','A01'),'volume_ul':20}
        for value in [-1,float('nan'),float('inf'),True,361]:
            with self.subTest(value=value),self.assertRaises(ValueError):self.compile(self.custom([{**base,'volume_ul':value}]))
        for field,value in [('source',loc('Sources','Z99')),('target',loc('Plate01','A99')),('target',base['source'])]:
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):self.compile(self.custom([{**base,field:value}]))
        shortage={**base,'target':loc('Sources','A02'),'volume_ul':3801}
        with self.assertRaisesRegex(ValueError,'dead volume'):self.compile(self.custom([shortage]))

    def test_tip_exhaustion_does_not_fall_back_to_oversized_tips(self):
        context=copy.deepcopy(self.context)
        for rack in context['tip_racks']:
            if rack['variant']=='tip_10_ul':
                for slot in rack['slots']:slot['occupied']=False
        with self.assertRaisesRegex(ValueError,'Fresh tips exhausted'):self.compile(self.source,context)

    def test_demand_forecast_survives_empty_stock_without_inventing_executable_tips(self):
        context=copy.deepcopy(self.context)
        for rack in context['tip_racks']:
            for slot in rack['slots']:slot['occupied']=False
        demand=protocol.compile_protocol(protocol=self.source,context=context,demand_only=True)
        self.assertEqual(demand['format'],'solidcraftbot.pipetting-tip-demand/1')
        self.assertNotIn('transfers',demand)
        self.assertNotIn('actions',demand)
        self.assertIn(240,demand['required_tips'].values())
        bad=self.custom([{'id':'Bad','operation':'transfer','source':loc('Sources','Z99'),
            'target':loc('Plate01','A01'),'volume_ul':20}])
        with self.assertRaises(ValueError):protocol.compile_protocol(protocol=bad,context=context,demand_only=True)

    def test_selector_axes_and_tip_reuse_policy_are_strict(self):
        variants=[]
        source=copy.deepcopy(self.source);source['steps'][0]['volumes']['values_ul']=[1];variants.append(source)
        source=copy.deepcopy(self.source);source['steps'][0]['target']['wells']=['A01','A01'];variants.append(source)
        source=copy.deepcopy(self.source);source['tip_policy']='reuse_everywhere';variants.append(source)
        source=copy.deepcopy(self.source);source['steps'][1]['id']=source['steps'][0]['id'];variants.append(source)
        source=copy.deepcopy(self.source);source['setup']['source_sha256']='0'*64;variants.append(source)
        source=copy.deepcopy(self.source);source['mode']='hardware';variants.append(source)
        for source in variants:
            with self.subTest(source=source['id']),self.assertRaises(ValueError):self.compile(source)

    def test_bad_mix_and_fill_requests_are_rejected(self):
        transfer={'id':'Transfer','operation':'transfer','source':loc('Sources','A01'),'target':loc('Plate01','A01'),'volume_ul':20}
        for spec in [{},None,{'volume_ul':21,'cycles':3},{'volume_ul':10,'cycles':0},{'volume_ul':10,'cycles':True}]:
            with self.subTest(spec=spec),self.assertRaises(ValueError):self.compile(self.custom([{**transfer,'mix_after':spec}]))
        fill={'id':'Fill','operation':'fill_to','source':loc('Sources','A03'),'target':targets('A01'),'total_volume_ul':10}
        with self.assertRaisesRegex(ValueError,'below current'):self.compile(self.custom([transfer,fill]))

    def test_invalid_plan_writes_no_partial_output(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'exports') as temp:
            directory=Path(temp);source=copy.deepcopy(self.source);source['steps'][0]['volumes']['values_ul']=[999]*12
            path=directory/'bad.json';path.write_text(json.dumps(source))
            output=directory/'result'
            with self.assertRaises(ValueError):run.build(path,output)
            self.assertFalse(output.exists())


if __name__=='__main__':unittest.main()
