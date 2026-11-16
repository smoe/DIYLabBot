"""Standard native probe admission for the source-derived stair guards."""
import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import build_building_stack as build
import building_stack as model


class StairwellRailingBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = model.load()
        cls.parameters = model.parameters(cls.spec)
        cls.contract = model.interfaces(cls.spec, cls.parameters)
        legacy = copy.deepcopy(cls.spec)
        legacy['circulation']['stairs'].pop('guard_profile_ref')
        for instance in legacy['circulation']['stairs']['instances']:
            instance.pop('top_guard_wall', None)
        cls.legacy = model.interfaces(legacy, cls.parameters)

    def reject(self, change):
        contract = copy.deepcopy(self.contract)
        change(contract['circulation'])
        with self.assertRaises(ValueError):
            build.circulation_probe_specs(contract)

    def test_regular_probe_admission_includes_all_41_attachments_and_16_clearances(self):
        result = build.circulation_probe_specs(self.contract)
        attachments = [item for item in result if item['category'] == 'stair_guard_attachment']
        clearances = [item for item in result if item['category'] == 'stair_guard_clearance']
        self.assertEqual(len(attachments), 41)
        self.assertEqual(len(clearances), 16)
        self.assertEqual(len(result), len(build.circulation_probe_specs(self.legacy))+57)
        self.assertEqual(len(result), len({item['probe']['id'] for item in result}))
        guard_ids = set(self.contract['circulation']['guard_body_ids'])
        for item in attachments:
            volume = build.prism_volume(item['probe'])
            self.assertGreater(volume, 0)
            self.assertEqual(item['probe']['expectation'], 'filled')
            self.assertEqual(set(item['expected']), set(item['probe']['target_bodies']))
            for value in item['expected'].values():
                self.assertAlmostEqual(value, volume, delta=max(1e-5, volume*1e-9))
        for item in clearances:
            self.assertEqual(item['probe']['expectation'], 'empty')
            self.assertEqual(item['expected'], {name: 0. for name in guard_ids})
            self.assertEqual(item['probe']['scope'], 'new_guard_members_only')

    def test_guard_body_group_and_post_manifests_are_complete_and_unique(self):
        for change in (
            lambda c: c['guard_body_ids'].pop(),
            lambda c: c['guard_body_ids'].append(c['guard_body_ids'][0]),
            lambda c: c['guard_groups'].pop(),
            lambda c: c['guard_groups'].append(copy.deepcopy(c['guard_groups'][0])),
            lambda c: c['guard_groups'][0]['body_ids'].append('UndeclaredGuard'),
            lambda c: c['guard_groups'][0]['post_body_ids'].pop(),
            lambda c: c['guard_posts'].pop(),
            lambda c: c['guard_posts'].append(copy.deepcopy(c['guard_posts'][0])),
            lambda c: c['guard_posts'][0].update(body_id='NotAGuardPost'),
            lambda c: c['detail_visibility_ids'].remove(c['guard_body_ids'][0]),
        ):
            with self.subTest(change=change):
                self.reject(change)

    def test_stair_connector_and_global_group_records_must_agree(self):
        for change in (
            lambda c: c['stairs'][0]['guard_body_ids'].pop(),
            lambda c: c['stairs'][0]['guard_groups'].pop(),
            lambda c: c['stairs'][0]['connectors'][0]['guard_body_ids'].pop(),
            lambda c: c['guard_groups'][0].update(connector_id='AnotherConnector'),
            lambda c: c['guard_groups'][0].update(from_level='AnotherLevel'),
            lambda c: c['guard_groups'][0].update(kind='AnotherGuardKind'),
            lambda c: c['guard_groups'][0].update(profile_ref='#/roof/guard'),
        ):
            with self.subTest(change=change):
                self.reject(change)

    def test_each_post_requires_exactly_its_own_named_attachment(self):
        for change in (
            lambda c: c['guard_attachment_witnesses'].pop(),
            lambda c: c['guard_attachment_witnesses'].append(copy.deepcopy(c['guard_attachment_witnesses'][0])),
            lambda c: c['guard_attachment_witnesses'][0].update(id='UnexpectedAttachment'),
            lambda c: c['guard_posts'][0].update(attachment_probe_id='UnexpectedAttachment'),
        ):
            with self.subTest(change=change):
                self.reject(change)

    def test_attachment_targets_match_post_and_existing_support_without_extras(self):
        for change in (
            lambda c: c['guard_attachment_witnesses'][0]['target_bodies'].pop(),
            lambda c: c['guard_attachment_witnesses'][0]['target_bodies'].append('BuildingLiftCabin'),
            lambda c: c['guard_attachment_witnesses'][0]['target_bodies'].append(c['guard_attachment_witnesses'][0]['target_bodies'][0]),
            lambda c: c['guard_posts'][0].update(support_body_id='BuildingLiftCabin'),
            lambda c: c['guard_posts'][0].update(support_body_ids=['AnotherSupport']),
            lambda c: c['guard_attachment_witnesses'][0].update(expectation='empty'),
            lambda c: c['guard_attachment_witnesses'][0]['expected_volumes_mm3'].pop(c['guard_posts'][0]['support_body_id']),
            lambda c: c['guard_attachment_witnesses'][0]['expected_volumes_mm3'].update({c['guard_posts'][0]['support_body_id']: 0}),
            lambda c: c['guard_attachment_witnesses'][0]['expected_volumes_mm3'].update({c['guard_posts'][0]['support_body_id']: 1}),
        ):
            with self.subTest(change=change):
                self.reject(change)

    def test_all_four_named_clearances_per_internal_connector_are_required(self):
        for change in (
            lambda c: c['guard_clearance_probes'].pop(),
            lambda c: c['guard_clearance_probes'].append(copy.deepcopy(c['guard_clearance_probes'][0])),
            lambda c: c['guard_clearance_probes'][0].update(id='UnknownGuardClearance'),
            lambda c: c['guard_clearance_probes'][0].update(scope='whole_building'),
            lambda c: c['guard_clearance_probes'][0].update(expectation='filled'),
            lambda c: c['guard_clearance_probes'][0]['target_bodies'].pop(),
            lambda c: c['guard_clearance_probes'][0]['target_bodies'].append('BuildingLiftCabin'),
            lambda c: c['guard_clearance_probes'][0]['target_bodies'].append(c['guard_body_ids'][0]),
        ):
            with self.subTest(change=change):
                self.reject(change)

    def test_legacy_without_guard_reference_or_guard_data_retains_its_probes(self):
        result = build.circulation_probe_specs(self.legacy)
        self.assertTrue(result)
        self.assertFalse(any(item['category'].startswith('stair_guard_') for item in result))
        broken = copy.deepcopy(self.legacy)
        broken['circulation']['guard_body_ids'] = ['HiddenGuard']
        with self.assertRaises(ValueError):
            build.circulation_probe_specs(broken)
        self.reject(lambda c: c.update(guard_profile_ref=None))
        self.reject(lambda c: c.update(guard_profile_ref='#/roof/guard'))

    def test_guard_geometry_does_not_escalate_safety_qualification(self):
        self.reject(lambda c: c.update(guard_safety_qualified=True))
        self.reject(lambda c: c['stairs'][0].update(guard_safety_qualified=True))


if __name__ == '__main__':
    unittest.main()
