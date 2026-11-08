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
import build_mobile_base
import mobile_base_model
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
            sections[str(ROOT/self.library['parts']['RMD-X6-P20-60-E']['sections']['housing']['step'])]={
                'step':str(step),'sha256':robot.digest(step),'body_names':['VendorHousingPart%02d'%(i+1) for i in range(7)]}
            with patch.dict(sys.modules,{'FreeCAD':None,'Part':None}):commands,manifest=native.construction(self.scene,sections)
            self.assertEqual(len(manifest),223)
            names=[n for b in manifest for n in b['names']];self.assertEqual(len(names),241);self.assertEqual(len(set(names)),241)
            self.assertEqual(len(next(b for b in manifest if b['id']=='Arm.A1_housing')['names']),4)
            self.assertEqual(len(next(b for b in manifest if b['id']=='Arm.A4_housing')['names']),3)
            self.assertEqual(len(next(b for b in manifest if b['id']=='Arm.A2_housing')['names']),7)
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

    def test_semantic_metrics_require_all_closed_parts_and_weight_their_centers(self):
        bodies=[{'name':name,'closed':True,'volume_mm3':volume,'center_of_mass':[x,0,0],
                 'bbox':{'min':[x-1,-1,-1],'max':[x+1,1,1]}}
                for name,volume,x in [('Front',1,0),('Back',3,4)]]
        aliases={'Case':['Front','Back']}
        case=vendor.semantic_bodies(bodies,['Case'],aliases)['Case']
        self.assertEqual(case['volume_mm3'],4);self.assertEqual(case['center_of_mass'],[3,0,0])
        self.assertEqual(case['bbox'],{'min':[-1,-1,-1],'max':[5,1,1]})
        expected=[{'body':'Case','volume_mm3':4,'world_center_of_mass_mm':[3,0,0],'bbox':case['bbox']}]
        self.assertTrue(build_mobile_base.compare({'bodies':bodies},expected,aliases)[0]['passed'])
        wrong=copy.deepcopy(bodies);wrong[1]['center_of_mass'][0]+=1
        self.assertFalse(build_mobile_base.compare({'bodies':wrong},expected,aliases)[0]['passed'])
        for defect in ['missing','duplicate','extra','open','center','nan','volume']:
            bad=copy.deepcopy(bodies)
            if defect=='missing':bad.pop()
            elif defect=='duplicate':bad.append(copy.deepcopy(bad[0]))
            elif defect=='extra':bad.append(dict(bad[0],name='Unexpected'))
            elif defect=='open':bad[0]['closed']=False
            elif defect=='center':bad[0]['center_of_mass']=None
            elif defect=='nan':bad[0]['center_of_mass'][0]=float('nan')
            else:bad[0]['volume_mm3']=float('nan')
            with self.subTest(defect=defect),self.assertRaises(ValueError):vendor.semantic_bodies(bad,['Case'],aliases)

    def test_arm_and_mobile_imports_keep_world_frames_and_joint_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            step=Path(directory)/'prepared.step';step.write_text('test payload')
            sections={str(ROOT/self.library['parts'][e['part']]['sections']['housing']['step']):{
                'step':str(step),'sha256':robot.digest(step),'body_names':['Part%02d'%i for i in range(len(e['expected_housing']))]}
                for e in self.fixture['parts']}
            sections[str(ROOT/self.library['parts']['RMD-X6-P20-60-E']['sections']['housing']['step'])]={
                'step':str(step),'sha256':robot.digest(step),'body_names':['Part%02d'%i for i in range(7)]}
            spec=mobile_base_model.load();p=mobile_base_model.parameters(spec)
            for commands in [robot.solidcraft_commands(self.arm),mobile_base_model.solidcraft_commands(spec,self.arm,p)]:
                result,aliases=vendor.replace_imports(commands,sections)
                self.assertEqual(set(aliases),{'A1_housing','A2_housing','A3_housing','A4_housing','A5_housing','A6_housing'})
                self.assertEqual([c for c in result if c['command'].startswith('joint.')],
                                 [c for c in commands if c['command'].startswith('joint.')])
                self.assertEqual([c['params']['matrix'] for c in result if c['command']=='file.insert_step'],
                                 [c['params']['matrix'] for c in commands if c['command']=='file.insert_step'])

    def test_vendor_preparation_isolates_repeated_occurrences_before_renaming(self):
        entry=next(e for e in self.fixture['parts'] if e['part']=='RMD-X4-P36-36-E-L')
        bodies=copy.deepcopy(entry['bodies']);selected=components.exterior_sections(self.library['parts'][entry['part']],bodies)['housing']
        originals=[next(b for b in bodies if b['name']==name) for name in selected]
        originals[0]['name']='Repeated';originals[1]['name']='Repeated (OriginalVendor:1/Part:2)'
        def execute(cli,commands,script,measurement,**options):
            phase=Path(script).name
            if phase=='import.commands.json':return {'bodies':bodies}
            if phase=='select.commands.json':
                self.assertEqual([c['params']['bodies'] for c in commands[1:]],[[b['name']] for b in originals])
                self.assertFalse(any(c['command'] in {'body.rename','solid.remove'} for c in commands))
                for command in commands[1:]:Path(command['params']['path']).write_text('single native STEP body')
                return {}
            if phase.startswith('VendorHousingPart'):
                i=int(phase.split('.')[0].removeprefix('VendorHousingPart'))-1
                return {'bodies':[dict(originals[i],name='Isolated')]}
            if phase=='exterior.commands.json':
                self.assertEqual([c['params']['body'] for c in commands if c['command']=='body.rename'],['Isolated']*len(originals))
                Path(commands[-1]['params']['path']).write_text('native STEP test payload')
                return {}
            self.assertEqual(phase,'roundtrip.commands.json')
            return {'bodies':[dict(body,name='VendorHousingPart%02d'%(i+1)) for i,body in enumerate(originals)]}
        with tempfile.TemporaryDirectory() as directory, patch.object(vendor,'AFFECTED',{entry['part']}),patch.object(vendor,'run',side_effect=execute):
            replacements,report=vendor.prepare(self.arm,'test-cli',directory)
        self.assertEqual(len(replacements),1);self.assertTrue(report['passed'])
        self.assertEqual(len(report['parts'][0]['isolated_parts']),len(originals))


if __name__=='__main__':unittest.main()
