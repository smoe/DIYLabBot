"""Synthetic Puregene cultured-cell extraction and manual TapeStation QC; no hardware."""
from extraction_cli import run_cli
from puregene_extraction_demo import run_demo
from puregene_extraction_workflow import PuregeneWorkflow


def main(argv=None):
    return run_cli(PuregeneWorkflow, run_demo, __doc__, argv)


if __name__ == '__main__':
    raise SystemExit(main())
