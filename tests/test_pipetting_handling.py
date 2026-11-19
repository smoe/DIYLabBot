import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import labware_transfer as transfer
import pipetting_station as station
import run_pipetting_protocol as runner


class HandlingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context=station.compile_setup()

    def test_arm_variant_tool_and_all_endpoint_reachability(self):
        c=self.context
        self.assertEqual(set(c['arms']),{'PS01Arm','PS01TransferArm'})
        self.assertEqual(c['spatial']['devices']['PS01Arm']['source'],c['spatial']['devices']['PS01TransferArm']['source'])
        report=transfer.endpoint_report(c)
        self.assertTrue(report['passed'])
        self.assertEqual(len(report['checks']),24)
        for check in report['checks']:
            for value,joint in zip(check['joints_deg'],c['arms']['PS01TransferArm']['arm']['joints']):
                self.assertTrue(joint['limits_deg'][0]<=value<=joint['limits_deg'][1])

    def test_carriers_raise_all_dependent_payload_frames(self):
        c=self.context;p=transfer.parameters(c['handling']['source'])
        plate=c['labware']['Plate01'];pad=c['frames']['PS01.S08']
        self.assertEqual(plate['matrix'][2][3]-pad[2][3],p['foot_h']+p['base_t'])
        for rack in c['tip_racks']:
            self.assertEqual(rack['slots'][0]['mouth_world_mm'][2],14+10+90)
        self.assertEqual(len(c['handling']['carriers']),8)
        rack=c['handling']['carriers']['Carrier.Rack01']['content']
        self.assertEqual(rack['slots'],['Slot%02d'%i for i in range(1,13)])
        self.assertEqual(rack['rack_id'],'Carrier.Rack01')

    def test_undergrip_geometry_and_parameter_bounds(self):
        spec=self.context['handling']['source'];p=transfer.parameters(spec)
        report=transfer.grip_interface_report(spec)
        self.assertEqual(report['open_lip_clearance_per_side_mm'],7)
        self.assertEqual(report['lip_to_dock_clearance_mm'],3)
        for gap in [p['carrier_d'],106,p['open_gap']]:self.assertEqual(len(transfer.gripper_parts(spec,gap)),6)
        for gap in [90,130,float('nan')]:
            with self.assertRaises(ValueError):transfer.gripper_parts(spec,gap)
        with self.assertRaises(ValueError):transfer.carrier_parts(spec,[135,85,15])
        bad=copy.deepcopy(spec);bad['parameters']['open_gap']['expression']=100
        with self.assertRaises(ValueError):transfer.parameters(bad)

    def test_transfer_plan_preserves_content_without_booking_stock(self):
        c=self.context;before=copy.deepcopy(c['handling']['occupied'])
        result=transfer.plan(c)
        self.assertEqual(c['handling']['occupied'],before)
        self.assertEqual(result['projected_locations']['Carrier.Plate01'],'PS01.Outfeed')
        self.assertEqual(result['projected_locations']['Carrier.ReserveTips200'],'PS01.S07')
        self.assertEqual(len(result['steps'][0]['content']['tip_ids']),96)
        for step in result['steps']:
            self.assertEqual(step['content'],c['handling']['carriers'][step['carrier']]['content'])
            self.assertTrue(all(phase['required_feedback'] for phase in step['phases']))
        self.assertFalse(result['material_or_tip_stock_bookings'])
        self.assertFalse(result['feedback_observed'])
        self.assertIsNone(result['motion'])

    def test_bad_destinations_identity_and_missing_interlock_fail_closed(self):
        original=station.read(transfer.PROTOCOL);cases=[]
        for target in ['PS01.S01','PS01.S06','unknown']:
            bad=copy.deepcopy(original);bad['steps'][0]['destination']=target;cases.append(bad)
        bad=copy.deepcopy(original);bad['steps'][0]['carrier']='missing';cases.append(bad)
        bad=copy.deepcopy(original);bad['coordination']['transport_requires']=[];cases.append(bad)
        bad=copy.deepcopy(original);bad['steps'][1]['id']=bad['steps'][0]['id'];cases.append(bad)
        with tempfile.TemporaryDirectory(dir=ROOT/'exports') as directory:
            path=Path(directory)/'bad.json'
            for case in cases:
                path.write_text(json.dumps(case))
                with self.assertRaises(ValueError):transfer.plan(self.context,path)

    def test_ports_and_payload_registration_reject_invalid_layout(self):
        reference=self.context['setup']['handling'];original_bound=station.bound
        for mutation in ['port','binding','duplicate']:
            bad=copy.deepcopy(self.context['handling']['layout'])
            if mutation=='port':bad['ports'][0]['xyz'][0]=10000
            if mutation=='binding':bad['carriers'][0]['host']='PS01.S07'
            if mutation=='duplicate':bad['carriers'][1]['id']=bad['carriers'][0]['id']
            with patch.object(station,'bound',side_effect=lambda ref:bad if ref==reference else original_bound(ref)):
                with self.assertRaises(ValueError):station.compile_setup()

    def test_schemas_and_export(self):
        try:
            import jsonschema
            from referencing import Registry,Resource
        except ImportError:
            self.skipTest('jsonschema is not installed')
        schema=station.read(ROOT/'model/labware-transfer.schema.json');schema['$id']=(ROOT/'model/labware-transfer.schema.json').as_uri()
        assembly=station.read(ROOT/'model/assembly-reference.schema.json');assembly['$id']=(ROOT/'model/assembly-reference.schema.json').as_uri()
        registry=Registry().with_resource(assembly['$id'],Resource.from_contents(assembly))
        jsonschema.Draft202012Validator.check_schema(schema)
        validator=jsonschema.Draft202012Validator(schema,registry=registry)
        for name in ['labware-transfer.shared.json','pipetting-transfer-ps01.setup.json','pipetting-transfer-ps01.protocol.json']:
            validator.validate(station.read(ROOT/'model'/name))
        with tempfile.TemporaryDirectory(dir=ROOT/'exports') as directory:
            path=runner.build(transfer.PROTOCOL,Path(directory))
            result=station.read(path/'plan.json');self.assertTrue(result['endpoint_reachability']['passed'])
            self.assertFalse((path/'well-volumes.csv').exists())


if __name__=='__main__':unittest.main()
