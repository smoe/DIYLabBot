"""JUnit collection must not turn absent or skipped ROS execution into success."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import check_ros2_ci_results as results


class RosCiResultsTests(unittest.TestCase):
    def check_xml(self, xml):
        with tempfile.TemporaryDirectory() as directory:
            if xml is not None:
                (Path(directory)/'pytest.xml').write_text(xml)
            return results.check(Path(directory))

    def test_no_results_or_only_non_junit_xml_cannot_pass(self):
        for xml in (None, '<package><name>solidcraftbot_ros</name></package>', '<testsuite tests="0"/>'):
            with self.subTest(xml=xml), self.assertRaisesRegex(ValueError, 'no JUnit'):
                self.check_xml(xml)

    def test_offline_success_cannot_replace_a_live_mock_test(self):
        with self.assertRaisesRegex(ValueError, 'missing the live'):
            self.check_xml('<testsuite><testcase name="test_protocol"/></testsuite>')

    def test_failed_or_skipped_case_is_rejected_despite_a_passing_live_case(self):
        for defect in ('failure', 'error', 'skipped'):
            xml='<testsuites><testsuite><testcase name="test_live_mock_stationary_hold"/><testcase name="other"><'+defect+'/></testcase></testsuite></testsuites>'
            with self.subTest(defect=defect), self.assertRaisesRegex(ValueError, 'without skips'):
                self.check_xml(xml)

    def test_nonzero_suite_summary_cannot_hide_a_setup_error(self):
        for field in ('failures', 'errors', 'skipped'):
            xml='<testsuite '+field+'="1"><testcase name="test_live_mock_stationary_hold"/></testsuite>'
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'JUnit suite'):
                self.check_xml(xml)

    def test_complete_live_and_offline_results_pass(self):
        value=self.check_xml('<testsuites><testsuite tests="2" failures="0" errors="0" skipped="0"><testcase name="test_live_mock_stationary_hold"/><testcase name="test_installed_assets"/></testsuite></testsuites>')
        self.assertTrue(value['passed']);self.assertEqual(value['tests'],2)


if __name__=='__main__':unittest.main()
