"""Run a purely synthetic NanoDrop task; all persistent output stays in exports/."""
import csv
import io

from nanodrop_manual import SOURCE, Workflow, inventory_observations
from manual_workflow_cli import output_path, run_cli

DEMO_ACTOR = 'SYN.Operator01'

def synthetic_report(state):
    """Fictitious report in intentionally reversed measurement order."""
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(['Application:', state['definition']['protocol']['method']])
    writer.writerow(['Serial Number:', state['definition']['profile']['instrument']['serial_number']])
    writer.writerow(['Sample Name', 'ng/µL', 'A260/A280', 'A260/A230', 'A260', 'Factor', 'Warnings'])
    for index, name in enumerate(reversed(list(state['planned_measurements'].values())), 1):
        writer.writerow([name, 20 + index, 1.8, 2.0, 0.4 + index / 100, 50, 'SYNTHETIC TEST DATA'])
    return stream.getvalue().encode('utf-8')

def run_demo(flow, pause_after_intent=False):
    """Only this explicit demo manufactures positive SYNTHETIC observations."""
    actor = DEMO_ACTOR
    flow.act('rack_ready', actor, observations=inventory_observations(flow.state))
    flow.act('workspace_clear', actor, confirmed=True)
    flow.act('claim', actor)
    flow.act('blank', actor, reference_id='SYN.Blank.Buffer01', cleaned=True)
    for sample_id, sample in flow.state['samples'].items():
        flow.act('take', actor, sample_id=sample_id, observed_sample_id=sample_id,
                 rack_id=sample['location']['rack_id'], place_id=sample['original_place_id'])
        flow.act('begin_measurement', actor, sample_id=sample_id,
                 measurement_id=flow.state['planned_measurements'][sample_id])
        if pause_after_intent:
            return
        flow.act('confirm_measurement', actor,
                 intent_id=flow.state['pending_measurement']['intent_id'],
                 observed_sample_id=sample_id,
                 volume_ul=flow.state['definition']['profile']['parameters']['sample_volume_ul'],
                 cleaned=True)
        flow.act('place', actor, sample_id=sample_id, observed_sample_id=sample_id,
                 rack_id=flow.state['definition']['profile']['rack']['id'],
                 place_id=sample['original_place_id'])
    content = synthetic_report(flow.state)
    file = output_path(flow.journal.path.parent / flow.run_id / 'synthetic-report.csv')
    file.write_bytes(content)
    flow.import_file(file, actor)
    flow.act('review_results', actor, decision='accepted', reason='Explicit synthetic demo decision; no real QC qualification')
    flow.act('release', actor, workspace_clear=True)

def main():
    return run_cli(Workflow, SOURCE, run_demo, __doc__)


if __name__ == '__main__':
    raise SystemExit(main())
