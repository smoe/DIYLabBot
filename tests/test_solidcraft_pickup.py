"""Independent native recipes, exterior identity and strict posed-body checks."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import centrifuge_pickup_solidcraft as native
import centrifuge_robot_pickup as pickup
import robot_components as components
import robot_spec as robot
import solidcraft_vendor as vendor
from export_centrifuge_robot_pickup_solidcraft import validate_snapshot


class NativeSolidCraftTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scene=pickup.load();cls.arm=pickup.arm_source(cls.scene);cls.library=components.library(cls.arm)
        cls.fixture=json.loads((ROOT/'tests/fixtures/solidcraft-vendor-exterior.json').read_text())

    def test_original_case_partition_matches_reviewed_vendor_exteriors(self):
        for entry in self.fixture['parts']:
            part=self.library['parts'][entry['part']]
            self.assertEqual(robot.digest(ROOT/entry['original']),entry['original_sha256'])
            found=components.exterior_sections(part,entry['bodies'])
            self.assertEqual(found['housing'],entry['expected_housing'])
            self.assertEqual(found['output'],entry['expected_output'])
            self.assertEqual(found['pins'],[])

    def test_missing_ambiguous_or_open_vendor_sections_are_rejected(self):
        entry=self.fixture['parts'][0];part=self.library['parts'][entry['part']]
        for defect in ['missing','ambiguous','open']:
            bodies=copy.deepcopy(entry['bodies'])
            if defect=='missing':bodies=[b for b in bodies if b['name'] not in entry['expected_output']]
            elif defect=='ambiguous':
                extra=copy.deepcopy(next(b for b in bodies if b['name'] in entry['expected_output']));extra['name']='OtherOutput';bodies.append(extra)
            else:next(b for b in bodies if b['name'] in entry['expected_housing'])['closed']=False
            with self.subTest(defect=defect),self.assertRaises(ValueError):components.exterior_sections(part,bodies)

    def test_native_scene_builds_without_freecad_and_keeps_semantic_housing_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            step=Path(directory)/'prepared.step';step.write_text('isolated test payload')
            sections={str(ROOT/self.library['parts'][e['part']]['sections']['housing']['step']):{
                'step':str(step),'sha256':robot.digest(step),'body_names':['VendorHousingPart%02d'%(i+1) for i in range(len(e['expected_housing']))]} for e in self.fixture['parts']}
            with patch.dict(sys.modules,{'FreeCAD':None,'Part':None}):commands,manifest=native.construction(self.scene,sections)
            self.assertEqual(len(manifest),223)
            names=[n for b in manifest for n in b['names']];self.assertEqual(len(names),235);self.assertEqual(len(set(names)),235)
            self.assertEqual(len(next(b for b in manifest if b['id']=='Arm.A1_housing')['names']),4)
            self.assertEqual(len(next(b for b in manifest if b['id']=='Arm.A4_housing')['names']),3)
            imports=[c['params']['path'] for c in commands if c['command']=='file.insert_step']
            self.assertTrue(imports);self.assertTrue(all(p==str(step) or p.startswith(str(ROOT/'cad/vendor')) for p in imports))
            self.assertFalse(any(c['command'].startswith('joint.') for c in commands))
            self.assertTrue(any(c['command']=='solid.cylinder' and c['params'].get('body_name')=='Rotor' for c in commands))
            step.write_text('changed')
            with self.assertRaisesRegex(ValueError,'changed'):native.construction(self.scene,sections)

    def test_aliases_follow_component_and_appearance_references(self):
        with tempfile.TemporaryDirectory() as directory:
            step=Path(directory)/'part.step';step.write_text('fixture')
            commands=[{'command':'file.insert_step','params':{'path':'original.step','matrix':robot.identity()}},
                      {'command':'body.rename','params':{'body':'Vendor','name':'A1_housing'}},
                      {'command':'component.move_bodies','params':{'component':'L0_Base','bodies':['A1_housing','BasePlate']}},
                      {'command':'appearance.assign','params':{'bodies':['A1_housing'],'opacity':1}}]
            result,aliases=vendor.replace_imports(commands,{'original.step':{'step':str(step),'sha256':robot.digest(step),'body_names':['Front','Back']}})
            self.assertEqual(aliases['A1_housing'],['A1_housing_Part01','A1_housing_Part02'])
            self.assertEqual(result[-2]['params']['bodies'],aliases['A1_housing']+['BasePlate'])
            self.assertEqual(result[-1]['params']['bodies'],aliases['A1_housing'])

    def test_pose_validation_rejects_wrong_identity_open_body_and_wrong_placement(self):
        body={'name':'Probe','closed':True,'volume_mm3':10,'center_of_mass':[2,0,1]}
        base={'bodies':[body]};manifest=[{'id':'StableProbe','group':'Tool','names':['Probe'] }]
        matrix=[[0,-1,0,10],[1,0,0,20],[0,0,1,30],[0,0,0,1]]
        actual=copy.deepcopy(base);actual['bodies'][0]['center_of_mass']=[10,22,31]
        self.assertTrue(validate_snapshot(base,actual,manifest,{'Tool':matrix})['passed'])
        wrong=copy.deepcopy(actual);wrong['bodies'][0]['center_of_mass'][0]+=1
        self.assertFalse(validate_snapshot(base,wrong,manifest,{'Tool':matrix})['passed'])
        for defect in ['open','missing','duplicate','renamed']:
            bad=copy.deepcopy(actual)
            if defect=='open':bad['bodies'][0]['closed']=False
            elif defect=='missing':bad['bodies']=[]
            elif defect=='duplicate':bad['bodies']*=2
            else:bad['bodies'][0]['name']='Other'
            with self.subTest(defect=defect),self.assertRaises(ValueError):validate_snapshot(base,bad,manifest,{'Tool':matrix})


if __name__=='__main__':unittest.main()
