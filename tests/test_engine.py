from mcp_server_redaction.engine import RedactionEngine


class TestRedactionEngine:
    def setup_method(self):
        self.engine = RedactionEngine()

    def test_redact_email(self):
        result = self.engine.redact("Contact john@example.com for info")
        assert "john@example.com" not in result["redacted_text"]
        assert "[EMAIL_ADDRESS_1]" in result["redacted_text"]
        assert result["entities_found"] >= 1
        assert "session_id" in result

    def test_redact_preserves_non_sensitive_text(self):
        result = self.engine.redact("Hello world")
        assert result["redacted_text"] == "Hello world"
        assert result["entities_found"] == 0

    def test_redact_multiple_same_type(self):
        result = self.engine.redact("Email a@b.com and c@d.com")
        text = result["redacted_text"]
        assert "[EMAIL_ADDRESS_1]" in text
        assert "[EMAIL_ADDRESS_2]" in text
        assert result["entities_found"] >= 2

    def test_unredact_restores_original(self):
        original = "Contact john@example.com for info"
        redact_result = self.engine.redact(original)
        unredact_result = self.engine.unredact(
            redact_result["redacted_text"], redact_result["session_id"]
        )
        assert unredact_result["original_text"] == original
        assert unredact_result["entities_restored"] >= 1

    def test_unredact_unknown_session_raises(self):
        result = self.engine.unredact("some text", "nonexistent-session-id")
        assert "error" in result

    def test_analyze_returns_entities_with_partial_mask(self):
        result = self.engine.analyze("Contact john@example.com")
        assert len(result["entities"]) >= 1
        entity = result["entities"][0]
        assert entity["type"] == "EMAIL_ADDRESS"
        assert "score" in entity
        # Partially masked — should not show the full email
        assert entity["text"] != "john@example.com"

    def test_redact_with_entity_type_filter(self):
        text = "John Smith john@example.com"
        result = self.engine.redact(text, entity_types=["EMAIL_ADDRESS"])
        assert "[EMAIL_ADDRESS_1]" in result["redacted_text"]
        # PERSON should NOT be redacted since we filtered to EMAIL only
        assert "John Smith" in result["redacted_text"] or "[PERSON" not in result["redacted_text"]
