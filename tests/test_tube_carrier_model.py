"""H01 source contracts: interchangeable carriers, distinct cavities and gated transfer."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import tube_carrier_model as model


class TubeCarrierModelTests(unittest.TestCase):
    def setUp(self):
        self.spec = model.load(); self.p = model.parameters(self.spec)

    def test_same_outer_carrier_for_different_tube_bottoms(self):
        operations = model.expanded(self.spec, self.p)['operations']
        shells = []
        for tag, offset in [('V15', -46), ('V20', 46)]:
            shapes = []
            for op in operations:
                if op['body'] != tag + '_CarrierShell': continue
                shape = model.numeric_shape(op['shape'], self.p); shape['origin'][0] -= offset
                shapes.append((op['action'], shape))
            shells.append(shapes)
        self.assertEqual(shells[0], shells[1])
        profiles = {op['id']: op['shape'] for op in operations if op['shape']['kind'] == 'revolved_profile'}
        self.assertGreater(len(profiles['V20_InsertProfile']['points_rz']), len(profiles['V15_InsertProfile']['points_rz']))
        self.assertNotEqual(profiles['V15_InsertProfile']['points_rz'], profiles['V20_InsertProfile']['points_rz'])

    def test_transfer_samples_require_open_latch(self):
        for sample in model.samples(self.spec, self.p):
            values = sample['values_mm']
            model.validate_pose(model.expanded(self.spec, self.p), values)
            for tag in ['V15', 'V20']:
                if values['Slide' + tag] > 0:
                    self.assertEqual(values['Latch' + tag], self.p['latch_travel'])

    def test_motion_axes_and_units_are_explicit(self):
        source = model.expanded(self.spec, self.p)
        values = model.pose(self.spec, self.p, 'both_outside')
        self.assertEqual(model.displacement(source, 'CarrierV15', values), [0, -55, 0])
        self.assertEqual(model.displacement(source, 'DockLatchV20', values), [35, 0, 0])
        self.assertEqual(self.spec['units'], {'length': 'mm', 'angle': 'deg'})

    def test_unsupported_sizes_and_unknown_overrides_are_rejected(self):
        for override in [{'tube_radius': 20}, {'radial_clearance': 0}, {'module_pitch': 0}, {'unknown': 1}]:
            with self.assertRaises(ValueError): model.parameters(self.spec, override)
        with self.assertRaises(ValueError):
            model.validate_pose(model.expanded(self.spec, self.p), {'SlideV15': 999})


if __name__ == '__main__': unittest.main()
