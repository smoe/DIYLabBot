"""Direct-pickup composition and continuous-envelope regression checks."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import h02_direct_pickup as model
import tube_frame_model as holder
import centrifuge_robot_pickup as pickup
import build_h02_direct_pickup as build


class DirectPickupTests(unittest.TestCase):
    def setUp(self):
        self.scene=model.load();self.spec=model.context(self.scene,'V15');self.p=model.parameters(self.spec)

    def load_changed(self,scene):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'scene.json';path.write_text(json.dumps(scene));return model.load(path)

    def test_stale_holder_or_gripper_reference_rejected(self):
        for name in ['holder','gripper']:
            s=copy.deepcopy(self.scene);s['sources'][name]['source_sha256']='0'*64
            with self.assertRaises(ValueError):self.load_changed(s)

    def test_each_backend_resolves_only_its_own_cad(self):
        for backend,own,other in [('freecad','default_freecad_python','default_solidcraft_cli'),
                                  ('solidcraft','default_solidcraft_cli','default_freecad_python')]:
            with patch.object(build.tool_paths,own,return_value='tool') as found, \
                 patch.object(build.tool_paths,other,side_effect=AssertionError('Other CAD queried')), \
                 patch.object(build,'build',return_value={}):
                build.main(['--backend',backend]);found.assert_called_once_with()

    def test_neighbor_array_cannot_omit_a_direction_or_overlap_docks(self):
        for action in ['omit','duplicate','pitch']:
            s=copy.deepcopy(self.scene)
            if action=='omit':s['neighbor_offsets'].pop()
            elif action=='duplicate':s['neighbor_offsets'][0]=s['neighbor_offsets'][1]
            else:s['pitch_mm'][0]=43
            with self.assertRaises(ValueError):self.load_changed(s)

    def test_both_variants_reuse_passive_parts_without_lifter_or_receiver(self):
        before={r['source']:model.digest(ROOT/r['source']) for r in self.scene['sources'].values()}
        for variant in self.scene['variants']:
            spec=model.context(self.scene,variant);source=model.expanded(spec,model.parameters(spec))
            self.assertEqual(len(source['bodies']),9*5+6)
            self.assertEqual({b['id'].removeprefix('Selected_') for b in source['bodies'] if b['id'].startswith('Selected_')},set(model.PARTS))
            self.assertFalse(any('Receiver' in b['id'] or 'Lifter' in b['id'] for b in source['bodies']))
            self.assertEqual({tuple(c['instance_translation_mm'][:2]) for c in source['components'] if 'instance_translation_mm' in c},
                {(x*48,y*44) for x,y in self.scene['neighbor_offsets']})
        self.assertEqual(before,{n:model.digest(ROOT/n) for n in before})

    def test_existing_gripper_sizes_and_overhead_orientation_are_preserved(self):
        original=pickup.gripper_parts(self.spec['grip'],{})
        for old,new in zip(original,model.tool_shapes(self.spec)):
            a,b=old['shape'],new['shape']
            self.assertEqual(a['kind'],b['kind'])
            if a['kind']=='box':
                self.assertEqual(a['size'],b['size'])
                self.assertEqual(b['origin'][2]+b['size'][2],33-a['origin'][2])
            else:self.assertEqual(a['radius'],b['radius'])
        pad=next(v['shape'] for v in model.tool_shapes(self.spec) if v['id']=='LeftFingerPad')
        self.assertAlmostEqual(pad['origin'][2]-(self.spec['hp']['frame_guide_z']+2),1)
        self.assertAlmostEqual(self.spec['hp']['collar_z']-(pad['origin'][2]+pad['size'][2]),2)

    def test_box_sweep_contains_all_intermediate_translations(self):
        box={'kind':'box','origin':[2,3,4],'size':[5,6,7]}
        for axis in range(3):
            for distance in [-20,20]:
                d=[0,0,0];d[axis]=distance;envelope=model.sweep(box,d)
                for t in [0,.001,.27,.5,.93,1]:
                    for k in range(3):
                        a=box['origin'][k]+t*d[k];b=a+box['size'][k]
                        self.assertLessEqual(envelope['origin'][k],a+1e-12)
                        self.assertGreaterEqual(envelope['origin'][k]+envelope['size'][k],b-1e-12)
        with self.assertRaises(ValueError):model.sweep(box,[1,1,0])
        with self.assertRaises(ValueError):model.sweep(box,[0,0,0])

    def test_native_negative_control_is_between_tube_endpoints(self):
        source,pairs,_=model.proof(self.spec,self.p)
        blocker=next(o['shape'] for o in source['operations'] if o['body']=='NegativeMidpathBlocker')
        self.assertGreater(blocker['origin'][2],self.spec['hp']['collar_z']+2)
        self.assertLess(blocker['origin'][2]+blocker['size'][2],self.spec['hp']['tube_bottom_z']+self.scene['travel_mm'])
        self.assertTrue(any(v['a']=='extraction_TubeEnvelope' and v['b'].startswith('Neighbor') for v in pairs))
        self.assertTrue(any(v['kind']=='finger_self' for v in pairs))
        self.assertEqual(sum(v['intended_pad_contact'] for v in pairs),2)

    def test_loaded_extraction_moves_tube_and_tool_together(self):
        a=model.pose(self.spec,self.p,'grasp');b=model.pose(self.spec,self.p,'extracted')
        self.assertEqual(b['ToolZ']-a['ToolZ'],b['TubeZ']-a['TubeZ'])
        self.assertEqual((a['JawLeft'],a['JawRight'],b['JawLeft'],b['JawRight']),(0,0,0,0))

    def test_pva_bounds_do_not_depend_on_limit_dictionary_order(self):
        original=model.motion_profile(self.spec,self.p)
        s=copy.deepcopy(self.spec);s['scene']['motion_limits']=dict(reversed(list(s['scene']['motion_limits'].items())))
        changed=model.motion_profile(s,self.p)
        self.assertEqual(original,changed)
        extraction=original['phases'][-1]
        self.assertAlmostEqual(extraction['maximum_derivatives']['velocity_mm_s'],18.75)
        self.assertEqual(extraction['interior_stops'],0)
        s['scene']['motion_limits']['velocity_mm_s']=1
        with self.assertRaises(ValueError):model.motion_profile(s,self.p)


if __name__=='__main__':unittest.main()
