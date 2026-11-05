"""L01 qualitative layout, parameter coupling and unknown-measurement contracts."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import lab_room_model as model


class LabRoomTests(unittest.TestCase):
    def setUp(self): self.spec=model.load(); self.p=model.parameters(self.spec)

    def test_facade_endpoints_and_right_wall_relationship(self):
        self.assertEqual(model.rear_y(self.p,0),self.p['left_depth'])
        self.assertEqual(model.rear_y(self.p,1),self.p['right_depth'])
        self.assertLess(self.p['right_depth'],self.p['left_depth'])
        self.assertEqual(model.rear_y(self.p,0.5),(self.p['left_depth']+self.p['right_depth'])/2+self.p['facade_bulge'])

    def test_two_doors_six_bench_sections_and_shallow_closed_storage(self):
        source=model.expanded(self.spec,self.p); roles=[b['role'] for b in source['bodies']]
        self.assertEqual(roles.count('work_surface'),6)
        self.assertEqual(roles.count('closed_lower_storage'),4)
        self.assertEqual(roles.count('shallow_upper_storage'),2)
        self.assertEqual(roles.count('vertical_concrete_support'),1)
        self.assertEqual(roles.count('heating_cover_envelope'),3)
        self.assertEqual(roles.count('shared_central_shelf'),1)
        self.assertEqual(roles.count('central_shelf_upright_envelope'),3)
        self.assertEqual(roles.count('central_upper_cupboard'),2)
        self.assertEqual(roles.count('central_cupboard_upright_envelope'),3)
        self.assertEqual(roles.count('window_bench_leg_envelope'),4)
        self.assertEqual(len([f for f in source['frames'] if f['id'].startswith('L01.Door')]),2)
        self.assertTrue(all(v>0 for k,v in model.circulation(self.p).items() if k!='qualified_for_humans_or_robots'))
        self.assertFalse(model.circulation(self.p)['qualified_for_humans_or_robots'])

    def test_room_width_moves_island_and_door_frames_without_moving_origin(self):
        p=model.parameters(self.spec,{'room_width':7100}); a=model.expanded(self.spec,self.p); b=model.expanded(self.spec,p)
        def frame(source,params,name): return [model.evaluate(v,params) for v in next(f for f in source['frames'] if f['id']==name)['origin']]
        self.assertEqual(frame(b,p,'L01.IslandLeft.Worktop')[0]-frame(a,self.p,'L01.IslandLeft.Worktop')[0],250)
        self.assertEqual(frame(a,self.p,'L01.DoorA'),frame(b,p,'L01.DoorA'))
        self.assertIsNone(self.spec['reference']['building_frame_pose'])
        self.assertTrue(all(d['measured_mm'] is None for d in self.spec['parameters'].values()))

    def test_reported_support_and_straight_bench_front_alignment(self):
        self.assertEqual(self.spec['parameters']['support_width']['reported_approx_mm'],300)
        self.assertEqual(self.spec['parameters']['support_depth']['reported_approx_mm'],500)
        for overrides in [{},{'support_offset_x':250,'support_width':400,'support_depth':550}]:
            p=model.parameters(self.spec,overrides); source=model.expanded(self.spec,p)
            ops={o['id']:model.numeric_shape(o['shape'],p) for o in source['operations']}
            front=ops['ConcreteSupport']['origin'][1]
            self.assertEqual(ops['WindowBenchLeft_Worktop']['points'][1][1],front)
            self.assertEqual(ops['WindowBenchRight_Worktop']['points'][0][1],front)
            self.assertEqual(len(ops['WindowBenchLeft_Worktop']['points']),4)
            self.assertEqual(len(ops['WindowBenchRight_Worktop']['points']),4)

    def test_support_changes_leave_facade_and_windows_unchanged(self):
        a=model.expanded(self.spec,self.p)
        p=model.parameters(self.spec,{'support_offset_x':250,'support_width':400,'support_depth':550})
        b=model.expanded(self.spec,p)
        def facade(source,values):
            return [(op['id'],model.numeric_shape(op['shape'],values)) for op in source['operations']
                if op['body']=='FacadeWall' or op['body'].endswith('Glazing')]
        self.assertEqual(facade(a,self.p),facade(b,p))

    def test_invalid_layouts_do_not_generate_apparently_open_aisles(self):
        for changes in [{'room_width':5000},{'right_depth':7200},{'upper_depth':800},{'island_length':9000},{'door_a_x':5000},{'unknown':1}]:
            with self.assertRaises(ValueError): model.parameters(self.spec,changes)

    def test_central_shelf_tracks_both_benches_and_keeps_end_setbacks(self):
        for overrides in [{},{'room_width':7100,'island_length':3600,'island_shelf_top_z':1550,'island_shelf_depth':400,'island_shelf_end_inset':200}]:
            p=model.parameters(self.spec,overrides); source=model.expanded(self.spec,p)
            ops={o['id']:model.numeric_shape(o['shape'],p) for o in source['operations']}
            board=ops['IslandShelf_Board']; left=ops['IslandLeft_Worktop']; right=ops['IslandRight_Worktop']
            self.assertEqual(board['origin'][0]+board['size'][0]/2,right['origin'][0])
            self.assertEqual(left['origin'][0]+left['size'][0],right['origin'][0])
            self.assertEqual(board['origin'][1]-left['origin'][1],p['island_shelf_end_inset'])
            self.assertEqual(board['size'][1],p['island_length']-2*p['island_shelf_end_inset'])
            for i in range(1,4):
                post=ops['IslandShelf_Post'+str(i)]
                self.assertEqual(post['origin'][2],p['bench_height'])
                self.assertEqual(post['origin'][2]+post['size'][2],board['origin'][2])
        self.assertIsNone(self.spec['island_shelf']['load_rating_kg'])

    def test_shelf_cannot_intersect_worktops_or_cover_entire_island(self):
        for overrides in [{'island_shelf_top_z':1000,'bench_height':1000},{'island_shelf_depth':800,'island_half_width':450,'island_shelf_post':100,'island_shelf_end_inset':1000,'island_length':1500}]:
            with self.assertRaises(ValueError): model.parameters(self.spec,overrides)

    def test_window_cupboards_and_plinths_are_removed_from_source_geometry(self):
        names={b['id'] for b in model.expanded(self.spec,self.p)['bodies']}
        for side in ['Left','Right']:
            self.assertNotIn('WindowBench'+side+'_LowerStorage',names)
            self.assertNotIn('WindowBench'+side+'_Plinth',names)
        self.assertFalse(self.spec['window_bench']['lower_storage'])

    def test_central_cupboards_start_above_open_shelf_at_requested_heights(self):
        self.assertEqual(self.p['island_shelf_top_z'],1500)
        self.assertEqual(self.p['island_cupboard_bottom_z'],1750)
        self.assertTrue(self.spec['island_shelf']['upper_cupboards']['open_back_below'])
        for overrides in [{},{'island_shelf_top_z':1550,'island_cupboard_bottom_z':1850,'island_cupboard_height':500}]:
            p=model.parameters(self.spec,overrides); source=model.expanded(self.spec,p)
            shapes={o['id']:model.numeric_shape(o['shape'],p) for o in source['operations']}
            for i in [1,2]: self.assertEqual(shapes['IslandCupboard'+str(i)]['origin'][2],p['island_cupboard_bottom_z'])
            for i in [1,2,3]:
                post=shapes['IslandShelf_UpperPost'+str(i)]
                self.assertEqual(post['origin'][2],p['island_shelf_top_z'])
                self.assertEqual(post['origin'][2]+post['size'][2],p['island_cupboard_bottom_z'])
        for overrides in [{'island_shelf_top_z':1800},{'island_cupboard_bottom_z':2300,'island_cupboard_height':600}]:
            with self.assertRaises(ValueError): model.parameters(self.spec,overrides)


if __name__=='__main__': unittest.main()
