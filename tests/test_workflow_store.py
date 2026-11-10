"""All workflow CLIs must choose one shared store without silently splitting it."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from manual_tasks import TaskError
from manual_workflow import resolve_store


class WorkflowStoreTests(unittest.TestCase):
    def test_neutral_default_and_legacy_store_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            default = Path(folder) / 'workflows.sqlite3'
            legacy = default.with_name('nanodrop.sqlite3')
            with patch('manual_workflow.DEFAULT_STORE', default):
                self.assertEqual(resolve_store(None), default)
                legacy.touch()
                self.assertEqual(resolve_store(None), legacy)
                default.touch()
                with self.assertRaisesRegex(TaskError, 'Both.*--store'):
                    resolve_store(None)
                self.assertEqual(resolve_store(default), default)
                self.assertEqual(resolve_store(legacy), legacy)

    def test_two_names_of_the_same_database_do_not_split_reservations(self):
        with tempfile.TemporaryDirectory() as folder:
            default = Path(folder) / 'workflows.sqlite3'
            default.touch()
            default.with_name('nanodrop.sqlite3').symlink_to(default.name)
            with patch('manual_workflow.DEFAULT_STORE', default):
                self.assertEqual(resolve_store(None), default)


if __name__ == '__main__':
    unittest.main()
