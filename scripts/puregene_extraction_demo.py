"""Explicit fictional observations for the synthetic Puregene/TapeStation demo."""
from extraction_demo import REASON, actual_inputs, phase_observations
from extraction_demo import perform_phase as _perform_phase, run_demo as _run_demo
from puregene_extraction_sources import load
from puregene_extraction_workflow import PuregeneWorkflow

ACTOR = 'SYN.Puregene.Operator'


def perform_phase(flow, sample_id, step, *, pause_before_confirmation=False):
    return _perform_phase(flow, sample_id, step, actor_id=ACTOR,
                          pause_before_confirmation=pause_before_confirmation)


def run_demo(journal, run_id=None, source=None, pause_after=None):
    return _run_demo(journal, workflow_class=PuregeneWorkflow, definition_loader=load,
                     run_prefix='SYN.PUREGENE.', actor_id=ACTOR,
                     run_id=run_id, source=source, pause_after=pause_after)
