"""Derive B0 ROS action definitions; no ROS imports, build or execution."""
import argparse
import json
from pathlib import Path

from dna_quantification_tasks import fields, load_contract
from manual_tasks import TaskError, digest
from manual_workflow import ROOT


def action_text(contract):
    sections = []
    for section in ['goal', 'result', 'feedback']:
        lines = ['# Generated from ' + contract['source_path'],
                 '# Contract SHA-256: ' + contract['source_sha256'],
                 '# B0 synthetic semantic fields only; no ROS or robot motion executed.']
        for field in fields(contract, section):
            lines.extend(['# ' + field['description'], field['ros_type'] + ' ' + field['name']])
        sections.append('\n'.join(lines))
    return '\n---\n'.join(sections) + '\n'


def build(output=None, contract=None):
    contract = load_contract() if contract is None else contract
    protocol = contract['protocol']; package_name = protocol['ros_package']
    package = (ROOT / 'ros2_ws/src' / package_name if output is None else Path(output)).resolve()
    if not package.is_relative_to(ROOT):
        raise TaskError('Generated DNA task package must stay in this project')
    action = 'action/' + protocol['action_name'] + '.action'
    files = {
        action: action_text(contract),
        'CMakeLists.txt': '\n'.join([
            'cmake_minimum_required(VERSION 3.8)', 'project(' + package_name + ')',
            'find_package(ament_cmake REQUIRED)', 'find_package(rosidl_default_generators REQUIRED)',
            'find_package(action_msgs REQUIRED)', 'rosidl_generate_interfaces(${PROJECT_NAME}',
            '  "' + action + '"', '  DEPENDENCIES action_msgs', ')',
            'ament_export_dependencies(rosidl_default_runtime)', 'ament_package()', '']),
        'package.xml': '\n'.join([
            '<?xml version="1.0"?>', '<package format="3">', '  <name>' + package_name + '</name>',
            '  <version>0.1.0</version>', '  <description>Generated B0 synthetic DNA task fields; no ROS node or motion.</description>',
            '  <maintainer email="maintainers@example.invalid">SolidCraftBot contributors</maintainer>',
            '  <license>UNLICENSED</license>', '  <buildtool_depend>ament_cmake</buildtool_depend>',
            '  <build_depend>rosidl_default_generators</build_depend>', '  <exec_depend>rosidl_default_runtime</exec_depend>',
            '  <depend>action_msgs</depend>', '  <member_of_group>rosidl_interface_packages</member_of_group>',
            '  <export><build_type>ament_cmake</build_type></export>', '</package>', ''])}
    for relative, content in files.items():
        path = package / relative; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
    report = {'format': 'solidcraftbot.dna-ros-interfaces/1', 'package': package_name,
              'action': protocol['action_name'], 'source': contract['source_path'],
              'source_sha256': contract['source_sha256'],
              'generator_sha256': digest(Path(__file__).read_bytes()),
              'decoder_sha256': digest((ROOT / 'scripts/dna_quantification_tasks.py').read_bytes()),
              'artifacts': {relative: digest((package / relative).read_bytes()) for relative in files},
              'runtime': {'ros2_built': False, 'ros2_executed': False,
                          'motion_executed': False, 'hardware_executed': False},
              'limitations': protocol['limitations']}
    (package / 'transport-contract.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Generated package folder inside this project')
    args = parser.parse_args(argv)
    print(json.dumps(build(args.output), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
