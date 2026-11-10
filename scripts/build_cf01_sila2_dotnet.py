"""Build the independent client against one verified, unchanged upstream revision."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = 'https://gitlab.com/SiLA2/vendors/sila_tecan.git'
REVISION = 'adf5dbadfdfdf033956657cd278566ede75a746f'
SOURCE = ROOT / 'exports/research/sila-tecan'
OUTPUT = ROOT / 'exports/generated/cf01-sila2/dotnet'
ASSEMBLY = OUTPUT / 'bin/Debug/net10.0/SiLAInterop.dll'
REPORT = OUTPUT / 'build-report.json'
INPUTS = [Path(__file__), *(ROOT / 'tests/sila2-dotnet' / name for name in
          ('Program.cs', 'SiLAInterop.csproj', 'Directory.Build.props', 'runner_bridge.py'))]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_sources():
    revision = subprocess.check_output(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != REVISION:
        raise ValueError('Tecan checkout must be pinned to ' + REVISION)
    subprocess.run(['git', '-C', str(SOURCE), 'diff', '--quiet', 'HEAD', '--'], check=True)


def verify_build():
    """Reject stale assemblies rather than claiming tests exercised current code."""
    verify_sources()
    report = json.loads(REPORT.read_text())
    expected = {str(path.relative_to(ROOT)): digest(path) for path in INPUTS}
    if (report['source_files_sha256'] != expected or report['upstream_revision'] != REVISION
            or report['assembly_sha256'] != digest(ASSEMBLY)):
        raise ValueError('Independent client build is stale; rebuild it before testing')


def build(dotnet):
    verify_sources()
    environment = {**os.environ, 'DOTNET_CLI_HOME': str(ROOT / 'exports/tools/dotnet-home'),
                   'NUGET_PACKAGES': str(ROOT / 'exports/tools/nuget'),
                   'DOTNET_SKIP_FIRST_TIME_EXPERIENCE': '1', 'DOTNET_NOLOGO': '1',
                   'DOTNET_CLI_TELEMETRY_OPTOUT': '1'}
    sdk = subprocess.check_output([str(dotnet), '--version'], env=environment, text=True).strip()
    subprocess.run([str(dotnet), 'build', str(ROOT / 'tests/sila2-dotnet/SiLAInterop.csproj'),
                    '-f', 'net10.0', '-p:TargetFrameworks=net10.0'], env=environment, check=True, cwd=ROOT)
    report = {'upstream': UPSTREAM, 'upstream_revision': REVISION, 'dotnet_sdk': sdk,
              'source_files_sha256': {str(path.relative_to(ROOT)): digest(path) for path in INPUTS},
              'assembly_sha256': digest(ASSEMBLY), 'network_executed': False}
    REPORT.write_text(json.dumps(report, indent=2) + '\n')
    return REPORT


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dotnet', type=Path, default=ROOT / 'exports/tools/dotnet/dotnet')
    print(build(parser.parse_args().dotnet.resolve()))
