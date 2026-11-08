"""Stable NanoDrop behavior projection, captured before the shared-core extraction."""
import copy


def project(report):
    def clean(value):
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items()
                    if k not in {'intent_id', 'artifact_sha256', 'initial_volume_source'}}
        if isinstance(value, list):
            return [clean(v) for v in value]
        return value

    result = {key: clean(copy.deepcopy(report[key])) for key in [
        'format', 'run_id', 'attempt_id', 'mode', 'passed', 'status', 'order_restored',
        'recovery_required', 'samples', 'measurements', 'results', 'result_review',
        'network_executed', 'hardware_executed', 'robot_motion_executed',
        'safety_function_qualified', 'real_export_validated', 'cf01_continuation_executed']}
    result['trace'] = [{'kind': event['kind'],
                        'samples': {key: {k: clean(sample[k]) for k in [
                            'location', 'remaining_volume_ul', 'volume_uncertain']}
                                    for key, sample in event['state']['samples'].items()}}
                       for event in report['trace']]
    return result
