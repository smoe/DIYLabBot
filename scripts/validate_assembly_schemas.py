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
    names = ['assembly-reference.schema.json','lab-layout.schema.json','centrifuge-cf01.robot-pickup.schema.json']
    schemas = {}
    for name in names:
        path = ROOT/'model'/name
        schema = json.loads(path.read_text(encoding='utf-8'))
        Draft202012Validator.check_schema(schema)
        # Rebase portable schema IDs to local files, so relative refs never use a network.
        schema['$id'] = path.as_uri()
        schemas[name] = schema
    registry = Registry().with_resources((schema['$id'],Resource.from_contents(schema)) for schema in schemas.values())
    for document, name in [('lab-layout-l01.shared.json','lab-layout.schema.json'),('centrifuge-cf01.robot-pickup.shared.json','centrifuge-cf01.robot-pickup.schema.json')]:
        data = json.loads((ROOT/'model'/document).read_text(encoding='utf-8'))
        Draft202012Validator(schemas[name],registry=registry).validate(data)
        print(document+': schema passed')


if __name__ == '__main__':
    main()
