"""Assembly identity, coupled parameter variants and checked artifact resolution."""
from pathlib import Path
import copy
import json
import math
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import assembly_model as assembly
import robot_spec as robot
import lab_layout_model as layout
import lab_transfer_model as transfer
import centrifuge_robot_pickup as pickup
import robot_components as components
import tip_collector_model as collector


class ParameterizedAssemblies(unittest.TestCase):
    def test_arm_instance_changes_geometry_dimensions_and_joint_anchors_without_changing_source(self):
        scene=layout.load(validate_builds=False); item=copy.deepcopy(scene['instances'][0])
        base=layout.instance_source(scene,item)
        item['overrides']={'upper_len':220}
        variant=layout.instance_source(scene,item)
        self.assertEqual(robot.parameters(variant)['upper_len'],220)
        self.assertEqual(robot.frame(variant['joints'][2],robot.parameters(variant))[2][3]-robot.frame(base['joints'][2],robot.parameters(base))[2][3],20)
        flange=base['flange_reference'];q=robot.home(base)
        def point(spec):return robot.transform(robot.forward(spec,q)[flange['link']],[robot.evaluate(v,robot.parameters(spec)) for v in flange['point']])
        self.assertAlmostEqual(math.dist(point(base),point(variant)),20)
        self.assertEqual(robot.parameters(robot.load())['upper_len'],200)
        with self.assertRaisesRegex(ValueError,'Non-positive'):
            layout.instance_source(scene,{**item,'overrides':{'upper_len':-20}})

    def test_vehicle_instance_override_changes_actual_handoff_height(self):
        scene=layout.load(validate_builds=False);protocol=transfer.load()
        before=transfer.data(protocol,scene)
        changed=copy.deepcopy(scene);changed['parameters']['vehicle_deck_z']+=10
        after=transfer.data(protocol,changed)
        self.assertEqual(after['targets']['vehicle_grip'][0][2]-before['targets']['vehicle_grip'][0][2],10)
        vehicle=next(i for i in changed['instances'] if i['id']=='TR01')
        vehicle['overrides']['floor_deck_z']=920
        self.assertEqual(layout.provider('transporter').parameters(layout.instance_source(changed,vehicle))['floor_deck_z'],920)
        rack=next(i for i in changed['instances'] if i['asset']=='tube_rack')
        self.assertEqual(layout.provider('tube_rack').parameters(layout.instance_source(changed,rack))['floor_deck_z'],920)

    def test_rack_override_is_applied_and_an_empty_rack_variant_is_rejected(self):
        scene=layout.load(validate_builds=False)
        rack=copy.deepcopy(next(i for i in scene['instances'] if i['asset']=='tube_rack'))
        rack['overrides']={'floor_deck_z':940}
        source=layout.instance_source(scene,rack)
        self.assertEqual(layout.provider('tube_rack').parameters(source)['floor_deck_z'],940)
        self.assertEqual(layout.cassette_datum(source,rack)[2],942)
        with self.assertRaisesRegex(ValueError,'tube cassette'):
            layout.instance_variant(layout.instance_source(scene,rack),{**rack,'variant':'Floor_P2'})

    def test_unknown_derived_nonfinite_or_unitless_override_is_rejected(self):
        source=robot.load()
        for overrides in [{'unknown':1},{'elbow_z':400},{'upper_len':float('nan')},{'upper_len':True},{'upper_len':'missing_name'}]:
            with self.subTest(overrides=overrides),self.assertRaises(ValueError):assembly.parameter_variant(source,overrides)
        del source['parameters']['upper_len']['unit']
        with self.assertRaisesRegex(ValueError,'unit'):assembly.parameter_variant(source,{'upper_len':220})
        tr=layout.provider('transporter').load()
        with self.assertRaisesRegex(ValueError,'range'):assembly.parameter_variant(tr,{'floor_deck_z':100000})

    def test_scene_forward_kinematics_uses_same_frames_and_variant_as_shared_arm(self):
        scene=pickup.load();source=pickup.arm_source(scene);kin=pickup.Kinematics(source,scene)
        for q in [robot.home(source),scene['ik_seed_deg'],[0]*6]:
            for name,expected in robot.forward(source,q).items():
                expected=robot.multiply(kin.base,expected);actual=kin.forward(q)[name]
                for i in range(4):
                    for j in range(4):self.assertAlmostEqual(actual[i][j],expected[i][j],places=10)

    def test_lane_metadata_tracks_actual_parameterized_geometry(self):
        source=collector.load();a=collector.parameters(source);b=collector.parameters(source,{'groove_S':5})
        self.assertTrue(all(not {'width_mm','x_mm'}&set(g) for g in source['grooves']))
        self.assertEqual(collector.grooves(source,b)[0]['width_mm'],5)
        refs=lambda p:{r['body']:r for r in collector.references(source,p)}
        self.assertLess(refs(b)['Fork_S']['volume_mm3'],refs(a)['Fork_S']['volume_mm3'])
        commands=collector.solidcraft_commands(source,b)
        parameter=next(c['params'] for c in commands if c['command']=='parameters.add' and c['params']['name']=='groove_S')
        self.assertEqual(float(parameter['expression']),5)

    def test_selection_references_mechanical_sources_without_copied_registration(self):
        selection=json.loads((robot.ROOT/'model/actuator-selection.json').read_text())
        library=components.library(robot.load())
        for part in selection['parts']:
            self.assertNotIn('verified_mounting_interface',part)
            ref=part['mounting_interface_ref'];canonical=library['parts'][ref['part']]
            self.assertEqual(ref['source'],canonical['interface_spec']['path'])
        self.assertNotIn('preferred_joint_bindings',selection)
        self.assertEqual(selection['joint_bindings_source'],'model/robot.json')

    def test_retired_generators_cannot_overwrite_current_outputs(self):
        import prepare_tip_collector,prepare_tube_station_draft,validate_tip_collector
        for module in [prepare_tip_collector,prepare_tube_station_draft,validate_tip_collector]:
            with self.subTest(module=module.__name__),self.assertRaisesRegex(SystemExit,'retired'):module.main()


class ArtifactReferences(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve()
        (self.root/'model').mkdir();(self.root/'build').mkdir()
        (self.root/'model/source.json').write_text('{}')
        self.ref={'source':'model/source.json','report':'build/report.json','case':'default'}

    def report(self,name='revision-1.FCStd'):
        artifact=self.root/'build'/name;artifact.write_bytes(b'checked artifact')
        report={'passed':True,'source_sha256':robot.digest(self.root/'model/source.json'),'cases':[{'id':'default','passed':True,'files':{'freecad':'build/'+name},'artifact_sha256':{'freecad':robot.digest(artifact)}}]}
        (self.root/'build/report.json').write_text(json.dumps(report));return artifact

    def test_named_case_survives_new_revision_path_and_checks_artifact_bytes(self):
        self.report();self.assertEqual(assembly.resolve_artifact(self.ref,self.root).name,'revision-1.FCStd')
        artifact=self.report('revision-2.FCStd');self.assertEqual(assembly.resolve_artifact(self.ref,self.root),artifact)
        artifact.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'artifact changed'):assembly.resolve_artifact(self.ref,self.root)

    def test_stale_failed_or_missing_case_is_rejected(self):
        for change in ['stale','failed','case']:
            with self.subTest(change=change):
                self.report();p=self.root/'build/report.json';d=json.loads(p.read_text())
                if change=='stale':d['source_sha256']='0'*64
                elif change=='failed':d['passed']=False
                else:d['cases'][0]['id']='other'
                p.write_text(json.dumps(d))
                with self.assertRaises(ValueError):assembly.resolve_artifact(self.ref,self.root)

    def test_paths_cannot_escape_project_and_native_paths_are_not_source_fields(self):
        for value in ['../outside.json','/private/tmp/outside.json']:
            with self.assertRaises(ValueError):assembly.validate_reference({'source':value},self.root)
        with self.assertRaisesRegex(ValueError,'fields'):assembly.validate_reference({**self.ref,'native':'build/old.FCStd'},self.root)
        ref={**self.ref,'source_sha256':'0'*64}
        with self.assertRaisesRegex(ValueError,'source changed'):assembly.validate_reference(ref,self.root)

    def test_invalid_instance_shapes_and_unknown_fields_fail(self):
        base={'id':'ArmA','asset':'arm','xyz':[0,0,0],'yaw_deg':0}
        for fields in [{'xyz':[1,2]},{'xyz':[True,0,0]},{'joints_deg':[0,0]},{'unexpected':1},{'yaw_deg':float('inf')}]:
            with self.subTest(fields=fields),self.assertRaises(ValueError):assembly.validate_instance({**base,**fields})


if __name__=='__main__':unittest.main()
