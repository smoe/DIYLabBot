"""Native build boundaries using synthetic reports, not CAD qualification."""
import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import build_lab_layout as build
import export_building_walkthrough_freecad as export


class BackendSelectionTests(unittest.TestCase):
    def test_freecad_backend_does_not_discover_or_invoke_solidcraft(self):
        with patch.object(build.tool_paths,'default_freecad_python',return_value='native-python') as native, \
             patch.object(build.tool_paths,'default_solidcraft_cli',side_effect=AssertionError('Other CAD queried')), \
             patch.object(build,'prepare',return_value={}) as prepare:
            build.main(['--backend','freecad','--prepare-only'])
        native.assert_called_once_with()
        self.assertEqual(prepare.call_args.args[0].backend,'freecad')

    def test_default_backend_retains_both_tool_requirements(self):
        with patch.object(build.tool_paths,'default_freecad_python',return_value='native-python') as native, \
             patch.object(build.tool_paths,'default_solidcraft_cli',return_value='solidcraft') as other, \
             patch.object(build,'prepare',return_value={}) as prepare:
            build.main(['--prepare-only'])
        native.assert_called_once_with();other.assert_called_once_with()
        self.assertEqual(prepare.call_args.args[0].backend,'both')

    def test_freecad_preparation_never_compiles_solidcraft_commands(self):
        context={'backends':'freecad'}
        with patch.object(build,'prepare_native',return_value=({},context)), \
             patch.object(build.room,'solidcraft_commands',side_effect=AssertionError('Other CAD compiled')):
            self.assertIs(build.prepare(SimpleNamespace(backend='freecad')),context)

    def test_resume_rejects_a_different_backend(self):
        with self.assertRaisesRegex(ValueError,'backend differs'):
            build.finish({'backends':'freecad'},SimpleNamespace(backend='both'))

    def test_snapshot_binds_vendor_steps_interfaces_cameras_and_native_adapters(self):
        pins=build.source_snapshot(build.model.load(validate_builds=False))
        expected=['scripts/robot_cameras.py','scripts/servo_mounting_design.py','scripts/x6_mounting_design.py',
                  'scripts/build_lab_layout_freecad.py','scripts/build_lab_equipment_freecad.py',
                  'scripts/centrifuge_mechanisms.py','cad/vendor/myactuator/component-library.json']
        self.assertTrue(set(expected)<=set(pins))
        self.assertEqual(len([p for p in pins if p.endswith('.step')]),6)
        self.assertEqual(len([p for p in pins if p.endswith('interface-check-fit-v1.json')]),3)


class NativeReportBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.out=self.root/'exports/generated/fixture';self.out.mkdir(parents=True)
        (self.root/'cad').mkdir();(self.root/'model').mkdir()
        self.source=self.root/'model/lab-layout-l01.shared.json';self.source.write_text('synthetic source')
        self.scene=self.root/'cad/fixture.FCStd';self.scene.write_bytes(b'synthetic native artifact; not a real CAD proof')
        self.validation={'passed':True,'geometry_valid':True,'invalid_objects':[],'body_count':1,
                         'scene_geometry':[{'body':'FixtureTube','bbox':{'min':[0,0,0],'max':[1,1,1]}}],
                         'vehicle_route':{'samples':1}}
        self.context={'backends':'freecad','revision':'fixture','out':str(self.out),'scene_file':str(self.scene),
                      'source_sha256':build.model.digest(self.source),'styles':{'FixtureTube':{'color':'#ffffff','opacity':1}},
                      'source_files_sha256':{'model/lab-layout-l01.shared.json':build.model.digest(self.source)},
                      'freecad_runtime':{'version':['synthetic'],'python':'synthetic'}}
        self.spec={'assets':{},'limitations':['Synthetic fixture only']}
        self.persist=SimpleNamespace(persist=lambda *args:{'passed':True,'gui_render_checked':False})

    def finish(self):
        (self.out/'layout-validation.json').write_text(json.dumps(self.validation))
        with patch.object(build.model,'ROOT',self.root),patch.object(build.model,'load',return_value=self.spec), \
             patch.dict(sys.modules,{'persist_station_view':self.persist}):
            return build.finish_freecad(self.context)

    def test_native_only_report_is_accepted_and_claims_no_cross_cad_checks(self):
        report=self.finish()
        self.assertTrue(report['passed']);self.assertEqual(report['backends'],'freecad')
        self.assertIs(report['cross_cad_checked'],False)
        self.assertEqual(set(report['files']),{'freecad','validation'})
        self.assertNotIn('equipment_body_comparisons',report)
        path=self.root/'cad/lab-layout-l01/shared-build-report.json'
        self.assertEqual(export.checked_report(path,'lab',self.root),report)
        self.scene.write_bytes(b'changed artifact')
        with self.assertRaisesRegex(ValueError,'Changed or missing checked input'):
            export.checked_report(path,'lab',self.root)

    def test_changed_input_rejects_report_before_presentation_or_shared_write(self):
        self.source.write_text('changed during build')
        with self.assertRaisesRegex(ValueError,'input changed'):
            self.finish()
        self.assertFalse((self.root/'cad/lab-layout-l01/shared-build-report.json').exists())

    def test_failed_or_incomplete_native_validation_never_becomes_a_successful_report(self):
        for change in [{'passed':False},{'geometry_valid':False},{'body_count':2},{'invalid_objects':['bad']},
                       {'scene_geometry':[]},{'scene_geometry':self.validation['scene_geometry']*2,'body_count':2}]:
            with self.subTest(change=change):
                original=copy.deepcopy(self.validation);self.validation.update(change)
                with self.assertRaises(ValueError):self.finish()
                self.assertFalse((self.out/'build-report.json').exists())
                self.validation=original


if __name__=='__main__':unittest.main()
