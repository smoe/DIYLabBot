"""Optional local corner caps preserve ordinary source path geometry."""
import copy
import math
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import building_fleet_motion as motion
import building_fleet_model as model
from building_fleet_missions import waypoint_progress
from building_fleet_runner import point_progress


class CornerCapsTests(unittest.TestCase):
    def test_default_and_empty_caps_have_identical_full_geometry_and_exports(self):
        points=[[0,0],[2000,0],[2000,2000],[4000,2000]]
        a=motion.Path(points,250);b=motion.Path(points,250,corner_trim_caps=[])
        self.assertEqual(a.pieces,b.pieces);self.assertEqual(a.ends,b.ends);self.assertEqual(a.samples,b.samples)
        source=model.load();self.assertEqual(motion.compile_motion(a,source),motion.compile_motion(b,source))

    def test_local_caps_equal_the_former_small_trim_only_on_port_corners(self):
        points=[[0,0],[1000,0],[1000,400],[2000,400]]
        caps=[{'point_index':2,'maximum_trim_mm':62.5},{'point_index':1,'maximum_trim_mm':62.5}]
        before=copy.deepcopy(caps);small=motion.Path(points,62.5);local=motion.Path(points,250,corner_trim_caps=caps)
        self.assertEqual(small.pieces,local.pieces);self.assertEqual(small.ends,local.ends);self.assertEqual(small.samples,local.samples)
        self.assertEqual(caps,before)
        self.assertEqual([r['point_index']for r in local.corner_trim_caps],[1,2])
        self.assertEqual(motion.compile_motion(small,model.load()),motion.compile_motion(local,model.load()))
        extended=points+[[2000,2400],[4000,2400]]
        capped=motion.Path(extended,250,corner_trim_caps=caps);ordinary=motion.Path(extended,250)
        def corner(path,point):return next(p for p in path.pieces if len(p['controls'])==8 and p['controls'][3][:2]==point)
        self.assertEqual(corner(capped,extended[-2]),corner(ordinary,extended[-2]))

    def test_markers_and_zone_progress_use_the_actual_capped_curve(self):
        points=[[0,0],[2000,0],[2000,2000],[4000,2000]]
        path=motion.Path(points,250,corner_trim_caps=[{'point_index':1,'maximum_trim_mm':50}])
        for progresses in(waypoint_progress(path,points),point_progress(path,points,250)):
            self.assertEqual(progresses,sorted(progresses));self.assertEqual(progresses[-1],path.length)

    def test_caps_reject_duplicates_endpoints_widening_and_nonfinite_values(self):
        points=[[0,0],[2000,0],[2000,2000]]
        invalid=[{},[{}],[{'point_index':0,'maximum_trim_mm':1}],[{'point_index':2,'maximum_trim_mm':1}],
            [{'point_index':True,'maximum_trim_mm':1}],[{'point_index':1,'maximum_trim_mm':251}],
            [{'point_index':1,'maximum_trim_mm':0}],[{'point_index':1,'maximum_trim_mm':math.nan}],
            [{'point_index':1,'maximum_trim_mm':math.inf}],[{'point_index':1,'maximum_trim_mm':True}],
            [{'point_index':1,'maximum_trim_mm':1,'extra':1}],
            [{'point_index':1,'maximum_trim_mm':1},{'point_index':1,'maximum_trim_mm':2}]]
        for caps in invalid:
            with self.subTest(caps=caps):
                with self.assertRaises(ValueError):motion.Path(points,250,corner_trim_caps=caps)


if __name__=='__main__':unittest.main()
