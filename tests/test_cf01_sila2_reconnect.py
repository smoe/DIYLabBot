"""A failed reconnect must remain bounded even when transport cleanup stalls."""
import asyncio
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from cf01_sila2_client import read_station_status


class ReconnectDeadlineTests(unittest.IsolatedAsyncioTestCase):
    async def test_stalled_connect_and_cleanup_do_not_defeat_the_deadline(self):
        class StalledClient:
            def __init__(self, config):
                pass

            async def open(self):
                await asyncio.Event().wait()

            async def close(self):
                await asyncio.Event().wait()

        sdk = types.ModuleType('sila.client')
        sdk.Client = StalledClient
        sdk.ClientConfig = lambda **kwargs: kwargs
        package = types.ModuleType('sila')
        package.client = sdk
        ready = {'tls': True, 'simulation_only': True, 'hardware_available': False,
                 'bind': '127.0.0.1', 'port': 1, 'certificate': 'SYN.PublicCertificate'}
        with patch.dict(sys.modules, {'sila': package, 'sila.client': sdk}), \
                patch('cf01_sila2_client.Path.read_bytes', return_value=b'SYN.PUBLIC.CERTIFICATE'):
            with self.assertRaisesRegex(RuntimeError, 'Could not read authenticated CF01'):
                await asyncio.wait_for(read_station_status(ready, 'SYN.Observer', 'SYN.Secret', timeout_s=.02), timeout=2)


if __name__ == '__main__':
    unittest.main()
