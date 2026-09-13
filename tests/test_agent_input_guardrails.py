import pytest

from agent import enforce_agent_input_limit


def test_agent_input_guardrail_rejects_oversized_text_without_model_request() -> None:
    with pytest.raises(RuntimeError, match="No OpenAI request was sent"):
        enforce_agent_input_limit(
            "x" * 11,
            max_chars=10,
        )


def test_agent_input_guardrail_allows_text_within_limit() -> None:
    enforce_agent_input_limit("x" * 10, max_chars=10)
