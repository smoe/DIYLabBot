"""Measure the actual synthetic twelve-sample workflow in private stores.

Both modes execute the same real CF01 -> NanoDrop -> Qubit demo and current
journal implementation. ``full`` additionally audits the entire chain before
each append; ``cached`` uses the normal verified-prefix path. This compares
verification cadence, not historical implementations. Timings have no pass
threshold. Source drift makes the result non-reproducible and fails the report.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import sqlite3
import sys
import tempfile
import time
import uuid

from manual_tasks import Journal, encoded
from manual_workflow_cli import output_path
from lab_workflow import Workflow
from run_lab_workflow import run_demo

ROOT = Path(__file__).resolve().parents[1]


class CountingJournal(Journal):
    def __init__(self, path, full_before_append=False):
        self.full_before_append = full_before_append
        self.full_checks = 0
        self.append_count = 0
        super().__init__(path)

    def history(self, run_id):
        self.full_checks += 1
        return super().history(run_id)

    def append(self, run_id, revision, kind, payload, state, artifact=None):
        if self.full_before_append:
            self.history(run_id)
        result = super().append(run_id, revision, kind, payload, state, artifact)
        self.append_count += 1
        return result


def hashes_match(sources):
    return [name for name, checksum in sources.items()
            if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != checksum]


def measure(transport, mode):
    scratch = ROOT / 'exports/manual-workflows'
    scratch.mkdir(parents=True, exist_ok=True)
    run_id = 'SYN.Benchmark.' + transport + '.' + mode + '.' + uuid.uuid4().hex[:8]
    print('Benchmarking ' + transport + ' / ' + mode, file=sys.stderr, flush=True)
    with tempfile.TemporaryDirectory(prefix='lab-benchmark-', dir=scratch) as folder:
        path = Path(folder) / 'private.sqlite3'
        with CountingJournal(path, mode == 'full') as journal:
            flow = Workflow.create(journal, run_id=run_id)
            definition = flow.state['definition']
            checks_before = journal.full_checks
            started = time.perf_counter()
            run_demo(flow, transport=transport)
            runtime = time.perf_counter() - started
            checks_during_run = journal.full_checks - checks_before
            state, revision = journal.get_current(run_id)
            largest_state = len(encoded(state).encode())
            started = time.perf_counter()
            journal.get_current(run_id, verify=True)
            full_audit_runtime = time.perf_counter() - started
            started = time.perf_counter()
            report = flow.report()
            report_runtime = time.perf_counter() - started
            assert report['passed'] and report['order_restored'] and not journal.owners()
            assert len(report['samples']) == 12 and len(report['bookings']) == 24
            assert all(record['outcome'] == 'performed' for record in report['bookings'].values())
            for sample in report['samples'].values():
                expected = sample['initial_volume_ul']
                if expected is not None:
                    expected -= sum(definition['stages'][stage]['profile']['parameters']['sample_volume_ul']
                                    for stage in ['nanodrop', 'qubit'])
                    assert math.isclose(sample['remaining_volume_ul'], expected, rel_tol=0, abs_tol=1e-9)
                else:
                    assert sample['remaining_volume_ul'] is None
            assert all(v['location']['kind'] == 'discarded'
                       for v in state['inventory']['vessels'].values() if v['origin'] != 'original')
            document_bytes, maximum_event_bytes = journal.connection.execute(
                'SELECT SUM(length(CAST(document AS BLOB))), MAX(length(CAST(document AS BLOB))) FROM events'
            ).fetchone()
            artifact_bytes = journal.connection.execute(
                'SELECT COALESCE(SUM(length(content)), 0) FROM artifacts').fetchone()[0]
            integrity = journal.connection.execute('PRAGMA integrity_check').fetchone()[0]
            assert integrity == 'ok'
            flow.close()
        result = {'transport': transport, 'read_mode': mode,
                  'root_runtime_seconds': runtime, 'stored_events': revision,
                  'durable_appends': journal.append_count,
                  'full_chain_checks_during_run': checks_during_run,
                  'independent_full_audit_seconds': full_audit_runtime,
                  'report_seconds': report_runtime, 'database_bytes': path.stat().st_size,
                  'event_document_bytes': document_bytes, 'artifact_bytes': artifact_bytes,
                  'largest_event_document_bytes': maximum_event_bytes,
                  'final_state_document_bytes': largest_state,
                  'root_state_fields': sorted(state),
                  'stage_state_fields': {key: sorted(value) for key, value in state['stages'].items()},
                  'original_samples': len(report['samples']),
                  'vessels': len(state['inventory']['vessels']), 'bookings': len(report['bookings']),
                  'manual_measurements': {key: len(state['stages'][key]['measurements'])
                                          for key in ['nanodrop', 'qubit']},
                  'logical_time_s': report['logical_time_s'],
                  'embedded_cf01_trace': 'trace' in (state['stages']['cf01']['view'] or {}),
                  'sqlite_integrity': integrity, 'sources_changed': hashes_match(definition['source_files_sha256']),
                  'source_files_sha256': definition['source_files_sha256'],
                  'passed': True}
        result['passed'] = not result['sources_changed']
        print(json.dumps({key: result[key] for key in [
            'transport', 'read_mode', 'root_runtime_seconds', 'stored_events',
            'database_bytes', 'sources_changed']}), file=sys.stderr, flush=True)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['cached', 'full', 'all'], default='cached',
                        help='Normal workflow by default; full/all audits each append and can take minutes')
    parser.add_argument('--transport', choices=['ros2', 'sila2', 'all'], default='all')
    parser.add_argument('--out', type=Path, help='Optional JSON result inside project exports/')
    args = parser.parse_args()
    target = output_path(args.out) if args.out else None
    modes = ['cached', 'full'] if args.mode == 'all' else [args.mode]
    transports = ['ros2', 'sila2'] if args.transport == 'all' else [args.transport]
    cases = [measure(transport, mode) for transport in transports for mode in modes]
    source_versions_agree = all(case['source_files_sha256'] == cases[0]['source_files_sha256'] for case in cases)
    report = {'format': 'solidcraftbot.lab-workflow-benchmark/1',
              'created_at_utc': datetime.now(timezone.utc).isoformat(),
              'python': platform.python_version(), 'sqlite': sqlite3.sqlite_version,
              'comparison': 'Same workflow and journal; normal verified prefix versus full audit before each append',
              'no_timing_pass_threshold': True, 'temporary_stores_removed': True,
              'source_versions_agree': source_versions_agree,
              'limits': 'Synthetic inputs and local decoders only; no network, hardware, or new CAD validation',
              'benchmark_script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'cases': cases, 'passed': source_versions_agree and all(case['passed'] for case in cases)}
    if target:
        target.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
