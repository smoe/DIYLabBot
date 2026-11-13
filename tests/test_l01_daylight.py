import datetime,math,sys,unittest
from pathlib import Path
from zoneinfo import ZoneInfo
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import l01_daylight as light
class DaylightPhysics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.program=light.derive()
    def test_timezone_changes_do_not_change_sun(self):
        local=datetime.datetime(2026,11,12,14,tzinfo=ZoneInfo('Europe/Berlin'))
        a=light.solar_position(54.084603,12.098202,local);b=light.solar_position(54.084603,12.098202,local.astimezone(datetime.timezone.utc))
        self.assertEqual(a,b)
        with self.assertRaises(ValueError):light.solar_position(54,12,local.replace(tzinfo=None))
    def test_no_invented_november_sunbeam(self):
        november=next(c for c in self.program['scenarios'] if c['id']=='november')
        self.assertTrue(209<november['azimuth_deg']<212)
        self.assertTrue(12<november['altitude_deg']<15)
        self.assertFalse(november['direct_window_incidence_possible'])
        self.assertEqual(november['utc_datetime'],'2026-11-12T13:00:00+00:00')
    def test_summer_evening_can_enter_confirmed_nw_windows(self):
        summer=next(c for c in self.program['scenarios'] if c['id']=='summer')
        self.assertTrue(summer['direct_window_incidence_possible'])
        self.assertTrue(268<summer['azimuth_deg']<272)
        self.assertTrue(28<summer['altitude_deg']<31)
        self.assertEqual(summer['utc_datetime'],'2026-06-21T16:00:00+00:00')
    def test_emitters_are_inside_source_apertures(self):
        p=self.program;self.assertEqual(len(p['emitters']),9)
        for e in p['emitters']:
            self.assertTrue(p['window_vertical_gl'][0]<e['position_gl'][1]<p['window_vertical_gl'][1])
            self.assertGreater(e['area_gl2'],0)
            self.assertAlmostEqual(sum(x*x for x in e['outward_gl']),1)
        for c in p['scenarios']:self.assertAlmostEqual(sum(x*x for x in c['sun_direction_gl']),1)
        self.assertEqual({e['window_id'] for e in p['emitters']},{0,1,2})
    def test_solar_east_west_sign(self):
        morning=light.solar_position(0,0,datetime.datetime(2026,3,20,9,tzinfo=datetime.timezone.utc))
        evening=light.solar_position(0,0,datetime.datetime(2026,3,20,15,tzinfo=datetime.timezone.utc))
        self.assertGreater(morning['direction_enu'][0],0)
        self.assertLess(evening['direction_enu'][0],0)

    def test_daily_samples_and_ceiling_assumptions(self):
        p=self.program
        for scenario in p['scenarios']:
            self.assertEqual(len(scenario['time_samples']),289)
            for sample in scenario['time_samples']:
                self.assertAlmostEqual(sum(x*x for x in sample[:3]),1,places=6)
            self.assertLess(scenario['time_samples'][0][4],-6)
            self.assertEqual(scenario['time_samples'][0][5],0)
        panels=p['artificial_lighting']['panels']
        self.assertEqual(len(panels),4)
        for panel in panels:
            self.assertGreater(panel['position_mm'][2],2400)
            self.assertGreater(panel['area_gl2'],0)
