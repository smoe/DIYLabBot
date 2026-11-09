"""Instrument concept interfaces, parameter variants and actual CAD evidence."""
import copy
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import instrument_concept as model


class InstrumentSourceTests(unittest.TestCase):
    def test_closed_microvolume_probe_is_aligned_above_flat_sample_face(self):
        spec = model.load(model.SOURCES['nanodrop-concept'])
        for overrides in ({}, {'base_h': 38}, {'width': 195, 'depth': 215}):
            p = model.parameters(spec, overrides)
            frames = model.interfaces(spec, p)
            self.assertEqual(frames['upper_surface'][:2], frames['sample_surface'][:2])
            self.assertAlmostEqual(frames['upper_surface'][2]-frames['sample_surface'][2], 1.2)
            opened = model.interfaces(spec, p, spec['poses_deg']['loading'])
            self.assertGreater(opened['upper_surface'][2]-frames['sample_surface'][2], 70)

    def test_housing_variant_moves_geometry_targets_and_hinge_together(self):
        for source in model.SOURCES.values():
            spec = model.load(source)
            base = model.parameters(spec)
            raised = model.parameters(spec, {'base_h': base['base_h']+4})
            first, second = model.interfaces(spec, base), model.interfaces(spec, raised)
            for frame in first:
                self.assertEqual(first[frame][:2], second[frame][:2])
                self.assertAlmostEqual(second[frame][2]-first[frame][2], 4)
            old = model.expanded(spec, base)['joints'][0]
            new = model.expanded(spec, raised)['joints'][0]
            self.assertAlmostEqual(model.evaluate(new['origin'][2], raised)
                                   -model.evaluate(old['origin'][2], base), 4)

    def test_only_declared_independent_parameters_and_finite_angles_are_accepted(self):
        for source in model.SOURCES.values():
            spec = model.load(source)
            for overrides in ({'sample_z': 50}, {'width': 0}, {'base_h': True},
                              {'unknown': 1}, {'width': float('nan')}):
                with self.subTest(source=source.name, overrides=overrides), self.assertRaises(ValueError):
                    model.parameters(spec, overrides)
            p = model.parameters(spec)
            expanded = model.expanded(spec, p)
            for value in (-1, p['max_open']+1, True, float('inf')):
                with self.subTest(angle=value), self.assertRaises(ValueError):
                    model.validate_pose(expanded, {'Hinge': value})

    def test_hinge_motion_is_reversible_and_fixed_sample_does_not_move(self):
        for source in model.SOURCES.values():
            spec = model.load(source)
            p = model.parameters(spec)
            sample = model.interfaces(spec, p)['sample_surface']
            for state in model.samples(spec, p):
                angle = state['joint_values']['Hinge']
                model.validate_pose(model.expanded(spec, p), state['joint_values'])
                moving = model.transform(spec, p, 'MovingArm', sample, angle)
                restored = model.transform(spec, p, 'MovingArm', moving, -angle)
                self.assertLess(math.dist(sample, restored), 1e-10)
                self.assertEqual(model.transform(spec, p, 'Frame', sample, angle), sample)

    def test_source_cannot_swap_length_angle_units_or_declare_unimplemented_parameters(self):
        for source in model.SOURCES.values():
            for field, unit in [('width', 'deg'), ('max_open', 'mm')]:
                spec = model.load(source)
                spec['parameters'][field]['unit'] = unit
                with self.subTest(field=field), self.assertRaises(ValueError):
                    model.parameters(spec)
            spec = model.load(source)
            spec['parameters']['future_parameter'] = copy.deepcopy(spec['parameters']['width'])
            with self.assertRaisesRegex(ValueError, 'Only declared'):
                model.parameters(spec)

    def test_one_to_two_microlitre_drop_uses_cubic_mm_without_visual_scaling(self):
        base = model.load(model.SOURCES['nanodrop-concept'])
        for volume in (1, 1.5, 2):
            spec = copy.deepcopy(base)
            spec['sample_reference']['volume_ul'] = volume
            p = model.parameters(spec)
            operations = model.expanded(spec, p)['operations']
            sphere = next(o['shape'] for o in operations if o['id'] == 'SampleDrop')
            radius = sphere['radius']
            self.assertAlmostEqual(2*math.pi*radius**3/3, volume)
            self.assertLess(radius, 1.35)
            self.assertEqual(sphere['origin'], ['sample_x', 'sample_y', 'sample_z'])

    def test_qubit_has_one_real_chamber_cut_and_an_independent_reference_tube(self):
        spec = model.load(model.SOURCES['qubit-4-concept'])
        p = model.parameters(spec)
        source = model.expanded(spec, p)
        operations = source['operations']
        opening = next(o for o in operations if o['id'] == 'ChamberOpening')
        self.assertEqual(opening['action'], 'cut')
        self.assertEqual(opening['shape']['origin'][:2], ['sample_x', 'sample_y'])
        self.assertEqual([b['id'] for b in source['bodies'] if b['role'] == 'sample_chamber'], ['ChamberCollar'])
        self.assertEqual(next(b['component'] for b in source['bodies'] if b['id'] == 'ReferenceTube'), 'Frame')

    def test_sources_are_independent_concepts_and_reject_unknown_recipe(self):
        for source in model.SOURCES.values():
            spec = model.load(source)
            self.assertFalse(spec['design']['manufacturer_geometry_used'])
            self.assertFalse(spec['design']['manufacturer_logos_used'])
            self.assertFalse(spec['design']['dimensions_measured'])
            spec['recipe'] = 'unimplemented'
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder)/'invalid.json'
                path.write_text(json.dumps(spec))
                with self.assertRaisesRegex(ValueError, 'Unsupported'):
                    model.load(path)


class InstrumentBuildEvidenceTests(unittest.TestCase):
    def test_native_models_match_and_actual_sample_interfaces_are_checked(self):
        for family, source in model.SOURCES.items():
            report_path = ROOT/'cad'/family/'shared-build-report.json'
            if not report_path.exists():
                self.skipTest('Build instrument concepts to check native CAD evidence')
            report = json.loads(report_path.read_text())
            self.assertTrue(report['passed'])
            self.assertEqual(report['source_sha256'], model.digest(source))
            for path, checksum in report['source_files_sha256'].items():
                self.assertEqual(model.digest(ROOT/path), checksum, path)
            for case in report['cases']:
                with self.subTest(family=family, case=case['id']):
                    self.assertTrue(case['passed'])
                    self.assertEqual(case['maximum_step_xor_mm3'], 0)
                    self.assertTrue(all(c['passed'] for c in case['closed_pose_body_comparisons']))
                    native = json.loads((ROOT/case['files']['freecad_validation']).read_text())
                    self.assertEqual(len(native['motion_samples']), 16)
                    self.assertTrue(all(s['passed'] and not s['between_components'] for s in native['motion_samples']))
                    self.assertTrue(all(i['passed'] for i in native['interfaces']))
                    for kind, checksum in case['artifact_sha256'].items():
                        self.assertEqual(model.digest(ROOT/case['files'][kind]), checksum)


if __name__ == '__main__':
    unittest.main()
