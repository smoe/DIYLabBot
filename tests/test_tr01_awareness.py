"""Source contract, empty derivation and placement of the additive camera kit."""
from pathlib import Path
import copy
import hashlib
import json
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import tr01_camera_model as kit
import sample_transport_model as transport


class AwarenessKitTests(unittest.TestCase):
    def setUp(self):
        self.spec=kit.load()

    def test_pinned_source_and_independent_lowering(self):
        ref=self.spec['transport'];self.assertEqual(ref['source_sha256'],kit.digest(ROOT/ref['source']))
        source=kit.expanded(self.spec);self.assertEqual(len(source['omitted_load_bodies']),48)
        self.assertEqual(len(source['bodies']),35)
        self.assertIn('TransportCover',{b['id']for b in source['bodies']})
        self.assertFalse(any(b['role']=='closed_tube_reference_envelope' for b in source['bodies']))
        self.assertEqual({o['body']for o in source['operations']},{b['id']for b in source['bodies']})
        base=transport.load();p=transport.parameters(base);v=next(v for v in base['variants']if v['id']=='Floor_T48');before=transport.expanded(base,p,v)
        retained={b['id']for b in before['bodies']if b['role']!='closed_tube_reference_envelope'}
        self.assertEqual([o for o in source['operations']if o['body']in retained],[o for o in before['operations']if o['body']in retained])

    def test_frame_follows_transporter_dimensions(self):
        original=transport.load();changed=copy.deepcopy(original);changed['parameters']['floor_length']['expression']=550
        with patch.object(transport,'load',return_value=changed):
            frame=kit.expanded(self.spec)['camera_frame']
        self.assertEqual(frame['origin_mm'][0],275)
        self.assertEqual(frame['axis'],[1,0,0]);self.assertEqual(frame['x'],[0,-1,0])

    def test_camera_clear_of_sensor_and_cassette_region(self):
        out=kit.expanded(self.spec);p=out['parameters'];ops={o['id']:o['shape']for o in out['operations']}
        body=ops['TR01_Awareness_Body'];mount=ops['TR01_Awareness_Mount0']
        self.assertGreaterEqual(body['origin'][2]-p['navigation_top'],p['camera_clearance'])
        self.assertGreater(mount['origin'][0],p['navigation_front'])
        self.assertEqual(mount['origin'][2],p['chassis_top'])
        self.assertEqual(mount['origin'][2]+mount['size'][2],body['origin'][2])
        self.assertLess(body['origin'][2]+body['size'][2],p['floor_deck_z']-12)
        self.assertLessEqual(out['camera_frame']['origin_mm'][0],p['floor_length']/2+6)

    def test_unknown_fields_and_unsupported_states_rejected(self):
        cases=[lambda s:s.update(extra=True),lambda s:s.update(load_state='loaded'),lambda s:s.update(cover_state='open'),lambda s:s['parameters'].update(other={'unit':'mm','expression':1,'range':[0,2],'basis':'x'}),lambda s:s['camera']['frame'].update(origin=[0,0,0]),lambda s:s['camera']['connection'].update(interface='USB'),lambda s:s['qualification'].update(camera_hardware_selected=0)]
        for change in cases:
            with self.subTest(change=change):
                s=copy.deepcopy(self.spec);change(s)
                with self.assertRaises(ValueError):kit.validate(s)

    def test_parameter_ranges_nonfinite_and_bools_rejected(self):
        for value in [0,-1,True,float('nan'),float('inf'),10000]:
            with self.subTest(value=value):
                s=copy.deepcopy(self.spec);s['parameters']['camera_clearance']['expression']=value
                with self.assertRaises(ValueError):kit.validate(s)
        with self.assertRaises(ValueError):kit.parameters(self.spec,{'floor_length':550})

    def test_changed_source_pin_rejected(self):
        self.spec['transport']['source_sha256']='0'*64
        with self.assertRaises(ValueError):kit.validate(self.spec)

    def test_native_command_coverage_and_view_cone(self):
        source=kit.expanded(self.spec);commands=kit.solidcraft_commands(source)
        self.assertEqual(len([c for c in commands if c['command'].startswith('solid.')]),len(source['operations']))
        self.assertEqual(len([c for c in commands if c['command']=='solid.cone']),1)
        camera_roles={b['id']:b['role']for b in source['bodies']if b['id'].startswith('TR01_Awareness')}
        self.assertEqual(set(camera_roles.values()),{'camera_envelope','camera_mount','viewing_cone'})


if __name__=='__main__':unittest.main()
