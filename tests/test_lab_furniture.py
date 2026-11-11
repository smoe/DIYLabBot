"""Storage access, source reuse, fixture placement and native motion evidence."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import lab_room_model as room
import lab_layout_model as layout
import lab_equipment as equipment
from tube_cam_model import matrix


class LaboratoryFurnitureTests(unittest.TestCase):
    def setUp(self):
        self.spec=room.load();self.p=room.parameters(self.spec)
        self.source=room.expanded(self.spec,self.p)

    def test_each_lower_cupboard_has_two_shelves_and_separately_driven_fronts(self):
        bodies={b['id']:b for b in self.source['bodies']}
        for identity in ('LeftBench','RightBench','IslandLeft','IslandRight','WetStation'):
            self.assertEqual(bodies[identity+'_LowerStorage']['role'],'hollow_lower_storage')
            shelves=[b for b in bodies.values() if b['id'].startswith(identity+'_') and b['role']=='internal_shelf']
            self.assertEqual(len(shelves),2)
            joints=[j for j in self.source['joints'] if j['id'].startswith(identity+'_Door')]
            self.assertGreater(len(joints),1)
            self.assertTrue(all(j['limits_deg']==[0,90] and j['type']=='revolute' for j in joints))
        closed=room.storage_interfaces(self.spec,self.p,room.pose(self.spec,self.p,'closed'))
        opened=room.storage_interfaces(self.spec,self.p,room.pose(self.spec,self.p,'open'))
        self.assertTrue(all(not f['accessible'] for f in closed.values() if f['access_kind']=='front_shelf'))
        self.assertTrue(all(f['accessible'] for f in opened.values()))

    def test_upper_storage_has_no_fronts_and_remains_accessible_in_both_poses(self):
        for prefix in ('LeftUpperStorage','RightUpperStorage','IslandCupboard1','IslandCupboard2'):
            self.assertFalse(any(j['id'].startswith(prefix) for j in self.source['joints']))
            refs=[v for k,v in room.storage_interfaces(self.spec,self.p).items() if k.startswith(prefix+'.')]
            self.assertTrue(refs)
            self.assertTrue(all(v['accessible'] and v['access_kind']=='open_shelf' for v in refs))

    def test_three_parked_stools_reuse_one_recipe_and_seat_frames_follow_the_lift(self):
        stools=[i for i in self.spec['_furnishings']['instances'] if i['type']=='lab_stool']
        self.assertEqual(len(stools),3)
        for item in stools:
            frame=next(f for f in self.source['frames'] if f['id']=='L01.'+item['id']+'.Seat')
            point=[room.evaluate(x,self.p) for x in frame['origin']]
            for name,z in [('closed',450),('open',650)]:
                world=room.robot_spec.transform(matrix(self.source,frame['component'],self.p,room.pose(self.spec,self.p,name)),point)
                self.assertAlmostEqual(world[2],z)
            base=[b for b in self.source['bodies'] if b['id'].startswith(item['id']+'_')]
            self.assertEqual(sum(b['role']=='stool_caster' for b in base),5)

    def test_room_width_variant_moves_door_hinges_with_their_carcasses(self):
        wide=room.parameters(self.spec,{'room_width':7100})
        after=room.expanded(self.spec,wide)
        a={j['id']:j for j in self.source['joints']};b={j['id']:j for j in after['joints']}
        for identity in ('IslandLeft_Door1','IslandRight_Door1'):
            old=[room.evaluate(x,self.p) for x in a[identity]['origin']]
            new=[room.evaluate(x,wide) for x in b[identity]['origin']]
            self.assertEqual([new[i]-old[i] for i in range(3)],[250,0,0])

    def test_wet_place_hood_and_transport_route_have_distinct_spaces(self):
        spec=layout.load(validate_builds=False);p=layout.parameters(spec)
        hood=next(i for i in spec['instances'] if i['id']=='Hood01')
        h=layout.xyz(hood['xyz'],p)
        self.assertEqual(hood['yaw_deg'],90)
        self.assertEqual(h[1]-p['Hood01_width']/2,p['wet_start_y']+p['wet_length']+p['cold_wall_gap'])
        self.assertLess(h[1]+p['Hood01_width']/2,p['perimeter_start_y']+p['left_front_equipment_bay'])
        wet=[b['role'] for b in self.source['bodies'] if b['id'].startswith('WetStation_')]
        for role in ('wash_basin','water_tap','paper_towel_dispenser','glass_drip_area','glass_drying_rack'):self.assertIn(role,wet)
        route=[layout.xyz(v,p) for v in spec['vehicle_route']['waypoints']]
        self.assertGreater(len(route),2)
        self.assertGreater(route[2][0],h[0]+42+206)

    def test_water_bath_and_hood_access_change_with_their_real_closures(self):
        catalog=equipment.load()
        for identity,frame in [('water_bath_13l','bath_tank'),('fume_hood_1200','work_chamber')]:
            spec=equipment.materialize(catalog,identity);p=equipment.parameters(spec)
            self.assertFalse(equipment.interfaces(spec,p,equipment.pose(spec,p,'closed'))[frame]['accessible'])
            self.assertTrue(equipment.interfaces(spec,p,equipment.pose(spec,p,'access'))[frame]['accessible'])
        hood=equipment.materialize(catalog,'fume_hood_1200')
        self.assertEqual(hood['furniture']['source'],'model/furniture/laboratory.catalog.json')
        self.assertFalse(equipment.interfaces(hood,equipment.parameters(hood))['work_chamber']['extraction_connected'])


class NativeFurnitureEvidenceTests(unittest.TestCase):
    def test_current_room_has_checked_cavities_shelf_access_and_open_close_motion(self):
        path=room.ROOT/'cad/lab-room-l01/shared-build-report.json'
        if not path.exists():self.skipTest('Build the current room for native evidence')
        report=json.loads(path.read_text())
        if report['source_sha256']!=room.digest(room.SOURCE):self.skipTest('Current room has not been built')
        self.assertTrue(report['passed'])
        for name,digest in report['source_files_sha256'].items():self.assertEqual(room.digest(room.ROOT/name),digest,name)
        for case in report['cases']:
            self.assertTrue(case['furniture_checks'])
            self.assertTrue(all(v['passed'] for v in case['furniture_checks']))
            self.assertTrue(any(v['id']=='LeftBench_Door1.1' for v in case['furniture_checks']))
            self.assertTrue(any(v['id']=='Stool1_SeatLift.1' for v in case['furniture_checks']))


if __name__=='__main__':unittest.main()
