"""Describe a candidate CUT&RUN input-sonication plan without laboratory effects."""
import argparse
import json
from pathlib import Path

from dna_sonication import ROOT, SOURCE, TaskError, compile_plan


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise TaskError(message)


def output_path(value):
    path = Path(value).resolve()
    directory = (ROOT / 'exports').resolve()
    if (path == directory or not directory.is_relative_to(ROOT.resolve())
            or not path.is_relative_to(directory) or path.suffix != '.json'):
        raise TaskError('Sonication output must be a new JSON file inside this project exports/')
    return path


def main(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument('--profile', type=Path, default=SOURCE)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--require-complete', action='store_true')
    try:
        args = parser.parse_args(argv)
        plan = compile_plan(args.profile)
        content = json.dumps(plan, ensure_ascii=False, allow_nan=False, indent=2) + '\n'
        if args.out is not None:
            path = output_path(args.out)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('x', encoding='utf-8') as stream:
                stream.write(content)
        print(content, end='')
        return 2 if args.require_complete and not plan['planning_complete'] else 0
    except (TaskError, ValueError, OSError, TypeError, OverflowError) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
