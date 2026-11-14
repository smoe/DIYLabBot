"""DNeasy-specific binding of the common ordered extraction/TapeStation engine."""
from extraction_workflow import ExtractionWorkflow, number, require


class DNeasyWorkflow(ExtractionWorkflow):
    REPORT_FORMAT = 'solidcraftbot.dneasy-workflow-report/1'
    ENGINE = 'dneasy_synthetic/1'
    SOURCE_MODULE = 'dneasy_extraction_sources'
    RUN_PREFIX = 'SYN.DNEASY.'
    EFFECT_PREFIX = 'dneasy'
    RECOVERY_PREFIX = 'dneasy'
    WORK_AREA = 'SYN.DNeasy.WorkArea'
    LIMITATIONS = (
        'Synthetic ordered extraction and manual TapeStation fixture observations only; no real chemistry or device execution.',
        'DNA quantity and yield are never inferred from pellet count or recipe volumes.',
        'DIN, concentration and fragment-size estimates are separate synthetic observations; no real export decoder or biological acceptance is qualified.',
        'No hardware, network, robot motion, centrifuge/column compatibility or safety qualification.',
        'Single sample, single elution, one attempt per phase and one TapeStation assay; nonperformance or physical deviations require controlled abort.',
        'No independent-run stock handoff or automatic migration of old journals.',
    )
