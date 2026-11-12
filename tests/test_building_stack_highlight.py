"""Building-only highlight selection and immutable proof guards."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import render_building_stack_highlight as highlight


class BuildingHighlightTests(unittest.TestCase):
    def proof(self, root):
        (root/'model').mkdir(); (root/'native').mkdir()
        source=root/'model/source.json'; source.write_text('{}\n')
        native=root/'native/model.sc'; native.write_bytes(b'synthetic native artifact')
        report={'format':'solidcraftbot.building-stack-build/1','passed':True,'backends':'solidcraft','solidcraft_checks':{'passed':True},
                'source':'model/source.json','source_sha256':highlight.digest(source),'source_files_sha256':{'model/source.json':highlight.digest(source)},
                'files':{'solidcraft':'native/model.sc'},'artifact_sha256':{'solidcraft':highlight.digest(native)}}
        path=root/'build.json'; path.write_text(json.dumps(report))
        return path,report

    def test_checked_report_rejects_source_and_artifact_drift(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path,report=self.proof(root)
            _,native,bindings=highlight.checked_build(path,root)
            self.assertEqual(native,(root/'native/model.sc').resolve())
            native.write_bytes(b'changed')
            with self.assertRaises(ValueError):highlight.verify(bindings,root)
            with self.assertRaises(ValueError):highlight.checked_build(path,root)
            native.write_bytes(b'synthetic native artifact')
            (root/'model/source.json').write_text('{"changed":true}\n')
            with self.assertRaises(ValueError):highlight.verify(bindings,root)
            with self.assertRaises(ValueError):highlight.checked_build(path,root)

    def test_failed_or_incomplete_native_proof_and_foreign_paths_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path,report=self.proof(root)
            for mutate in [lambda r:r.update(passed=False),lambda r:r.update(solidcraft_checks=None),
                           lambda r:r['artifact_sha256'].clear(),lambda r:r['files'].update(solidcraft='../outside.sc')]:
                changed=copy.deepcopy(report);mutate(changed);path.write_text(json.dumps(changed))
                with self.assertRaises(ValueError):highlight.checked_build(path,root)
            for name in ['/outside.sc','../outside.sc']:
                with self.assertRaises(ValueError):highlight.local(root,name)

    def test_room_and_boundary_walls_are_resolved_from_level_source_metadata(self):
        level={'id':'OG3','label':'3. OG','template_source':'model/synthetic.json','template_id':'Synthetic',
               'floor_bodies':['UpperFloor'],'wall_bodies':['UpperWall']}
        area={'id':'R3_003','label':'3.003','kind':'room','boundary':[{'wall':'Boundary'},{'wall':'UnknownBoundary'}]}
        bodies=[{'id':'UpperFloor','level_id':'OG3','source_body_id':'Area_R3_003'},
                {'id':'UpperWall','level_id':'OG3','source_body_id':'Wall_Boundary'},
                {'id':'LowerFloor','level_id':'OG2','source_body_id':'Area_R3_003'}]
        with patch.object(highlight.model,'interfaces',return_value={'levels':[level],'roof':{'body_ids':['Roof']}}), \
             patch.object(highlight.model,'level_plan',return_value={'areas':[area]}), \
             patch.object(highlight.model,'expanded',return_value={'bodies':bodies}):
            selected=highlight.selection({},{});self.assertEqual(selected['floor_body_id'],'UpperFloor')
            self.assertEqual(selected['wall_body_ids'],['UpperWall'])
            self.assertNotIn('LowerFloor',selected['wall_body_ids'])
            area['kind']='corridor'
            with self.assertRaises(ValueError):highlight.selection({},{})

    def test_view_changes_only_appearance_and_roof_visibility(self):
        selected={'roof_body_ids':['Roof'],'top_level_wall_ids':['Wall','NeighborWall'],
                  'floor_body_id':'TargetFloor','wall_body_ids':['Wall']}
        commands=highlight.view_commands(selected)
        self.assertEqual({command['command']for command in commands},{'browser.visibility','appearance.assign'})
        self.assertEqual(commands[0]['params'],{'items':['Roof'],'visible':False})
        orange=[command['params']for command in commands if command['params'].get('color')==highlight.COLOR]
        self.assertEqual([item['bodies']for item in orange],[['TargetFloor'],['Wall']])
        self.assertTrue(any(item.get('opacity')==1. for item in orange))

    def test_camera_retains_full_vertical_building_context(self):
        geometry=[{'bbox':{'min':[0,0,-250],'max':[10000,20000,16750]}}]
        cam=highlight.camera(geometry)
        self.assertEqual(cam['target'],[5000.,10000.,8250.])
        self.assertGreater(cam['distance'],20000.)
        with self.assertRaises(ValueError):highlight.camera([])
        with self.assertRaises(ValueError):highlight.camera(geometry,pitch=float('nan'))

    def test_render_cli_never_discovers_freecad_or_starts_a_builder(self):
        with patch.object(highlight.tool_paths,'default_solidcraft_cli',return_value='native-sc') as own, \
             patch.object(highlight.tool_paths,'default_freecad_python',side_effect=AssertionError('Other CAD queried')), \
             patch.object(highlight,'render',return_value={}):
            highlight.main([]);own.assert_called_once_with()


if __name__=='__main__':
    unittest.main()
