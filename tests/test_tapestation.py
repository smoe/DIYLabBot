import copy
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import tapestation_model as model


class TapeStationTests(unittest.TestCase):
    def test_manual_envelope_and_installation_space(self):
        spec=model.load();p=model.parameters(spec)
        self.assertIsNone(spec['selected_model'])
        self.assertEqual([p[k] for k in ('width','depth','height')],[435,510,445])
        self.assertEqual(model.interfaces(spec,p)['installation_keepout']['size_mm'],[585,660,695])
        self.assertFalse(spec['robot_loading_implemented'])
        source=model.expanded(spec,p)
        self.assertEqual(source['joints'],[])
        self.assertEqual(len(source['bodies']),8)
        commands=model.solidcraft_commands(spec,p)
        self.assertFalse(any(c['command'] in {'joint.create','joint.drive'} for c in commands))

    def test_no_undeclared_dimension_or_automation(self):
        spec=model.load()
        with self.assertRaises(ValueError):model.parameters(spec,{'width':500})
        changed=copy.deepcopy(spec);changed['parameters']['bench_width']['expression']=600
        changed['parameters']['bench_width']['range']=[600,600]
        with self.assertRaises(ValueError):model.parameters(changed)

    def test_new_source_schemas(self):
        try:
            import jsonschema
            from referencing import Registry,Resource
        except ImportError:self.skipTest('jsonschema unavailable')
        registry=Registry()
        for path in (ROOT/'model').glob('*.schema.json'):
            schema=json.loads(path.read_text())
            registry=registry.with_resource(path.name,Resource.from_contents(schema))
        for source,schema in [('tapestation.shared.json','tapestation.schema.json'),
                              ('lab-station-transport.protocol.json','lab-station-transport.schema.json')]:
            document=json.loads((ROOT/'model'/source).read_text())
            validator=jsonschema.Draft202012Validator(json.loads((ROOT/'model'/schema).read_text()),registry=registry)
            validator.validate(document)
            document['unexpected']=True
            self.assertFalse(validator.is_valid(document))

    def test_native_build_evidence_when_available(self):
        report_path=ROOT/'cad/tapestation/shared-build-report.json'
        if not report_path.exists():self.skipTest('Native TS01 build not available')
        report=json.loads(report_path.read_text())
        self.assertTrue(report['passed']);self.assertTrue(report['cross_cad_checked'])
        for key,sha in report['source_files_sha256'].items():self.assertEqual(model.digest(ROOT/key),sha)
        for key,path in report['files'].items():self.assertEqual(model.digest(ROOT/path),report['artifact_sha256'][key])
        self.assertEqual(len(report['body_comparisons']),8)


if __name__=='__main__':unittest.main()
