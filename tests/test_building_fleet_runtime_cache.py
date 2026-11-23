"""Exact static math reuse must retain source, geometry and live peer guards."""
import copy
from fractions import Fraction
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import building_fleet_runtime_cache as cache
from building_fleet_control import preparation_digest
from building_fleet_sim import SensorWorld,SegmentIndex


class StaticRuntimeDataTests(unittest.TestCase):
    def test_closed_codec_preserves_exact_types_and_rationals(self):
        value={('EG',0):[Fraction(7,19),(0,-0.0),{3,9}], 'float':math.nextafter(1.,2.)}
        restored=cache._typed_bytes(cache._json(cache._pack(value)))
        self.assertEqual(restored,value)
        self.assertIs(type(restored['float']),float)
        self.assertIs(type(restored['EG',0][1][0]),int)
        self.assertEqual(restored['EG',0][1][1].hex(),'-0x0.0p+0')
        self.assertIs(type(restored['EG',0][0]),Fraction)

    def test_closed_codec_rejects_executable_or_nonfinite_values(self):
        for value in(lambda:0,object(),float('nan'),float('inf')):
            with self.subTest(value=type(value)):
                with self.assertRaises(ValueError):cache._pack(value)


class StaticHomeRayTests(unittest.TestCase):
    def make(self):
        static=SegmentIndex([((500,-800),(500,800))]);landing=SegmentIndex([]);cabin=SegmentIndex([])
        for name,index,key in(('static',static,'EG'),('landing',landing,('EG',())),('cabin',cabin,())):
            index._runtime_static_index_binding=('source',name,key,'exact-native-index')
        indices={'static':{'EG':static},'landings':{('EG',()):landing},'cabin':{():cabin}}
        world=SensorWorld({'angular_step_deg':90,'range_mm':1000}, {'EG':static.segments},
            cabin_segments_by_sides={():cabin.segments},
            landing_segments_by_level_sides={('EG',()):landing.segments},prepared_indices=indices)
        pose=[0,0,0.];values=world._first_returns(*pose,static,landing,cabin,[])
        row={'level':'EG','pose_mm_rad':pose,'landing_sides':(),'cabin_sides':(),
            'index_bindings':[index._runtime_static_index_binding for index in(static,landing,cabin)],
            'directions_sha256':cache._direction_fingerprint(world,pose[2]),'distances_mm':values}
        capsule={'format':'solidcraftbot.building-fleet-static-rays/1','no_peer_data':True,
            'no_observation_times':True,'settings_sha256':preparation_digest(world.settings),'rows':[row]}
        world._static_cache.clear();return world,capsule,static,landing,cabin

    def test_exact_static_hit_keeps_current_peer_overlay(self):
        world,capsule,static,landing,cabin=self.make()
        peers=[('disc',150.,0.,25.)]
        expected=world._first_returns(0,0,0.,static,landing,cabin,peers)
        world._static_cache.clear();world.static_rays=0
        self.assertEqual(cache.seed_static_rays(world,capsule),{'seeded':1,'trig_mismatches':0,'index_mismatches':0})
        self.assertEqual(world._first_returns(0,0,0.,static,landing,cabin,peers),expected)
        self.assertEqual(world.static_rays,0)
        self.assertLess(expected[0],capsule['rows'][0]['distances_mm'][0])
        changed=world._first_returns(0,0,0.,static,landing,cabin,[('disc',250.,0.,25.)])
        self.assertNotEqual(changed,expected)
        self.assertEqual(world.scans,0)

    def test_trig_or_native_index_difference_uses_original_queries(self):
        for field in('directions_sha256','index_bindings'):
            with self.subTest(field=field):
                world,capsule,static,landing,cabin=self.make()
                if field=='directions_sha256':capsule['rows'][0][field]='another-platform-trig'
                else:static._runtime_static_index_binding=('different','geometry')
                stats=cache.seed_static_rays(world,capsule)
                self.assertEqual(stats['seeded'],0)
                self.assertEqual(len(world._static_cache),0)
                before=world.static_rays
                world._first_returns(0,0,0.,static,landing,cabin,[])
                self.assertEqual(world.static_rays-before,4)

    def test_actual_numeric_type_signed_zero_and_pose_changes_miss(self):
        for pose in([0.,0,0.],[0,0,-0.0],[math.nextafter(0.,1.),0,0.]):
            with self.subTest(pose=pose):
                world,capsule,static,landing,cabin=self.make();cache.seed_static_rays(world,capsule)
                before=world.static_rays;world._first_returns(*pose,static,landing,cabin,[])
                self.assertEqual(world.static_rays-before,4)

    def test_changed_source_or_invalid_distances_fail(self):
        for mutate in(lambda c:c.update(settings_sha256='another-source'),
                       lambda c:c['rows'][0].update(distances_mm=[float('nan')]*4),
                       lambda c:c.update(no_peer_data=False)):
            world,capsule,*_=self.make();mutate(capsule)
            with self.assertRaises(ValueError):cache.seed_static_rays(world,capsule)


if __name__=='__main__':unittest.main()
