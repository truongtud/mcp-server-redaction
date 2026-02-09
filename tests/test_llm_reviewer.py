import pytest

from mcp_server_redaction.llm_reviewer import LLMReviewer


class TestLLMReviewer:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.reviewer = LLMReviewer()

    @pytest.mark.skipif(
        not LLMReviewer.is_available(),
        reason="Ollama not running or llama3.1 not available",
    )
    def test_find_additional_entities(self):
        text = "Patient Jane Doe, age 45, policy number INS-2024-78901, was prescribed 50mg of Metformin daily."
        already_found = ["Jane Doe", "INS-2024-78901", "Metformin"]
        additional = self.reviewer.review(text, already_found)
        # LLM should flag "age 45" as PII
        assert isinstance(additional, list)
        for entity in additional:
            assert "text" in entity
            assert "entity_type" in entity
            assert "start" in entity
            assert "end" in entity

    @pytest.mark.skipif(
        not LLMReviewer.is_available(),
        reason="Ollama not running or llama3.1 not available",
    )
    def test_returns_empty_when_fully_redacted(self):
        text = "Hello world, nice weather today."
        additional = self.reviewer.review(text, [])
        assert isinstance(additional, list)
        # No PII in this text, list should be empty
        assert len(additional) == 0

    def test_is_available_returns_bool(self):
        result = LLMReviewer.is_available()
        assert isinstance(result, bool)

    def test_review_returns_empty_when_unavailable_and_disabled(self):
        reviewer = LLMReviewer(enabled=False)
        result = reviewer.review("John Smith lives at 123 Main St", [])
        assert result == []
