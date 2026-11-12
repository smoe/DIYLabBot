"""CLI fixtures demonstrate bookkeeping without running preparation protocols."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from manual_tasks import Journal


class MaterialLifecycleCliTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'exports').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='material-cli-test-', dir=ROOT / 'exports')
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.store = self.folder / 'shared.sqlite3'

    def run_cli(self, *arguments, store=None):
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/run_material_lifecycle.py'),
                                 '--store', str(self.store if store is None else store), *map(str, arguments)],
                                cwd=ROOT, capture_output=True, text=True)
        try:
            content = json.loads(result.stdout)
        except ValueError:
            self.fail('CLI did not return JSON: ' + result.stderr + result.stdout[:500])
        return result, content

    def test_both_domains_share_store_and_finish_with_retained_products_and_typed_parentage(self):
        for domain, count in [('cutrun', 3), ('extraction', 2)]:
            identity = 'SYN.CLI.' + domain
            with self.subTest(domain=domain):
                result, report = self.run_cli('demo', '--domain', domain, '--run-id', identity)
                self.assertEqual(result.returncode, 0, report.get('error', result.stderr))
                self.assertTrue(report['passed']);self.assertEqual(report['status'], 'completed')
                self.assertEqual(report['domain'], domain)
                for field in ['hardware_executed', 'network_executed', 'biochemical_protocol_executed',
                              'preparation_execution_ready', 'safety_function_qualified']:
                    self.assertIs(report[field], False)
                self.assertEqual(report['resources'], []);self.assertIsNone(report['pending_operation'])
                materials = report['inventory']['materials']
                products = [item for item in materials.values() if item['kind'] == 'product']
                byproducts = [item for item in materials.values() if item['kind'] == 'byproduct']
                sources = [item for item in materials.values() if item['kind'] in {'sample', 'control'}]
                self.assertEqual((len(products), len(byproducts), len(sources)), (count, count, count))
                reagent = identity + '.IssuedReagent'
                self.assertEqual(report['remaining'][reagent]['value'], 100 - 5 * count)
                self.assertEqual(report['remaining'][reagent]['unit'], 'uL')
                self.assertEqual(materials[reagent]['disposition'], 'retained')
                self.assertEqual(len(report['bookings']), 2 * count)
                for source in sources:
                    self.assertEqual(source['initial_quantity'], {'value': 100000, 'unit': 'cells'})
                    self.assertEqual(source['disposition'], 'consumed')
                    self.assertEqual(report['remaining'][source['id']]['value'], 0)
                for product in products:
                    self.assertEqual(report['remaining'][product['id']]['value'], 28)
                    self.assertEqual(product['disposition'], 'retained')
                    self.assertIsNotNone(product['vessel_id'])
                    self.assertEqual(len(product['parents']), 2)
                    self.assertIn(reagent, product['parents'])
                    self.assertEqual(len(set(product['parents']) & {source['id'] for source in sources}), 1)
                for byproduct in byproducts:
                    self.assertIsNone(report['remaining'][byproduct['id']]['value'])
                    self.assertEqual(byproduct['disposition'], 'retained')
                    self.assertIsNotNone(byproduct['vessel_id'])
                first = report['trace'][0]['state']
                self.assertEqual(set(first['inventory']['vessels']), set(report['inventory']['vessels']))
                self.assertEqual(len({json.dumps(item['location'], sort_keys=True)
                                      for item in report['inventory']['vessels'].values()}),
                                 len(report['inventory']['vessels']))
                for booking in report['bookings'].values():
                    self.assertEqual(booking['outcome'], 'performed')
                    self.assertIn('fixture', booking['request']['purpose'])
                    self.assertIn('no biochemical operation', booking['confirmation']['reason'])
                    if booking['request']['kind'] == 'withdrawal':
                        self.assertEqual(booking['request']['outputs'], [])
                        self.assertEqual(materials[booking['request']['inputs'][0]['material_id']]['kind'], 'product')
                if domain == 'extraction':
                    self.assertEqual({product['role'] for product in products}, {'rna_product', 'dna_product'})
        with Journal(self.store) as journal:
            self.assertEqual(journal.owners(), {})
            self.assertEqual(len(journal.audit_material_allocations()), 4)

    def test_demo_report_file_roundtrip_and_status_do_not_append_read_events(self):
        path = self.folder / 'demo.json'
        result, original = self.run_cli('demo', '--domain', 'cutrun', '--run-id', 'SYN.CLI.Roundtrip', '--out', path)
        self.assertEqual(result.returncode, 0, original.get('error', result.stderr))
        self.assertEqual(json.loads(path.read_text()), original)
        with Journal(self.store) as journal:
            count = len(journal.history(original['run_id']))
        second_path = self.folder / 'report.json'
        result, report = self.run_cli('report', original['run_id'], '--out', second_path)
        self.assertEqual(result.returncode, 0, report.get('error', result.stderr))
        self.assertEqual(report, original);self.assertEqual(json.loads(second_path.read_text()), original)
        result, status = self.run_cli('status', original['run_id'])
        self.assertEqual(result.returncode, 0, status.get('error', result.stderr))
        self.assertEqual(status['status'], 'completed');self.assertFalse(status['biochemical_protocol_executed'])
        self.assertNotIn('trace', status)
        with Journal(self.store) as journal:
            self.assertEqual(len(journal.history(original['run_id'])), count)

    def test_report_output_rejects_outside_exports_and_preserves_existing_files_before_demo(self):
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / 'report.json'
            result, content = self.run_cli('demo', '--domain', 'cutrun', '--out', target)
            self.assertEqual(result.returncode, 1);self.assertIn('exports', content['error'])
            self.assertFalse(target.exists());self.assertFalse(self.store.exists())
        existing = self.folder / 'original.json';existing.write_text('KEEP ORIGINAL\n')
        result, content = self.run_cli('demo', '--domain', 'cutrun', '--out', existing)
        self.assertEqual(result.returncode, 1);self.assertIn('already exists', content['error'])
        self.assertEqual(existing.read_text(), 'KEEP ORIGINAL\n');self.assertFalse(self.store.exists())
        result, content = self.run_cli('demo', '--domain', 'cutrun', '--out', self.folder / 'not-json.sqlite3')
        self.assertEqual(result.returncode, 1);self.assertIn('JSON', content['error'])
        self.assertFalse(self.store.exists())

    def test_store_rejects_outside_exports_and_report_requires_existing_store(self):
        with tempfile.TemporaryDirectory() as outside:
            path = Path(outside) / 'shared.sqlite3'
            result, content = self.run_cli('demo', '--domain', 'cutrun', store=path)
            self.assertEqual(result.returncode, 1);self.assertIn('exports', content['error'])
            self.assertFalse(path.exists())
        result, content = self.run_cli('report', 'SYN.Missing')
        self.assertEqual(result.returncode, 1);self.assertIn('existing material journal', content['error'])
        self.assertFalse(self.store.exists())

    def test_unimplemented_execution_arguments_are_rejected_without_creating_store(self):
        result, content = self.run_cli('demo', '--domain', 'cutrun', '--execute')
        self.assertEqual(result.returncode, 1);self.assertIn('error', content)
        self.assertFalse(self.store.exists())


if __name__ == '__main__':
    unittest.main()
