"""SP01 construction invariants; geometric capacity is never dosing evidence."""
import copy
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import syringe_pipette as model


class SyringeConceptTests(unittest.TestCase):
    def setUp(self):
        self.raw = json.loads(model.SOURCE.read_text(encoding='utf-8'))
        self.spec = model.load()
        self.p = model.parameters(self.spec)

    def load_mutation(self, mutate):
        source = copy.deepcopy(self.raw)
        mutate(source)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'concept.json'
            path.write_text(json.dumps(source), encoding='utf-8')
            return model.load(path)

    def test_changed_bore_preserves_nominal_capacity_and_updates_glass_and_travel(self):
        base = model.expanded(self.spec, self.p)
        changed = model.parameters(self.spec, {'radiusFine': 2.6, 'radiusCoarse': 8})
        variant = model.expanded(self.spec, changed)
        for tag, nominal in [('Fine', 1000), ('Coarse', 10000)]:
            radius, stroke = 'radius'+tag, 'stroke'+tag
            self.assertNotEqual(changed[stroke], self.p[stroke])
            self.assertAlmostEqual(math.pi*changed[radius]**2*changed[stroke], nominal)
            self.assertAlmostEqual(changed[stroke]/self.p[stroke], (self.p[radius]/changed[radius])**2)
            old = next(o for o in base['operations'] if o['body'] == 'Glass'+tag and o['action'] == 'create')
            new = next(o for o in variant['operations'] if o['body'] == 'Glass'+tag and o['action'] == 'create')
            self.assertNotEqual(model.evaluate(old['shape']['height'], self.p),
                                model.evaluate(new['shape']['height'], changed))
            joint = next(j for j in variant['joints'] if j['id'] == 'Stroke'+tag)
            self.assertEqual(joint['limits_mm'], [0, changed[stroke]])
            observation = model.interfaces(self.spec, changed)['syringes'][tag]
            self.assertAlmostEqual(observation['geometric_swept_volume_ul'], nominal)
            self.assertIsNone(observation['calibrated_dispensed_volume_ul'])

    def test_spacing_and_height_move_barrels_valves_and_named_interfaces_together(self):
        variant = model.parameters(self.spec, {'spacing': 135, 'axisZ': 63})
        baseline = model.expanded(self.spec, self.p)
        source = model.expanded(self.spec, variant)
        for tag, sign in [('Fine', -1), ('Coarse', 1)]:
            shift = [sign*(135-self.p['spacing'])/2, 0, 63-self.p['axisZ']]
            for ident in ('Glass'+tag, 'ValveBody'+tag):
                old = next(o['shape'] for o in baseline['operations'] if o['body'] == ident and o['action'] == 'create')
                shape = next(o['shape'] for o in source['operations'] if o['body'] == ident and o['action'] == 'create')
                before = [model.evaluate(v, self.p) for v in old['origin']]
                origin = [model.evaluate(v, variant) for v in shape['origin']]
                self.assertEqual([b-a for a, b in zip(before, origin)], shift)
            old_valve = next(j for j in baseline['joints'] if j['id'] == 'Valve'+tag)
            valve = next(j for j in source['joints'] if j['id'] == 'Valve'+tag)
            before = [model.evaluate(v, self.p) for v in old_valve['origin']]
            after = [model.evaluate(v, variant) for v in valve['origin']]
            self.assertEqual([b-a for a, b in zip(before, after)], shift)
            before = model.interfaces(self.spec, self.p)['syringes'][tag]['axis_origin_mm']
            after = model.interfaces(self.spec, variant)['syringes'][tag]['axis_origin_mm']
            self.assertEqual([b-a for a, b in zip(before, after)], shift)

    def test_parameter_overrides_cannot_change_derived_quantities_or_hide_invalid_units(self):
        for override in ({'strokeFine': 5}, {'unknown': 1}, {'radiusFine': 0},
                         {'spacing': float('nan')}, {'spacing': float('inf')},
                         {'radiusFine': True}, {'axisZ': 1000}):
            with self.subTest(override=override), self.assertRaises(ValueError):
                model.parameters(self.spec, override)
        altered = copy.deepcopy(self.spec)
        altered['parameters']['radiusFine']['unit'] = 'uL'
        with self.assertRaisesRegex(ValueError, 'units'):
            model.parameters(altered)

    def test_each_actuator_moves_only_its_own_rigid_component(self):
        source = model.expanded(self.spec, self.p)
        before = model.pose(self.spec, self.p, 'park')
        after = dict(before); after['StrokeFine'] = self.p['strokeFine']/4
        point = [1.0, 2.0, 3.0]
        moved = model.pose_change_point(source, 'PlungerFine', point, self.p, before, after)
        self.assertEqual(moved[::2], point[::2])
        self.assertAlmostEqual(moved[1]-point[1], self.p['strokeFine']/4)
        for group in ['Frame', 'PlungerCoarse', 'RotorFine', 'RotorCoarse', 'TipHead']:
            with self.subTest(group=group):
                self.assertLess(math.dist(model.pose_change_point(source, group, point, self.p, before, after), point), 1e-10)

    def test_quarter_turn_keeps_its_pivot_fixed_and_does_not_turn_the_other_valve(self):
        source = model.expanded(self.spec, self.p)
        before = model.pose(self.spec, self.p, 'fine')
        after = dict(before); after['ValveFine'] = 90
        pivot = [-self.p['spacing']/2, -68, self.p['axisZ']]
        handle = [pivot[0], pivot[1]+10, pivot[2]]
        self.assertLess(math.dist(model.pose_change_point(source, 'RotorFine', pivot, self.p, before, after), pivot), 1e-10)
        expected = [pivot[0]-10, pivot[1], pivot[2]]
        self.assertLess(math.dist(model.pose_change_point(source, 'RotorFine', handle, self.p, before, after), expected), 1e-10)
        self.assertEqual(model.component_matrix(source, 'RotorCoarse', self.p, before),
                         model.component_matrix(source, 'RotorCoarse', self.p, after))
        for values in ({**after, 'ValveFine': -1}, {**after, 'ValveFine': 91},
                       {**after, 'HeadRemoval': True}, {**after, 'StrokeCoarse': float('nan')}, {}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                model.validate_pose(source, values)

    def test_exchangeable_profiles_share_the_mount_but_change_tip_and_removed_pose(self):
        states = {name: model.interfaces(self.spec, self.p, head=name) for name in ('micro', 'macro')}
        self.assertEqual(states['micro']['head_receiver_mm'], states['macro']['head_receiver_mm'])
        self.assertEqual(states['micro']['head_mating_face_mm'], states['macro']['head_mating_face_mm'])
        self.assertNotEqual(states['micro']['tip_tcp_mm'], states['macro']['tip_tcp_mm'])
        for head in states:
            attached = model.expanded(self.spec, self.p, head=head)
            before = model.pose(self.spec, self.p, 'park')
            after = model.pose(self.spec, self.p, 'head_removed')
            tcp = model.interfaces(self.spec, self.p, before, head)['tip_tcp_mm']
            actual = model.pose_change_point(attached, 'TipHead', tcp, self.p, before, after)
            expected = model.interfaces(self.spec, self.p, after, head)['tip_tcp_mm']
            self.assertLess(math.dist(actual, expected), 1e-10)
            self.assertAlmostEqual(tcp[2]-actual[2], self.p['headTravel'])
        with self.assertRaisesRegex(ValueError, 'head'):
            model.expanded(self.spec, self.p, head='unselected_commercial_tip')

    def test_changed_default_head_is_honored_by_geometry_interfaces_probes_and_metadata(self):
        spec = self.load_mutation(lambda raw: raw.update(default_head='macro'))
        p = model.parameters(spec)
        actual = model.expanded(spec, p)
        explicit = model.expanded(spec, p, head='macro')
        self.assertEqual(actual, explicit)
        self.assertEqual(model.interfaces(spec, p), model.interfaces(spec, p, head='macro'))
        self.assertNotEqual(model.interfaces(spec, p)['tip_tcp_mm'],
                            model.interfaces(spec, p, head='micro')['tip_tcp_mm'])
        values = model.pose(spec, p)
        self.assertEqual(model.geometry_probes(spec, p, values),
                         model.geometry_probes(spec, p, values, head='macro'))
        commands = model.solidcraft_commands(spec, p)
        metadata = next(c['params']['values'] for c in commands if c['command'] == 'document.metadata.set')
        self.assertEqual(metadata['org.solidcraftbot.syringe-pipette']['head'], 'macro')
        self.assertEqual(commands, model.solidcraft_commands(spec, p, head='macro'))
        for invalid in ('', 'unknown', False):
            for helper in (lambda: model.expanded(spec, p, head=invalid),
                           lambda: model.interfaces(spec, p, head=invalid),
                           lambda: model.geometry_probes(spec, p, values, head=invalid),
                           lambda: model.solidcraft_commands(spec, p, head=invalid)):
                with self.subTest(head=invalid), self.assertRaisesRegex(ValueError, 'head'):
                    helper()

    def test_every_generated_sample_stays_inside_strict_limits_including_exact_endpoints(self):
        for overrides in ({}, {'radiusFine': 2.6, 'radiusCoarse': 8},
                          {'radiusFine': 2, 'radiusCoarse': 6.5},
                          {'radiusFine': 2.8, 'radiusCoarse': 8.5}):
            p = model.parameters(self.spec, overrides)
            source = model.expanded(self.spec, p)
            samples = model.samples(self.spec, p)
            for sample in samples+model.build_samples(self.spec, p):
                with self.subTest(overrides=overrides, sample=sample['id']):
                    model.validate_pose(source, sample['joint_values'])
            for tag in ('Fine', 'Coarse'):
                values = [row['joint_values']['Stroke'+tag] for row in samples
                          if row['id'].startswith(tag+'_stroke_')]
                self.assertEqual(min(values), 0)
                self.assertEqual(max(values), p['stroke'+tag])
                outside = model.pose(self.spec, p, 'park')
                outside['Stroke'+tag] = math.nextafter(p['stroke'+tag], math.inf)
                with self.assertRaisesRegex(ValueError, 'position'):
                    model.validate_pose(source, outside)

    def test_geometric_valve_witnesses_follow_independent_states_and_existing_bodies(self):
        source = model.expanded(self.spec, self.p)
        bodies = {b['id'] for b in source['bodies']}
        expected = {'fine': ('clear', 'blocked'), 'coarse': ('blocked', 'clear'),
                    'both_closed': ('blocked', 'blocked'), 'head_removed': ('blocked', 'blocked')}
        for name, states in expected.items():
            probes = model.geometry_probes(self.spec, self.p, model.pose(self.spec, self.p, name))
            indexed = {row['id']: row for row in probes}
            self.assertEqual((indexed['Fine_valve_centerline']['expected'], indexed['Coarse_valve_centerline']['expected']), states)
            for row in probes:
                self.assertTrue(set(row['body_ids']) <= bodies)
                self.assertGreater(math.dist(row['start_mm'], row['end_mm']), 0)
            self.assertEqual('attached_head_axis' in indexed, name != 'head_removed')
        for tag in ('Fine', 'Coarse'):
            self.assertTrue(any(o['action'] == 'cut' and o['body'] == 'Glass'+tag for o in source['operations']))
            self.assertTrue(any(o['action'] == 'cut' and o['body'] == 'ValveRotor'+tag for o in source['operations']))

    def test_unknown_performance_stays_explicit_and_cannot_be_promoted_by_source_flags(self):
        self.assertTrue(all(v is False for v in self.spec['qualification'].values()))
        self.assertTrue(all(v is None for v in self.spec['open_requirements'].values()))
        for name in self.raw['qualification']:
            def qualify(raw, key=name): raw['qualification'][key] = True
            with self.subTest(qualification=name), self.assertRaisesRegex(ValueError, 'unqualified'):
                self.load_mutation(qualify)
        with self.assertRaisesRegex(ValueError, 'null'):
            self.load_mutation(lambda raw: raw['open_requirements'].update(permitted_dose_error_ul=0))
        with self.assertRaisesRegex(ValueError, 'unqualified'):
            self.load_mutation(lambda raw: raw['qualification'].pop('leakage_verified'))
        with self.assertRaisesRegex(ValueError, 'isolation'):
            self.load_mutation(lambda raw: raw['air_path']['branches'][1].update(isolation_joint='ValveFine'))

    def test_invalid_hollow_profiles_or_unknown_source_contracts_fail_closed(self):
        mutations = [lambda raw: raw.update(recipe='future_recipe'),
                     lambda raw: raw.update(unimplemented_adapter='hardware'),
                     lambda raw: raw['tip_heads']['micro'].update(wall_mm=1),
                     lambda raw: raw['tip_heads']['macro'].update(tip_length_mm=False)]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.load_mutation(mutate)

    def test_native_quantity_formulas_remain_parametric_in_both_backends(self):
        expressions = model.native_parameter_expressions(self.spec)
        commands = model.solidcraft_commands(self.spec, self.p)
        declarations = {c['params']['name']: c['params'] for c in commands if c['command'] == 'parameters.add'}
        for tag, capacity in [('Fine', 1000), ('Coarse', 10000)]:
            name, radius = 'stroke'+tag, 'radius'+tag
            self.assertIn(str(capacity)+' mm^3', expressions[name])
            self.assertEqual(expressions[name].count('ModelParameters.'+radius), 2)
            self.assertEqual(declarations[name]['expression'], expressions[name].replace('ModelParameters.', ''))
        metadata = next(c['params']['values'] for c in commands if c['command'] == 'document.metadata.set')
        qualification = metadata['org.solidcraftbot.syringe-pipette']['qualification']
        self.assertTrue(all(v is False for v in qualification.values()))
        self.assertEqual(self.spec['parameters']['strokeFine']['expression'],
                         model.load()['parameters']['strokeFine']['expression'])

    def test_strict_schema_accepts_source_and_rejects_claims_or_hidden_parameters(self):
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest('jsonschema unavailable')
        schema = json.loads((ROOT/'model/syringe-pipette.schema.json').read_text())
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        validator.validate(self.raw)
        for mutate in (lambda raw: raw.update(physical_ready=True),
                       lambda raw: raw['qualification'].update(leakage_verified=True),
                       lambda raw: raw['parameters'].update(strokeFine={'expression':60,'unit':'mm','range':[50,70],'description':'hidden independent stroke'})):
            raw = copy.deepcopy(self.raw);mutate(raw)
            self.assertTrue(list(validator.iter_errors(raw)))


class SyringeNativeEvidenceTests(unittest.TestCase):
    def test_current_native_reports_bind_source_variants_interfaces_and_saved_artifacts(self):
        path = ROOT/'cad/syringe-pipette/shared-build-report.json'
        if not path.exists():
            self.skipTest('Build SP01 to check native evidence')
        report = json.loads(path.read_text())
        self.assertTrue(report['passed'])
        self.assertEqual(report['source_sha256'], model.digest(model.SOURCE))
        for name, digest in report['source_files_sha256'].items():
            self.assertEqual(model.digest(ROOT/name), digest, name)
        self.assertEqual({row['id'] for row in report['cases']}, {'default', 'radius_variant', 'wide', 'macro'})
        for case in report['cases']:
            with self.subTest(case=case['id']):
                self.assertTrue(case['passed'])
                for name, digest in case['artifact_sha256'].items():
                    self.assertEqual(model.digest(ROOT/case['files'][name]), digest, name)
                self.assertEqual(case['interfaces']['syringes']['Fine']['calibrated_dispensed_volume_ul'], None)
                if report['backends'] == 'both':
                    self.assertTrue(all(row['passed'] for row in case['body_comparisons']))
                    self.assertTrue(all(row['passed'] for row in case['named_pose_comparisons']))
                if 'freecad_validation' in case['files']:
                    native = json.loads((ROOT/case['files']['freecad_validation']).read_text())
                    self.assertTrue(native['reopened']['passed'])
                    self.assertTrue(all(row['passed'] for row in native['native_parameter_checks']))
                    self.assertTrue(all(row['passed'] for row in native['motion_samples']))
                    self.assertTrue(all(probe['passed'] for row in native['motion_samples'] for probe in row['air_path_probes']))
                    self.assertFalse(native['hardware_motion_qualified'])
                    self.assertFalse(native['gas_tightness_qualified'])
                    self.assertFalse(native['dosing_accuracy_qualified'])


if __name__ == '__main__':
    unittest.main()
