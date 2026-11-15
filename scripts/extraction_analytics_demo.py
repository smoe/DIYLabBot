"""Explicit fictional extraction, NanoDrop, Qubit and TapeStation observations.

Only this opt-in fixture driver invents positive observations and report bytes.
The device-operation and material validators never call its helpers.
"""
import uuid

from dna_quantification_demo import SyntheticBackend
from extraction_demo import REASON, perform_phase, run_tapestation
from manual_tasks import TaskError

ACTOR = 'SYN.ExtractionAnalytics.Operator'


class _DevicePort:
    """Adapt the existing measurement fixture driver to one material Root."""
    def __init__(self, flow):
        self.flow = flow

    def stage(self, device):
        return self.flow.device(device)

    def advance_time(self, actor_id, seconds):
        return self.flow.act('advance_time', actor_id, seconds=seconds)

    def finish_context(self, actor_id, device, workspace_clear):
        handle = self.stage(device)
        handle.act('review_results', actor_id, decision='accepted', reason=REASON)
        return handle.act('release', actor_id, workspace_clear=workspace_clear)


class SyntheticExtractionBackend(SyntheticBackend):
    """Reuse manual-device fixtures without creating another DNA inventory."""
    def _input_concentration(self, flow, context_id):
        if context_id not in {'nanodrop', 'qubit'}:
            raise TaskError('Unknown synthetic extraction measurement device')
        return self.original_concentrations[context_id]

    def run_device(self, flow, device, pause_after=None):
        port = _DevicePort(flow)
        if device == 'nanodrop':
            return self._run_nanodrop(port, device, pause_after)
        if device == 'qubit':
            return self._run_qubit(port, device, pause_after)
        raise TaskError('Unknown synthetic extraction measurement device')


def run_demo(journal, run_id=None, source=None, pause_after=None):
    """Create a fresh opt-in fixture; never replay interrupted effects."""
    from extraction_analytics_sources import load
    from extraction_analytics_workflow import ExtractionAnalyticsWorkflow

    definition = load(source)
    steps = definition['execution']['steps']
    markers = {step['id'] for step in steps}
    markers.update('before_confirm:' + step['id'] for step in steps)
    markers.update({'extracted', 'nanodrop', 'qubit', 'nanodrop_intent',
                    'qubit_intent', 'tapestation_loaded'})
    if pause_after is not None and pause_after not in markers:
        raise TaskError('Unknown integrated demo pause marker')
    flow = ExtractionAnalyticsWorkflow.create(journal, source=source,
        run_id=run_id or 'SYN.ExtractionQC.' + uuid.uuid4().hex[:12])
    try:
        flow.act('accept_inventory', ACTOR, observations=flow.inventory_observations())
        flow.act('workspace_clear', ACTOR, confirmed=True)
        flow.act('claim', ACTOR)
        for sample_id in definition['execution']['samples']:
            for step in steps:
                if not perform_phase(flow, sample_id, step, actor_id=ACTOR,
                        pause_before_confirmation=pause_after == 'before_confirm:' + step['id']):
                    return flow.report()
                if pause_after == step['id']:
                    return flow.report()
        if pause_after == 'extracted':
            return flow.report()
        backend = SyntheticExtractionBackend(actor_id=ACTOR)
        for device in ('nanodrop', 'qubit'):
            flow.act('start_device', ACTOR, device=device)
            if not backend.run_device(flow, device,
                    pause_after='measurement_intent' if pause_after == device + '_intent' else None):
                return flow.report()
            if pause_after == device:
                return flow.report()
        return run_tapestation(flow, definition, actor_id=ACTOR, pause_after=pause_after)
    finally:
        flow.close()
