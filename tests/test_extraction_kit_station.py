"""K01 source-driven static staging, synthetic envelope and native-binding checks."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import extraction_kit_station as model

try:
    from jsonschema import Draft202012Validator, ValidationError
    from referencing import Registry, Resource
except ImportError:
    Draft202012Validator = None


def native_bbox_fixture(spec):
    """Primitive exterior boxes stand in for measurements, never for native QA."""
    p = model.parameters(spec); shapes = {}
    for operation in model.expanded(spec, p)['operations']:
        if operation['action'] != 'create':
            continue  # Interior cuts leave these exterior bounds intact.
        shape = model.numeric_shape(operation['shape'], p)
        if shape['kind'] == 'box':
            low = shape['origin']; high = [a+b for a, b in zip(low, shape['size'])]
        else:
            x, y, z = shape['origin']; r = shape['radius']
            low = [x-r, y-r, z]; high = [x+r, y+r, z+shape['height']]
        shapes[operation['body']] = {'body': operation['body'], 'bbox': {'min': low, 'max': high}}
    return list(shapes.values())


class KitStationTests(unittest.TestCase):
    def setUp(self):
        self.spec = model.load()
        self.p = model.parameters(self.spec)

    def test_materials_are_resolved_and_deduplicated_by_catalog_identity(self):
        catalog = model.catalog(self.spec)
        for module in model.ensemble(self.spec, self.p):
            kit = catalog['kits'][module['kit_id']]
            self.assertEqual(module['kit_name'], kit['name'])
            self.assertEqual(module['catalog_number'], kit['catalog_number'])
            self.assertEqual(len(module['materials']), 9)
            self.assertEqual({item['material_id'] for item in module['materials']}, set(kit['roles'].values()))
            self.assertTrue(all(item['status'] == 'planned_unobserved' for item in module['materials']))
        rna = model.ensemble(self.spec, self.p)[0]
        collection = next(item for item in rna['materials'] if 'collection_tube' in item['roles'])
        self.assertEqual(set(collection['roles']), {'collection_tube', 'gdna_collection_tube'})

    def test_catalog_pin_and_missing_kit_cannot_be_bypassed(self):
        bad = copy.deepcopy(self.spec); bad['catalog']['source_sha256'] = '0'*64
        with self.assertRaises(ValueError):
            model.validate(bad)
        bad = copy.deepcopy(self.spec); bad['modules'][0]['kit_id'] = 'unknown'
        with self.assertRaises(ValueError):
            model.validate(bad)
        bad = copy.deepcopy(self.spec); bad['modules'][0]['kit_id'] = bad['modules'][1]['kit_id']
        with self.assertRaises(ValueError):
            model.validate(bad)

    def test_catalog_label_and_sku_changes_flow_through_without_code_copies(self):
        catalog = model.catalog(self.spec)
        kit = catalog['kits'][self.spec['modules'][0]['kit_id']]
        kit['name'] = 'Changed catalog label'; kit['catalog_number'] = '12345'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'model').mkdir()
            data = json.dumps(catalog).encode(); (root/'model/catalog.json').write_bytes(data)
            spec = copy.deepcopy(self.spec)
            spec['catalog'] = {'source': 'model/catalog.json', 'source_sha256': hashlib.sha256(data).hexdigest()}
            with mock.patch.object(model, 'ROOT', root):
                value = model.ensemble(spec, self.p)[0]
        self.assertEqual((value['kit_name'], value['catalog_number']), ('Changed catalog label', '12345'))

    def test_both_inserts_have_one_shared_parametric_interface(self):
        interface = model.interfaces(self.spec, self.p)
        self.assertEqual(interface['inserts']['RNAInsert'], interface['inserts']['DNAInsert'])
        self.assertEqual(interface['common_insert']['width_mm'], 213)
        self.assertEqual(interface['common_insert']['depth_mm'], 173)
        self.assertEqual(interface['common_insert']['thickness_mm'], 8)
        self.assertFalse(interface['fit_qualified'])

    def test_wide_case_changes_container_insert_slot_and_reference_floor_together(self):
        original = copy.deepcopy(self.spec)
        wide = model.materialize(self.spec, 'wide_open'); wp = model.parameters(wide)
        self.assertEqual(self.spec, original)
        self.assertEqual(wp['outer_w']-self.p['outer_w'], 20)
        self.assertEqual(model.interfaces(wide, wp)['common_insert']['width_mm']-model.interfaces(self.spec, self.p)['common_insert']['width_mm'], 20)
        a = model.interfaces(self.spec, self.p)['modules']['RNA']
        b = model.interfaces(wide, wp)['modules']['RNA']
        self.assertNotEqual(a['slots'][0]['center_xy_mm'], b['slots'][0]['center_xy_mm'])
        for spec in [self.spec, wide]:
            self.assertTrue(all(c['passed'] for c in model.check_interface_geometry(spec, model.parameters(spec), native_bbox_fixture(spec))))

    def test_open_lids_stand_on_reference_floor_behind_containers(self):
        opened = model.materialize(self.spec, 'open'); p = model.parameters(opened)
        for module in model.interfaces(opened, p)['modules'].values():
            self.assertEqual(module['lid_bbox_mm']['min'][2], 0)
            self.assertGreaterEqual(module['lid_bbox_mm']['min'][1], module['container_bbox_mm']['max'][1]+p['rear_gap'])
        stored = model.materialize(self.spec, 'stored'); contract = model.interfaces(stored, model.parameters(stored))
        for module in contract['modules'].values():
            self.assertEqual(module['lid_inner_bbox_mm']['max'][2], 134)
            self.assertGreater(min(module['lid_inner_bbox_mm']['max'][2]-s['envelope_bbox_mm']['max'][2] for s in module['slots']), 0)

    def test_slots_are_disjoint_and_keep_articles_inside_the_container(self):
        for module in model.interfaces(self.spec, self.p)['modules'].values():
            slots = module['slots']; self.assertEqual(len({s['id'] for s in slots}), 9)
            for i, slot in enumerate(slots):
                box = slot['envelope_bbox_mm']
                for axis in (0, 1):
                    self.assertGreater(box['min'][axis], module['container_bbox_mm']['min'][axis]+self.p['wall'])
                    self.assertLess(box['max'][axis], module['container_bbox_mm']['max'][axis]-self.p['wall'])
                for other in slots[i+1:]:
                    b = other['envelope_bbox_mm']
                    self.assertTrue(any(box['max'][axis] < b['min'][axis] or b['max'][axis] < box['min'][axis] for axis in (0, 1)))

    def test_overlarge_or_tall_envelopes_fail_instead_of_claiming_fit(self):
        for change in ['radius', 'height']:
            spec = copy.deepcopy(self.spec)
            spec['prototypes']['large_bottle']['radius_mm' if change == 'radius' else 'height_mm'] = 40 if change == 'radius' else 140
            with self.subTest(change=change), self.assertRaises(ValueError):
                model.validate(spec)

    def test_assumed_dimensions_and_all_qualification_limits_remain_explicit(self):
        self.assertTrue(all(p['measured_dimensions'] is None and p['status'] == 'synthetic_assumption' for p in self.spec['prototypes'].values()))
        for change in ['fit_verified', 'sop_implemented', 'inventory_implemented', 'sample_storage_implemented']:
            spec = copy.deepcopy(self.spec); spec['qualification'][change] = True
            with self.subTest(change=change), self.assertRaises(ValueError):
                model.validate(spec)
        spec = copy.deepcopy(self.spec); spec['prototypes']['small_bottle']['measured_dimensions'] = {'radius_mm': 11}
        with self.assertRaises(ValueError):
            model.validate(spec)

    def test_static_cases_cannot_be_misrepresented_as_joint_motion(self):
        self.assertEqual([c['id'] for c in model.cases(self.spec)], ['stored', 'open', 'wide_open'])
        for case in model.cases(self.spec):
            spec = model.materialize(self.spec, case['id']); p = model.parameters(spec); expanded = model.expanded(spec, p)
            self.assertEqual(expanded['joints'], [])
            self.assertEqual(model.samples(spec, p), [{'id': spec['display_pose'], 'values_mm': {}}])
            model.validate_pose(expanded, model.pose(spec, p))
            with self.assertRaises(ValueError):
                model.validate_pose(expanded, {'Lid': 1})
        with self.assertRaises(ValueError):
            model.pose(self.spec, self.p, 'stored')

    def test_unknown_stock_quantity_or_sop_fields_are_rejected(self):
        for name, value in [('stock', {}), ('quantity', 50), ('sample_storage', []), ('sop', 'invented')]:
            spec = copy.deepcopy(self.spec); spec[name] = value
            with self.subTest(field=name), self.assertRaises(ValueError):
                model.validate(spec)

    def test_native_interface_checks_detect_changed_article_lid_and_container_poses(self):
        for case in ['stored', 'open', 'wide_open']:
            spec = model.materialize(self.spec, case); p = model.parameters(spec)
            baseline = native_bbox_fixture(spec)
            checks = model.check_interface_geometry(spec, p, baseline)
            self.assertEqual(len({c['id'] for c in checks}), len(checks))
            self.assertTrue(all(c['passed'] for c in checks))
            for body in ['RNA_Slot01_ClosedEnvelope', 'DNA_Lid', 'RNA_Container', 'DNA_Insert']:
                measured = copy.deepcopy(baseline)
                item = next(m for m in measured if m['body'] == body)
                item['bbox']['min'][0] += 1; item['bbox']['max'][0] += 1
                with self.subTest(case=case, body=body):
                    self.assertFalse(all(c['passed'] for c in model.check_interface_geometry(spec, p, measured)))

    def test_shared_primitive_adapter_and_dependencies_do_not_require_lab_glassware(self):
        names = [str(path.relative_to(ROOT)) for path in model.source_dependencies(self.spec)]
        self.assertIn(self.spec['catalog']['source'], names)
        self.assertFalse(any('glassware' in name or name.endswith(('.FCStd', '.step', '.sc')) for name in names))
        with mock.patch.object(model.primitive, 'solidcraft_commands', wraps=model.primitive.solidcraft_commands) as shared:
            commands = model.solidcraft_commands(self.spec, self.p)
        shared.assert_called_once()
        self.assertTrue(any(c['command'] == 'solid.box' for c in commands))
        self.assertFalse(any(c['command'] in {'joint.create', 'joint.drive'} for c in commands))
        metadata = next(c['params']['values'] for c in commands if c['command'] == 'document.metadata.set')
        self.assertEqual(metadata['org.solidcraftbot.extraction-kit-station']['catalog'], self.spec['catalog'])

    @unittest.skipIf(Draft202012Validator is None, 'Optional jsonschema development dependency required')
    def test_formal_schema_uses_local_refs_and_rejects_real_fit_or_stock_claims(self):
        resources = []
        for name in ['assembly-reference.schema.json', 'extraction-kit-station.schema.json']:
            path = ROOT/'model'/name; schema = json.loads(path.read_text()); Draft202012Validator.check_schema(schema)
            schema['$id'] = path.as_uri(); resources.append((schema['$id'], Resource.from_contents(schema)))
        validator = Draft202012Validator(schema, registry=Registry().with_resources(resources))
        validator.validate(self.spec)
        for name, value in [('stock', {}), ('measured_dimensions', {'width_mm': 20}), ('fit', True)]:
            bad = copy.deepcopy(self.spec)
            if name == 'stock':
                bad['stock'] = value
            elif name == 'fit':
                bad['qualification']['fit_verified'] = value
            else:
                bad['prototypes']['large_bottle'][name] = value
            with self.subTest(change=name), self.assertRaises(ValidationError):
                validator.validate(bad)


if __name__ == '__main__':
    unittest.main()
