"""Closed BF01 contracts reject silent scope or qualification changes."""
import copy
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import building_fleet_model as model


class FleetContractTests(unittest.TestCase):
    def setUp(self):
        self.source = model.load()

    def reject(self, change):
        source = copy.deepcopy(self.source)
        change(source)
        with self.assertRaises(ValueError):
            model.validate(source, verify_pins=False)

    def test_only_explicit_k0013_deferral(self):
        self.assertEqual(self.source['missions']['deferred_targets'][0]['area'], 'K0_013')
        self.assertEqual(len(self.source['missions']['targets']), 19)
        self.reject(lambda s: s['missions']['targets'].pop())
        self.reject(lambda s: s['missions']['targets'].append(copy.deepcopy(s['missions']['targets'][0])))
        self.reject(lambda s: s['missions']['deferred_targets'].clear())

    def test_stair_exclusion_and_qualifications_are_not_optional(self):
        self.reject(lambda s: s['exclusions']['areas'].remove('R3_028'))
        self.reject(lambda s: s['qualification'].update(navigation_qualified=True))
        self.reject(lambda s: s['fleet'].update(load_state='loaded'))
        self.reject(lambda s: s['fleet'].update(count=True))
        self.reject(lambda s: s['fleet'].update(payload_kg=1))

    def test_units_ranges_and_unconfirmed_area_labels(self):
        self.reject(lambda s: s['motion']['empty_linear_limits'].update(velocity_mm_s=1451))
        self.reject(lambda s: s['motion']['empty_linear_limits'].update(acceleration_mm_s2=float('nan')))
        self.reject(lambda s: s['missions'].update(seed=1.5))
        self.reject(lambda s: s['communication'].update(latency_s=[1, .5]))
        self.reject(lambda s: s['missions']['targets'][8].update(basis='owner_description'))

    def test_long_range_fleet_scan_preserves_legacy_sensor_safety_settings(self):
        effective = model.resolved_sensor(self.source)
        original = model.reference(self.source, 'sensor')['sensor']
        self.assertEqual(effective['range_mm'], 12000)
        self.assertEqual(effective['angular_step_deg'], .36)
        self.assertEqual(model.scan_beam_count(effective['angular_step_deg']), 1000)
        self.assertEqual(effective['maximum_obstacle_closing_speed_mm_s'], 1450)
        for field in ('latency_s', 'period_s', 'stale_after_s', 'range_error_mm', 'clear_observation_s'):
            self.assertEqual(effective[field], original[field])
        self.assertEqual(effective['clearance_mm'], 75)
        self.assertLess(model.scan_angular_allowance(effective),
                        model.scan_angular_allowance(model.resolved_sensor(self.source, for_layout=True)))
        self.reject(lambda s: s['sensor']['synthetic_scan'].update(maximum_obstacle_closing_speed_mm_s=500))
        self.reject(lambda s: s['sensor']['synthetic_scan'].update(angular_step_deg=.37))
        self.reject(lambda s: s['sensor']['synthetic_scan'].update(angular_step_deg=1))
        self.reject(lambda s: s['sensor']['synthetic_scan'].update(stale_after_s=1))
        self.reject(lambda s: s['sensor'].update(basis='referenced_E5_no_override'))
        self.reject(lambda s: s['sensor'].pop('synthetic_scan'))

    def test_support_rule_is_explicit_and_cannot_be_widened(self):
        rule=model.support_settings(self.source)
        self.assertEqual(rule['gap']['maximum'],15)
        self.assertEqual(rule['closing_radius_mm'],7.5)
        self.assertIn('keine Radqualifikation',rule['basis'])
        self.reject(lambda s:s['support_rule']['gap'].update(maximum=15.5))
        self.reject(lambda s:s['support_rule']['gap'].update(open_edge_overhang=True))
        self.reject(lambda s:s['support_rule']['lift_height_exception'].update(offset_mm=3))
        self.reject(lambda s:s['support_rule']['lift_height_exception']['allowed_body_roles'].append('other_floor'))
        self.reject(lambda s:s.pop('support_rule'))

    def test_pin_change_fails_before_effects(self):
        source = copy.deepcopy(self.source)
        source['sources']['vehicle']['sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'Changed'):
            model.validate(source)
        self.assertEqual(model.resolved_sensor(self.source)['clearance_mm'], 75)

    def test_foreign_admission_policy_cannot_skip_fences_or_activation(self):
        policy=model.admission_settings(self.source)
        self.assertEqual(policy['maximum_foreign_boundaries'],1)
        self.reject(lambda s:s['missions'].pop('admission_policy'))
        self.reject(lambda s:s['missions']['admission_policy'].update(maximum_foreign_boundaries=2))
        self.reject(lambda s:s['missions']['admission_policy'].update(lookahead_source='time_only'))


if __name__ == '__main__':
    unittest.main()
