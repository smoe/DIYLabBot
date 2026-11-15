#!/usr/bin/env python3
"""CLI for opt-in synthetic extraction and three complementary DNA-QC methods."""
from extraction_cli import run_cli
from extraction_analytics_demo import run_demo
from extraction_analytics_workflow import ExtractionAnalyticsWorkflow


if __name__ == '__main__':
    raise SystemExit(run_cli(ExtractionAnalyticsWorkflow, run_demo,
        'Synthetic Puregene/DNeasy extraction -> NanoDrop -> Qubit 4 -> TapeStation; no hardware.'))
