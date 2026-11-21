"""Canonical support and numeric compiled-gate fixtures; not native evidence."""
import copy
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import building_fleet_lift_geometry as geometry
from check_building_fleet_freecad import LiftTimeline


def triangles(xlo,xhi):
    return [[[xlo,-1000.],[xhi,-1000.],[xhi,1000.]],
            [[xlo,-1000.],[xhi,1000.],[xlo,1000.]]]


def context(gap=8.,schedule=()):
    # Bypass only the real native-file constructor in this small geometry
    # fixture. The actual timeline, R1 engine and interval gate are exercised.
    value=geometry.PortSupportContext.__new__(geometry.PortSupportContext)
    door={'id':'Door','mechanism':'lift_door','states':{'closed':0.,'open':100.}}
    port={'id':'P','active':True,'level_id':'EG','z_mm':0.,'side':'inward','door_object_ids':['Door']}
    config={'object_id':'Cabin','reference_level':'EG','reference_z_mm':0.,'ports':[port],'door_objects':[door]}
    value.timeline=LiftTimeline(config,list(schedule))
    value.mesh=SimpleNamespace(manifest={'elevator':config,'objects':[door]})
    value.port_id='P';value.vehicle_id='BF01';value.level='EG';value.settings={'gap':{'maximum':15.}}
    value.metadata={'port_id':'P','source_derived_height_offset_mm':3.}
    value.applications=[];value.height_applications=[];value._proof_cache={}
    raised=triangles(gap,1000.)
    from building_fleet_clearance import PolygonIndex
    value._raised_index=PolygonIndex(raised)
    value._raised_body_by_triangle={id(p):'LiftCabinSill_inward'for p in raised}
    value._raised_rows=[{'body_id':'LiftCabinSill_inward'}]
    return value


class PortContextTests(unittest.TestCase):
    def test_gap_rule_is_used_instead_of_a_floor_waiver(self):
        ordinary=triangles(-1000.,0.)
        for gap,passed in[(8.,True),(15.,True),(15.5,False),(297.,False)]:
            with self.subTest(gap=gap):
                value=context(gap)
                result=value.support([gap/2,0.],0.,200.,100.,start_s=0.,end_s=1.,
                    ordinary_triangles=ordinary,ordinary_body_ids=['Slab']*2,curve_ref='fixture')
                self.assertEqual(result['passed'],passed)
                self.assertTrue(result['lift_height_exception_applied'])
                if passed:self.assertTrue(result['applications'])

    def test_close_and_reopen_between_open_endpoints_still_fails(self):
        schedule=[{'kind':'doors','start_s':0.,'end_s':1.,'level':'EG','target':'closed'},
                  {'kind':'doors','start_s':1.,'end_s':2.,'level':'EG','target':'open'}]
        value=context(schedule=schedule)
        with self.assertRaises(ValueError):value._gate_interval(0.,2.)

    def test_ordinary_supported_prefix_needs_no_raised_floor(self):
        value=context(schedule=[{'kind':'doors','start_s':0.,'end_s':1.,'level':'EG','target':'closed'}])
        result=value.support([-500.,0.],0.,100.,100.,start_s=1.,end_s=2.,
            ordinary_triangles=triangles(-1000.,0.),ordinary_body_ids=['Slab']*2)
        self.assertTrue(result['passed']);self.assertFalse(result['lift_height_exception_applied'])
        self.assertEqual(value.height_applications,[])


if __name__=='__main__':unittest.main()
