"""Puregene-specific binding of the common ordered extraction/TapeStation engine."""
from extraction_workflow import ExtractionWorkflow


class PuregeneWorkflow(ExtractionWorkflow):
    REPORT_FORMAT = 'solidcraftbot.puregene-workflow-report/1'
    ENGINE = 'puregene_synthetic/1'
    SOURCE_MODULE = 'puregene_extraction_sources'
    RUN_PREFIX = 'SYN.PUREGENE.'
    EFFECT_PREFIX = 'puregene'
    RECOVERY_PREFIX = 'puregene'
    WORK_AREA = 'SYN.Puregene.WorkArea'
    LIMITATIONS = (
        'Synthetic Puregene cultured-cell sequence and manual TapeStation fixture observations only; no real chemistry or device execution.',
        'The original pellet and residual liquid are an explicit composite fixture; no DNA amount or extraction yield is inferred.',
        'Coexisting pellets and supernatants remain one canonical material until actual physical separation; named fraction metadata is not a second quantity ledger.',
        'Transfer-tip aspiration and dispense are unqualified automation adaptations of the handbook transfer.',
        'Overnight duration is an explicitly invented test-clock setting, not a manufacturer minimum or qualified SOP.',
        'DIN, concentration and fragment-size estimates are separate synthetic observations; no native export or biological acceptance is qualified.',
        'No hardware, network, robot motion, centrifuge/tube compatibility or safety qualification.',
        'One cultured-cell sample, one attempt per phase and one TapeStation assay; nonperformance or physical deviations require controlled abort.',
        'No independent-run stock handoff or automatic migration of old journals.',
    )
