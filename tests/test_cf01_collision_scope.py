"""Report-binding tests only; fabricated reports do not establish native clearance."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import cf01_collision_scope as scope
import centrifuge_robot_pickup as pickup


class CollisionScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scene=pickup.load();cls.data=pickup.trajectory(cls.scene)

    def setUp(self):
        (ROOT/'exports').mkdir(exist_ok=True)
        self.directory=tempfile.TemporaryDirectory(dir=ROOT/'exports')
        self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name)
        self.report=self.root/'synthetic-report-fixture.json'

    def fixture(self):
        spatial=scope.workspace.load()
        trajectory=self.root/'trajectory.json';trajectory.write_text(json.dumps(self.data))
        report={'format':'solidcraftbot.synthetic-lab-scene/1','passed':True,
                'instrument_motion_validation':{'passed':True,'cf01_path_samples':len(self.data['samples']),
                    'coverage':{'moving_bodies':['Arm.link','GripperBody'],
                        'overlap':{'fixed_instrument_bodies':['NanoDrop.Frame','Qubit.Frame'],'maximum_volume_mm3':1e-3},
                        'clearance':{'nanodrop_lever_bodies':['NanoDrop.Lever'],'minimum_distance_mm':5}},
                    'exclusions':{'carried_bodies':['Tube01','ClosedCap01'],
                        'minimum_clearance_against_other_instrument_bodies':['NanoDrop.Frame','Qubit.Frame']},
                    'scope':'Fabricated arm/tool-only report-binding fixture; no native geometry proof.',
                    'exact_overlap_tests':0,'exact_distance_tests':0},
                'source_files_sha256':{str(p.relative_to(ROOT)):scope.cf.digest(p) for p in scope.workspace.source_dependencies(spatial)},
                'source_bindings':{key:value['source'] for key,value in spatial['devices'].items()},
                'cf01_trajectory':{'path':str(trajectory.relative_to(ROOT)),'sha256':scope.cf.digest(trajectory),
                                   'semantic_sha256':scope.trajectory_signature(self.data)}}
        self.write(report)
        return report,trajectory

    def write(self,report):self.report.write_text(json.dumps(report))
    def check(self,data=None):return scope.collision_scope(self.scene,data or self.data,self.report.relative_to(ROOT))

    def test_missing_report_explicitly_excludes_additional_workspace_devices(self):
        result=self.check()
        spatial=scope.workspace.load()
        self.assertEqual({item['instance_id'] for item in result['excluded_workspace_devices']},set(spatial['devices'])-{'Arm','CF01','Rack'})
        self.assertEqual(len(result['excluded_workspace_devices']),2)
        self.assertFalse(result['standalone_models_all_workspace_devices'])
        self.assertTrue(result['overall_workspace_validation_required'])
        self.assertEqual(result['overall_report']['status'],'missing')

    def test_only_current_source_and_identical_trajectory_can_cover_excluded_devices(self):
        report,_=self.fixture()
        self.assertTrue(self.check()['overall_report']['current_trajectory_checked'])
        changed=copy.deepcopy(self.data);changed['samples'][1]['joints_deg'][0]+=.1
        result=self.check(changed)
        self.assertFalse(result['overall_report']['current_trajectory_checked'])
        self.assertTrue(result['overall_workspace_validation_required'])
        report['source_files_sha256'][next(iter(report['source_files_sha256']))]='0'*64
        self.write(report)
        self.assertFalse(self.check()['overall_report']['current_trajectory_checked'])

    def test_missing_trajectory_binding_failed_report_and_changed_artifact_are_rejected(self):
        report,trajectory=self.fixture()
        report.pop('cf01_trajectory');self.write(report)
        self.assertFalse(self.check()['overall_report']['current_trajectory_checked'])
        report,trajectory=self.fixture()
        report['passed']=False;self.write(report)
        self.assertFalse(self.check()['overall_report']['current_trajectory_checked'])
        self.fixture();trajectory.write_text(trajectory.read_text()+'\n')
        self.assertFalse(self.check()['overall_report']['current_trajectory_checked'])

    def test_overall_report_must_name_every_excluded_device(self):
        report,_=self.fixture()
        report['source_bindings']={'Arm':{},'CF01':{},'Rack':{}};self.write(report)
        self.assertFalse(self.check()['overall_report']['current_trajectory_checked'])

    def test_current_report_exposes_the_producers_coverage_without_reinterpretation(self):
        report,_=self.fixture()
        result=self.check()
        self.assertEqual(result['overall_report']['status'],'current')
        self.assertFalse(result['overall_workspace_validation_required'])
        for key in ('coverage','exclusions','scope','exact_overlap_tests','exact_distance_tests'):
            self.assertEqual(result['overall_report'][key],report['instrument_motion_validation'][key])
        self.assertIn('does not imply complete workspace coverage',result['limits'])

    def test_missing_or_invalid_declared_scope_is_unverified(self):
        for key in ('coverage','exclusions','scope'):
            for value in (None,[],{}):
                with self.subTest(key=key,value=value):
                    report,_=self.fixture()
                    report['instrument_motion_validation'][key]=value;self.write(report)
                    result=self.check()
                    self.assertEqual(result['overall_report']['status'],'unverified')
                    self.assertIn('no declared coverage/exclusions/scope',result['overall_report']['reason'])
                    self.assertTrue(result['overall_workspace_validation_required'])
        report,_=self.fixture();report['instrument_motion_validation'].pop('coverage');self.write(report)
        self.assertEqual(self.check()['overall_report']['status'],'unverified')

    def test_malformed_report_objects_are_unverified_without_raising(self):
        cases=[(None,[],'Overall report must be an object'),
               ('instrument_motion_validation',None,'instrument_motion_validation must be an object'),
               ('instrument_motion_validation',[],'instrument_motion_validation must be an object'),
               ('source_files_sha256',[],'source_files_sha256 must be an object'),
               ('source_files_sha256',{'bad':None},'source_files_sha256 must be an object'),
               ('source_bindings',[],'source_bindings must be an object'),
               ('source_bindings',{'Arm':None},'source_bindings must be an object'),
               ('cf01_trajectory',[],'cf01_trajectory must be an object'),
               ('cf01_trajectory',None,'cf01_trajectory must be an object'),
               ('cf01_trajectory',{'path':[]},'cf01_trajectory must be an object')]
        for field,value,reason in cases:
            with self.subTest(field=field,value=value):
                report,_=self.fixture()
                if field is None:report=value
                else:report[field]=value
                self.write(report)
                result=self.check()
                self.assertEqual(result['overall_report']['status'],'unverified')
                self.assertIn(reason,result['overall_report']['reason'])
                self.assertFalse(result['overall_report']['current_trajectory_checked'])
                self.assertTrue(result['overall_workspace_validation_required'])
