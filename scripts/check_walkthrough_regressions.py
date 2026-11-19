"""Run a walkthrough test pattern and reject skipped or undiscovered checks."""
import argparse
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pattern', required=True, help='unittest discovery pattern')
    parser.add_argument('--start-directory', type=Path, default=ROOT/'tests')
    parser.add_argument('--report', type=Path, help='Optional JSON result beneath exports/')
    args = parser.parse_args(argv)
    if args.report:
        args.report = args.report.resolve()
        if not args.report.is_relative_to((ROOT/'exports').resolve()):
            parser.error('--report must be beneath the ignored repository exports/ directory')

    suite = unittest.TestLoader().discover(str(args.start_directory.resolve()), pattern=args.pattern)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    passed = result.wasSuccessful() and not result.skipped and result.testsRun > 0
    report = {
        'format': 'solidcraftbot.walkthrough-regressions/1',
        'pattern': args.pattern,
        'tests_run': result.testsRun,
        'failures': len(result.failures),
        'errors': len(result.errors),
        'skipped': len(result.skipped),
        'expected_failures': len(result.expectedFailures),
        'unexpected_successes': len(result.unexpectedSuccesses),
        'skipped_tests': [{'test_id': test.id(), 'reason': reason} for test, reason in result.skipped],
        'passed': passed,
    }
    if result.skipped:
        print('Walkthrough CI requires every selected test to run; skips are failures.', file=sys.stderr)
    if result.testsRun == 0:
        print('Walkthrough CI selected no tests; check the discovery pattern.', file=sys.stderr)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
