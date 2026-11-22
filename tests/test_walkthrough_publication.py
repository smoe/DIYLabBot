"""A correct HTML hash alone must not allow an obsolete Pages snapshot."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import check_walkthrough_publication as publication


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.program = {key: [] for key in ('objects', 'interaction', 'stops', 'levels', 'settings', 'rendering', 'hidden_body_ids')}
        self.program['objects'] = [{'id': 'Kitchen1008.Microwave.Door', 'moving_body_ids': ['Door', 'Window', 'Handle']}]
        self.program['source_files_sha256'] = {'model/current.json': 'a'*64}
        self.payload = copy.deepcopy(self.program)
        for name in ('scripts/build_building_walkthrough.py', 'scripts/export_building_walkthrough_freecad.py',
                     'scripts/walkthrough_world.py', 'scripts/building_walkthrough_viewer.html',
                     'scripts/walkthrough_interaction.js'):
            self.payload['source_files_sha256'][name] = hashlib.sha256((publication.ROOT/name).read_bytes()).hexdigest()
        self.payload['scenes'] = {'building': {'groups': [{'id': 'Computer_MonitorScreen'}, {'id': 'Door'}]}}

    def verify(self, payload, mutate_manifest=None):
        html = ('<script id="walkthrough-data" type="application/json">'+json.dumps(payload)+'</script>').encode()
        manifest = {'html': {'sha256': hashlib.sha256(html).hexdigest(), 'bytes': len(html)},
                    'source_files_sha256': copy.deepcopy(payload['source_files_sha256'])}
        if mutate_manifest:
            mutate_manifest(manifest)
        return publication.check(html, manifest, self.program, {'Computer_MonitorScreen', 'Door'})

    def test_current_snapshot_passes(self):
        self.assertTrue(self.verify(self.payload)['passed'])

    def test_old_or_missing_interaction_is_rejected_even_with_valid_html_hash(self):
        for objects in ([], [{'id': 'Kitchen1008.Fridge.Door'}]):
            payload = copy.deepcopy(self.payload); payload['objects'] = objects
            with self.subTest(objects=objects), self.assertRaisesRegex(ValueError, 'objects'):
                self.verify(payload)

    def test_missing_equipment_or_duplicate_body_is_rejected(self):
        for groups in ([{'id': 'Door'}], [{'id': 'Door'}, {'id': 'Door'}]):
            payload = copy.deepcopy(self.payload); payload['scenes']['building']['groups'] = groups
            with self.subTest(groups=groups), self.assertRaisesRegex(ValueError, 'body coverage'):
                self.verify(payload)

    def test_old_source_or_renderer_is_rejected(self):
        for name in ('model/current.json', 'scripts/walkthrough_interaction.js'):
            payload = copy.deepcopy(self.payload); payload['source_files_sha256'][name] = '0'*64
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'Stale published source'):
                self.verify(payload)

    def test_manifest_tampering_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'checksum'):
            self.verify(self.payload, lambda m: m['html'].update(sha256='0'*64))
        with self.assertRaisesRegex(ValueError, 'manifest'):
            self.verify(self.payload, lambda m: m['source_files_sha256'].update({'model/current.json': '0'*64}))

    def test_scene_contracts_cannot_drift_behind_valid_geometry(self):
        for key in ('robots', 'laboratories', 'equipment_source', 'elevator', 'places', 'topology', 'room_signs'):
            self.program[key] = {'current': key}
            payload = copy.deepcopy(self.payload)
            payload[key] = {'obsolete': key}
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, key):
                self.verify(payload)
            self.program.pop(key)

    def test_camera_wall_and_renderer_pins_are_required(self):
        self.program['camera_wall'] = {'monitors': [{'id': 'FoyerMonitor1'}]}
        payload = copy.deepcopy(self.payload)
        payload['camera_wall'] = copy.deepcopy(self.program['camera_wall'])
        for name in ('scripts/camera_monitor_wall.js', 'scripts/monitor_frustum.js'):
            payload['source_files_sha256'][name] = hashlib.sha256((publication.ROOT/name).read_bytes()).hexdigest()
        self.assertTrue(self.verify(payload)['passed'])

        for replacement in (None, {'monitors': []}):
            stale = copy.deepcopy(payload)
            if replacement is None:
                stale.pop('camera_wall')
            else:
                stale['camera_wall'] = replacement
            with self.subTest(camera_wall=replacement), self.assertRaisesRegex(ValueError, 'camera_wall'):
                self.verify(stale)

        for name in ('scripts/camera_monitor_wall.js', 'scripts/monitor_frustum.js'):
            stale = copy.deepcopy(payload)
            stale['source_files_sha256'].pop(name)
            with self.subTest(source=name), self.assertRaisesRegex(ValueError, 'Stale published source'):
                self.verify(stale)
            with self.subTest(manifest=name), self.assertRaisesRegex(ValueError, 'Stale publication manifest'):
                self.verify(payload, lambda manifest: manifest['source_files_sha256'].pop(name))

    def test_checked_browser_equipment_and_functional_supports_extend_native_coverage(self):
        from unittest.mock import patch
        program = {'laboratories': [{'id': 'Lab'}],
                   'equipment_source': {'build_report': 'fixture.json', 'source_sha256': 'a'*64}}
        report = {'source_sha256': 'a'*64, 'layout_validation': {
            'scene_geometry': [{'body': 'Arm__Housing'}, {'body': 'MountArm__Frame'}, {'body': 'People_study'}],
            'instance_metrics': {'Arm': {'body_count': 1}, 'MountArm': {'body_count': 1}}}}
        bindings = [({}, {'id': 'Arm', 'body_prefix': 'Lab_Arm_'}),
                    ({}, {'id': 'MountArm', 'body_prefix': 'Lab_MountArm_'})]
        with patch.object(publication.native_mesh, 'checked_report', return_value=report), \
                patch.object(publication.native_mesh, 'native_equipment_bindings', return_value=bindings):
            self.assertEqual(publication.required_body_ids(program, {'Wall'}),
                             {'Wall', 'Lab_Arm_Housing', 'Lab_MountArm_Frame'})
            report['layout_validation']['instance_metrics']['Arm']['body_count'] = 2
            with self.assertRaisesRegex(ValueError, 'Incomplete'):
                publication.required_body_ids(program, {'Wall'})


if __name__ == '__main__':
    unittest.main()
