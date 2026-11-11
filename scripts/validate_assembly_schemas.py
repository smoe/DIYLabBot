"""Validate supported assembly documents against their local JSON Schemas.

Optional development dependency: python -m pip install jsonschema
The ordinary unittest suite and CAD generators do not require this package.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    try:
        from jsonschema import Draft202012Validator
        from referencing import Registry, Resource
    except ImportError:
        raise SystemExit('Install the optional schema validator: python -m pip install jsonschema')
    names = ['assembly-reference.schema.json','lab-layout.schema.json','centrifuge-cf01.robot-pickup.schema.json','room-composition.schema.json','room-geometry.schema.json','furniture-catalog.schema.json','furnishings.schema.json','synthetic-environment.schema.json','synthetic-workspace.schema.json','equipment-layout.schema.json','guided-tube-rack.schema.json','cf01-rack-batch.schema.json','synthetic-lab-workflow.schema.json']
    names.append('instrument-concept.schema.json')
    names.append('lab-glassware.schema.json')
    names.append('lab-equipment.schema.json')
    names.extend(['lab-transfer-l01.schema.json','cf01-unload-demo.schema.json'])
    schemas = {}
    for name in names:
        path = ROOT/'model'/name
        schema = json.loads(path.read_text(encoding='utf-8'))
        Draft202012Validator.check_schema(schema)
        # Rebase portable schema IDs to local files, so relative refs never use a network.
        schema['$id'] = path.as_uri()
        schemas[name] = schema
    registry = Registry().with_resources((schema['$id'],Resource.from_contents(schema)) for schema in schemas.values())
    for document, name in [('lab-layout-l01.shared.json','lab-layout.schema.json'),('centrifuge-cf01.robot-pickup.shared.json','centrifuge-cf01.robot-pickup.schema.json'),('lab-room-l01.shared.json','room-composition.schema.json'),('environments/l01.geometry.json','room-geometry.schema.json'),('furniture/laboratory.catalog.json','furniture-catalog.schema.json'),('furnishings/l01.furnishings.json','furnishings.schema.json'),('environments/synthetic-unbounded.json','synthetic-environment.schema.json'),('synthetic-cf01-workspace.shared.json','synthetic-workspace.schema.json'),('furniture/reference-bench.catalog.json','furniture-catalog.schema.json'),('furnishings/cf01-reference-bench.json','furnishings.schema.json'),('equipment/cf01-workspace.json','equipment-layout.schema.json'),('guided-tube-rack.shared.json','guided-tube-rack.schema.json'),('cf01-rack-batch.protocol.json','cf01-rack-batch.schema.json'),('synthetic-lab-workflow.shared.json','synthetic-lab-workflow.schema.json')]:
        data = json.loads((ROOT/'model'/document).read_text(encoding='utf-8'))
        Draft202012Validator(schemas[name],registry=registry).validate(data)
        print(document+': schema passed')
    for family in ['nanodrop-concept', 'qubit-4-concept']:
        document = family + '.shared.json'
        data = json.loads((ROOT/'model'/document).read_text(encoding='utf-8'))
        Draft202012Validator(schemas['instrument-concept.schema.json'], registry=registry).validate(data)
        print(document + ': schema passed')
    document = 'lab-glassware.shared.json'
    data = json.loads((ROOT/'model'/document).read_text(encoding='utf-8'))
    Draft202012Validator(schemas['lab-glassware.schema.json'], registry=registry).validate(data)
    print(document + ': schema passed')
    document = 'lab-equipment.shared.json'
    data = json.loads((ROOT/'model'/document).read_text(encoding='utf-8'))
    Draft202012Validator(schemas['lab-equipment.schema.json'], registry=registry).validate(data)
    print(document + ': schema passed')
    workflow_schema = schemas['synthetic-lab-workflow.schema.json']
    for document,name in [('lab-transfer-l01.protocol.json','lab-transfer-l01.schema.json'),
                          ('cf01-unload-demo.motion.json','cf01-unload-demo.schema.json')]:
        data=json.loads((ROOT/'model'/document).read_text(encoding='utf-8'))
        Draft202012Validator(schemas[name],registry=registry).validate(data)
        print(document+': schema passed')
    manifest = json.loads((ROOT/'model/synthetic-lab-workflow.manifest.json').read_text())
    manifest_schema = {'$schema':workflow_schema['$schema'], '$id':workflow_schema['$id']+'?manifest-check',
                       '$defs':workflow_schema['$defs'], '$ref':'#/$defs/manifest'}
    Draft202012Validator.check_schema(manifest_schema)
    Draft202012Validator(manifest_schema,registry=registry).validate(manifest)
    print('synthetic-lab-workflow.manifest.json: schema passed')


if __name__ == '__main__':
    main()
