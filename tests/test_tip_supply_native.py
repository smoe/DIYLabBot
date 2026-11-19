"""Opt-in validation of locally generated native T01 gauge evidence, not tip fit."""
import json
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import build_tip_supply as build
import tip_supply_model as model


class NativeTipSupplyTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('SOLIDCRAFTBOT_TIP_SUPPLY_NATIVE_TESTS') == '1', 'Opt-in native evidence check; run build_tip_supply.py --check-freecad first')
    def test_current_native_gauges_are_valid_without_claiming_tip_compatibility(self):
        paths = list((ROOT/'exports/generated').glob('tip-supply-*/build-report.json'))
        if not paths:
            self.skipTest('No local tip-supply native build report')
        report = json.loads(max(paths, key=lambda p: p.stat().st_mtime_ns).read_text())
        self.assertTrue(report['passed'])
        self.assertEqual(report['source_files_sha256'], build.dependencies(model.load()))
        native = report['native_screen']
        if native.get('status') == 'not_run':
            self.skipTest('This data-only build did not run FreeCAD')
        self.assertTrue(native['passed'])
        self.assertEqual(native['source_files_sha256'], report['source_files_sha256'])
        for key, path in report['files'].items():
            self.assertEqual(model.robot.digest(Path(path)), report['artifact_sha256'][key])
        self.assertEqual(model.robot.digest(Path(native['native_file'])), native['native_sha256'])
        self.assertEqual(len(native['gauge_checks']), 6)
        self.assertTrue(all(c['passed'] for c in native['gauge_checks']))
        self.assertEqual(set(native['tip_fit_status'].values()), {'open'})
        self.assertFalse(native['full_tip_fit_checked'])
        self.assertFalse(native['tip_or_box_solids_generated'])


if __name__ == '__main__': unittest.main()
