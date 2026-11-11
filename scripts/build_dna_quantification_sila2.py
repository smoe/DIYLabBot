"""Generate the additive simulation-only DNA SiLA feature; no SDK is required."""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from manual_tasks import TaskError
from manual_workflow import ROOT, keys, positive
from dna_quantification_sources import load as load_dna

SOURCE = ROOT / 'model/dna-quantification-sila2.shared.json'
NS = 'http://www.sila-standard.org'
Q = lambda name: '{' + NS + '}' + name
COMMANDS = {'CreateRun', 'RunUntilDecision', 'ChooseDilution', 'AcceptResult',
            'ResumeRun', 'ReconcileInventory', 'CancelRun', 'FinishCancel'}
ERRORS = ['WorkflowRejected', 'RecoveryRequired', 'CommandCanceled', 'PersistenceFailure']


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def camel(name):
    return ''.join(part[:1].upper() + part[1:] for part in name.split('_'))


def load(path=SOURCE):
    path = Path(path).resolve()
    data = json.loads(path.read_text(encoding='utf-8'))
    keys(data, 'format id mode dna_profile dna_protocol task_contract feature commands standard_features runtime_sources publish_interval_s limitations', 'DNA SiLA profile')
    if data['format'] != 'solidcraftbot.dna-sila2/1' or data['mode'] != 'synthetic_only':
        raise ValueError('Simulation-only DNA SiLA profile required')
    sources = {}

    def remember(file):
        file = Path(file).resolve()
        if not file.is_relative_to(ROOT):
            raise ValueError('DNA SiLA sources must stay in the project')
        sources[str(file.relative_to(ROOT))] = digest(file)

    for name in ['dna_profile', 'dna_protocol', 'task_contract']:
        ref = data[name]
        keys(ref, 'source source_sha256', 'DNA SiLA source reference')
        file = (ROOT / ref['source']).resolve()
        if not file.is_relative_to(ROOT / 'model') or digest(file) != ref['source_sha256']:
            raise ValueError('Changed DNA SiLA source: ' + ref['source'])
        remember(file)
    dna = load_dna(ROOT / data['dna_profile']['source'])
    if dna['profile']['protocol'] != data['dna_protocol']:
        raise ValueError('DNA SiLA profile and protocol pins disagree')
    sources.update(dna['source_files_sha256'])
    expected = {'SiLAService', 'AuthenticationService', 'AuthorizationService', 'LockController', 'CancelController', 'SimulationController'}
    if {ref['identifier'] for ref in data['standard_features']} != expected or len(data['standard_features']) != len(expected):
        raise ValueError('Exactly the archived standard features are required')
    for ref in data['standard_features']:
        keys(ref, 'identifier source source_sha256 upstream_path', 'standard feature reference')
        file = (ROOT / ref['source']).resolve()
        if not file.is_relative_to(ROOT / 'interfaces/sila2/standard') or digest(file) != ref['source_sha256']:
            raise ValueError('Changed standard feature: ' + ref['identifier'])
        if ref['identifier'] == 'LockController' and file.name != 'LockController-v1_0.sila.xml':
            raise ValueError('LockController v1.0 must remain pinned')
        remember(file)
    feature = data['feature']
    keys(feature, 'identifier originator category version sila_version maturity locale', 'DNA feature')
    if feature != {'identifier': 'DnaQuantificationWorkflow', 'originator': 'org.solidcraftbot', 'category': 'analytics',
                   'version': '1.0', 'sila_version': '1.1', 'maturity': 'Draft', 'locale': 'en-us'}:
        raise ValueError('Unsupported DNA feature identity')
    commands = data['commands']
    if {c['name'] for c in commands} != COMMANDS or len(commands) != len(COMMANDS):
        raise ValueError('Exactly the supported DNA commands are required')
    for command in commands:
        keys(command, 'name observable arguments', 'DNA SiLA command')
        if command['observable'] is not (command['name'] == 'RunUntilDecision'):
            raise ValueError('Only RunUntilDecision is observable')
        fields = command['arguments']
        if len({f['name'] for f in fields}) != len(fields):
            raise ValueError('Duplicate DNA command parameter')
        if [f['name'] for f in fields[:2]] != ['request_identifier', 'run_identifier']:
            raise ValueError('Every mutation requires request and root run identifiers')
        for field in fields:
            keys(field, 'name type description', 'DNA command field')
            if field['type'] not in {'string', 'float64', 'bool'} or field['name'] == 'pause_after':
                raise ValueError('Unsupported DNA network parameter')
    for name in data['runtime_sources']:
        file = (ROOT / name).resolve()
        if not file.is_relative_to(ROOT / 'scripts'):
            raise ValueError('DNA runtime source must stay in scripts/')
        remember(file)
    positive(data['publish_interval_s'], 'status publication interval')
    remember(path)
    remember(ROOT / 'model/dna-quantification-sila2.schema.json')
    return {**data, 'source_files_sha256': sources}


def header(parent, identifier, description):
    for key, value in [('Identifier', identifier), ('DisplayName', identifier), ('Description', description)]:
        ET.SubElement(parent, Q(key)).text = value


def value(parent, tag, identifier, kind, description):
    node = ET.SubElement(parent, Q(tag))
    header(node, identifier, description)
    ET.SubElement(ET.SubElement(node, Q('DataType')), Q('Basic')).text = {
        'string': 'String', 'bool': 'Boolean', 'float64': 'Real'}[kind]
    return node


def feature(data=None):
    data = load() if data is None else data
    f = data['feature']
    ET.register_namespace('', NS)
    root = ET.Element(Q('Feature'), {'SiLA2Version': f['sila_version'], 'FeatureVersion': f['version'],
        'MaturityLevel': f['maturity'], 'Originator': f['originator'], 'Category': f['category'], 'Locale': f['locale']})
    header(root, f['identifier'], 'Synthetic DNA NanoDrop/Qubit coordinator over TLS. The existing root Journal owns all stock, observations and atomic network receipts. No hardware or ROS runtime. Command acceptance does not prove transfer, measurement, cancellation clearance or release.')
    for source in data['commands']:
        command = ET.SubElement(root, Q('Command'))
        header(command, source['name'], 'Simulation-only root operation ' + source['name'] + '; explicit reconciliation is required after uncertainty. Request identifiers are durable and cannot silently repeat effects.')
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
            ('Report', False, 'Read-only full JSON root report with original artifacts and scientific limits; no new sample ledger.')]:
        prop = ET.SubElement(root, Q('Property'))
        header(prop, identifier, description)
        ET.SubElement(prop, Q('Observable')).text = 'Yes' if observable else 'No'
        ET.SubElement(ET.SubElement(prop, Q('DataType')), Q('Basic')).text = 'String'
    for identifier in ERRORS:
        header(ET.SubElement(root, Q('DefinedExecutionError')), identifier,
               'Root operation refused or uncertain: ' + identifier + '. Inspect root status; never replay or release custody automatically.')
    ET.indent(root)
    return ET.tostring(root, encoding='unicode', xml_declaration=True) + '\n'


def build(directory=None):
    directory = Path(directory or ROOT / 'exports/generated/dna-sila2/contracts').resolve()
    if not directory.is_relative_to(ROOT / 'exports'):
        raise ValueError('Generated DNA contracts must stay in exports/')
    data = load()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / 'DnaQuantificationWorkflow-v1_0.sila.xml'
    target.write_text(feature(data), encoding='utf-8')
    report = {'format': 'solidcraftbot.dna-sila-contract/1', 'feature': str(target.relative_to(ROOT)),
              'sha256': digest(target), 'source_files_sha256': data['source_files_sha256'],
              'schema_validated': False, 'network_executed': False, 'hardware_executed': False, 'ros2_executed': False}
    (directory / 'generation-report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return target


if __name__ == '__main__':
    print(build())
