"""Station source migration, dependency behavior and range/error checks."""
from pathlib import Path
import copy
import json
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import station_model as model


class StationModelTests(unittest.TestCase):
    def setUp(self): self.spec=model.load()

    def test_reviewed_c01_volumes_preserved(self):
        baseline=json.loads((model.ROOT/'tests/fixtures/c01-geometry-reference.json').read_text(encoding='utf-8'))
        expected={b['name']:b['volume_mm3'] for b in baseline['parts']}
        reference_ids={b['id'] for b in self.spec['bodies'] if b['role']!='marking'}
        actual={b['body']:b['volume_mm3'] for b in model.references(self.spec,model.parameters(self.spec)) if b['body'] in reference_ids}
        self.assertEqual(set(actual),set(expected))
        for name in expected: self.assertAlmostEqual(actual[name],expected[name],places=7)

    def test_work_height_moves_pivots_and_supports(self):
        base=model.parameters(self.spec); raised=model.parameters(self.spec,{'tube_mouth_z':110})
        self.assertEqual(raised['pivot_z']-base['pivot_z'],10)
        normal={b['body']:b for b in model.references(self.spec,base)}
        other={b['body']:b for b in model.references(self.spec,raised)}
        for name in ['ReferenceTube','ColdInsert','OpeningFinger','MotorEnvelopeLeft']:
            self.assertAlmostEqual(other[name]['center_of_mass_mm'][2]-normal[name]['center_of_mass_mm'][2],10)
        self.assertEqual(other['FramePostLeft']['bbox']['max'][2]-normal['FramePostLeft']['bbox']['max'][2],10)
        self.assertEqual(other['FramePostLeft']['bbox']['min'][2],normal['FramePostLeft']['bbox']['min'][2])

    def test_coolant_displacement_disappears_at_contact_boundary(self):
        def volume(height):
            return next(b['volume_mm3'] for b in model.references(self.spec,model.parameters(self.spec,{'tube_mouth_z':height})) if b['body']=='IceWaterReference')
        self.assertEqual(volume(100),573612)
        self.assertEqual(volume(102),576204)
        self.assertEqual(volume(103),577500)
        self.assertEqual(volume(110),577500)

    def test_source_ranges_and_derived_parameter_guard(self):
        for override in [{'base_length':199},{'tube_mouth_z':111},{'pivot_z':105},{'NotAParameter':1}]:
            with self.assertRaises(ValueError): model.parameters(self.spec,override)

    def test_joint_rotation_sign_and_units(self):
        p=model.parameters(self.spec)
        pose={j['id']:0 for j in self.spec['joints']}; pose['Opener']=-90
        actual=model.transform(self.spec,'Opener',[0,-3,101],p,pose)
        for a,b in zip(actual,[0,7,111]): self.assertAlmostEqual(a,b,places=9)
        pose['Opener']=-141
        with self.assertRaises(ValueError): model.validate_pose(self.spec,pose)


if __name__=='__main__': unittest.main()
