"""Generate the additive test-only S09 SiLA feature without loading an SDK."""
import ast
import hashlib
import json
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from cutrun_input_sonication_sources import compile_profile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'model/cutrun-input-sonication-sila2.protocol.json'
SCHEMA = ROOT / 'model/cutrun-input-sonication-sila2.schema.json'
NS = 'http://www.sila-standard.org'
Q = lambda name: '{' + NS + '}' + name
COMMANDS = {'CreateRun', 'RunUntilDecision', 'ResumeRun', 'ReconcileRun',
            'CancelRun', 'FinishCancel'}
ERRORS = ['WorkflowRejected', 'RecoveryRequired', 'ReconciliationRequired',
          'CommandCanceled', 'PersistenceFailure']
REFERENCES = {'composition_profile': 'model/cutrun-input-sonication.profile.json',
              'fixture': 'model/cutrun-input-sonication.fixture.json',
              'standard_provenance': 'interfaces/sila2/standard/provenance.json'}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def camel(name):
    return ''.join(part[:1].upper() + part[1:] for part in name.split('_'))


def _project(name):
    if not isinstance(name, str) or Path(name).is_absolute():
        raise ValueError('S09 SiLA source must be a project-relative path')
    path = (ROOT / name).resolve()
    if not path.is_relative_to(ROOT) or str(path.relative_to(ROOT)) != name:
        raise ValueError('S09 SiLA source must stay in the project: ' + name)
    return path


def _keys(value, names, label):
    if not isinstance(value, dict) or set(value) != set(names):
        raise ValueError('Unexpected fields in ' + label)


def verify_source_files(pins):
    """Reject drift against a previously frozen root or evidence closure."""
    if not isinstance(pins, dict) or not pins:
        raise ValueError('Nonempty S09 SiLA source pins required')
    for name, checksum in pins.items():
        path = _project(name)
        if (not isinstance(checksum, str) or not re.fullmatch('[0-9a-f]{64}', checksum)
                or not path.is_file() or digest(path) != checksum):
            raise ValueError('S09 SiLA source changed: ' + name)


def _runtime_closure(names):
    """Find local import dependencies without executing optional SDK/CAD code."""
    pending, found = list(names), set()
    while pending:
        name = pending.pop()
        path = _project(name)
        if name in found:
            continue
        if not path.is_relative_to(ROOT / 'scripts') or path.suffix != '.py' or not path.is_file():
            raise ValueError('S09 SiLA runtime source missing or outside scripts/: ' + name)
        found.add(name)
        for node in ast.walk(ast.parse(path.read_bytes(), filename=name)):
            modules = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                       else [node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
            for module in modules:
                dependency = ROOT / 'scripts' / (module.split('.')[0] + '.py')
                if dependency.is_file():
                    pending.append(str(dependency.relative_to(ROOT)))
    return sorted(found)


def load(path=SOURCE):
    path = Path(path).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError('S09 SiLA contract must stay in the project')
    data = json.loads(path.read_text(encoding='utf-8'))
    schema = json.loads(SCHEMA.read_text(encoding='utf-8'))
    _keys(data, schema['required'], 'S09 SiLA contract')
    # The schema is the single declaration of the accepted wire surface. These
    # constants can be checked with stdlib; jsonschema is an offline test tool.
    for name, definition in schema['properties'].items():
        if ('const' in definition
                and json.dumps(data[name], sort_keys=True, allow_nan=False)
                != json.dumps(definition['const'], sort_keys=True, allow_nan=False)):
            raise ValueError('Unsupported S09 SiLA contract field: ' + name)
    interval = data['publish_interval_s']
    if type(interval) not in (int, float) or not math.isfinite(interval) or not 0 < interval <= 1:
        raise ValueError('Finite S09 status publication interval in (0, 1] required')
    limitations = data['limitations']
    if (not isinstance(limitations, list) or not limitations
            or any(not isinstance(item, str) or not item.strip() for item in limitations)):
        raise ValueError('Explicit S09 SiLA limitations required')
    pins = {}

    def remember(file):
        file = Path(file).resolve()
        name = str(file.relative_to(ROOT))
        _project(name)
        checksum = digest(file)
        if name in pins and pins[name] != checksum:
            raise ValueError('S09 SiLA source changed while loading: ' + name)
        pins[name] = checksum

    def reference(ref, expected, label):
        _keys(ref, ('source', 'source_sha256'), label)
        if ref['source'] != expected:
            raise ValueError('Unsupported S09 SiLA source: ' + label)
        file = _project(ref['source'])
        if not file.is_file() or digest(file) != ref['source_sha256']:
            raise ValueError('Changed S09 SiLA source: ' + label)
        remember(file)
        return file

    files = {name: reference(data[name], expected, name) for name, expected in REFERENCES.items()}
    compiled = compile_profile(files['composition_profile'])
    for name, checksum in compiled['source_files_sha256'].items():
        if name in pins and pins[name] != checksum:
            raise ValueError('S09 SiLA composition pins disagree: ' + name)
        pins[name] = checksum
    fixture = json.loads(files['fixture'].read_text(encoding='utf-8'))
    if (fixture.get('format') != 'solidcraftbot.cutrun-input-sonication-fixture/1'
            or fixture.get('mode') != 'test_fixture_only'):
        raise ValueError('Explicit S09 test fixture required')
    provenance = json.loads(files['standard_provenance'].read_text(encoding='utf-8'))
    if data['standard_features'] != provenance['files']:
        raise ValueError('S09 standard feature references disagree with archived provenance')
    for ref in data['standard_features']:
        _keys(ref, ('identifier', 'source', 'source_sha256', 'upstream_path'), 'standard feature reference')
        file = _project(ref['source'])
        if not file.is_relative_to(ROOT / 'interfaces/sila2/standard') or digest(file) != ref['source_sha256']:
            raise ValueError('Changed standard feature: ' + ref['identifier'])
        remember(file)
    runtime = [*data['runtime_sources'],
               *(name for name in pins if name.startswith('scripts/') and name.endswith('.py'))]
    for name in _runtime_closure(runtime):
        remember(ROOT / name)
    remember(path)
    remember(SCHEMA)
    remember(ROOT / 'requirements/sila2-test.lock')
    verify_source_files(pins)
    return {**data, 'source_files_sha256': dict(sorted(pins.items()))}


def header(parent, identifier, description):
    for key, value in [('Identifier', identifier), ('DisplayName', identifier), ('Description', description)]:
        ET.SubElement(parent, Q(key)).text = value


def value(parent, tag, identifier, kind, description):
    node = ET.SubElement(parent, Q(tag))
    header(node, identifier, description)
    ET.SubElement(ET.SubElement(node, Q('DataType')), Q('Basic')).text = {
        'string': 'String', 'bool': 'Boolean'}[kind]
    return node


def feature(data=None):
    data = load() if data is None else data
    f = data['feature']
    ET.register_namespace('', NS)
    root = ET.Element(Q('Feature'), {'SiLA2Version': f['sila_version'], 'FeatureVersion': f['version'],
        'MaturityLevel': f['maturity'], 'Originator': f['originator'], 'Category': f['category'], 'Locale': f['locale']})
    header(root, f['identifier'], 'Test-fixture-only S09 input-sonication coordinator over TLS. The existing input_sonication_mock/1 root owns its journal, material ledger, resources and atomic network receipts. No hardware or ROS runtime. S09 completion is not completion of the CUT&RUN workflow; command acceptance proves no physical effect or resource clearance.')
    for source in data['commands']:
        command = ET.SubElement(root, Q('Command'))
        header(command, source['name'], 'Test-only root operation ' + source['name'] + '; uncertain effects require explicit reconciliation. Durable request identifiers cannot silently repeat effects.')
        ET.SubElement(command, Q('Observable')).text = 'Yes' if source['observable'] else 'No'
        for field in source['arguments']:
            value(command, 'Parameter', camel(field['name']), field['type'], field['description'])
        value(command, 'Response', 'StatusJson', 'string', 'Complete JSON response from the authoritative root; preserve receipt and run identifiers.')
        if source['observable']:
            value(command, 'IntermediateResponse', 'StatusJson', 'string', 'Observed root progress; an intermediate response is not terminal success.')
        errors = ET.SubElement(command, Q('DefinedExecutionErrors'))
        for error in ERRORS:
            ET.SubElement(errors, Q('Identifier')).text = error
    for identifier, observable, description in [
            ('Status', True, 'Read-only JSON status; observation never acquires a process lock or advances the workflow.'),
            ('Report', False, 'Read-only full JSON root report with original artifacts, material ledger and separate real/synthetic readiness.')]:
        prop = ET.SubElement(root, Q('Property'))
        header(prop, identifier, description)
        ET.SubElement(prop, Q('Observable')).text = 'Yes' if observable else 'No'
        ET.SubElement(ET.SubElement(prop, Q('DataType')), Q('Basic')).text = 'String'
    for identifier in ERRORS:
        header(ET.SubElement(root, Q('DefinedExecutionError')), identifier,
               'Root operation refused or uncertain: ' + identifier + '. Inspect root status; never replay effects or release resources automatically.')
    ET.indent(root)
    return ET.tostring(root, encoding='unicode', xml_declaration=True) + '\n'


def build(directory=None):
    directory = Path(directory or ROOT / 'exports/generated/sonication-sila2/contracts').resolve()
    if not directory.is_relative_to(ROOT / 'exports'):
        raise ValueError('Generated S09 contracts must stay in exports/')
    data = load()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / 'CutRunInputSonicationWorkflow-v1_0.sila.xml'
    target.write_text(feature(data), encoding='utf-8')
    report = {'format': 'solidcraftbot.cutrun-input-sonication-sila-contract/1',
              'feature': str(target.relative_to(ROOT)), 'sha256': digest(target),
              'source_files_sha256': data['source_files_sha256'],
              'simulation_only': True, 'test_fixture_only': True,
              'schema_validated': False, 'network_executed': False,
              'hardware_executed': False, 'ros2_executed': False}
    (directory / 'generation-report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return target


if __name__ == '__main__':
    print(build())
