from runtime import _specialist_output_indicates_failure


def test_specialist_output_insufficient_evidence_is_failure() -> None:
    output = (
        "I need the authorized sandbox path and task ID to inspect the project. "
        "No repository evidence or status has been provided yet, so I can't "
        "reliably summarize progress or priorities."
    )

    assert _specialist_output_indicates_failure(output) is True
