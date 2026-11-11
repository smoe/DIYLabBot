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
import furniture_model as furniture
from tube_cam_model import matrix


class LaboratoryFurnitureTests(unittest.TestCase):
    def setUp(self):
        self.spec=room.load();self.p=room.parameters(self.spec)
        self.source=room.expanded(self.spec,self.p)

    def test_each_compartment_has_two_shelves_and_a_pair_or_final_single_door(self):
        bodies={b['id']:b for b in self.source['bodies']}
        for identity in ('LeftBench','RightBench','IslandLeft','IslandRight','WetStation'):
            self.assertEqual(bodies[identity+'_LowerStorage']['role'],'hollow_lower_storage')
            shelves=[b for b in bodies.values() if b['id'].startswith(identity+'_') and b['role']=='internal_shelf']
            joints=[j for j in self.source['joints'] if j['id'].startswith(identity+'_Door')]
            self.assertGreater(len(joints),1)
            self.assertTrue(all(j['limits_deg']==[0,90] and j['type']=='revolute' for j in joints))
            bays=[s for s in self.source['storage'] if s['id'].startswith(identity+'.') and s['id'].endswith('.Level0')]
            self.assertEqual([len(s['joints']) for s in bays],[2]*(len(joints)//2)+([1] if len(joints)%2 else []))
            self.assertEqual(len(shelves),2*len(bays))
            for a,b in zip(joints,joints[1:]):self.assertEqual(a['axis'][2],-b['axis'][2])
        closed=room.storage_interfaces(self.spec,self.p,room.pose(self.spec,self.p,'closed'))
        opened=room.storage_interfaces(self.spec,self.p,room.pose(self.spec,self.p,'open'))
        self.assertTrue(all(not f['accessible'] for f in closed.values() if f['access_kind']=='front_shelf'))
        for identity,ref in opened.items():
            self.assertEqual(ref['accessible'],ref['access_kind']=='open_shelf' or '.Bay1.' in identity)

    def test_inspection_opens_only_one_compartment_per_bench_and_keeps_mounted_handles(self):
        values=room.pose(self.spec,self.p,'inspection')
        shapes={o['id']:room.numeric_shape(o['shape'],self.p) for o in self.source['operations']}
        for item in self.spec['_furnishings']['instances']:
            if item['type'] not in ('storage_bench','wet_bench'):continue
            joints=[j for j in self.source['joints'] if j['id'].startswith(item['id']+'_Door')]
            self.assertEqual(sum(values[j['id']]>0 for j in joints),2)
            for j in joints:
                door=shapes[j['id']];handle_id=j['id'].replace('_Door','_Handle');bar=shapes[handle_id]
                if item['front']=='negative_x':gap=door['origin'][0]-(bar['origin'][0]+bar['size'][0])
                else:gap=bar['origin'][0]-(door['origin'][0]+door['size'][0])
                self.assertGreaterEqual(gap,15)
                self.assertTrue(all(handle_id+'_Mount'+str(i) in shapes for i in (1,2)))

    def test_shared_compartment_requires_both_doors_and_has_no_middle_partition(self):
        ref=next(s for s in self.source['storage'] if s['id']=='IslandLeft.Bay1.Level0')
        self.assertEqual(ref['joints'],['IslandLeft_Door1','IslandLeft_Door2'])
        for opened in ([],ref['joints'][:1],ref['joints'][1:],ref['joints']):
            values=room.pose(self.spec,self.p,'closed')
            values.update({j:90 for j in opened})
            result=room.storage_interfaces(self.spec,self.p,values)[ref['id']]
            self.assertEqual(result['accessible'],len(opened)==2)
            self.assertEqual(len(result['access_paths_mm']),2)
        shapes={o['id']:room.numeric_shape(o['shape'],self.p) for o in self.source['operations']}
        bench=next(i for i in self.spec['_furnishings']['instances'] if i['id']=='IslandLeft')
        origin=[room.evaluate(x,self.p) for x in bench['xyz']]
        first=shapes['IslandLeft_Shelf1'];partition=shapes['IslandLeft_Partition1']
        # The shelf crosses the middle seam of the first pair and ends at the
        # actual partition after the pair, without a central stile.
        leaf_width=self.p['island_length']/7
        self.assertLess(first['origin'][1],origin[1]+leaf_width)
        self.assertGreater(first['origin'][1]+first['size'][1],origin[1]+leaf_width)
        self.assertAlmostEqual(partition['origin'][1]+partition['size'][1]/2,origin[1]+2*leaf_width)

    def test_single_compartments_can_override_the_catalog_default(self):
        item={'id':'Independent','type':'storage_bench','component':'Furniture','bindings':{
            'width':600,'length':1500,'height':900,'top_t':40,'plinth_h':100,'panel_t':18,'door_gap':3,'leaf_width':550},
            'xyz':[0,0,0],'yaw_deg':0}
        for grouping,doors in [('paired',[2,1]),('single',[1,1,1])]:
            item['door_grouping']=grouping
            source=furniture.instantiate(self.spec['_catalog'],item,{})
            bays=[r for r in source['storage'] if r['id'].endswith('.Level0')]
            self.assertEqual([len(r['joints']) for r in bays],doors)
            self.assertEqual(sum(b['role']=='internal_shelf' for b in source['bodies']),2*len(doors))
        item['door_grouping']='unsupported'
        with self.assertRaises(ValueError):furniture.instantiate(self.spec['_catalog'],item,{})

    def test_mirrored_hinges_open_outward_on_both_access_sides(self):
        from tube_cam_model import pose_change_point
        for identity in ('LeftBench','RightBench','IslandLeft','IslandRight'):
            item=next(i for i in self.spec['_furnishings']['instances'] if i['id']==identity)
            joints=[j for j in self.source['joints'] if j['id'].startswith(identity+'_Door')]
            front_sign=-1 if item['front']=='negative_x' else 1
            self.assertEqual(joints[0]['axis'][2],-front_sign)
            for a,b in zip(joints[::2],joints[1::2]):
                self.assertEqual(a['axis'][2],-b['axis'][2])
                self.assertLess(room.evaluate(a['origin'][1],self.p),room.evaluate(b['origin'][1],self.p))
                closed=room.pose(self.spec,self.p,'closed');opened={**closed,a['id']:90,b['id']:90}
                for j in (a,b):
                    op=next(o for o in self.source['operations'] if o['id']==j['id'])
                    shape=room.numeric_shape(op['shape'],self.p)
                    centre=[shape['origin'][k]+shape['size'][k]/2 for k in range(3)]
                    after=pose_change_point(self.source,j['child'],centre,self.p,closed,opened)
                    self.assertGreater(front_sign*(after[0]-centre[0]),0)
        hood=equipment.materialize(equipment.load(),'fume_hood_1200');p=equipment.parameters(hood)
        source=equipment.expanded(hood,p)
        self.assertEqual([len(r['joints']) for r in source['base_storage'] if r['id'].endswith('.Level0')],[2,1])
        self.assertTrue(all(list(r['axis'])==[0,0,s] for r,s in zip(source['joints'][:3],[-1,1,-1])))

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
        p=equipment.parameters(hood);values=equipment.pose(hood,p,'base_access')
        self.assertEqual(sum(v>0 for name,v in values.items() if name.startswith('HoodBase_Door')),2)
        refs=equipment.interfaces(hood,p,values)
        self.assertTrue(refs['HoodBase.Bay1.Level0']['accessible'])
        self.assertFalse(refs['HoodBase.Bay2.Level0']['accessible'])
        with self.assertRaisesRegex(ValueError,'Mounted base handles'):
            equipment.pose(hood,p,'all_open')


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
            self.assertTrue({'furniture.combined_pose.'+name for name in ('closed','open','inspection','odd_doors_open','even_doors_open')}
                            <= {v['id'] for v in case['furniture_checks']})


if __name__=='__main__':unittest.main()
