"""Run a fully synthetic Qubit-4 task on the shared manual workflow store."""
import csv
import io

from manual_workflow import inventory_observations
from manual_workflow_cli import output_path, run_cli
from qubit_manual import Workflow, SOURCE, calibration_binding, next_preparation
from qubit_csv import FORMAT

ACTOR = 'SYN.Operator01'


def begin_preparation(flow, kind, target_id):
    state = flow.state
    occupied = [v['location'] for v in state['derived_vessels'].values()]
    place = next(place for place in state['definition']['profile']['logical_places']
                 if {'kind': 'logical', **place} not in occupied)
    tube_id = next_preparation(state) + '.Tube'
    flow.act('begin_preparation', ACTOR, kind=kind, target_id=target_id,
             vessel_id=tube_id, observed_vessel_id=tube_id, empty_tube_confirmed=True, **place)
    return flow.state['pending_operation']


def confirm_preparation(flow):
    state = flow.state
    pending = state['pending_operation']
    preparation = state['preparations'][pending['preparation_id']]
    parameters = state['definition']['profile']['parameters']
    flow.act('confirm_preparation', ACTOR, intent_id=pending['intent_id'],
             observed_vessel_id=pending['vessel_id'],
             observed_sample_id=preparation['target_id'] if preparation['kind'] == 'sample' else None,
             volume_ul=parameters['sample_volume_ul' if preparation['kind'] == 'sample' else 'standard_volume_ul'],
             assay_total_volume_ul=parameters['assay_total_volume_ul'], mixed=True)


def measure(flow, preparation_id):
    state = flow.state
    preparation = state['preparations'][preparation_id]
    flow.act('begin_measurement', ACTOR, preparation_id=preparation_id,
             measurement_id=preparation['measurement_id'], observed_vessel_id=preparation['vessel_id'],
             calibration_id=state['calibration']['id'] if preparation['kind'] == 'sample' else None)
    flow.act('confirm_measurement', ACTOR, intent_id=flow.state['pending_operation']['intent_id'],
             observed_vessel_id=preparation['vessel_id'], returned_to_holder=True)


def prepare_standards(flow):
    for standard in flow.state['definition']['protocol']['assay']['standards']:
        begin_preparation(flow, 'standard', standard['id'])
        confirm_preparation(flow)
    flow.act('advance_time', ACTOR, seconds=flow.state['definition']['profile']['parameters']['incubation_min_s'])
    for key in list(flow.state['preparations']):
        measure(flow, key)
    state = flow.state
    mapping = {preparation['target_id']: preparation['measurement_id']
               for preparation in state['preparations'].values() if preparation['kind'] == 'standard'}
    flow.act('approve_calibration', ACTOR, binding=calibration_binding(state),
             standard_measurements=mapping, confirmed=True,
             reason='Explicit synthetic approval after confirmed standards; no calibration curve computed')


def synthetic_report(state):
    """Synthetic internal layout; calibration IDs are deliberately not device data."""
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(['Format', FORMAT])
    writer.writerow(['Measurement ID', 'Record Type', 'Vessel ID', 'Assay ID', 'Assay Revision',
                     'Kit Lot', 'Standard Lot', 'Instrument Serial', 'Tube Concentration', 'Tube Unit',
                     'Original Concentration', 'Original Unit', 'Sample Volume uL', 'Warnings', 'Assay Total Volume uL'])
    binding = calibration_binding(state)
    for index, measurement in enumerate(reversed(list(state['measurements'].values())), 1):
        preparation = state['preparations'][measurement['preparation_id']]
        tube = 0.1 * index
        # Mixed explicit units exercise conversion; alternate samples omit the
        # original concentration to exercise one documented derivation.
        unit = 'ng/mL' if index % 2 == 0 else 'ng/uL'
        reported_tube = tube * 1000 if unit == 'ng/mL' else tube
        original = tube * preparation['assay_total_volume_ul'] / preparation['sample_volume_ul']
        supplied = preparation['kind'] == 'sample' and index % 2 == 0
        writer.writerow([measurement['measurement_id'], preparation['kind'], preparation['vessel_id'],
                         binding['assay_id'], binding['assay_revision'], binding['kit_lot'],
                         binding['standard_lot'], binding['instrument_serial'], reported_tube, unit,
                         original * 1000 if supplied else '', 'ng/mL' if supplied else '',
                         preparation['sample_volume_ul'], 'SYNTHETIC TEST DATA', preparation['assay_total_volume_ul']])
    return stream.getvalue().encode('utf-8')


def run_demo(flow, pause_after_intent=False):
    flow.act('rack_ready', ACTOR, observations=inventory_observations(flow.state))
    flow.act('workspace_clear', ACTOR, confirmed=True)
    flow.act('claim', ACTOR)
    prepare_standards(flow)
    for sample_id, sample in flow.state['samples'].items():
        flow.act('take', ACTOR, sample_id=sample_id, observed_sample_id=sample_id,
                 rack_id=sample['location']['rack_id'], place_id=sample['original_place_id'])
        begin_preparation(flow, 'sample', sample_id)
        if pause_after_intent:
            return
        confirm_preparation(flow)
        flow.act('place', ACTOR, sample_id=sample_id, observed_sample_id=sample_id,
                 rack_id=flow.state['definition']['profile']['rack']['id'], place_id=sample['original_place_id'])
    flow.act('advance_time', ACTOR, seconds=flow.state['definition']['profile']['parameters']['incubation_min_s'])
    for key, preparation in flow.state['preparations'].items():
        if preparation['kind'] == 'sample':
            measure(flow, key)
    for vessel_id in flow.state['derived_vessels']:
        flow.act('dispose_vessel', ACTOR, vessel_id=vessel_id, observed_vessel_id=vessel_id,
                 reason='Explicit synthetic tube disposal after measurement')
    file = output_path(flow.journal.path.parent / flow.run_id / 'synthetic-report.csv')
    file.write_bytes(synthetic_report(flow.state))
    flow.import_file(file, ACTOR)
    flow.act('review_results', ACTOR, decision='accepted', reason='Explicit synthetic test decision')
    flow.act('release', ACTOR, workspace_clear=True)


def main():
    return run_cli(Workflow, SOURCE, run_demo, __doc__)


if __name__ == '__main__':
    raise SystemExit(main())
