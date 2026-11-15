"""Generate the additive extraction analytics feature for the existing DNA service."""
import ast
import hashlib
import json
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import build_dna_quantification_sila2 as dna_contract
from extraction_analytics_sources import load as load_analytics
from extraction_preparation import parse_json
from manual_workflow import ROOT

SOURCE = ROOT / 'model/extraction-analytics-sila2.protocol.json'
SCHEMA = ROOT / 'model/extraction-analytics-sila2.schema.json'
NS, Q, camel = dna_contract.NS, dna_contract.Q, dna_contract.camel
COMMANDS = {'CreateRun', 'RunUntilDecision', 'ResumeRun', 'ReconcileRun', 'CancelRun', 'FinishCancel'}
ERRORS = dna_contract.ERRORS


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _keys(value, names, label):
    if not isinstance(value, dict) or set(value) != set(names):
        raise ValueError('Unexpected fields in ' + label)


def _project(name):
    if not isinstance(name, str) or Path(name).is_absolute():
        raise ValueError('Extraction SiLA source must be project-relative')
    path = (ROOT / name).resolve()
    if not path.is_relative_to(ROOT) or str(path.relative_to(ROOT)) != name:
        raise ValueError('Extraction SiLA source must stay in the project: ' + name)
    return path


def verify_source_files(pins):
    """Check previously frozen network/root source bytes without migration."""
    if not isinstance(pins, dict) or not pins:
        raise ValueError('Nonempty extraction SiLA source pins required')
    for name, expected in pins.items():
        path = _project(name)
        if (not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected)
                or not path.is_file() or digest(path) != expected):
            raise ValueError('Extraction SiLA source changed: ' + name)


def _runtime_closure(names):
    """Pin local imports without importing optional SDK, ROS or CAD backends."""
    pending, found = list(names), set()
    while pending:
        name = pending.pop()
        if name in found:
            continue
        path = _project(name)
        if not path.is_relative_to(ROOT / 'scripts') or path.suffix != '.py' or not path.is_file():
            raise ValueError('Extraction SiLA runtime source missing: ' + name)
        found.add(name)
        for node in ast.walk(ast.parse(path.read_bytes(), filename=name)):
            modules = ([item.name for item in node.names] if isinstance(node, ast.Import)
                       else [node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
            for module in modules:
                dependency = ROOT / 'scripts' / (module.split('.')[0] + '.py')
                if dependency.is_file():
                    pending.append(str(dependency.relative_to(ROOT)))
    return sorted(found)


def load(path=SOURCE):
    path = Path(path).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError('Extraction SiLA contract must stay in the project')
    data = parse_json(path.read_bytes())
    schema = parse_json(SCHEMA.read_bytes())
    _keys(data, schema['required'], 'extraction SiLA contract')
    # The schema declares the exact closed wire surface once. Runtime checks
    # require no optional jsonschema package.
    for name, definition in schema['properties'].items():
        if ('const' in definition
                and json.dumps(data[name], sort_keys=True, allow_nan=False)
                != json.dumps(definition['const'], sort_keys=True, allow_nan=False)):
            raise ValueError('Unsupported extraction SiLA contract field: ' + name)
    interval = data['publish_interval_s']
    if type(interval) not in (int, float) or not math.isfinite(interval) or not 0 < interval <= 1:
        raise ValueError('Finite extraction SiLA publication interval in (0, 1] required')
    limits = data['limitations']
    if not isinstance(limits, list) or not limits or any(not isinstance(v, str) or not v.strip() for v in limits):
        raise ValueError('Explicit extraction SiLA qualification limits required')
    pins = {}

    def remember(file):
        file = Path(file).resolve()
        name = str(file.relative_to(ROOT))
        _project(name)
        checksum = digest(file)
        if name in pins and pins[name] != checksum:
            raise ValueError('Extraction SiLA source changed while reading: ' + name)
        pins[name] = checksum

    def reference(ref, expected):
        _keys(ref, ('source', 'source_sha256'), 'extraction SiLA source reference')
        if ref['source'] != expected:
            raise ValueError('Unsupported extraction SiLA source selection: ' + expected)
        file = _project(expected)
        if not file.is_file() or digest(file) != ref['source_sha256']:
            raise ValueError('Changed extraction SiLA source: ' + expected)
        remember(file)
        return file

    _keys(data['families'], ('dneasy', 'puregene'), 'extraction SiLA family selection')
    definitions = {}
    for family in ('dneasy', 'puregene'):
        source = reference(data['families'][family], 'model/extraction-analytics.' + family + '.json')
        definitions[family] = load_analytics(source)
        if definitions[family]['execution']['analytics']['family'] != family:
            raise ValueError('Extraction SiLA family and composition differ')
        for name, expected in definitions[family]['source_files_sha256'].items():
            if name in pins and pins[name] != expected:
                raise ValueError('Extraction SiLA composition source pins disagree: ' + name)
            pins[name] = expected
    protocol = reference(data['analytics_protocol'], 'model/extraction-analytics.protocol.json')
    for definition in definitions.values():
        if definition['analytics_profile']['protocol'] != data['analytics_protocol']:
            raise ValueError('Extraction SiLA composition and analytics protocol pins differ')
    provenance = reference(data['standard_provenance'], 'interfaces/sila2/standard/provenance.json')
    if data['standard_features'] != parse_json(provenance.read_bytes())['files']:
        raise ValueError('Extraction SiLA standard features disagree with archived provenance')
    for ref in data['standard_features']:
        _keys(ref, ('identifier', 'source', 'source_sha256', 'upstream_path'), 'standard feature reference')
        file = _project(ref['source'])
        if not file.is_relative_to(ROOT / 'interfaces/sila2/standard') or digest(file) != ref['source_sha256']:
            raise ValueError('Changed standard feature: ' + ref['identifier'])
        remember(file)
    scripts = [*data['runtime_sources'], *(name for name in pins if name.startswith('scripts/') and name.endswith('.py'))]
    for name in _runtime_closure(scripts):
        remember(ROOT / name)
    remember(path)
    remember(SCHEMA)
    remember(ROOT / 'requirements/sila2-test.lock')
    verify_source_files(pins)
    return {**data, 'source_files_sha256': dict(sorted(pins.items())), 'definitions': definitions}


def feature(data=None):
    """Reuse the existing DNA FDL generator; its original output is unchanged."""
    data = load() if data is None else data
    root = ET.fromstring(dna_contract.feature(data))
    root.find(Q('Description')).text = (
        'Synthetic Puregene/DNeasy extraction, NanoDrop, Qubit and TapeStation coordinator in the existing DNA TLS service. '
        'One existing material root owns identities, stock, observations, resources and atomic network receipts. '
        'No hardware or ROS runtime. Command acceptance proves no physical effect or resource release.')
    ET.indent(root)
    return ET.tostring(root, encoding='unicode', xml_declaration=True) + '\n'


def build(directory=None):
    directory = Path(directory or ROOT / 'exports/generated/extraction-analytics-sila2/contracts').resolve()
    if not directory.is_relative_to(ROOT / 'exports'):
        raise ValueError('Generated extraction SiLA contracts must stay in exports/')
    data = load()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / 'ExtractionAnalyticsWorkflow-v1_0.sila.xml'
    target.write_text(feature(data), encoding='utf-8')
    report = {'format': 'solidcraftbot.extraction-analytics-sila-contract/1',
        'feature': str(target.relative_to(ROOT)), 'sha256': digest(target),
        'source_files_sha256': data['source_files_sha256'], 'simulation_only': True,
        'schema_validated': False, 'network_executed': False, 'hardware_executed': False, 'ros2_executed': False}
    (directory / 'generation-report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return target


if __name__ == '__main__':
    print(build())
