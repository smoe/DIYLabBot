"""Glassware access semantics, dimensional variants and actual native CAD evidence."""
import copy
import importlib.util
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import lab_glassware as model


class GlasswareSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = model.load()

    def test_shared_families_cover_beakers_funnels_and_two_removable_closures(self):
        self.assertEqual(len(self.catalog['families']), 3)
        self.assertEqual(len(self.catalog['items']), 9)
        self.assertEqual(len(model.cases(self.catalog)), 13)
        for identity, state in model.cases(self.catalog):
            spec = model.materialize(self.catalog, identity, state)
            p = model.parameters(spec)
            source = model.expanded(spec, p)
            self.assertEqual(source['joints'], [])
            self.assertEqual(sum(b['role'] == 'glass_vessel' or b['role'] == 'glass_funnel'
                                 for b in source['bodies']), 1)
            self.assertEqual(len(source['bodies']), 2 if spec['item']['family'] == 'bottle' else 1)

    def test_reference_facts_do_not_turn_assumed_dimensions_into_manufacturer_data(self):
        ref = self.catalog['references']['Z740576']
        self.assertEqual(ref['nominal_volume_ml'], 250)
        self.assertEqual(ref['reference_graduations_ml'], {'first': 25, 'last': 200, 'step': 25})
        self.assertIsNone(ref['outer_dimensions_mm'])
        self.assertIsNone(self.catalog['material']['measured_empty_mass_g'])
        self.assertEqual(self.catalog['items']['beaker_250']['reference'], 'Z740576')

    def test_millilitre_conversion_and_fill_height_are_distinct_from_nominal_capacity(self):
        spec = model.materialize(self.catalog, 'beaker_250')
        p = model.parameters(spec)
        expected_height = p['bottom'] + 250000/(math.pi*p['inner_radius']**2)
        self.assertAlmostEqual(model.fill_height_mm(spec, p, 250), expected_height)
        self.assertAlmostEqual(model.cavity_volume_ml(spec, p, expected_height), 250)
        self.assertGreater(model.cavity_volume_ml(spec, p), 250)
        self.assertLess(expected_height, p['height']-p['spout_depth'])
        self.assertEqual(model.interfaces(spec, p)['nominal_fill_plane']['origin_mm'][:2], [0, 0])

    def test_bottle_fill_height_is_continuous_through_body_shoulder_and_neck(self):
        spec = model.materialize(self.catalog, 'screw_bottle_250', 'open')
        p = model.parameters(spec)
        previous = -1
        for height in (p['bottom'], p['body_height']-1e-6, p['body_height'], p['body_height']+1e-6,
                       p['shoulder_top']-1e-6, p['shoulder_top'], p['shoulder_top']+1e-6, p['height']):
            volume = model.cavity_volume_ml(spec, p, height)
            self.assertGreaterEqual(volume, previous)
            self.assertAlmostEqual(model.fill_height_mm(spec, p, volume), height, places=7)
            previous = volume

    def test_closed_bottles_block_access_and_open_closures_are_independent_parts(self):
        for identity in ('screw_bottle_100', 'screw_bottle_250', 'screw_bottle_500', 'stopper_bottle_250'):
            with self.subTest(identity=identity):
                closed = model.materialize(self.catalog, identity, 'closed')
                opened = model.materialize(self.catalog, identity, 'open')
                pc, po = model.parameters(closed), model.parameters(opened)
                self.assertEqual(model.interfaces(closed, pc)['mouth']['origin_mm'],
                                 model.interfaces(opened, po)['mouth']['origin_mm'])
                with self.assertRaisesRegex(ValueError, 'Remove the closure'):
                    model.accessible_mouth(closed, pc)
                self.assertTrue(model.accessible_mouth(opened, po)['accessible'])
                self.assertEqual(pc['closure_x'], 0)
                self.assertGreater(po['closure_x']-po['cap_radius'], po['outer_radius'])
                closure = next(b for b in model.expanded(opened, po)['bodies'] if b['id'] == 'Closure')
                self.assertNotEqual(closure['component'], 'Glass')

    def test_funnels_expose_a_distinct_open_outlet_and_do_not_claim_storage_capacity(self):
        for identity in ('funnel_60', 'funnel_80'):
            spec = model.materialize(self.catalog, identity)
            p = model.parameters(spec)
            targets = model.interfaces(spec, p)
            self.assertIsNone(spec['item']['nominal_volume_ml'])
            self.assertEqual(targets['outlet']['origin_mm'], [0, 0, 0])
            self.assertEqual(targets['outlet']['z_axis'], [0, 0, -1])
            self.assertGreater(targets['mouth']['clear_diameter_mm'], targets['outlet']['clear_diameter_mm'])
            self.assertNotIn('support', targets)
            with self.assertRaises(ValueError):
                model.materialize(self.catalog, identity, 'closed')

    def test_parameter_variants_move_geometry_and_access_references_together(self):
        original = model.materialize(self.catalog, 'beaker_250')
        changed = model.materialize(self.catalog, 'beaker_250', overrides={'height': 'base_height+10', 'diameter': 76},
                                    context={'base_height': 95})
        a, b = model.parameters(original), model.parameters(changed)
        self.assertEqual(b['inner_radius']-a['inner_radius'], 3)
        self.assertEqual(model.interfaces(changed, b)['mouth']['origin_mm'][2]
                         -model.interfaces(original, a)['mouth']['origin_mm'][2], 10)
        self.assertGreater(model.cavity_volume_ml(changed, b), model.cavity_volume_ml(original, a))
        self.assertEqual(self.catalog['families']['beaker']['parameters']['height']['expression'], 95)

    def test_invalid_dimensions_derived_overrides_and_unimplemented_states_are_rejected(self):
        for identity, overrides in (
            ('beaker_250', {'inner_radius': 20}), ('beaker_250', {'height': True}),
            ('beaker_250', {'height': float('nan')}), ('beaker_250', {'diameter': 35}),
            ('beaker_250', {'spout_width': 8, 'wall': 4}),
            ('funnel_60', {'wall': 3, 'stem_diameter': 6}),
            ('screw_bottle_250', {'neck_height': 14, 'cap_skirt': 20}),
            ('screw_bottle_250', {'closure_x': 0}), ('beaker_250', {'future_feature': 2}),
        ):
            with self.subTest(identity=identity, overrides=overrides), self.assertRaises(ValueError):
                model.materialize(self.catalog, identity, overrides=overrides)
        for state in ('unscrewing', '', False, 0):
            with self.subTest(state=state), self.assertRaises(ValueError):
                model.materialize(self.catalog, 'screw_bottle_250', state)

    def test_invalid_volume_inputs_cannot_create_planning_targets(self):
        spec = model.materialize(self.catalog, 'beaker_250')
        p = model.parameters(spec)
        for volume in (-1, True, float('nan'), float('inf'), '250', 10000):
            with self.subTest(volume=volume), self.assertRaises(ValueError):
                model.fill_height_mm(spec, p, volume)

    def test_common_assembly_reference_selects_an_explicit_catalog_configuration(self):
        ref = {'source': 'model/lab-glassware.shared.json', 'source_sha256': model.digest(model.SOURCE),
               'case': 'screw_bottle_250_open'}
        spec = model.resolve_reference(ref)
        self.assertEqual(spec['item_id'], 'screw_bottle_250')
        self.assertTrue(model.accessible_mouth(spec, model.parameters(spec))['accessible'])
        for invalid in ({**ref, 'source_sha256': '0'*64}, {**ref, 'case': 'unknown'},
                        {**ref, 'source': '../outside.json'}):
            with self.subTest(ref=invalid), self.assertRaises(ValueError):
                model.resolve_reference(invalid)

    def test_source_rejects_unknown_recipes_units_and_parameter_fields(self):
        for field in ('recipe', 'units', 'parameter'):
            source = copy.deepcopy(self.catalog)
            if field == 'recipe':
                source['families']['beaker']['recipe'] = 'unimplemented'
            elif field == 'units':
                source['families']['beaker']['parameters']['height']['unit'] = 'm'
            else:
                source['families']['beaker']['parameters']['future_feature'] = copy.deepcopy(source['families']['beaker']['parameters']['height'])
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder)/'invalid.json'
                path.write_text(json.dumps(source))
                with self.subTest(field=field), self.assertRaises(ValueError):
                    model.load(path)

    def test_overview_is_derived_from_item_references_and_uses_native_construction_commands(self):
        spec, source, placements = model.overview(self.catalog)
        self.assertEqual(len(placements), 5)
        self.assertEqual(len(source['bodies']), 8)
        self.assertTrue(all(p['reference']['source'] == 'model/lab-glassware.shared.json' for p in placements))
        item = model.materialize(self.catalog, 'beaker_250')
        commands = model.solidcraft_commands(item, model.parameters(item))
        self.assertTrue(any(c['command'] == 'solid.revolve' for c in commands))
        self.assertTrue(any(c['command'] == 'solid.extrude' and c['params']['operation'] == 'cut' for c in commands))
        self.assertFalse(any('import' in c['command'] for c in commands))

    @unittest.skipUnless(importlib.util.find_spec('jsonschema'), 'Optional jsonschema development dependency not installed')
    def test_portable_json_schema_matches_the_catalog(self):
        from jsonschema import Draft202012Validator
        schema = json.loads((ROOT/'model/lab-glassware.schema.json').read_text())
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(self.catalog)


class GlasswareNativeEvidenceTests(unittest.TestCase):
    def test_full_native_build_checks_all_cavities_openings_closures_and_artifact_pins(self):
        path = ROOT/'cad/lab-glassware/shared-build-report.json'
        if not path.exists():
            self.skipTest('Run scripts/build_lab_glassware.py to validate actual native CAD geometry')
        report = json.loads(path.read_text())
        if not report['complete_catalog'] or not report['cross_cad_checked']:
            self.skipTest('The current report is a selected-item or single-backend build, not the complete native comparison')
        self.assertTrue(report['passed'])
        self.assertTrue(report['native_functional_checks_run'])
        for source, checksum in report['source_files_sha256'].items():
            self.assertEqual(model.digest(ROOT/source), checksum, source)
        by_id = {case['id']: case for case in report['cases']}
        self.assertEqual(len(by_id), 15)
        self.assertIn('beaker_250_resized', by_id)
        self.assertIn('overview', by_id)
        for case in report['cases']:
            with self.subTest(case=case['id']):
                self.assertTrue(case['passed'])
                self.assertTrue(all(c['passed'] for c in case['body_comparisons']))
                if case['item'] is not None:
                    checks = {c['id']: c for c in case['functional_checks']}
                    self.assertTrue(checks['real_clear_interior']['passed'])
                    self.assertTrue(checks['mouth_access_matches_configuration']['passed'])
                for kind, checksum in case['artifact_sha256'].items():
                    self.assertEqual(model.digest(ROOT/case['files'][kind]), checksum)
        for image in report['renders'].values():
            self.assertEqual(model.digest(ROOT/image['path']), image['sha256'])
        a, b = by_id['beaker_250_open']['interfaces'], by_id['beaker_250_resized']['interfaces']
        self.assertEqual(b['mouth']['origin_mm'][2]-a['mouth']['origin_mm'][2], 10)
        self.assertEqual(b['mouth']['clear_diameter_mm']-a['mouth']['clear_diameter_mm'], 6)


if __name__ == '__main__':
    unittest.main()
