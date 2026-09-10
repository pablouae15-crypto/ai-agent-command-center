from __future__ import annotations

from agent import SpecialistOutcome


def test_specialist_outcome_accepts_completed() -> None:
    outcome = SpecialistOutcome(
        status="completed",
        summary="Work completed.",
        evidence=["pytest passed"],
    )

    assert outcome.status == "completed"
    assert outcome.summary == "Work completed."
    assert outcome.evidence == ["pytest passed"]


def test_specialist_outcome_accepts_blocked() -> None:
    outcome = SpecialistOutcome(
        status="blocked",
        summary="Approval is required.",
        evidence=[],
    )

    assert outcome.status == "blocked"


def test_specialist_outcome_accepts_failed() -> None:
    outcome = SpecialistOutcome(
        status="failed",
        summary="Verification failed.",
        evidence=["pytest failed"],
    )

    assert outcome.status == "failed"


def test_specialist_outcome_accepts_partial() -> None:
    outcome = SpecialistOutcome(
        status="partial",
        summary="Inspection completed but implementation was not.",
        evidence=["repository inspected"],
    )

    assert outcome.status == "partial"


def test_specialist_outcome_summary_is_plain_text_compatible() -> None:
    outcome = SpecialistOutcome(
        status="completed",
        summary="Verified work completed.",
        evidence=["pytest passed"],
    )

    assert outcome.summary == "Verified work completed."

def test_specialist_outcome_status_schema_defines_completed_inspection_semantics() -> None:
    description = SpecialistOutcome.model_fields["status"].description or ""

    assert "inspection" in description.lower()
    assert "disproved" in description.lower()
    assert "completed" in description.lower()
