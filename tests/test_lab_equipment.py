"""Equipment access contracts, dependent dimensions and actual native CAD evidence."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import lab_equipment as model
import tube_carrier_model as portable


class EquipmentSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = model.load()

    def device(self, identity, overrides=None):
        spec = model.materialize(self.catalog, identity, overrides)
        return spec, model.parameters(spec)

    def test_reference_envelopes_and_unknown_readings_are_separate(self):
        for identity, outside, inside in (
            ('fridge_4c', (597,654,1684), (460,423,1460)),
            ('cellar_ult_f440n', (955,898,1950), (616,600,1265)),
        ):
            spec,p = self.device(identity)
            self.assertEqual(tuple(p[k] for k in ('width','depth','height')), outside)
            self.assertEqual(tuple(p[k] for k in ('inner_width','inner_depth','inner_height')), inside)
            self.assertIsNone(spec['profile']['reported_temperature_c'])
        spec,p = self.device('analytical_balance')
        pan = model.interfaces(spec,p)['pan_surface']
        for key in ('capacity_g','readability_g','measured_mass_g'):
            self.assertIsNone(pan[key])
        self.assertIn('876 mm',self.catalog['references']['f440n']['scope'])
        self.assertIn('Local electrical variant',self.catalog['references']['f440n']['scope'])

    def test_open_refrigerator_exposes_all_five_levels_directly(self):
        spec,p = self.device('fridge_4c')
        closed = model.interfaces(spec,p,model.pose(spec,p,'closed'))
        opened = model.interfaces(spec,p)
        self.assertEqual(len(opened),5)
        self.assertFalse(any(f['accessible'] for f in closed.values()))
        self.assertTrue(all(f['accessible'] and f['access_kind']=='front_shelf' for f in opened.values()))
        source = model.expanded(spec,p)
        self.assertEqual(len(source['joints']),1)
        self.assertEqual(sum(b['role']=='shelf' for b in source['bodies']),4)

    def test_plastic_drawers_have_distinct_storage_frames_and_a_clear_selected_bin(self):
        spec,p = self.device('freezer_minus20')
        source = model.expanded(spec,p)
        closed = model.interfaces(spec,p,model.pose(spec,p,'closed'))
        opened = model.interfaces(spec,p)
        self.assertEqual(len(opened),6)
        self.assertEqual([k for k,f in opened.items() if f['accessible']],['Drawer04'])
        self.assertAlmostEqual(opened['Drawer04']['origin_mm'][1]-closed['Drawer04']['origin_mm'][1],-p['drawer_travel'])
        self.assertEqual(sum(o['action']=='cut' and o['body'].startswith('Drawer') for o in source['operations']),6)
        all_open = model.interfaces(spec,p,model.pose(spec,p,'all_open'))
        self.assertEqual([k for k,f in all_open.items() if f['accessible']],['Drawer06'])
        self.assertTrue(all(f['reference_setpoint_c']==-20 for f in opened.values()))

    def test_cellar_ult_requires_both_doors_and_keeps_manual_only_status(self):
        spec,p = self.device('cellar_ult_f440n')
        levels = model.storage_levels(spec,p)
        self.assertEqual([v['height_mm'] for v in levels],[245.5,242,242,242,245.5])
        self.assertEqual(levels[-1]['z_mm']+levels[-1]['height_mm'],p['opening_bottom']+p['inner_height'])
        values = model.pose(spec,p,'closed')
        values['OuterDoor']=p['max_open']
        self.assertFalse(any(f['accessible'] for f in model.interfaces(spec,p,values).values()))
        opened = model.interfaces(spec,p)
        self.assertEqual([k for k,f in opened.items() if f['accessible']],['Compartment03'])
        self.assertTrue(all(f['handling']=='manual_only' for f in opened.values()))
        self.assertTrue(all(f['accessible'] for f in model.interfaces(spec,p,model.pose(spec,p,'all_open')).values()))

    def test_balance_has_independent_sliding_side_panes_and_hinged_top(self):
        spec,p = self.device('analytical_balance')
        source = model.expanded(spec,p)
        self.assertEqual([j['type'] for j in source['joints']],['slider','slider','revolute'])
        closed = model.pose(spec,p,'closed')
        self.assertFalse(model.interfaces(spec,p,closed)['pan_surface']['accessible'])
        side = {**closed,'LeftSlide':p['side_travel']}
        self.assertTrue(model.interfaces(spec,p,side)['pan_surface']['accessible'])
        self.assertFalse(model.interfaces(spec,p,side)['pan_surface']['vertical_accessible'])
        partial = {**closed,'TopCover':70}
        self.assertFalse(model.interfaces(spec,p,partial)['pan_surface']['vertical_accessible'])
        self.assertTrue(model.interfaces(spec,p)['pan_surface']['vertical_accessible'])

    def test_opening_order_unknown_joints_and_invalid_values_are_rejected(self):
        for identity in ('freezer_minus20','cellar_ult_f440n'):
            spec,p = self.device(identity)
            source = model.expanded(spec,p)
            values = model.pose(spec,p,'access')
            values['OuterDoor']=0
            with self.assertRaisesRegex(ValueError,'Open the outer door'):
                model.interfaces(spec,p,values)
        spec,p = self.device('analytical_balance')
        source = model.expanded(spec,p)
        closed = model.pose(spec,p,'closed')
        for invalid in ({}, {**closed,'Unknown':0}, *({**closed,'TopCover':v} for v in (-1,86,True,float('nan')))):
            with self.subTest(values=invalid),self.assertRaises(ValueError):
                model.validate_pose(source,invalid)
        with self.assertRaises(ValueError):
            model.pose(spec,p,'unimplemented')

    def test_driving_variants_update_door_hinges_drawers_pan_and_access_frames(self):
        a,pa = self.device('freezer_minus20')
        b,pb = self.device('freezer_minus20',{'width':640,'inner_width':490})
        self.assertEqual(pb['hinge_x']-pa['hinge_x'],20)
        self.assertEqual(pb['drawer_width']-pa['drawer_width'],40)
        source = model.expanded(b,pb)
        hinge = next(j for j in source['joints'] if j['id']=='OuterDoor')
        self.assertEqual(model.evaluate(hinge['origin'][0],pb),320)
        a,pa = self.device('analytical_balance')
        b,pb = self.device('analytical_balance',{'base_height':90})
        self.assertEqual(pb['hinge_z']-pa['hinge_z'],10)
        self.assertEqual(model.interfaces(b,pb)['pan_surface']['origin_mm'][2]-model.interfaces(a,pa)['pan_surface']['origin_mm'][2],10)
        self.assertEqual(self.catalog['families']['analytical_balance']['parameters']['base_height']['expression'],80)

    def test_invalid_dimensions_and_derived_overrides_fail_before_export(self):
        for overrides in ({'width':True},{'width':float('inf')},{'hinge_x':300},
                          {'unknown':1},{'inner_width':590},{'drawer_travel':220},
                          {'max_open':100,'access_angle':110}):
            with self.subTest(overrides=overrides),self.assertRaises(ValueError):
                self.device('freezer_minus20',overrides)

    def test_source_rejects_unimplemented_units_recipes_readings_and_automatic_cellar(self):
        for change in ('units','recipe','reading','handling','compartments'):
            catalog = copy.deepcopy(self.catalog)
            if change=='units':
                catalog['families']['cold_storage']['parameters']['width']['unit']='m'
            elif change=='recipe':
                catalog['families']['cold_storage']['recipe']='unimplemented'
            elif change=='reading':
                catalog['profiles']['fridge_4c']['reported_temperature_c']=4
            elif change=='handling':
                catalog['profiles']['cellar_ult_f440n']['handling']='automated'
            else:
                catalog['profiles']['cellar_ult_f440n']['insert']['compartment_heights_mm']=[1200]
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder)/'invalid.json'
                path.write_text(json.dumps(catalog))
                with self.subTest(change=change),self.assertRaises(ValueError):
                    model.load(path)

    def test_all_joint_samples_respect_the_manual_opening_order(self):
        for identity in self.catalog['profiles']:
            spec,p = self.device(identity)
            source = model.expanded(spec,p)
            for sample in model.samples(spec,p):
                with self.subTest(profile=identity,pose=sample['id']):
                    model.validate_pose(source,sample['joint_values'])
            commands = model.solidcraft_commands(spec,p)
            self.assertTrue(any(c['command']=='joint.create' for c in commands))
            self.assertFalse(any('import' in c['command'] for c in commands))

    def test_overview_reuses_three_device_profiles_without_room_coordinates(self):
        spec,source,placements = model.overview(self.catalog)
        self.assertEqual(len(placements),3)
        self.assertEqual(source['joints'],[])
        self.assertTrue(all(c['grounded'] for c in source['components']))
        self.assertTrue(all(v['reference']['source']=='model/lab-equipment.shared.json' for v in placements))
        self.assertNotIn('room',spec)
        for op in source['operations']:
            shape = portable.numeric_shape(op['shape'],{})
            self.assertIn(shape['kind'],('polygon_prism','cylinder'))

    @unittest.skipUnless(importlib.util.find_spec('jsonschema'),'Optional jsonschema package not installed')
    def test_schema_validates_source_and_rejects_a_fictitious_reading(self):
        from jsonschema import Draft202012Validator,ValidationError
        schema = json.loads((ROOT/'model/lab-equipment.schema.json').read_text())
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        validator.validate(self.catalog)
        changed = copy.deepcopy(self.catalog)
        changed['profiles']['analytical_balance']['capacity_g']=200
        with self.assertRaises(ValidationError):
            validator.validate(changed)


class EquipmentNativeEvidenceTests(unittest.TestCase):
    def test_all_devices_variants_and_access_poses_have_current_native_evidence(self):
        path = ROOT/'cad/lab-equipment/shared-build-report.json'
        if not path.exists():
            self.skipTest('Run scripts/build_lab_equipment.py for native geometry evidence')
        report = json.loads(path.read_text())
        if not report['complete_catalog'] or not report['cross_cad_checked']:
            self.skipTest('Full FreeCAD/SolidCraft comparison has not been built locally')
        self.assertTrue(report['passed'])
        self.assertEqual(report['source_sha256'],model.digest(model.SOURCE))
        for source,checksum in report['source_files_sha256'].items():
            self.assertEqual(model.digest(ROOT/source),checksum,source)
        cases = {c['id']:c for c in report['cases']}
        self.assertEqual(len(cases),7)
        self.assertIn('storage_overview',cases)
        self.assertIn('freezer_minus20_wide',cases)
        self.assertIn('analytical_balance_raised',cases)
        for identity,case in cases.items():
            with self.subTest(case=identity):
                self.assertTrue(case['passed'])
                self.assertTrue(all(c['passed'] for c in case['body_comparisons']))
                for kind,checksum in case['artifact_sha256'].items():
                    self.assertEqual(model.digest(ROOT/case['files'][kind]),checksum)
                native = json.loads((ROOT/case['files']['freecad_validation']).read_text())
                self.assertTrue(native['reopened']['passed'])
                self.assertTrue(all(c['passed'] for c in native['solidcraft_step_xor']))
                if case['profile']:
                    self.assertTrue(all(c['passed'] for c in case['closed_pose_comparisons']))
                    self.assertTrue(all(c['passed'] for c in native['motion_samples']))
                    self.assertTrue(all(c['passed'] for group in native['access_checks'].values() for c in group))
        for view in report['renders'].values():
            self.assertEqual(model.digest(ROOT/view['path']),view['sha256'])


if __name__=='__main__':
    unittest.main()
