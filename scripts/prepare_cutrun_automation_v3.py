"""Check the local CUT&RUN draft binding without creating a runtime or executing effects."""

import json
from pathlib import Path

from cutrun_preparation_v3 import SOURCE, compile_plan
from prepare_cutrun_automation import Parser, TaskError, output_path


def main(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument('--profile', type=Path, default=SOURCE)
    parser.add_argument('--original-pdf', type=Path)
    parser.add_argument('--out', type=Path)
    try:
        args = parser.parse_args(argv)
        report = compile_plan(args.profile, original_pdf=args.original_pdf)
        content = json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + '\n'
        if args.out is not None:
            target = output_path(args.out)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('x', encoding='utf-8') as stream:
                stream.write(content)
        print(content, end='')
        return 0
    except (TaskError, ValueError, TypeError, OSError) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
