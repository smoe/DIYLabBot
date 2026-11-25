"""Prove that the new source binding is versioned and grants no approval."""

import json
from pathlib import Path
import sys
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import cutrun_preparation as legacy
import cutrun_preparation_v3 as revised
from manual_tasks import TaskError


class DraftPreflightTests(unittest.TestCase):
    def setUp(self):
        self.profile = json.loads(revised.SOURCE.read_bytes())

    def compile_override(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'profile.json'
            path.write_text(json.dumps(self.profile), encoding='utf-8')
            return revised.compile_plan(path)

    def test_new_source_binding_preserves_the_legacy_planning_graph(self):
        original = legacy.compile_plan()
        plan = revised.compile_plan()
        self.assertEqual(plan['format'], 'solidcraftbot.cutrun-preparation-plan/3')
        for key in ('branches', 'lineage', 'qc', 'stop_plan', 'effects'):
            self.assertEqual(plan[key], original[key])
        self.assertEqual(plan['source_binding'], self.profile['source_binding'])
        self.assertTrue(any(item.get('decision_id') == 'O11' for item in plan['open_requirements']))
        self.assertNotIn('historical_sop_revision', plan['source_binding'])
        self.assertFalse(plan['execution_ready'])
        self.assertFalse(plan['manufacturer_original_verified'])
        self.assertEqual(legacy.compile_plan(), original)

    def test_source_tampering_and_unearned_approval_fail(self):
        for section, field, value in [('sop_draft', 'source_sha256', '0' * 64),
                                      ('sop_draft', 'revision', '0.2'),
                                      ('manufacturer', 'protocol_revision', '01/2025'),
                                      ('confirmation', 'status', 'confirmed')]:
            self.profile = json.loads(revised.SOURCE.read_bytes())
            self.profile['source_binding'][section][field] = value
            with self.subTest(section=section, field=field), self.assertRaises(TaskError):
                self.compile_override()

    def test_mismatched_pdf_does_not_verify_the_original(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'manufacturer.pdf'
            path.write_bytes(b'%PDF-1.7\nwrong original\n')
            with self.assertRaises(TaskError):
                revised.compile_plan(original_pdf=path)
