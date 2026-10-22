from optimus_swarm.environmental_cues import CueEvaluation, CueSeverity, ResponseKind


def present_cues(evaluation: CueEvaluation) -> dict:
    visual_cues = []
    audio_cues = []
    for cue in evaluation.cues:
        visual_cues.append(
            {
                "cue_id": cue.cue_id,
                "robot_id": cue.robot_id,
                "title": cue.title,
                "message": cue.message,
                "severity": cue.severity.value,
                "evidence_class": cue.evidence_class.value,
                "evidence_id": cue.evidence_id,
                "source_id": cue.source_id,
                "response": cue.response.value,
                "physical_execution_permitted": False,
            }
        )
        if cue.severity in (CueSeverity.WARNING, CueSeverity.CRITICAL):
            audio_cues.append(
                {
                    "cue_id": cue.cue_id,
                    "suggested_tone": "urgent" if cue.severity == CueSeverity.CRITICAL else "warning",
                    "message": cue.title,
                    "requires_ui_confirmation": True,
                }
            )

    blocked = any(cue.response == ResponseKind.BLOCK_PROPOSAL for cue in evaluation.cues)
    return {
        "interpretation_id": evaluation.interpretation_id,
        "evaluation_accepted": evaluation.accepted,
        "issues": list(evaluation.issues),
        "visual_cues": visual_cues,
        "audio_cues": audio_cues,
        "response_blocked": blocked or not evaluation.accepted,
        "mode": "SIMULATION_ONLY",
        "physical_execution_permitted": False,
    }
