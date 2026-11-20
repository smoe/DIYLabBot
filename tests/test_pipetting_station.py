import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import pipetting_station as station


class StationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context=station.compile_setup()

    def test_reference_composition_and_deck_roles(self):
        s=self.context
        self.assertEqual(set(s['spatial']['devices']),{'PS01','PS01Arm','PS01TransferArm','PS01Waste'})
        self.assertEqual(len(s['frames']),9)
        self.assertEqual(s['unused_bays'],['PS01.S07','PS01.S09'])
        self.assertEqual(sum(t['occupied_count'] for t in s['tip_racks']),480)
        self.assertEqual(s['station']['qualifications']['robot_motion_implemented'],False)
        self.assertEqual(s['station']['tool_capabilities']['minimum_qualified_volume_ul'],None)

    def test_imported_plate_geometry_and_orientation(self):
        plate=self.context['labware']['Plate01']
        self.assertEqual(len(plate['wells']),96)
        a,h=plate['wells']['A01'],plate['wells']['H12']
        self.assertEqual(a['original_id'],'A1')
        self.assertAlmostEqual(h['mouth_mm'][0]-a['mouth_mm'][0],99)
        self.assertAlmostEqual(a['mouth_mm'][1]-h['mouth_mm'][1],63)
        self.assertEqual(a['capacity_ul'],360)
        self.assertEqual((a['row'],a['column'],h['row'],h['column']),(0,0,7,11))
        self.assertEqual(plate['size_mm'],[127.76,85.47,14.22])

    def test_parameterized_deck_rebuilds_frames_and_rejects_overlap(self):
        source=station.load();old=station.deck(source)[1]
        changed=copy.deepcopy(source);changed['parameters']['deck_w']['expression']=600
        changed['parameters']['pitch_x']['expression']=190
        new=station.deck(changed)[1]
        self.assertEqual(new['PS01.S01'][0][3]-old['PS01.S01'][0][3],-20)
        self.assertEqual(new['PS01.S03'][0][3]-old['PS01.S03'][0][3],20)
        changed['parameters']['deck_w']['expression']=500
        with self.assertRaises(ValueError):station.deck(changed)

    def test_generic_reservoir_grid_has_capacity_below_geometry(self):
        catalog=station.labware();changed=copy.deepcopy(catalog)
        changed['types']['reservoir3'].update(rows=2,columns=2)
        variant=station.labware_type(changed,'reservoir3')
        self.assertEqual(set(variant['wells']),{'A01','A02','B01','B02'})
        self.assertGreater(variant['wells']['A01']['cross_section_mm2']*25,40000)
        changed['types']['reservoir3']['capacity_ul']=100000
        with self.assertRaises(ValueError):station.labware_type(changed,'reservoir3')

    def test_nominal_tip_frames_derive_from_shared_geometry(self):
        rack=self.context['tip_racks'][0]
        self.assertEqual(rack['parameters']['capacity'],10)
        positions={s['id']:s['mouth_world_mm'] for s in rack['slots']}
        self.assertAlmostEqual(positions['H12'][0]-positions['A01'][0],99)
        self.assertAlmostEqual(positions['H12'][1]-positions['A01'][1],63)
        self.assertEqual(rack['fit_to_T01']['status'],'open')
        self.assertFalse(rack['solid_geometry_ready'])

    def test_selected_tool_case_does_not_copy_or_repin_historical_geometry(self):
        source=self.context['setup']['assets']['tool_envelope']
        kit=station.bound(source)
        parts,frames=station.tools.kit_parts(kit,'pipette')
        current=next(g for g in self.context['groups'] if g['id']=='PipetteEnvelope')
        self.assertEqual(current['parts'],parts)
        self.assertEqual(frames['tcp'],[0,0,190])
        self.assertIn(ROOT/'model/robot.json',station.source_paths())

    def test_invalid_deck_registration_is_rejected(self):
        variants=[]
        source=station.read(station.SETUP);source['labware'][0]['xyz'][2]=5;variants.append(source)
        source=station.read(station.SETUP);source['labware'][0]['xyz'][0]=40;variants.append(source)
        source=station.read(station.SETUP);source['tip_stocks'][0]['assembly']['asset']='plate';variants.append(source)
        source=station.read(station.SETUP);source['tip_stocks'][0]['assembly']['xyz'][0]=100;variants.append(source)
        source=station.read(station.SETUP);source['tip_stocks'][0]['assembly']['host']=source['labware'][0]['host'];variants.append(source)
        with tempfile.TemporaryDirectory(dir=ROOT/'exports') as directory:
            path=Path(directory)/'setup.json'
            for source in variants:
                path.write_text(json.dumps(source))
                with self.subTest(source=source['id']),self.assertRaises(ValueError):station.compile_setup(path)

    def test_sources_and_schema(self):
        try:
            import jsonschema
            from referencing import Registry,Resource
        except ImportError:
            self.skipTest('jsonschema is not installed')
        schema=station.read(ROOT/'model/pipetting.schema.json')
        schema['$id']=(ROOT/'model/pipetting.schema.json').as_uri()
        assembly=station.read(ROOT/'model/assembly-reference.schema.json')
        assembly['$id']=(ROOT/'model/assembly-reference.schema.json').as_uri()
        registry=Registry().with_resource(assembly['$id'],Resource.from_contents(assembly))
        validator=jsonschema.Draft202012Validator(schema,registry=registry,format_checker=jsonschema.FormatChecker())
        jsonschema.Draft202012Validator.check_schema(schema)
        for filename in ['pipetting-labware.shared.json','pipetting-station-ps01.shared.json','pipetting-station-ps01.setup.json','pipetting-matrix-96.protocol.json']:
            with self.subTest(filename=filename):validator.validate(station.read(ROOT/'model'/filename))
        bad=station.read(ROOT/'model/pipetting-matrix-96.protocol.json');bad['steps'][0]['mix_after']={}
        self.assertTrue(list(validator.iter_errors(bad)))
        bad=station.load();bad['qualifications']['hardware_execution_implemented']=True
        self.assertTrue(list(validator.iter_errors(bad)))
        for source in station.source_paths():self.assertTrue(source.is_file())


if __name__=='__main__':unittest.main()
