"""Reject empty, skipped or failed ROS CI tests, including missing live checks."""
import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET

REQUIRED = 'test_live_mock_stationary_hold'


def check(directory):
    files = sorted(Path(directory).rglob('*.xml'))
    results = []
    for path in files:
        root = ET.parse(path).getroot()
        if root.tag not in {'testsuite', 'testsuites'}:
            continue
        for suite in root.iter('testsuite'):
            if any(int(suite.get(field, '0')) for field in ('failures', 'errors', 'skipped')):
                raise ValueError('ROS CI JUnit suite reports failures, errors or skipped tests')
        for case in root.iter('testcase'):
            results.append({'file': str(path), 'name': case.get('name', ''),
                            'classname': case.get('classname', ''),
                            'failed': case.find('failure') is not None or case.find('error') is not None,
                            'skipped': case.find('skipped') is not None})
    if not results:
        raise ValueError('ROS CI discovered no JUnit test cases')
    if any(row['failed'] or row['skipped'] for row in results):
        raise ValueError('ROS CI requires every test to pass without skips')
    if not any(row['name'] == REQUIRED for row in results):
        raise ValueError('ROS CI is missing the live stationary mock action test')
    return {'passed': True, 'tests': len(results), 'results': results,
            'scope': 'Installed package and ROS mock middleware/controller checks; not hardware or motion qualification.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    result = check(args.directory)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print('ROS CI tests passed without skips:', result['tests'])


if __name__ == '__main__':
    main()
