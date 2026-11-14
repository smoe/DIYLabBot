"""Synthetic DNeasy 69504 extraction and manual TapeStation QC; no hardware."""
from extraction_cli import run_cli
from dneasy_extraction_demo import run_demo
from dneasy_extraction_workflow import DNeasyWorkflow


def main(argv=None):
    return run_cli(DNeasyWorkflow, run_demo, __doc__, argv)


if __name__ == '__main__':
    raise SystemExit(main())
