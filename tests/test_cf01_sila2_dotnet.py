"""Independent Tecan client over real TLS; deliberately separate acceptance gate."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'tests/sila2-dotnet'))
DOTNET = ROOT / 'exports/tools/dotnet/dotnet'
CLIENT = ROOT / 'exports/generated/cf01-sila2/dotnet/bin/Debug/net10.0/SiLAInterop.dll'
ENABLED = (os.getenv('SOLIDCRAFTBOT_SILA_DOTNET_TESTS') == '1'
           and importlib.util.find_spec('sila') is not None)


@unittest.skipUnless(ENABLED, 'Build the Tecan probe and set SOLIDCRAFTBOT_SILA_DOTNET_TESTS=1')
class DotnetTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_runner_roundtrip_over_independent_tecan_transport(self):
        from cf01_sila2_auth import credential
        from cf01_sila2_server import CF01Server
        from cf01_sila2_batch import ClientJournal
        from cf01_rack_batch import Runner
        from runner_bridge import TecanStation
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            application = CF01Server(root / 'station.sqlite3',
                [credential('operator', 'independent-test-password', 'operator')], root / 'tls')
            await application.start()
            try:
                ready = root / 'ready.json'
                ready.write_text(json.dumps({'server_uuid': application.runtime.store.server_uuid,
                    'boot_id': application.runtime.sim.boot_id, 'bind': '127.0.0.1',
                    'certificate': str(root / 'tls/server.crt'), 'port': application.port,
                    'capacity': application.runtime.sim.spec['rotor']['slots'],
                    'braking_s': application.runtime.sim.spec['mechanisms']['braking']['simulation_stop_s']}))
                secret = root / 'login.json'
                secret.touch(mode=0o600)
                secret.write_text(json.dumps({'username': 'operator', 'password': 'independent-test-password'}))
                def run():
                    journal = ClientJournal(root / 'tecan-batch.jsonl')
                    station = None
                    try:
                        station = TecanStation(ready, secret, journal)
                        runner = Runner(transport='sila2', station_backend=station, checkpoint=journal.checkpoint)
                        self.assertIsNone(runner.sim)
                        return runner.run()
                    finally:
                        if station is not None:
                            station.close()
                        journal.close()
                report = await asyncio.wait_for(asyncio.to_thread(run), 90)
                self.assertTrue(report['passed'])
                self.assertTrue(report['order_restored'])
                self.assertTrue(report['network_executed'])
                self.assertTrue(report['spin_completed'])
                self.assertEqual(report['initial_order'], report['final_order'])
                self.assertEqual(report['network']['implementation'], 'Tecan.Sila2')
                self.assertIsNone(application.runtime.sim.owner)
                self.assertTrue(all(not value['present'] for value in application.runtime.sim.slots.values()))
            finally:
                await application.stop()

    async def test_independent_tecan_tls_client(self):
        from cf01_sila2_auth import credential
        from cf01_sila2_server import CF01Server
        from build_cf01_sila2_dotnet import verify_build
        self.assertTrue(DOTNET.is_file(), 'Install the local .NET SDK')
        self.assertTrue(CLIENT.is_file(), 'Build tests/sila2-dotnet/SiLAInterop.csproj')
        verify_build()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            application = CF01Server(root / 'station.sqlite3',
                [credential('operator', 'independent-test-password', 'operator')], root / 'tls')
            await application.start()
            try:
                (root / 'ready.json').write_text(json.dumps({
                    'server_uuid': application.runtime.store.server_uuid,
                    'certificate': str(root / 'tls/server.crt'), 'port': application.port,
                    'capacity': application.runtime.sim.spec['rotor']['slots'],
                    'braking_s': application.runtime.sim.spec['mechanisms']['braking']['simulation_stop_s']}))
                secret = root / 'login.json'
                secret.touch(mode=0o600)
                secret.write_text(json.dumps({'username': 'operator', 'password': 'independent-test-password'}))
                process = await asyncio.create_subprocess_exec(str(DOTNET), str(CLIENT),
                    str(root / 'ready.json'), str(secret), str(root / 'result.json'),
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=ROOT)
                try:
                    stdout, stderr = await asyncio.wait_for(process.communicate(), 45)
                except BaseException:
                    if process.returncode is None:
                        process.kill()
                        await process.wait()
                    raise
                self.assertEqual(process.returncode, 0, stderr.decode() + stdout.decode())
                result = json.loads((root / 'result.json').read_text())
                for field in ('passed', 'tls', 'feature_discovery', 'authentication',
                              'lock_metadata', 'observable_completion', 'duplicate_rejected',
                              'real_mode_rejected', 'spin_completed', 'cancellation_tested', 'status_subscription'):
                    self.assertTrue(result[field], field)
                self.assertEqual(result['server_uuid'], application.runtime.store.server_uuid)
                self.assertIsNone(application.runtime.lock_id)
            finally:
                await application.stop()
