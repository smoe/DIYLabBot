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
                'instrument_motion_validation':{'passed':True,'cf01_path_samples':len(self.data['samples'])},
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
