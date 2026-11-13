import unittest,sys,math,json,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import l01_orientation as orientation

class OrientationReference(unittest.TestCase):
    def test_confirmed_sector_and_local_axes(self):
        r=orientation.derive()
        self.assertEqual(r['nominal_window_azimuth_deg_clockwise_from_true_north'],315)
        self.assertEqual(r['l01_axes_azimuth_deg'],{'+X':45,'+Y':315})
        self.assertIsNone(r['measured_window_azimuth_deg'])
        self.assertIsNone(r['metric_registration'])
    def test_rotation_is_right_handed_and_north_is_unit(self):
        r=orientation.derive();m=r['rotation_l01_to_enu'];columns=list(zip(*m))
        for i,a in enumerate(columns):
            for j,b in enumerate(columns):self.assertAlmostEqual(sum(x*y for x,y in zip(a,b)),1 if i==j else 0)
        x,y,z=columns;cross=[x[1]*y[2]-x[2]*y[1],x[2]*y[0]-x[0]*y[2],x[0]*y[1]-x[1]*y[0]]
        for a,b in zip(cross,z):self.assertAlmostEqual(a,b)
        north=r['true_north_in_l01'];actual=[sum(m[i][j]*north[j] for j in range(3)) for i in range(3)]
        for a,b in zip(actual,[0,1,0]):self.assertAlmostEqual(a,b)
    def test_only_actual_exterior_segments(self):
        r=orientation.derive();self.assertEqual({s['wall_id'] for s in r['facade_segments']},{'W037','W061'})
        s=json.loads(orientation.SOURCE.read_text());s['exterior_facade_wall_ids']=['W070']
        with self.assertRaisesRegex(ValueError,'exterior boundary'):orientation.derive(s)
    def test_no_accidental_metric_registration(self):
        s=json.loads(orientation.SOURCE.read_text());s['metric_registration']={'scale':1000}
        with self.assertRaisesRegex(ValueError,'not implemented'):orientation.derive(s)
