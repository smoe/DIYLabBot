"""Regressions for reuse of the native load check on exact return motion."""
import copy
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from check_lab3003_cf01_transfer_freecad import (
    JAW_PVA, PVA, _reflected_evidence, _swept_box, _verify_return_samples,
)
import robot_spec as robot


def point(time, positions, fields):
    zero = [0.] * len(positions)
    return {'time_s': time, fields[0]: positions, fields[1]: zero[:], fields[2]: zero[:]}


def tracks():
    load = {'id': 'B2_Tube01', 'slot': 1, 'grip_s': 2., 'seat_s': 5.,
            'points': [point(i, [float(q)] * 6, PVA)
                       for i, q in zip((0, 1, 2, 4, 5, 6), (0, 1, 1, 2, 2, 0))],
            'jaw_points': [point(t, [float(gap)], JAW_PVA)
                           for t, gap in zip((0, 1, 2, 4, 5, 5.5, 6), (11, 11, 6, 6, 19, 19, 11))]}
    load['points'][0][PVA[1]][0] = 1.
    unload = {'id': load['id'], 'slot': load['slot'], 'direction': 'unload',
              'grip_s': 2., 'seat_s': 5.}
    for name, fields in (('points', PVA), ('jaw_points', JAW_PVA)):
        unload[name] = [dict(row, time_s=6.-row['time_s'],
                             **{fields[1]: [-v for v in row[fields[1]]]})
                        for row in reversed(load[name])]
    return load, unload


class NativeCF01ReturnTests(unittest.TestCase):
    def test_exact_reverse_checks_arm_jaw_and_custody(self):
        load, unload = tracks()
        _verify_return_samples([load], [unload])
        for mutate in (lambda track: track['points'][-1][PVA[1]].__setitem__(0, 1.),
                       lambda track: track['jaw_points'][0][JAW_PVA[0]].__setitem__(0, 12.),
                       lambda track: track.update(grip_s=1.)):
            changed = copy.deepcopy(unload)
            mutate(changed)
            with self.assertRaises(ValueError):
                _verify_return_samples([load], [changed])

    def test_changes_of_ownership_require_the_arm_to_hold(self):
        load, unload = tracks()
        load['points'][2][PVA[2]][0] = 1.
        with self.assertRaisesRegex(ValueError, 'held throughout jaw travel'):
            _verify_return_samples([load], [unload])

    def test_reflected_intervals_are_contiguous_and_keep_numerical_reserve(self):
        evidence = {'id': 'B2_Tube01', 'slot': 1, 'passed': True, 'duration_s': 7.,
                    'lift_mm': 16., 'seat_axis_error_mm': 0.,
                    'raised_pose_from_cassette': robot.identity(),
                    'intervals': [{'start_s': 0., 'end_s': 2., 'clearance_lower_mm': .1},
                                  {'start_s': 2., 'end_s': 7., 'clearance_lower_mm': .2}]}
        reverse = _reflected_evidence(evidence)
        self.assertEqual([(x['start_s'], x['end_s']) for x in reverse['intervals']],
                         [(0., 5.), (5., 7.)])
        self.assertAlmostEqual(.2-reverse['intervals'][0]['clearance_lower_mm'],
                               reverse['reflection_allowance_mm'])

    def test_parked_station_box_includes_intermediate_hinge_extremum(self):
        box = (-4., 2., 0., 8., 3., 6.)
        joint = {'type': 'revolute', 'axis': [-1, 0, 0], 'origin': [0, 0, 0], 'limits': [0, 105]}
        lower_x, _, _, upper_x, upper_y, _ = _swept_box(box, robot.identity(), joint)
        self.assertAlmostEqual(lower_x, -4., places=4)
        self.assertAlmostEqual(upper_x, 8., places=4)
        self.assertAlmostEqual(upper_y, math.hypot(3., 6.), places=4)


if __name__ == '__main__':
    unittest.main()
