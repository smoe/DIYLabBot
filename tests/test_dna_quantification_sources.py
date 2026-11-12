"""The leading DNA recipe pins inputs and validates its bounded HS target."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import dna_quantification_sources as sources
from dna_quantification import Workflow
from manual_tasks import Journal, TaskError, digest, encoded


class DnaQuantificationSourcesTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'exports').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='dna-source-test-', dir=ROOT / 'exports')
        self.folder = Path(self.temp.name)
        self.profile = json.loads(sources.SOURCE.read_text(encoding='utf-8'))
        self.protocol_text = (ROOT / self.profile['protocol']['source']).read_text(encoding='utf-8')
        self.protocol = json.loads(self.protocol_text)
        self.counter = 0

    def tearDown(self):
        self.temp.cleanup()

    def profile_file(self, value=None):
        self.counter += 1
        path = self.folder / ('profile-%02d.json' % self.counter)
        path.write_text(json.dumps(self.profile if value is None else value), encoding='utf-8')
        return path

    def load_changed_profile(self, change):
        profile = copy.deepcopy(self.profile)
        change(profile)
        return sources.load(self.profile_file(profile))

    def load_protocol(self, protocol):
        # Keep actual pinned model bytes untouched; replace only this decoder's
        # return for the leading protocol, leaving nested device loaders intact.
        def decode(raw):
            return copy.deepcopy(protocol) if raw == self.protocol_text else json.loads(raw)
        with patch.object(sources, 'json', SimpleNamespace(loads=decode)):
            return sources.load(self.profile_file())

    def test_baseline_binds_every_source_and_runtime_file_by_current_checksum(self):
        definition = sources.load()
        hashes = definition['source_files_sha256']
        self.assertEqual(definition['source_path'], str(sources.SOURCE.relative_to(ROOT)))
        self.assertEqual(definition['clock_mode'], 'synthetic_events/1')
        for relative, checksum in hashes.items():
            self.assertEqual(digest((ROOT / relative).read_bytes()), checksum, relative)
        for name in sources.RUNTIME:
            self.assertIn('scripts/' + name, hashes)
        for relative in ['model/dna-quantification.synthetic.json', 'model/dna-quantification.protocol.json',
                         'model/dna-quantification.schema.json', 'model/guided-tube-rack.shared.json']:
            self.assertIn(relative, hashes)

    def test_hs_context_is_derived_at_200ul_without_changing_standalone_100ul_fixture(self):
        standalone = ROOT / self.profile['device_profiles']['qubit']['source']
        before = standalone.read_bytes()
        fixture = json.loads(before)
        self.assertEqual(fixture['parameters']['assay_total_volume_ul'], 100)
        definition = sources.load()
        qubit = definition['devices']['qubit']
        params = qubit['profile']['parameters']
        self.assertEqual(params['assay_total_volume_ul'], 200)
        self.assertEqual(params['standard_volume_ul'], 10)
        self.assertEqual(params['sample_volume_ul'], 2)
        self.assertEqual(params['incubation_min_s'], 120)
        self.assertEqual(qubit['protocol']['assay']['id'], 'SYN.DNA.HS')
        self.assertEqual(definition['protocol']['assays']['qubit']['id'], 'Qubit.dsDNA.HS')
        self.assertEqual(qubit['effective_profile_sha256'], digest(encoded(qubit['profile']).encode()))
        self.assertEqual(standalone.read_bytes(), before)

    def test_duplicate_sample_vessel_and_slot_are_each_rejected(self):
        for duplicate in ['id', 'vessel_id', 'rack_slot']:
            with self.subTest(duplicate=duplicate):
                def change(profile):
                    second = dict(profile['samples'][0], id='DNA02', vessel_id='SYN.DNA.Tube02', rack_slot=2)
                    second[duplicate] = profile['samples'][0][duplicate]
                    profile['samples'].append(second)
                with self.assertRaisesRegex(TaskError, 'Duplicate DNA manifest ' + duplicate):
                    self.load_changed_profile(change)

    def test_rack_sample_count_and_slot_contract_are_bounded(self):
        variants = [[], [dict(self.profile['samples'][0], id='DNA%02d' % i,
                             vessel_id='Tube%02d' % i, rack_slot=i) for i in range(1, 14)]]
        for samples in variants:
            with self.subTest(count=len(samples)), self.assertRaises(TaskError):
                self.load_changed_profile(lambda p: p.update(samples=samples))
        for slot in [0, 13, 1.0, True, '1']:
            with self.subTest(slot=slot), self.assertRaisesRegex(TaskError, 'Unknown original rack slot'):
                self.load_changed_profile(lambda p: p['samples'][0].update(rack_slot=slot))

    def test_nonfinite_or_negative_initial_volume_is_rejected(self):
        for value in [float('nan'), float('inf'), -float('inf'), -1, True, '40']:
            with self.subTest(value=value), self.assertRaisesRegex(TaskError, 'initial sample volume'):
                self.load_changed_profile(lambda p: p['samples'][0].update(initial_volume_ul=value))

    def test_unknown_initial_volume_stays_unknown_in_the_canonical_inventory(self):
        profile = copy.deepcopy(self.profile)
        profile['samples'][0]['initial_volume_ul'] = None
        source = self.profile_file(profile)
        self.assertIsNone(sources.load(source)['profile']['samples'][0]['initial_volume_ul'])
        with Journal(self.folder / 'unknown.sqlite3') as journal:
            flow = Workflow.create(journal, source=source, run_id='SYN.DNA.UNKNOWN')
            vessel = flow.report()['inventory']['vessels']['SYN.DNA.Tube01']
            self.assertIsNone(vessel['initial_volume_ul'])
            self.assertIsNone(vessel['remaining_volume_ul'])

    def test_nonfinite_and_nonpositive_parameters_are_rejected(self):
        for name in self.profile['parameters']:
            for value in [float('nan'), float('inf'), -1, 0, True, '2']:
                with self.subTest(name=name, value=value), self.assertRaisesRegex(TaskError, name):
                    self.load_changed_profile(lambda p: p['parameters'].update({name: value}))

    def test_device_volume_limits_and_calibration_window_are_enforced(self):
        variants = [('nanodrop_sample_volume_ul', 0.9), ('qubit_sample_volume_ul', 0.9),
                    ('qubit_sample_volume_ul', 20.1), ('synthetic_calibration_validity_s', 120)]
        for name, value in variants:
            with self.subTest(name=name, value=value), self.assertRaises(TaskError):
                self.load_changed_profile(lambda p: p['parameters'].update({name: value}))

    def test_source_pin_mismatch_is_rejected_before_runtime(self):
        for field in ['protocol', 'nanodrop', 'qubit', 'rack']:
            def change(profile):
                target = (profile['device_profiles'][field] if field in {'nanodrop', 'qubit'} else
                          profile['rack']['definition'] if field == 'rack' else profile['protocol'])
                target['source_sha256'] = '0' * 64
            with self.subTest(field=field), self.assertRaisesRegex(TaskError, 'Changed DNA source'):
                self.load_changed_profile(change)

    def test_unsupported_mode_assumptions_and_rack_binding_are_rejected(self):
        changes = [lambda p: p.update(mode='hardware'),
                   lambda p: p['assumptions'].update(new_dilutions_from_original_only=False),
                   lambda p: p['assumptions'].update(return_policy='any_empty_slot'),
                   lambda p: p['assumptions'].update(input_rack_delivered_on_table=False),
                   lambda p: p['dilution_rack'].update(id=p['rack']['id']),
                   lambda p: p['rack']['definition'].update(source='model/dna-quantification.protocol.json',
                           source_sha256=p['protocol']['source_sha256'])]
        for index, change in enumerate(changes):
            with self.subTest(variant=index), self.assertRaises(TaskError):
                self.load_changed_profile(change)

    def test_one_target_cannot_silently_use_ultrac_bounds_or_another_table(self):
        original = sources.nanodrop_manual.load_profile
        def altered(path, instrument='nanodrop_ultrac', frame=None):
            definition = original(path)
            definition['profile']['instrument']['type'] = instrument
            if frame is not None:
                definition['profile']['workspace']['frame'] = frame
            return definition
        with patch.object(sources.nanodrop_manual, 'load_profile', side_effect=altered):
            with self.assertRaisesRegex(TaskError, 'NanoDrop One pedestal'):
                sources.load()
        with patch.object(sources.nanodrop_manual, 'load_profile',
                          side_effect=lambda path: altered(path, 'nanodrop_one_wifi', 'OTHER.Table')):
            with self.assertRaisesRegex(TaskError, 'same declared table frame'):
                sources.load()

    def test_malformed_protocol_shapes_are_rejected(self):
        variants = [None, [], dict(self.protocol, assays=[]), dict(self.protocol, dilution_presets=None)]
        bad_target = copy.deepcopy(self.protocol)
        bad_target['assays']['nanodrop']['range'] = []
        variants.append(bad_target)
        for device in ['nanodrop', 'qubit']:
            bad_reference = copy.deepcopy(self.protocol)
            bad_reference['assays'][device]['reference'] = None
            variants.append(bad_reference)
        for index, protocol in enumerate(variants):
            with self.subTest(variant=index), self.assertRaises(TaskError):
                self.load_protocol(protocol)

    def test_nonfinite_bounds_and_unsupported_units_are_rejected(self):
        for device in ['nanodrop', 'qubit']:
            for field, value in [('lower', float('nan')), ('upper', float('inf')),
                                 ('lower', -1), ('upper', 0), ('unit', 'ug/mL')]:
                protocol = copy.deepcopy(self.protocol)
                protocol['assays'][device]['range'][field] = value
                with self.subTest(device=device, field=field, value=value), self.assertRaises(TaskError):
                    self.load_protocol(protocol)

    def test_inconsistent_target_range_and_volume_contract_are_rejected(self):
        variants = []
        for device in ['nanodrop', 'qubit']:
            protocol = copy.deepcopy(self.protocol)
            protocol['assays'][device]['range']['lower'] = protocol['assays'][device]['range']['upper']
            variants.append(protocol)
        for field, value in [('sample_volume_ul_max', 200), ('standard_volume_ul', 200),
                             ('assay_total_volume_ul', 100), ('incubation_min_s', float('inf'))]:
            protocol = copy.deepcopy(self.protocol)
            protocol['assays']['qubit'][field] = value
            variants.append(protocol)
        for index, protocol in enumerate(variants):
            with self.subTest(variant=index), self.assertRaises(TaskError):
                self.load_protocol(protocol)


if __name__ == '__main__':
    unittest.main()
