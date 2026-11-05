"""Collector migration regressions and coupled design changes; no CAD runtime."""
from pathlib import Path
import json
import math
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import tip_collector_model as model


class TipCollectorModelTests(unittest.TestCase):
    def setUp(self): self.spec=model.load()

    def test_reviewed_t01_geometry_is_retained_with_added_umr(self):
        # Compare with the previously inspected CAD, including its text cuts.
        old=json.loads((model.ROOT/'tests/fixtures/t01-cad-check-evidence.json').read_text(encoding='utf-8'))
        refs={r['body']:r for r in model.references(self.spec,model.parameters(self.spec))}
        self.assertEqual(len(refs),14)
        for b in old['final_measurement']['bodies']:
            name=b['name']
            if name.startswith('Fork_'): name='_'.join(name.split('_')[:2])
            r=refs[name]
            self.assertLess(abs(b['volume_mm3']-r['volume_mm3'])/r['volume_mm3'],0.00002)
            self.assertLess(math.dist(b['center_of_mass'],r['center_of_mass_mm']),0.001)
        self.assertEqual({n for n in refs if n.startswith('UMR_')},{'UMR_U_0','UMR_M_1','UMR_R_2'})

    def test_raised_bin_moves_hole_pattern_and_keeps_logo_centred(self):
        p=model.parameters(self.spec); q=model.parameters(self.spec,{'bin_h':160})
        refs={r['body']:r for r in model.references(self.spec,p)}
        raised={r['body']:r for r in model.references(self.spec,q)}
        for name in ['Fork_S','Fork_M','Fork_L','RearBeam']:
            self.assertAlmostEqual(raised[name]['center_of_mass_mm'][2]-refs[name]['center_of_mass_mm'][2],10,places=8)
        for name in ['UMR_U_0','UMR_M_1','UMR_R_2']:
            self.assertAlmostEqual(raised[name]['center_of_mass_mm'][2]-refs[name]['center_of_mass_mm'][2],5,places=8)
        pilot=next(o for o in self.spec['operations'] if o['id']=='PostTopPilot_Left_34')['shape']
        self.assertEqual(model.evaluate(pilot['base'][2],q)-model.evaluate(pilot['base'][2],p),10)
        self.assertEqual(raised['RemovableBin']['bbox']['min'][2],refs['RemovableBin']['bbox']['min'][2])

    def test_middle_groove_change_only_removes_expected_insert_material(self):
        a={r['body']:r for r in model.references(self.spec,model.parameters(self.spec))}
        b={r['body']:r for r in model.references(self.spec,model.parameters(self.spec,{'groove_M':7}))}
        expected=4*(9+29+math.pi*(49-36)/8)
        self.assertAlmostEqual(a['Fork_M']['volume_mm3']-b['Fork_M']['volume_mm3'],expected,places=7)
        for name in a.keys()-{'Fork_M'}: self.assertEqual(a[name],b[name])

    def test_bad_dimensions_and_derived_overrides_are_rejected(self):
        for change in [{'bin_h':130},{'groove_M':0},{'fork_z':180},{'no_such_parameter':1},
                       {'bin_wall':80},{'mouth_width':3},{'base_x':-10}]:
            with self.assertRaises(ValueError): model.parameters(self.spec,change)


if __name__=='__main__': unittest.main()
