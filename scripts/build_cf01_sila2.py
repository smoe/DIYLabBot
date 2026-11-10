"""Generate the CF01 v2 network FDL from the shared transport profile.

The local v1/ROS contracts and historical media are not rewritten. Requires only
the standard library; SDK/XSD validation is a separate network test dependency.
"""
import copy
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import build_centrifuge_interfaces as base
import centrifuge_model as model
import centrifuge_protocol as protocol

ROOT = model.ROOT
SOURCE = ROOT / 'model/cf01-sila2.shared.json'
NS = base.NS
Q = lambda name: '{' + NS + '}' + name


def load(path=SOURCE):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if data['format'] != 'solidcraftbot.cf01-sila2/1':
        raise ValueError('CF01 SiLA 2 profile required')
    if data['journal_format'] != 'solidcraftbot.cf01-intents/1':
        raise ValueError('Unsupported station journal format; no automatic migration')
    sources = {}
    for key in ('protocol', 'station', 'network_batch'):
        ref = data[key]
        source = (ROOT / ref['source']).resolve()
        if not source.is_relative_to(ROOT / 'model'):
            raise ValueError('Shared sources must stay in model/')
        if hashlib.sha256(source.read_bytes()).hexdigest() != ref['source_sha256']:
            raise ValueError('Changed shared source: ' + ref['source'])
        sources[key] = json.loads(source.read_text(encoding='utf-8'))
    for ref in data['standard_features']:
        source = (ROOT / ref['source']).resolve()
        if not source.is_relative_to(ROOT / 'interfaces/sila2/standard') or model.digest(source) != ref['source_sha256']:
            raise ValueError('Changed standard feature: ' + ref['identifier'])
    commands = [c for c in sources['protocol']['commands'] if c['id'] not in data['excluded_commands']]
    if set(data['command_errors']) != {c['id'] for c in commands}:
        raise ValueError('Every network command needs its own declared errors')
    return data, sources, commands


def header(parent, identifier, description):
    for name, value in [('Identifier', identifier), ('DisplayName', identifier), ('Description', description)]:
        ET.SubElement(parent, Q(name)).text = value


def data_type(parent, definition):
    """Generate the declared projection, including nested station observations."""
    node = ET.SubElement(parent, Q('DataType'))
    kind = definition['type']
    if kind == 'list':
        data_type(ET.SubElement(node, Q('List')), definition['element'])
    elif kind == 'structure':
        structure = ET.SubElement(node, Q('Structure'))
        for field in definition['fields']:
            element = ET.SubElement(structure, Q('Element'))
            header(element, base.camel(field['name']), field['description'])
            data_type(element, field)
    else:
        ET.SubElement(node, Q('Basic')).text = {
            'float64': 'Real', 'int64': 'Integer', 'bool': 'Boolean', 'string': 'String'}[kind]


def constrained(parameter, rule, station):
    dt = parameter.find(Q('DataType'))
    underlying = copy.deepcopy(dt)
    dt.clear()
    node = ET.SubElement(dt, Q('Constrained'))
    node.append(underlying)
    constraints = ET.SubElement(node, Q('Constraints'))
    for key, tag in [('minimum', 'MinimalInclusive'), ('exclusive_minimum', 'MinimalExclusive')]:
        if key in rule:
            ET.SubElement(constraints, Q(tag)).text = str(rule[key])
    if 'maximum_reference' in rule:
        value = station
        for key in rule['maximum_reference']:
            value = value[key]
        ET.SubElement(constraints, Q('MaximalInclusive')).text = str(value)
    if 'unit' in rule:
        rule = rule['unit']
        unit = ET.SubElement(constraints, Q('Unit'))
        for tag, value in [('Label', rule['label']), ('Factor', rule['factor']), ('Offset', 0)]:
            ET.SubElement(unit, Q(tag)).text = str(value)
        for name, exponent in rule['components']:
            component = ET.SubElement(unit, Q('UnitComponent'))
            ET.SubElement(component, Q('SIUnit')).text = name
            ET.SubElement(component, Q('Exponent')).text = str(exponent)


def feature(data=None):
    profile, sources, commands = load() if data is None else data
    # Reuse the original state type and parameter definitions. Only the v2
    # transport contract changes; no command or geometry is reimplemented here.
    root = ET.fromstring(base.feature(sources['protocol']))
    f = profile['feature']
    root.attrib.update(SiLA2Version=f['sila_version'], FeatureVersion=f['version'],
                       MaturityLevel=f['maturity'], Originator=f['originator'],
                       Category=f['category'], Locale=f['locale'])
    root.find(Q('Description')).text = (
        'CF01 simulation-only network feature. LockIdentifier is standard metadata; '
        'RequestIdentifier identifies durable state-changing intents. Command acceptance '
        'and Stop acceptance do not prove completion or standstill. No hardware execution.')
    by_name = {c['name']: c for c in commands}
    for command in list(root.findall(Q('Command'))):
        name = command.findtext(Q('Identifier'))
        if name not in by_name:
            root.remove(command)
            continue
        source = by_name[name]
        for parameter in list(command.findall(Q('Parameter'))):
            key = parameter.findtext(Q('Identifier'))
            if key == 'ControlToken':
                command.remove(parameter)
                continue
            argument = next(k for k in source['arguments'] if base.camel(k) == key)
            if argument in profile['parameters']:
                constrained(parameter, profile['parameters'][argument], sources['station'])
        errors = command.find(Q('DefinedExecutionErrors'))
        errors.clear()
        for error in profile['command_errors'][source['id']]:
            ET.SubElement(errors, Q('Identifier')).text = error
        if not list(errors):
            command.remove(errors)
    for error in list(root.findall(Q('DefinedExecutionError'))):
        root.remove(error)
    declared = sorted({e for values in profile['command_errors'].values() for e in values})
    for error in declared:
        header(ET.SubElement(root, Q('DefinedExecutionError')), error,
               'CF01 process error: ' + error + '. Inspect Status; uncertain effects require reconciliation.')
    metadata = ET.SubElement(root, Q('Metadata'))
    header(metadata, 'RequestIdentifier', 'Unique UUID for one state-changing intent. Repeated identifiers are rejected without repeating effects.')
    ET.SubElement(ET.SubElement(metadata, Q('DataType')), Q('Basic')).text = 'String'
    structure = root.find(Q('DataTypeDefinition')).find('.//' + Q('Structure'))
    for field in profile['state_fields']:
        node = ET.SubElement(structure, Q('Element'))
        header(node, base.camel(field['name']), field['description'])
        data_type(node, field)
    ET.indent(root)
    return ET.tostring(root, encoding='unicode', xml_declaration=True) + '\n'


def simulation_feature(data=None):
    profile, sources, _ = load() if data is None else data
    definition = profile['simulation_feature']
    attributes = ET.fromstring(feature(data)).attrib
    attributes['FeatureVersion'] = definition['version']
    root = ET.Element(Q('Feature'), attributes)
    header(root, definition['identifier'], definition['description'])
    command = ET.SubElement(root, Q('Command'))
    header(command, definition['command'], definition['description'])
    ET.SubElement(command, Q('Observable')).text = 'No'
    for field in definition['parameters']:
        parameter = ET.SubElement(command, Q('Parameter'))
        header(parameter, base.camel(field['name']), field['description'])
        data_type(parameter, field)
        if field['name'] == 'slot':
            constrained(parameter, profile['parameters']['slot'], sources['station'])
    errors = ET.SubElement(command, Q('DefinedExecutionErrors'))
    for error in definition['errors']:
        ET.SubElement(errors, Q('Identifier')).text = error
        header(ET.SubElement(root, Q('DefinedExecutionError')), error,
               'Synthetic robot observation refused: ' + error + '. Inspect the station journal; never assume withdrawal.')
    ET.indent(root)
    return ET.tostring(root, encoding='unicode', xml_declaration=True) + '\n'


def build(directory=None):
    directory = Path(directory or ROOT / 'exports/generated/cf01-sila2/contracts')
    directory.mkdir(parents=True, exist_ok=True)
    fdl = directory / 'CentrifugeControl-v2_0.sila.xml'
    fdl.write_text(feature(), encoding='utf-8')
    observation = directory / 'SyntheticRobotObservation-v1_0.sila.xml'
    observation.write_text(simulation_feature(), encoding='utf-8')
    dependencies = [SOURCE, protocol.SOURCE, model.SOURCE, ROOT / load()[0]['network_batch']['source'], Path(__file__), Path(base.__file__),
                    *(ROOT / ref['source'] for ref in load()[0]['standard_features'])]
    report = {'source_files_sha256': {str(p.relative_to(ROOT)): model.digest(p)
              for p in dependencies},
              'feature': str(fdl.relative_to(ROOT)), 'sha256': model.digest(fdl),
              'simulation_feature': str(observation.relative_to(ROOT)), 'simulation_feature_sha256': model.digest(observation),
              'schema_validated': False, 'network_executed': False, 'hardware_executed': False}
    (directory / 'generation-report.json').write_text(json.dumps(report, indent=2) + '\n')
    return fdl


if __name__ == '__main__':
    print(build())
