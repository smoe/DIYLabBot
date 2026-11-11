"""DNA-Proben synthetisch nacheinander mit NanoDrop und Qubit HS messen."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

from dna_quantification_demo import PRESETS, SyntheticBackend, run_synthetic
from manual_tasks import Journal, TaskError
from manual_workflow import resolve_store
from manual_workflow_cli import output_path


def card(flow):
    state = flow.state
    return {'run_id': flow.run_id, 'mode': 'synthetic_only', 'status': state['status'],
            'current_sample_id': state.get('current_sample_id'),
            'active_attempt_id': state.get('active_attempt_id'),
            'active_context_id': state.get('active_context_id'),
            'pending_dilution': state.get('pending_dilution'),
            'recovery_required': state.get('recovery_required'),
            'logical_time_s': state.get('logical_time_s'),
            'rack_on_table': state.get('rack_ready'),
            'offered_dilutions': flow.options(state.get('current_sample_id'))
                if state.get('current_sample_id') is not None else [],
            'samples': state['samples'],
            'attempts': {identity: {key: attempt.get(key) for key in
                ['sample_id', 'input_vessel_id', 'preset', 'external_factor', 'status', 'evaluations']}
                for identity, attempt in state.get('attempts', {}).items()},
            'resources': state.get('resources', [])}


def parser():
    result = argparse.ArgumentParser(description=__doc__,
        epilog='1+9 = Faktor 10; 1+19 = Faktor 20. Ausschließlich synthetische Abläufe, keine Geräteansteuerung.')
    result.add_argument('--store', type=Path,
        help='Gemeinsamer Laufzeit-Store unter exports/; vorhandenen Standard-Store wiederverwenden')
    result.add_argument('--actor', default='SYN.DNA.Operator01', help='Kennung für explizite synthetische Eingaben')
    commands = result.add_subparsers(dest='command', required=True)
    for name, help_text in [('create', 'DNA-Lauf ohne Messausführung anlegen'),
                            ('demo', 'Vollständig synthetischen automatischen Ablauf ausführen')]:
        child = commands.add_parser(name, help=help_text)
        child.add_argument('--profile', type=Path)
        child.add_argument('--run-id')
    for name in ['demo', 'run']:
        child = commands.add_parser(name, help='Vorhandenen Lauf ausdrücklich synthetisch fortführen') if name == 'run' else commands.choices[name]
        if name == 'run':
            child.add_argument('run_id')
            child.add_argument('--simulation', action='store_true', required=True,
                               help='Erforderlich: ausschließlich synthetische Beobachtungen und Daten erzeugen')
            child.add_argument('--resume', action='store_true', help='Unterbrochene Sitzung übernehmen; expliziter Abgleich bleibt erforderlich')
            child.add_argument('--reconcile-input', type=Path,
                               help='Explizite Abgleichdaten im selben Prozess vor der Fortsetzung anwenden')
        child.add_argument('--dilution', choices=PRESETS, default='none',
                           help='Vorverdünnung: none = unverdünnt; 1+9 = Faktor 10; 1+19 = Faktor 20')
        child.add_argument('--after-range', choices=PRESETS,
                           help='Angebotenen Wiederholungsansatz einmal wählen; none = unverdünnt, ohne Option anhalten')
        child.add_argument('--nanodrop-concentration', type=float, default=50,
                           help='Fiktive ursprüngliche NanoDrop-Konzentration in ng/µl')
        child.add_argument('--qubit-concentration', type=float, default=48,
                           help='Unabhängige fiktive ursprüngliche Qubit-Konzentration in ng/µl')
        child.add_argument('--qubit-reported-original', action='store_true',
                           help='Synthetischen Qubit-Bericht mit bereits assaykorrigiertem Eingangswert erzeugen')
        child.add_argument('--pause-after', choices=['dilution_intent', 'measurement_intent'],
                           help='Nach dauerhaft gespeicherter Absicht unterbrechen')
    for name in ['status', 'report', 'choose-dilution', 'reconcile', 'accept-result',
                 'dispose-material', 'complete', 'cancel', 'finish-cancel']:
        child = commands.add_parser(name)
        child.add_argument('run_id')
        if name == 'report':
            child.add_argument('--out', type=Path, help='Bericht zusätzlich unter exports/ speichern')
        if name not in {'status', 'report'}:
            child.add_argument('--resume', action='store_true')
            if name != 'reconcile':
                child.add_argument('--reconcile-input', type=Path,
                                   help='Explizite Abgleichdaten vor diesem Befehl anwenden')
        if name == 'choose-dilution':
            child.add_argument('preset', choices=PRESETS)
            child.add_argument('--sample-id', help='Sonst die aktuelle Probe verwenden')
        if name in {'reconcile', 'complete', 'finish-cancel'}:
            child.add_argument('--input', required=True, type=Path,
                               help='JSON mit ausdrücklich beobachtetem Inventar und Absichtsabgleich')
        if name == 'accept-result':
            child.add_argument('--sample-id', help='Sonst die aktuelle Probe verwenden')
            child.add_argument('--allow-unquantified', action='store_true',
                               help='Bereichsverletzte/ungeklärte Werte ausdrücklich ohne Quantifizierungsfreigabe behalten')
            child.add_argument('--reason', required=True, help='Begründung der ausdrücklichen Ergebnisbewertung')
        if name == 'dispose-material':
            child.add_argument('vessel_id')
            child.add_argument('--observed-vessel-id', required=True)
            child.add_argument('--reason', required=True)
        if name == 'cancel':
            child.add_argument('--reason', required=True)
    return result


def observation_input(path):
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or not {'observations', 'workspace_clear'} <= set(data):
        raise TaskError('JSON mit ausdrücklichen observations und workspace_clear ist erforderlich')
    return data


def main(argv=None):
    args = parser().parse_args(argv)
    # Import after argument validation: invalid real/unspecified execution modes
    # cannot create a journal or manufacture confirmations.
    from dna_quantification import Workflow
    flow = None
    try:
        backend = None
        if args.command in {'demo', 'run'}:
            backend = SyntheticBackend({'nanodrop': args.nanodrop_concentration,
                                        'qubit': args.qubit_concentration},
                                       qubit_report_original=args.qubit_reported_original,
                                       actor_id=args.actor)
        with Journal(output_path(resolve_store(args.store))) as journal:
            try:
                if args.command in {'create', 'demo'}:
                    flow = Workflow.create(journal, source=args.profile, run_id=args.run_id)
                elif args.command in {'status', 'report'}:
                    flow = Workflow(journal, args.run_id, None)
                else:
                    flow = Workflow.open(journal, args.run_id, resume=args.resume)
                if getattr(args, 'reconcile_input', None) is not None:
                    flow.reconcile(args.actor, **observation_input(args.reconcile_input))
                if args.command in {'demo', 'run'}:
                    run_synthetic(flow, args.dilution, args.after_range, backend, args.pause_after)
                elif args.command == 'choose-dilution':
                    flow.choose_dilution(args.actor, args.sample_id or flow.state['current_sample_id'], args.preset)
                elif args.command == 'reconcile':
                    flow.reconcile(args.actor, **observation_input(args.input))
                elif args.command == 'accept-result':
                    flow.accept_result(args.actor, args.sample_id or flow.state['current_sample_id'],
                                       allow_unquantified=args.allow_unquantified, reason=args.reason)
                elif args.command == 'dispose-material':
                    flow.dispose_material(args.actor, args.vessel_id,
                        observed_vessel_id=args.observed_vessel_id, reason=args.reason)
                elif args.command == 'complete':
                    flow.complete(args.actor, **observation_input(args.input))
                elif args.command == 'cancel':
                    flow.cancel(args.actor, args.reason)
                elif args.command == 'finish-cancel':
                    flow.finish_cancel(args.actor, **observation_input(args.input))
                if args.command == 'report':
                    report = flow.report()
                    if args.out is not None:
                        output_path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
                    print(json.dumps(report, ensure_ascii=False))
                else:
                    print(json.dumps(card(flow), ensure_ascii=False))
            finally:
                if flow is not None and args.command not in {'status', 'report'}:
                    flow.close()
    except (TaskError, ValueError, KeyError, TypeError, OSError, sqlite3.Error) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
