"""Opt-in checks of the current complete native logistics evidence package."""
import json
import os
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import build_ps01_logistics as build


@unittest.skipUnless(os.environ.get('SOLIDCRAFTBOT_PS01_LOGISTICS_NATIVE_TESTS')=='1',
                     'Native logistics evidence checks are opt-in; skip is not a CAD pass')
class NativeEvidenceTests(unittest.TestCase):
    def test_current_two_cad_continuous_evidence_and_exact_artifacts(self):
        path=ROOT/'exports/ps01-logistics-cad/final-report.json'
        self.assertTrue(path.is_file(),'Run both native audits and report_ps01_logistics.py first')
        report=json.loads(path.read_text())
        self.assertTrue(report['passed'])
        build.base.verify_pins(report['source_files_sha256'])
        for field in ('files_sha256','native_artifacts_sha256'):
            for name,digest in report[field].items():
                self.assertEqual(build.s.robot.digest(Path(name)),digest,name)
                if Path(name).name=='animation-report.json':
                    animation=json.loads(Path(name).read_text())
                    self.assertEqual(build.s.robot.digest(Path(name).with_name('animation.html')),animation['html_sha256'])
                if Path(name).name=='brep-equivalence.json':
                    equivalence=json.loads(Path(name).read_text())
                    self.assertEqual(build.s.robot.digest(ROOT/'scripts/verify_ps01_logistics_breps.py'),equivalence['verifier_sha256'])
        self.assertEqual(set(report['native_audits']),{'freecad','solidcraft'})
        for audit in report['native_audits'].values():
            self.assertTrue(audit['passed'])
            self.assertGreater(audit['continuous_intervals'],0)
        self.assertTrue(report['model_comparison']['passed'])
        self.assertEqual(report['model_comparison']['body_count'],len(report['model_comparison']['bodies']))
        self.assertFalse(report['hardware_executed'])
        self.assertFalse(report['human_speed_acceptance_proven'])


if __name__=='__main__':unittest.main()
