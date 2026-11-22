"""Room naming respects owner assignments and the limits of copied floorplans."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import building_stack as building
import building_room_labels as room_labels


class RoomLabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import json
        cls.spec = json.loads(building.SOURCE.read_text())
        cls.plans = {level['id']: building.level_plan(cls.spec, level['id'])
                     for level in cls.spec['levels']}
        cls.labels = room_labels.labels(cls.spec, cls.plans)

    def test_lower_storeys_do_not_inherit_unconfirmed_third_floor_numbers(self):
        for level in ('OG1', 'OG2'):
            self.assertNotIn((level, 'R3_011'), self.labels)
            self.assertNotIn((level, 'Suite3_006AB'), self.labels)
            self.assertFalse(any(value['text'].startswith('3.') for key, value in self.labels.items()
                                 if key[0] == level))
        self.assertEqual(self.labels['OG3', 'R3_011']['text'], '3.011')

    def test_confirmed_labs_offices_storage_and_secretariat_have_names(self):
        self.assertEqual(self.labels['EG', 'R0_001']['text'], 'EG 1 Labor')
        self.assertEqual(self.labels['OG1', 'R3_001']['text'], '1.001 Labor')
        self.assertEqual(self.labels['OG2', 'R3_004']['text'], '2.004 Büro')
        self.assertEqual(self.labels['OG3', 'R3_005']['text'], '3.005 Lager')
        self.assertEqual(self.labels['EG', 'R0_014A']['text'], '14A Lager')
        self.assertEqual(self.labels['OG3', 'Suite3_006AB']['text'], '3.006A/B Sekretariat')

    def test_obsolete_ground_floor_lab_use_is_not_displayed(self):
        record = self.labels['EG', 'R0_002']
        self.assertEqual(record['text'], '2')
        self.assertEqual(record['usage'], 'non_laboratory')

    def test_composite_kitchen_and_facade_room_keep_current_bound_numbers(self):
        for area in ('R3_008A', 'R3_008B', 'R3_009'):
            self.assertEqual(self.labels['OG1', area]['text'], '1.008 Küche')
        self.assertEqual(self.labels['OG3', 'R3_009']['text'], '3.008 Büro')
        self.assertNotIn('3.009', self.labels['OG3', 'R3_009']['text'])
        self.assertEqual(self.labels['OG3', 'R3_008A']['text'], '3.008 Küche')

    def test_documented_doctoral_identities_and_pinned_microscope_room(self):
        for level in ('OG1', 'OG2', 'OG3'):
            self.assertEqual(self.labels[level, 'R3_002']['text'], level[-1]+'.002 Doktorandenraum')
        record = self.labels['OG3', 'R3_007']
        self.assertEqual(record['text'], '3.007 Mikroskop')
        self.assertEqual(record['basis'], 'explicit_equipment_room_binding')

    def test_unknown_labels_qualifiers_and_open_assignments_are_not_guessed(self):
        self.assertNotIn(('KG', 'KServiceNorth'), self.labels)
        self.assertNotIn(('KG', 'KCompressors'), self.labels)
        self.assertNotIn(('OG3', 'CoreGap'), self.labels)
        self.assertNotIn(('OG3', 'LiftCore'), self.labels)
        self.assertEqual(self.labels['KG', 'R3_028']['text'], '0.018 Treppenkern')
        self.assertEqual(self.labels['KG', 'K0_007']['text'], '0.007 Flüssigstickstoff')
        self.assertFalse(any('?' in record['text'] or 'registrierter Konzeptbezug' in record['text']
                             for record in self.labels.values()))

    def test_named_rooms_without_corridor_doors_remain_known_for_placement_reporting(self):
        self.assertEqual(self.labels['KG', 'K0_004']['text'], '0.004 IT/BMA/TK-Anlage')
        self.assertEqual(self.labels['EG', 'R0_011']['text'], '11 Technik')

    def test_only_requested_level_plans_are_returned_without_mutation(self):
        before_spec, before_plans = copy.deepcopy(self.spec), copy.deepcopy(self.plans)
        result = room_labels.labels(self.spec, {'OG2': self.plans['OG2']})
        self.assertTrue(result)
        self.assertEqual({key[0] for key in result}, {'OG2'})
        self.assertEqual(self.spec, before_spec)
        self.assertEqual(self.plans, before_plans)

    def test_changed_semantic_source_pin_fails_closed(self):
        spec = copy.deepcopy(self.spec)
        spec['sources']['furnishings']['source_sha256'] = '0'*64
        with self.assertRaises(ValueError):
            room_labels.labels(spec, self.plans)

    def test_unassigned_furniture_recipe_does_not_invent_a_room_use(self):
        spec = {'sources': {'furnishings': {'source': 'synthetic.json', 'source_sha256': '0'*64}}}
        source = {'rooms': [{'id': 'UnclassifiedOffice', 'room': '2.777', 'level': 'OG2',
                            'template_areas': ['Other'], 'recipe': 'office'}]}
        plans = {'OG2': {'areas': [{'id': 'Other', 'kind': 'room', 'label': '3.777'}]}}
        with patch.object(room_labels, 'read', return_value=source):
            resolved = room_labels.labels(spec, plans)
        self.assertEqual(resolved['OG2', 'Other']['text'], '2.777')


if __name__ == '__main__':
    unittest.main()
