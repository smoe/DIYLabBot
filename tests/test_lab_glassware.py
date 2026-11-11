"""Glassware access semantics, dimensional variants and actual native CAD evidence."""
import copy
import ast
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
        self.assertEqual(len(self.catalog['families']), 4)
        self.assertEqual(len(self.catalog['items']), 15)
        self.assertEqual(len(model.cases(self.catalog)), 21)
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
                self.assertGreater(po['closure_x']-po['closure_radius'], po['outer_radius'])
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

    def test_measuring_cylinder_reference_height_and_named_size_variants(self):
        ref = self.catalog['references']['Z324310']
        self.assertEqual(ref['outer_dimensions_mm']['height'],115)
        self.assertIsNone(ref['outer_dimensions_mm']['diameter'])
        self.assertEqual(ref['reference_graduations_ml']['step'],.1)
        for volume in (5,10,25,50):
            spec = model.materialize(self.catalog,'measuring_cylinder_'+str(volume))
            p = model.parameters(spec)
            self.assertGreater(model.cavity_volume_ml(spec,p),volume)
            self.assertEqual(spec['item']['nominal_volume_ml'],volume)
            foot = next(o['shape'] for o in model.expanded(spec,p)['operations'] if o['id']=='HexagonalGlassFoot')
            self.assertEqual(foot['plane'],'XY')
            self.assertEqual(len(foot['points']),6)
            self.assertGreater(p['base_across_flats'],p['diameter'])
        self.assertEqual(model.parameters(model.materialize(self.catalog,'measuring_cylinder_5'))['height'],115)

    def test_all_body_sizes_share_one_identical_closure_profile_per_closure_type(self):
        for prefix in ('screw_bottle','stopper_bottle'):
            signatures = []
            for volume in (100,250,500):
                spec = model.materialize(self.catalog,prefix+'_'+str(volume))
                p = model.parameters(spec)
                signatures.append(model.closure_signature(spec,p))
                changed = model.materialize(self.catalog,prefix+'_'+str(volume),
                    overrides={'diameter':p['diameter']+6,'body_height':p['body_height']+10,'wall':2.5})
                self.assertEqual(model.closure_signature(changed,model.parameters(changed)),signatures[-1])
            self.assertEqual(signatures[0],signatures[1])
            self.assertEqual(signatures[0],signatures[2])
        for field in ('cap_wall','cap_clearance','neck_diameter','neck_wall','closure_radius'):
            with self.subTest(field=field),self.assertRaises(ValueError):
                model.materialize(self.catalog,'screw_bottle_250',overrides={field:3})
            with self.subTest(field=field),self.assertRaises(ValueError):
                model.parameters(model.materialize(self.catalog,'screw_bottle_250'),{field:3})

    def test_composed_body_and_closure_parameters_are_declared_in_dependency_order(self):
        for item in ('screw_bottle_100','stopper_bottle_500'):
            spec = model.materialize(self.catalog,item)
            declared = set()
            for name,definition in spec['parameters'].items():
                names = {n.id for n in ast.walk(ast.parse(str(definition['expression']),mode='eval')) if isinstance(n,ast.Name)}
                self.assertLessEqual(names,declared)
                declared.add(name)

    def test_size_presets_cannot_rescale_closures_or_make_them_depend_on_body_dimensions(self):
        for change in ('size','profile'):
            catalog = copy.deepcopy(self.catalog)
            if change=='size':
                catalog['families']['bottle']['sizes']['100_ml']['overrides']['neck_diameter']=25
            else:
                catalog['closures']['screw_cap_standard']['parameters']['closure_radius']['expression']='diameter/4'
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder)/'invalid.json'
                path.write_text(json.dumps(catalog))
                with self.subTest(change=change),self.assertRaises(ValueError):
                    model.load(path)

    def test_optional_marker_text_preserves_case_and_does_not_change_vessels_or_closures(self):
        for identity,text in [('beaker_250','DNA 01'),('funnel_60','Buffer'),
                              ('measuring_cylinder_5','QC'),('screw_bottle_250','Buffer A'),
                              ('stopper_bottle_250','70%\nEtOH')]:
            plain = model.materialize(self.catalog,identity)
            labeled = model.materialize(self.catalog,identity,label={'text':text,'color':'#154985'})
            p = model.parameters(labeled)
            self.assertEqual(labeled['label']['text'],text)
            self.assertIsNone(plain['label'])
            self.assertEqual(model.parameters(plain),p)
            self.assertEqual(model.interfaces(plain,p),model.interfaces(labeled,p))
            a = model.expanded(plain,p)
            b = model.expanded(labeled,p)
            self.assertEqual(a['operations'],[o for o in b['operations'] if not o['body'].startswith('MarkerInk')])
            ink = [body for body in b['bodies'] if body['role']=='marker_ink']
            self.assertTrue(ink)
            self.assertTrue(all(body['appearance']['color']=='#154985' for body in ink))
            self.assertEqual(model.closure_signature(plain,p),model.closure_signature(labeled,p))
        self.assertNotIn('marker_label',self.catalog['items']['beaker_250'])

    def test_marker_option_rejects_unsupported_glyphs_invalid_sizes_and_overlong_text(self):
        for label in ({'text':''},{'text':'🧪'},{'text':'x','color':'red'},{'text':'x','height_mm':True},
                      {'text':'x','line_width_mm':0},{'text':'a\nb\nc\nd'},{'text':'x'*81}):
            with self.subTest(label=label),self.assertRaises(ValueError):
                model.materialize(self.catalog,'beaker_250',label=label)

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
        self.assertEqual(len(placements), 7)
        self.assertEqual(sum(b['id'].endswith('_Vessel') for b in source['bodies']),7)
        self.assertTrue(any(b['role']=='marker_ink' for b in source['bodies']))
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
        label_validator = Draft202012Validator(schema['$defs']['marker_label'])
        label_validator.validate({'text':'Buffer A'})
        label_validator.validate({'text':'70% EtOH\n5 µl'})


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
        self.assertEqual(len(by_id), 27)
        self.assertIn('beaker_250_resized', by_id)
        self.assertIn('overview', by_id)
        self.assertEqual(len(report['closure_invariance_checks']),2)
        self.assertTrue(all(c['passed'] and c['distinct_body_sizes']==3 for c in report['closure_invariance_checks']))
        for case in report['cases']:
            with self.subTest(case=case['id']):
                self.assertTrue(case['passed'])
                self.assertTrue(all(c['passed'] for c in case['body_comparisons']))
                if case['item'] is not None:
                    checks = {c['id']: c for c in case['functional_checks']}
                    self.assertTrue(checks['real_clear_interior']['passed'])
                    self.assertTrue(checks['mouth_access_matches_configuration']['passed'])
                    if case['item'].startswith('measuring_cylinder'):
                        self.assertTrue(checks['hexagonal_glass_foot']['passed'])
                    if case['marker_label'] is not None:
                        self.assertTrue(checks['marker_ink_keeps_interior_clear']['passed'])
                for kind, checksum in case['artifact_sha256'].items():
                    self.assertEqual(model.digest(ROOT/case['files'][kind]), checksum)
        for image in report['renders'].values():
            self.assertEqual(model.digest(ROOT/image['path']), image['sha256'])
        a, b = by_id['beaker_250_open']['interfaces'], by_id['beaker_250_resized']['interfaces']
        self.assertEqual(b['mouth']['origin_mm'][2]-a['mouth']['origin_mm'][2], 10)
        self.assertEqual(b['mouth']['clear_diameter_mm']-a['mouth']['clear_diameter_mm'], 6)


if __name__ == '__main__':
    unittest.main()
