"""Offline fail-closed guards for linked geometry and native-evidence finishing."""
import copy
import base64
import contextlib
import gzip
import hashlib
import io
import json
import re
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import build_cf01_unload_demo as build
import cf01_unload_geometry as geometry


class GeometryCacheTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name).resolve()
        names=geometry.GEOMETRY_CODE|{'model/robot.json','model/centrifuge-cf01.shared.json',
                                    'model/centrifuge-cf01.robot-pickup.shared.json'}
        for name in names:
            target=self.root/name;target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes((ROOT/name).read_bytes())
        self.out=self.root/'exports/base';self.cad=self.root/'cad/base'
        self.out.mkdir(parents=True);self.cad.mkdir(parents=True)
        self.scene_path=self.root/'model/centrifuge-cf01.robot-pickup.shared.json'
        self.write(self.out/'scene-mesh.json',{'bodies':[]})
        self.write(self.out/'scene-source.json',{'purpose':'immutable fake construction snapshot'})
        self.write(self.out/'trajectory.json',{'scene_sha256':geometry.sha(self.scene_path)})
        (self.cad/'CF01_Robot_Closed.FCStd').write_bytes(b'FAKE NATIVE ARTIFACT; NEVER OPENED BY THESE TESTS\n')
        self.station_native=self.root/'cad/generated/station-revision/Centrifuge_CF01.FCStd'
        self.station_native.parent.mkdir(parents=True);self.station_native.write_bytes(b'FAKE STATION INPUT; NEVER OPENED\n')
        station_names={'model/centrifuge-cf01.shared.json','scripts/centrifuge_model.py',
                       'scripts/centrifuge_mechanisms.py','scripts/build_centrifuge_freecad.py',
                       'scripts/robot_spec.py','scripts/freecad/solidcraftbot_freecad.py'}
        station_sources={name:geometry.sha(self.root/name) for name in station_names}
        self.station_report={'format':'solidcraftbot.centrifuge-build/1','passed':True,
                             'source_files_sha256':station_sources,
                             'cases':[{'id':'default','passed':True,'files':{'freecad':str(self.station_native.relative_to(self.root))},
                                       'artifact_sha256':{'freecad':geometry.sha(self.station_native)}}]}
        self.station_path=self.root/'exports/generated/station-revision/build-report.json'
        self.station_path.parent.mkdir(parents=True);self.write(self.station_path,self.station_report)
        station_only={'scripts/centrifuge_mechanisms.py','scripts/build_centrifuge_freecad.py','scripts/freecad/solidcraftbot_freecad.py'}
        self.report={'format':'solidcraftbot.centrifuge-robot-pickup-build/1','passed':True,
                     'out':'exports/base','cad':'cad/base',
                     'centrifuge_native':str(self.station_native),'native_input_sha256':{str(self.station_native):geometry.sha(self.station_native)},
                     'source_files_sha256':{name:geometry.sha(self.root/name) for name in names if name not in station_only},
                     'solidcraft_snapshots':{'source_files_sha256':{}},
                     'artifact_sha256':{str(path.relative_to(self.root)):geometry.sha(path)
                                        for path in [*self.out.iterdir(),self.cad/'CF01_Robot_Closed.FCStd']}}
        self.report_path=self.root/'cad/report.json';self.save()
        for target,name,value in [(geometry,'ROOT',self.root),(geometry.pickup,'SOURCE',self.scene_path)]:
            replacement=patch.object(target,name,value);replacement.start();self.addCleanup(replacement.stop)

    def write(self,path,value):path.write_text(json.dumps(value)+'\n',encoding='utf-8')
    def save(self):self.write(self.report_path,self.report)

    def test_accepts_only_the_pinned_construction_bundle_not_old_motion_evidence(self):
        bundle=geometry.load_bundle(self.report_path)
        self.assertEqual(bundle['files']['native'],self.cad/'CF01_Robot_Closed.FCStd')
        self.assertIn('not evidence for the new program',bundle['evidence']['scope'])
        self.assertEqual(bundle['evidence']['report_sha256'],geometry.sha(self.report_path))

    def test_changed_model_or_geometry_helper_is_rejected(self):
        for name in ['model/robot.json','scripts/centrifuge_mechanisms.py']:
            with self.subTest(name=name):
                path=self.root/name;original=path.read_bytes();path.write_bytes(original+b'changed\n')
                with self.assertRaisesRegex(ValueError,'Geometry source changed'):
                    geometry.load_bundle(self.report_path)
                path.write_bytes(original)

    def test_changed_cached_mesh_or_native_artifact_is_rejected(self):
        for path in [self.out/'scene-mesh.json',self.cad/'CF01_Robot_Closed.FCStd']:
            with self.subTest(path=path.name):
                original=path.read_bytes();path.write_bytes(original+b'changed\n')
                with self.assertRaisesRegex(ValueError,'Frozen geometry artifact changed'):
                    geometry.load_bundle(self.report_path)
                path.write_bytes(original)

    def test_unpassed_or_incomplete_or_conflicting_source_evidence_is_rejected(self):
        original=copy.deepcopy(self.report)
        for mutation in ['failed','missing','conflicting']:
            self.report=copy.deepcopy(original)
            if mutation=='failed':self.report['passed']=False
            elif mutation=='missing':del self.report['source_files_sha256']['model/robot.json']
            else:self.report['solidcraft_snapshots']['source_files_sha256']['model/robot.json']='0'*64
            self.save()
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):geometry.load_bundle(self.report_path)

    def test_old_normalization_trajectory_must_belong_to_its_source(self):
        path=self.out/'trajectory.json'
        self.write(path,{'scene_sha256':'0'*64})
        # Updating an artifact hash cannot make a foreign normalization valid.
        self.report['artifact_sha256'][str(path.relative_to(self.root))]=geometry.sha(path);self.save()
        with self.assertRaisesRegex(ValueError,'normalization trajectory'):
            geometry.load_bundle(self.report_path)

    def test_artifact_paths_cannot_escape_the_project(self):
        self.report['out']=str(self.root.parent);self.save()
        with self.assertRaisesRegex(ValueError,'must stay in the project'):
            geometry.load_bundle(self.report_path)

    def test_linked_station_report_must_be_passed_and_bound_to_the_parent_native_input(self):
        original=copy.deepcopy(self.station_report)
        parent=copy.deepcopy(self.report);native_bytes=self.station_native.read_bytes()
        for mutation in ['failed','case_failed','wrong_case_native','wrong_case_hash','wrong_parent_hash','missing_helper_pin','changed_native']:
            self.report=copy.deepcopy(parent);self.save();self.station_native.write_bytes(native_bytes)
            self.station_report=copy.deepcopy(original)
            if mutation=='failed':self.station_report['passed']=False
            elif mutation=='case_failed':self.station_report['cases'][0]['passed']=False
            elif mutation=='wrong_case_native':self.station_report['cases'][0]['files']['freecad']='cad/other.FCStd'
            elif mutation=='wrong_case_hash':self.station_report['cases'][0]['artifact_sha256']['freecad']='0'*64
            elif mutation=='wrong_parent_hash':
                self.report['native_input_sha256'][str(self.station_native)]='0'*64;self.save()
            elif mutation=='missing_helper_pin':del self.station_report['source_files_sha256']['scripts/centrifuge_mechanisms.py']
            else:self.station_native.write_bytes(b'changed station native input\n')
            self.write(self.station_path,self.station_report)
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):geometry.load_bundle(self.report_path)


class PreviewPayloadTests(unittest.TestCase):
    def test_framing_samples_are_stored_once_and_full_pva_is_preserved(self):
        program={'duration_s':1.,'arm':{'points':[{'time_s':0.,'positions_rad':[.1234567890123456],
                   'velocities_rad_s':[.2345678901234567],'accelerations_rad_s2':[.3456789012345678]}]}}
        framing=[{'time_s':0.},{'time_s':1.}]
        def mesh(bundle,display):
            return {'bodies':[],'unload_program':display,'trajectory':{'samples':display['preview_samples']}}
        (ROOT/'tmp').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as folder,\
             patch.object(build,'preview_samples',return_value=framing),\
             patch.object(geometry,'mesh_for_program',side_effect=mesh):
            target=Path(folder)/'demo.html';build.render_html(program,{},target)
            packed=re.search(r'<script type="application/json" data-mesh>([^<]+)</script>',target.read_text())[1]
            payload=json.loads(gzip.decompress(base64.b64decode(packed)))
        self.assertEqual(payload['unload_program'],program)
        self.assertNotIn('preview_samples',payload['unload_program'])
        self.assertEqual(payload['trajectory']['samples'],framing)


class ProgramSourceTests(unittest.TestCase):
    def test_published_station_and_jaw_bounds_keep_explicit_track_units(self):
        bounds={field:{'max_abs':[i+1.]} for i,field in enumerate(build.compiler.FIELDS)}
        raw={'station_bounds':copy.deepcopy(bounds),'jaw_bounds':copy.deepcopy(bounds)}
        program={'station':{'joint_names':['Lid','Lift'],'units':['deg','mm']},
                 'jaw':{'joint_names':['jaw_gap'],'units':['mm']}}
        report=build.dynamics_report(program,raw)
        self.assertEqual(report['station_bounds']['units'],['deg','mm'])
        self.assertEqual(report['jaw_bounds']['joint_names'],['jaw_gap'])
        self.assertEqual(report['jaw_bounds']['a'],bounds[build.compiler.FIELDS[2]])
        self.assertNotIn('positions_rad',report['station_bounds'])
        self.assertIn('positions_rad',raw['station_bounds'])

    def setUp(self):
        build._DYNAMICS_CACHE.clear();self.addCleanup(build._DYNAMICS_CACHE.clear)
        validation=patch.object(build.dynamics,'validate_program',return_value={'passed':True})
        self.validation=validation.start();self.addCleanup(validation.stop)
        definition=build.compiler.load()
        scene=build.compiler.pickup.load()
        self.program={'format':build.compiler.FORMAT,'scene':scene,
                      'source_files_sha256':build.compiler._hashes(scene),
                      'source_sha256':geometry.sha(build.compiler.SOURCE),
                      'definition':definition,
                      'definition_sha256':hashlib.sha256(json.dumps(definition,sort_keys=True).encode()).hexdigest(),
                      'verification':{'qualified':False}}

    def test_current_complete_source_snapshot_is_accepted(self):build.verify_program(self.program)

    def test_changed_source_or_definition_or_qualification_is_rejected(self):
        for mutation in ['source','definition','qualified','format','embedded_scene','embedded_definition','definition_digest']:
            program=copy.deepcopy(self.program)
            if mutation=='source':program['source_files_sha256']['model/robot.json']='0'*64
            elif mutation=='definition':program['source_sha256']='0'*64
            elif mutation=='qualified':program['verification']['qualified']=True
            elif mutation=='format':program['format']='unknown/1'
            elif mutation=='embedded_scene':program['scene']['arm_fixture']['yaw_deg']+=1
            elif mutation=='embedded_definition':program['definition']['limits']['qualified']=True
            else:program['definition_sha256']='0'*64
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):build.verify_program(program)

    def test_incomplete_source_bindings_are_not_treated_as_source_current(self):
        self.program['source_files_sha256']={}
        with self.assertRaises(ValueError):build.verify_program(self.program)

    def test_identical_payload_reuses_validation_and_returns_detached_proof(self):
        self.validation.return_value={'passed':True,'bounds':{'velocity':[.1]}}
        first=build.verify_program(self.program);second=build.verify_program(copy.deepcopy(self.program))
        self.validation.assert_called_once()
        first['bounds']['velocity'][0]=99.
        self.assertEqual(second['bounds']['velocity'],[.1])
        self.assertEqual(build.verify_program(self.program)['bounds']['velocity'],[.1])
        self.assertEqual(self.validation.return_value['bounds']['velocity'],[.1])
        changed=copy.deepcopy(self.program);changed['changed_payload']=True
        build.verify_program(changed)
        self.assertEqual(self.validation.call_count,2)

    def test_validator_code_byte_change_invalidates_process_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            code=Path(directory)/'validator.py';code.write_text('version one\n',encoding='utf-8')
            with patch.object(build.dynamics,'__file__',str(code)):
                build.verify_program(self.program);build.verify_program(self.program)
                self.assertEqual(self.validation.call_count,1)
                code.write_text('version two\n',encoding='utf-8')
                build.verify_program(self.program)
                self.assertEqual(self.validation.call_count,2)


class FinishExistingTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name).resolve()
        self.out=self.root/'exports/revision';self.renders=self.root/'renders/revision'
        self.out.mkdir(parents=True);self.renders.mkdir(parents=True)
        self.program=self.out/'program.json';self.write(self.program,{'purpose':'fake program, separately source-checked'})
        self.posed=self.root/'cad/posed.FCStd';self.posed.parent.mkdir();self.posed.write_bytes(b'fake checked native bytes\n')
        self.code_names=['scripts/cf01_unload_geometry.py','scripts/check_cf01_unload_motion.py','scripts/lab_transfer_model.py']
        for name in self.code_names:
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes((ROOT/name).read_bytes())
        self.geometry={'cache':'original construction geometry'};self.instruments={'cache':'original instrument geometry'}
        self.native={'format':'solidcraftbot.cf01-unload-native-motion-validation/1','passed':True,
                     'program':{'sha256':geometry.sha(self.program)},'geometry':self.geometry,'instruments':self.instruments,
                     'posed_models':[{'path':'cad/posed.FCStd','sha256':geometry.sha(self.posed)}]}
        self.native_path=self.out/'native-motion-validation.json';self.write(self.native_path,self.native)
        self.previous={'format':'solidcraftbot.cf01-unload-build/1','passed':True,
                       'source_files_sha256':{name:geometry.sha(self.root/name) for name in self.code_names},
                       'native_report':{'sha256':geometry.sha(self.native_path)}}
        self.previous_path=self.out/'build-report.json';self.write(self.previous_path,self.previous)
        self.context={'revision':'fake-revision','out':str(self.out),'renders':str(self.renders),
                      'program':str(self.program),'program_sha256':geometry.sha(self.program),
                      'geometry_report':str(self.root/'cad/base-report.json'),'geometry':self.geometry}
        self.context_path=self.out/'context.json';self.write(self.context_path,self.context)
        for target,name,value in [(geometry,'ROOT',self.root),(build,'ROOT',self.root)]:
            replacement=patch.object(target,name,value);replacement.start();self.addCleanup(replacement.stop)

    def write(self,path,value):path.write_text(json.dumps(value)+'\n',encoding='utf-8')

    def finish(self,geometry_evidence=None,instrument_evidence=None,render_side_effect=None):
        with patch.object(build,'verify_program'),patch.object(build.tool_paths,'resolve_tool_arguments'),\
             patch.object(geometry,'load_bundle',return_value={'evidence':geometry_evidence if geometry_evidence is not None else self.geometry}),\
             patch.object(geometry,'load_instruments',return_value={'evidence':instrument_evidence if instrument_evidence is not None else self.instruments}),\
             patch.object(build,'render_html',side_effect=render_side_effect,return_value={'path':'renders/revision/demo.html'}),\
             patch.object(build,'publish_report') as publish,contextlib.redirect_stdout(io.StringIO()):
            build.main(['--finish-existing',str(self.context_path)])
        return publish

    def test_only_visualization_changes_when_all_native_inputs_still_match(self):
        native_before=self.native_path.read_bytes();posed_before=self.posed.read_bytes()
        publish=self.finish();publish.assert_called_once()
        self.assertEqual(self.native_path.read_bytes(),native_before)
        self.assertEqual(self.posed.read_bytes(),posed_before)
        self.assertEqual(publish.call_args.args[3],self.native)

    def test_changed_program_native_report_or_posed_artifact_is_rejected(self):
        for path in [self.program,self.native_path,self.posed]:
            original=path.read_bytes()
            with self.subTest(path=path.name):
                if path==self.posed:path.write_bytes(original+b'changed\n')
                else:
                    value=json.loads(original);value['changed']=True;self.write(path,value)
                with self.assertRaises(ValueError):self.finish()
            path.write_bytes(original)

    def test_native_report_for_another_program_is_rejected_even_with_matching_artifact_hash(self):
        self.native['program']['sha256']='0'*64;self.write(self.native_path,self.native)
        self.previous['native_report']['sha256']=geometry.sha(self.native_path);self.write(self.previous_path,self.previous)
        with self.assertRaisesRegex(ValueError,'another program'):self.finish()

    def test_changed_critical_audit_implementation_is_rejected(self):
        for name in self.code_names:
            path=self.root/name;original=path.read_bytes();path.write_bytes(original+b'changed\n')
            with self.subTest(name=name),self.assertRaises(ValueError):self.finish()
            path.write_bytes(original)

    def test_new_valid_geometry_or_instrument_evidence_cannot_relabel_old_native_qa(self):
        for kind in ['geometry','instruments']:
            kwargs={'geometry_evidence':{'cache':'different valid construction'}} if kind=='geometry' else {'instrument_evidence':{'cache':'different valid instruments'}}
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.finish(**kwargs)

    def test_context_cannot_relabel_the_geometry_checked_by_the_native_report(self):
        self.context['geometry']={'cache':'another geometry'};self.write(self.context_path,self.context)
        with self.assertRaisesRegex(ValueError,'geometry evidence changed'):self.finish()

    def test_critical_change_during_html_render_prevents_native_evidence_retention(self):
        def change_source(*args):
            path=self.root/self.code_names[0];path.write_bytes(path.read_bytes()+b'changed during rendering\n')
            return {'path':'renders/revision/demo.html'}
        with self.assertRaises(ValueError):self.finish(render_side_effect=change_source)

    def test_native_evidence_change_during_html_render_is_rejected(self):
        def change_native(*args):
            native=copy.deepcopy(self.native);native['changed_during_render']=True
            self.write(self.native_path,native)
            return {'path':'renders/revision/demo.html'}
        with self.assertRaisesRegex(ValueError,'Native evidence changed during rendering'):
            self.finish(render_side_effect=change_native)


if __name__=='__main__':unittest.main()
