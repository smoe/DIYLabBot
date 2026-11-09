"""Measure current journal APIs with representative synthetic JSON snapshots.

This is a persistence benchmark, not an executed laboratory workflow. Snapshots
contain 12 original vessels, 12 assay vessels, 2 standards, 3 stage contexts and
24 completed withdrawal records. No growing trace is embedded in each state.
Both modes use the SAME current append implementation; the comparison measures
full state verification per transition versus opt-in verified-prefix reads. It
does not reconstruct or claim timings for an earlier implementation. Results are
observations, with no timing-based pass threshold. Temporary databases are removed.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import sqlite3
import tempfile
import time

from manual_tasks import Journal

ROOT = Path(__file__).resolve().parents[1]


class CountingJournal(Journal):
    full_checks = 0

    def history(self, run_id):
        self.full_checks += 1
        return super().history(run_id)


def representative_state():
    originals = {
        'Tube%02d' % i: {
            'id': 'Tube%02d' % i, 'sample_id': 'Sample%02d' % i,
            'home': {'rack_instance_id': 'Rack', 'place_id': 'Slot%02d' % i},
            'location': {'kind': 'rack', 'instance_id': 'Rack', 'place_id': 'Slot%02d' % i},
            'initial_volume_ul': 40, 'remaining_volume_ul': 36.5,
            'volume_uncertain': False, 'mass_confirmation_valid': False}
        for i in range(1, 13)}
    derived = {
        'AssayTube%02d' % i: {
            'id': 'AssayTube%02d' % i, 'source_sample_id': 'Sample%02d' % i,
            'preparation_id': 'QB.P%02d' % i, 'sample_volume_ul': 2,
            'assay_total_volume_ul': 100, 'location': {'kind': 'discarded'},
            'disposition_confirmation': {'actor_id': 'SYN.Operator', 'reason': 'Synthetic disposal'}}
        for i in range(1, 13)}
    derived.update({
        'StandardTube%02d' % i: {
            'id': 'StandardTube%02d' % i, 'standard_id': 'SYN.Standard%02d' % i,
            'location': {'kind': 'discarded'},
            'disposition_confirmation': {'actor_id': 'SYN.Operator', 'reason': 'Synthetic disposal'}}
        for i in range(1, 3)})
    withdrawals = {
        '%s.W%02d' % (stage, i): {
            'id': '%s.W%02d' % (stage, i), 'intent_id': '%s.I%02d' % (stage, i),
            'stage_id': stage, 'sample_id': 'Sample%02d' % i,
            'source_vessel_id': 'Tube%02d' % i,
            'destination': {'kind': 'discarded_aliquot'} if stage == 'ND' else
                           {'kind': 'assay_vessel', 'vessel_id': 'AssayTube%02d' % i},
            'actual_volume_ul': volume, 'status': 'confirmed', 'evidence': 'synthetic_input'}
        for stage, volume in [('ND', 1.5), ('QB', 2)] for i in range(1, 13)}
    stages = {
        'CF01': {'status': 'synthetic_progress', 'job_id': 'SYN.CF01.Job',
                 'station': {'indexed_slot': 1, 'standstill_confirmed': True,
                             'parking_brake_held': True, 'hardware_qualified': False},
                 'slots': {str(i): {'present': False, 'seated': False, 'mass_g': None}
                           for i in range(1, 13)}, 'pending_handoff': None},
        'ND': {'status': 'synthetic_progress', 'blank_id': 'SYN.ND.Blank',
               'measurements': {'ND.M%02d' % i: {'sample_id': 'Sample%02d' % i,
                   'withdrawal_id': 'ND.W%02d' % i, 'value_ng_ul': i, 'basis': 'reported'}
                   for i in range(1, 13)}},
        'QB': {'status': 'synthetic_progress', 'calibration_id': 'SYN.QB.Calibration',
               'standard_measurements': {'SYN.Standard%02d' % i: 'QB.StandardM%02d' % i
                                         for i in range(1, 3)},
               'measurements': {'QB.M%02d' % i: {'sample_id': 'Sample%02d' % i,
                   'preparation_id': 'QB.P%02d' % i, 'vessel_id': 'AssayTube%02d' % i,
                   'withdrawal_id': 'QB.W%02d' % i, 'value_ng_ul': i,
                   'basis': 'derived', 'binding_source': 'workflow_record'}
                   for i in range(1, 13)}}}
    return {'format': 'solidcraftbot.journal-benchmark-state/1', 'synthetic_only': True,
            'resources': ['rack:Rack', 'workspace:Bench', 'arm:Arm', 'instrument:CF01',
                          'instrument:NanoDrop', 'instrument:Qubit4'] +
                         ['vessel:' + key for key in [*originals, *derived]],
            'iteration': 0, 'logical_time_s': 0, 'vessels': {**originals, **derived},
            'withdrawals': withdrawals, 'stages': stages}


def measure(folder, events, full_verification):
    path = folder / ('full.sqlite3' if full_verification else 'cached.sqlite3')
    with CountingJournal(path, clock=lambda: 0.0) as journal:
        journal.create('SYN.Benchmark', representative_state())
        started = time.perf_counter()
        for index in range(1, events + 1):
            state, revision = (journal.state('SYN.Benchmark') if full_verification else
                               journal.get_current('SYN.Benchmark'))
            state['iteration'] = index
            state['logical_time_s'] = index * 0.25
            journal.append('SYN.Benchmark', revision, 'synthetic_transition',
                           {'operation_id': 'SYN.Operation%06d' % index}, state)
        elapsed = time.perf_counter() - started
        checks_during_transitions = journal.full_checks
        started = time.perf_counter()
        history = journal.history('SYN.Benchmark')
        audit_elapsed = time.perf_counter() - started
        assert len(history) == events + 1 and history[-1]['state']['iteration'] == events
        integrity = journal.connection.execute('PRAGMA integrity_check').fetchone()[0]
        assert integrity == 'ok'
        document_bytes, maximum = journal.connection.execute(
            'SELECT SUM(length(CAST(document AS BLOB))), MAX(length(CAST(document AS BLOB))) '
            'FROM events').fetchone()
    return {'read_mode': 'full_verification_per_transition' if full_verification else 'verified_prefix',
            'appended_events': events, 'stored_events': events + 1,
            'transition_seconds': elapsed, 'full_chain_checks_during_transitions': checks_during_transitions,
            'final_full_audit_seconds': audit_elapsed, 'database_bytes': path.stat().st_size,
            'event_document_bytes': document_bytes, 'largest_event_document_bytes': maximum,
            'sqlite_integrity': integrity, 'passed': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--events', type=int, default=400)
    parser.add_argument('--out', type=Path, help='Optional JSON result inside project exports/')
    args = parser.parse_args()
    if args.events < 1:
        parser.error('--events must be positive')
    if args.out and not args.out.resolve().is_relative_to((ROOT / 'exports').resolve()):
        parser.error('--out must be inside project exports/')
    scratch = ROOT / 'exports/manual-workflows'
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='journal-benchmark-', dir=scratch) as folder:
        cases = [measure(Path(folder), args.events, full) for full in [True, False]]
    report = {'format': 'solidcraftbot.manual-journal-benchmark/1',
              'created_at_utc': datetime.now(timezone.utc).isoformat(),
              'python': platform.python_version(), 'sqlite': sqlite3.sqlite_version,
              'snapshot': {'original_vessels': 12, 'assay_vessels': 12, 'standard_vessels': 2,
                           'stage_contexts': 3, 'confirmed_withdrawals': 24, 'embedded_trace': False},
              'comparison': 'Same current append API; full state audits versus verified-prefix reads',
              'no_timing_pass_threshold': True, 'temporary_databases_removed': True,
              'source_files_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                      for p in [Path(__file__), ROOT / 'scripts/manual_tasks.py']},
              'cases': cases, 'passed': all(case['passed'] for case in cases)}
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
