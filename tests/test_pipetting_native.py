import os
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import pipetting_station as station
import build_pipetting_station as build


@unittest.skipUnless(os.environ.get('SOLIDCRAFTBOT_PIPETTING_NATIVE_TESTS')=='1','Native PS01 artifact check is opt-in')
class NativeTests(unittest.TestCase):
    def test_current_independent_backends_and_qualified_scope(self):
        paths=list((ROOT/'exports/pipetting-cad').glob('*/build-report.json'))
        if not paths:self.skipTest('No native PS01 report available')
        path=max(paths,key=lambda p:p.stat().st_mtime)
        report=station.read(path)
        if not report['cross_cad_performed']:self.skipTest('The last native build did not run both backends')
        self.assertTrue(report['passed'])
        self.assertEqual(report['source_files_sha256'],build.source_pins())
        for item in report['files'].values():self.assertEqual(station.robot.digest(Path(item['path'])),item['sha256'])
        self.assertTrue(report['cross_cad_comparisons'])
        self.assertTrue(all(c['passed'] for c in report['cross_cad_comparisons']))
        native=station.read(path.parent/'freecad-report.json');solid=station.read(path.parent/'solidcraft-report.json')
        self.assertTrue(native['parked_pose_interference']['passed'])
        self.assertTrue(native['handling_grip_fit']['passed'])
        self.assertEqual(len(native['handling_grip_fit']['checks']),24)
        self.assertTrue(report['handling_endpoints']['passed'])
        self.assertEqual(len(report['handling_endpoints']['checks']),24)
        self.assertFalse(report['handling_plan']['feedback_observed'])
        self.assertEqual(native['bounding_box_method'],'optimalBoundingBox(useTriangulation=False, useShapeTolerance=False)')
        self.assertFalse(native['solidcraft_construction_dependency'])
        self.assertFalse(solid['freecad_construction_dependency'])
        self.assertTrue(native['reopened_valid'])
        self.assertFalse(report['tip_boxes_and_tips_modeled'])
        self.assertFalse(report['qualification']['robot_motion_implemented'])


if __name__=='__main__':unittest.main()
