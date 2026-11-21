"""Ordinary map support uses R1 but never borrows the lift height exception."""
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import building_fleet_floor as floor
import building_fleet_model as model


class Mesh:
    def __init__(self,gap=8,height=0,role='concept_storey_slab'):
        self.manifest={'levels':[{'id':'EG','z_mm':0}]}
        self.scene={'maximum_float32_error_mm':0,'groups':[
            {'id':name,'role':role,'bounds_mm':{'min':[a,-200,height-10],'max':[b,200,height]}}
            for name,a,b in[('floorA',-200,-gap/2),('floorB',gap/2,200)]]}
        self.height=height
    def bounds(self,group):return group['bounds_mm']
    def triangles(self,group):
        a,b=group['bounds_mm']['min'][0],group['bounds_mm']['max'][0];z=self.height
        return [[[a,-200,z],[b,-200,z],[b,200,z]],[[a,-200,z],[b,200,z],[a,200,z]]]


class OrdinaryFloorTests(unittest.TestCase):
    def test_exact_merge_across_native_body_seams_retains_both_identities(self):
        bank=floor.FloorSupport(Mesh(gap=0),'EG',model.load())
        with patch.object(floor.rule,'support_covers',side_effect=AssertionError('No new floor area needed')):
            result=bank.covers([0,0],.3,40,20)
        self.assertTrue(result['passed']);self.assertFalse(result['rule_applied'])
        self.assertEqual(result['source_body_ids'],['floorA','floorB'])

    def test_r1_is_used_for_the_entire_swept_line(self):
        bank=floor.FloorSupport(Mesh(), 'EG',model.load())
        result=bank.line([-40,0],[40,0],20,curve_ref={'route':'test'})
        self.assertTrue(result['passed']);self.assertTrue(result['rule_applied'])
        self.assertEqual(result['applications'][0]['adjacent_bodies'],['floorA','floorB'])
        self.assertAlmostEqual(result['applications'][0]['width_mm'],8)
    def test_gap_above_owner_limit_is_not_a_floor(self):
        self.assertFalse(floor.FloorSupport(Mesh(15.5),'EG',model.load()).covers([0,0],0,40,20)['passed'])
    def test_ordinary_three_mm_offset_remains_unsupported(self):
        self.assertFalse(floor.FloorSupport(Mesh(height=3),'EG',model.load()).covers([0,0],0,40,20)['passed'])
        self.assertFalse(floor.FloorSupport(Mesh(height=3,role='concept_lift_floor_finish'),'EG',model.load()).covers([0,0],0,40,20)['passed'])
    def test_open_edge_overhang_is_not_created_by_the_grid_provider(self):
        bank=floor.FloorSupport(Mesh(gap=0),'EG',model.load())
        self.assertFalse(bank.covers([190,0],0,17.5,20)['passed'])
    def test_exact_native_cell_fast_path_cannot_fill_a_missing_slot(self):
        bank=floor.FloorSupport(Mesh(),'EG',model.load())
        inside=bank.covers([-100,0],.2,20,20)
        self.assertTrue(inside['passed']);self.assertFalse(inside['rule_applied'])


if __name__=='__main__':unittest.main()
