"""Tip articles, variants, explicit occupancy and deliberately unresolved fit."""
import copy
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import assembly_model as assembly
import build_tip_supply as build
import tip_supply_model as model


class TipSupplyTests(unittest.TestCase):
    def setUp(self):
        self.spec = model.load()
        self.scene = json.loads(model.INSTANCES.read_text())

    def example(self, index=0):
        return copy.deepcopy(self.scene['instances'][index])

    def test_three_articles_derive_from_one_parameter_source(self):
        expected = [('tip_10_ul', '0030073754', 10, 34, 6),
                    ('tip_200_ul', '0030073819', 200, 52.7, 7.15),
                    ('tip_1000_ul', '0030073851', 1000, 70.7, 8.8)]
        original = copy.deepcopy(self.spec)
        for variant, article, capacity, length, collar in expected:
            p = model.parameters(self.spec, variant)
            self.assertEqual(self.spec['variants'][variant]['article']['catalog_number'], article)
            self.assertEqual((p['capacity'], p['tip_length'], p['collar_od']), (capacity, length, collar))
            self.assertEqual((p['slot_count'], p['strip_axis_span'], p['tray_axis_span_x']), (96, 63, 99))
        self.assertEqual(self.spec, original)
        self.assertEqual(self.spec['variants']['tip_200_ul']['article']['catalog_length_mm'], 53)

    def test_derived_and_unsupported_overrides_are_rejected(self):
        for overrides in ({'strip_axis_span': 62}, {'unknown': 1}, {'tip_length': -1}, {'collar_od': float('nan')}):
            with self.subTest(overrides=overrides), self.assertRaises((ValueError, SyntaxError)):
                assembly.parameter_variant(self.spec, overrides)
        item = self.example(); item['assembly']['overrides'] = {'tip_length': 40}
        with self.assertRaisesRegex(ValueError, 'sourced variant'):
            model.compile_instance(self.spec, item['assembly'], item['occupancy'])

    def test_complete_grid_is_twelve_eight_tip_columns_not_ninety_six_strips(self):
        item = self.example(); compiled = model.compile_instance(self.spec, item['assembly'], item['occupancy'])
        groups = {}
        for slot in compiled['slots']:
            groups.setdefault(slot['strip_id'], []).append(slot)
        self.assertEqual(len(groups), 12)
        self.assertTrue(all(len(group) == 8 for group in groups.values()))
        self.assertEqual(groups['Strip01'][0]['mouth_mm'], [0, 0, 0])
        self.assertEqual(groups['Strip12'][-1]['mouth_mm'], [99, 63, 0])
        self.assertEqual(len({s['tip_id'] for s in compiled['slots']}), 96)
        self.assertFalse(compiled['solid_geometry_ready'])
        self.assertIsNone(self.spec['geometry']['strip']['outer_length_mm'])
        self.assertIsNone(self.spec['geometry']['strip']['physical_carrier_confirmed'])

    def test_full_partial_empty_follow_explicit_slot_evidence(self):
        results = model.compile_instances()
        self.assertEqual([(v['pose'], v['occupied_count']) for v in results], [('full', 96), ('partial', 88), ('empty', 0)])
        partial = {s['id']: s for s in results[1]['slots']}
        self.assertTrue(all(not partial[row+'01']['occupied'] and partial[row+'01']['outlet_mm'] is None for row in 'ABCDEFGH'))
        self.assertTrue(partial['A02']['occupied'])
        self.assertTrue(all(s['tip_id'] is None for s in results[2]['slots']))
        self.assertTrue(all(v['occupancy_evidence']['kind'] == 'synthetic_fixture' for v in results))

    def test_bad_occupancy_is_rejected(self):
        for slots in (['A01', 'A01'], ['A00'], ['A13'], ['I01'], [None], 'full'):
            item = self.example(); item['occupancy']['occupied_slots'] = slots
            with self.subTest(slots=slots), self.assertRaises(ValueError):
                model.compile_instance(self.spec, item['assembly'], item['occupancy'])
        item = self.example(); item['assembly']['pose'] = 'empty'
        with self.assertRaisesRegex(ValueError, 'contradicts'):
            model.compile_instance(self.spec, item['assembly'], item['occupancy'])
        item = self.example(); item['occupancy']['evidence']['reference'] = ''
        with self.assertRaisesRegex(ValueError, 'Documented occupancy'):
            model.compile_instance(self.spec, item['assembly'], item['occupancy'])

    def test_instance_transform_preserves_grid_and_tip_length(self):
        item = self.example(1); item['assembly'].update(xyz=[100, 200, 300], yaw_deg=90)
        slots = {s['id']: s for s in model.compile_instance(self.spec, item['assembly'], item['occupancy'])['slots']}
        self.assertLess(math.dist(slots['A02']['mouth_mm'], [100, 209, 300]), 1e-10)
        self.assertLess(math.dist(slots['H01']['mouth_mm'], [37, 200, 300]), 1e-10)
        self.assertLess(math.dist(slots['A02']['outlet_mm'], [100, 209, 247.3]), 1e-10)
        self.assertAlmostEqual(math.dist(slots['A02']['mouth_mm'], slots['A02']['outlet_mm']), 52.7)

    def test_unknowns_never_become_invented_zeroes_or_qualification(self):
        for variant in self.spec['variants']:
            measurements = self.spec['variants'][variant]['unknown_measurements']
            self.assertTrue(all(m['value'] is None for m in measurements.values()))
            fit = model.fit_check(self.spec, variant)
            self.assertEqual(fit['status'], 'open')
            self.assertEqual(len(fit['missing']), 9)
            self.assertEqual(fit['checks'], {})
            self.assertFalse(fit['qualified'])
        large = model.fit_check(self.spec, 'tip_1000_ul')
        self.assertFalse(large['nominal_collar_screen']['retaining_overlap_possible'])
        self.assertAlmostEqual(large['nominal_collar_screen']['diametral_excess_mm'], -.2)

    def test_fit_logic_requires_every_bound_then_checks_radial_and_vertical_constraints(self):
        # Deliberately synthetic values exercise the algorithm, not the selected product.
        station = model.collector.load(); spec = copy.deepcopy(self.spec)
        station['fit_rule'].update(shaft_diameter_max_mm=5, collar_diameter_min_mm=7,
                                  radial_running_clearance_mm=.2, radial_capture_margin_mm=.2,
                                  access_gap_above_collar_min_mm=5)
        for key, value in dict(shaft_diameter_max=4.9, collar_diameter_min=7.1,
                               access_gap_above_collar=5, vertical_running_clearance=1).items():
            spec['variants']['tip_200_ul']['unknown_measurements'][key]['value'] = value
        self.assertEqual(model.fit_check(spec, 'tip_200_ul', station)['status'], 'passed')
        self.assertFalse(model.fit_check(spec, 'tip_200_ul', station)['qualified'])
        for key, value in [('shaft_diameter_max', 5.1), ('collar_diameter_min', 6.9),
                           ('access_gap_above_collar', 4.9), ('vertical_running_clearance', 2)]:
            changed = copy.deepcopy(spec); changed['variants']['tip_200_ul']['unknown_measurements'][key]['value'] = value
            self.assertEqual(model.fit_check(changed, 'tip_200_ul', station)['status'], 'failed', key)
        for key in ('shaft_diameter_max_mm', 'collar_diameter_min_mm', 'radial_running_clearance_mm', 'radial_capture_margin_mm', 'access_gap_above_collar_min_mm'):
            changed = copy.deepcopy(station); changed['fit_rule'][key] = None
            self.assertEqual(model.fit_check(spec, 'tip_200_ul', changed)['status'], 'open', key)
        self.assertTrue(all(value is None for key, value in model.collector.load()['fit_rule'].items() if key.endswith('_mm')))

    def test_measurements_need_evidence_and_finite_values(self):
        for value in (3, -1, float('nan')):
            spec = copy.deepcopy(self.spec)
            spec['variants']['tip_10_ul']['unknown_measurements']['tip_mass']['value'] = value
            with self.assertRaises(ValueError): model.validate(spec)
        spec = copy.deepcopy(self.spec); spec['geometry']['tip']['profile_complete'] = True
        with self.assertRaises(ValueError): model.validate(spec)
        spec = copy.deepcopy(self.spec); spec['geometry']['tip']['length_parameter'] = 'collar_od'
        with self.assertRaises(ValueError): model.validate(spec)

    def test_stale_collector_and_instance_sources_are_rejected(self):
        spec = copy.deepcopy(self.spec); spec['fit_to']['assembly']['source_sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'Pinned assembly'): model.validate(spec)
        self.scene['assets']['tip_supply']['source_sha256'] = '0'*64
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'instances.json'; path.write_text(json.dumps(self.scene))
            with self.assertRaisesRegex(ValueError, 'Pinned assembly'): model.compile_instances(path)

    def test_manufacturer_evidence_rejects_missing_or_modified_originals(self):
        small = {'sources': {'fixture': {**self.spec['sources']['drawing'], 'file': 'fixture.txt'}}}
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'Missing manufacturer'): build.evidence(small, directory)
            path = Path(directory)/'fixture.txt'; path.write_text('synthetic original')
            small['sources']['fixture']['sha256'] = model.robot.digest(path)
            self.assertEqual(build.evidence(small, directory)['fixture']['verified_sha256'], model.robot.digest(path))
            path.write_text('changed')
            with self.assertRaisesRegex(ValueError, 'differs'): build.evidence(small, directory)

    def test_sources_and_instances_match_strict_schema(self):
        try:
            import jsonschema
            from referencing import Registry, Resource
        except ImportError:
            self.skipTest('jsonschema is not installed')
        schemas = []
        for path in (ROOT/'model/assembly-reference.schema.json', model.SCHEMA):
            schema = json.loads(path.read_text()); schema['$id'] = path.as_uri()
            schemas.append((schema['$id'], Resource.from_contents(schema)))
        validator = jsonschema.Draft202012Validator(schema, registry=Registry().with_resources(schemas), format_checker=jsonschema.FormatChecker())
        validator.validate(self.spec); validator.validate(self.scene)
        bad = copy.deepcopy(self.spec); bad['geometry']['box']['outer_width_mm'] = 85
        with self.assertRaises(jsonschema.ValidationError): validator.validate(bad)
        bad = copy.deepcopy(self.scene); bad['instances'][0]['assembly']['overrides'] = {'capacity': 200}
        with self.assertRaises(jsonschema.ValidationError): validator.validate(bad)


if __name__ == '__main__': unittest.main()
