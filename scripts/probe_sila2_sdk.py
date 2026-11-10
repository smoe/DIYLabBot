"""Exercise actual TLS and SiLAService using two independent Python SDKs.

This prerequisite probe is not the CF01 integration/interoperability acceptance
test. The independent .NET client remains a separate mandatory test gate.
"""
import argparse
import asyncio
import importlib.metadata
import json
from pathlib import Path
import uuid


async def probe():
    from sila.server import Server, ServerConfig, create_certificate
    from sila.client import Client, ClientConfig
    server_uuid = str(uuid.uuid4())
    certificate = create_certificate(server_uuid, ip_addresses=['127.0.0.1'], dns_names=['localhost'])
    server = Server(ServerConfig(hostname='127.0.0.1', port=0, tls=True,
                    uuid=server_uuid, type='CF01SdkProbe', name='CF01 SDK probe',
                    certificate_chain=certificate.pem_certificate,
                    private_key=certificate.pem_private_key))
    await server.start()
    try:
        port = int(server._address.rsplit(':', 1)[1])
        async with Client(ClientConfig(hostname='127.0.0.1', port=port, tls=True,
                          root_certificates=certificate.pem_certificate, default_timeout=5000)) as client:
            received = await client.SiLAService.ServerUUID.read()
            assert received == server_uuid
        def legacy_client():
            from sila2.client import SilaClient
            client = SilaClient('127.0.0.1', port, root_certs=certificate.pem_certificate)
            try:
                return client.SiLAService.ServerUUID.get()
            finally:
                client.close()
        legacy_uuid = await asyncio.wait_for(asyncio.to_thread(legacy_client), timeout=10)
        assert legacy_uuid == server_uuid
        return {'passed': True, 'tls': True, 'sila_service': True,
                'independent_python_client': True, 'cf01_network_acceptance': False,
                'dotnet_acceptance': False,
                'versions': {p: importlib.metadata.version(p) for p in ['unitelabs-sila', 'sila2', 'grpcio']}}
    finally:
        await server.stop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    result = asyncio.run(probe())
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))
