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

    def test_redact_returns_entity_positions(self):
        result = self.engine.redact("Contact john@example.com for info")
        assert "entities" in result
        assert len(result["entities"]) >= 1
        entity = result["entities"][0]
        assert "original_start" in entity
        assert "original_end" in entity
        assert "placeholder" in entity
        assert "type" in entity
        # Verify positions point to actual PII in original text
        original_text = "Contact john@example.com for info"
        assert original_text[entity["original_start"]:entity["original_end"]] == "john@example.com"

    def test_redact_no_entities_returns_empty_list(self):
        result = self.engine.redact("Hello world")
        assert "entities" in result
        assert result["entities"] == []

    def test_redact_with_entity_type_filter(self):
        text = "John Smith john@example.com"
        result = self.engine.redact(text, entity_types=["EMAIL_ADDRESS"])
        assert "[EMAIL_ADDRESS_1]" in result["redacted_text"]
        # PERSON should NOT be redacted since we filtered to EMAIL only
        assert "John Smith" in result["redacted_text"] or "[PERSON" not in result["redacted_text"]


class TestHybridDetection:
    def setup_method(self):
        self.engine = RedactionEngine()

    def test_redact_detects_email_and_person(self):
        """Basic sanity: L1 regex + L2 GLiNER should both contribute."""
        text = "Contact John Smith at john@example.com"
        result = self.engine.redact(text)
        assert result["entities_found"] >= 2
        assert "[EMAIL_ADDRESS_" in result["redacted_text"]
        assert "[PERSON_" in result["redacted_text"]

    def test_redact_multilingual_name(self):
        """GLiNER should detect non-English names."""
        text = "Kontaktieren Sie Herrn Hans Müller für Details."
        result = self.engine.redact(text)
        # At minimum, GLiNER should detect the person name
        assert result["entities_found"] >= 1

    def test_llm_layer_disabled_by_default_in_tests(self):
        """LLM layer should not block engine when Ollama is not available."""
        engine = RedactionEngine(use_llm=False)
        text = "Test text with john@example.com"
        result = engine.redact(text)
        assert result["entities_found"] >= 1

    def test_engine_backward_compatible(self):
        """Existing interface unchanged: returns redacted_text, session_id, entities_found."""
        text = "My email is test@example.com"
        result = self.engine.redact(text)
        assert "redacted_text" in result
        assert "session_id" in result
        assert "entities_found" in result
        assert isinstance(result["session_id"], str)


class TestScoreThreshold:
    def test_default_threshold_filters_low_confidence(self):
        """Engine with default threshold (0.4) should not redact plain prose."""
        engine = RedactionEngine()
        text = "The sky is blue and the grass is green."
        result = engine.redact(text)
        assert result["entities_found"] == 0
        assert result["redacted_text"] == text

    def test_threshold_zero_accepts_more_than_default(self):
        """Threshold 0.0 should accept detections that 0.4 would reject."""
        text = "The sky is blue and the grass is green."
        default_engine = RedactionEngine(score_threshold=0.4)
        permissive_engine = RedactionEngine(score_threshold=0.0)
        assert permissive_engine.redact(text)["entities_found"] >= default_engine.redact(text)["entities_found"]

    def test_threshold_one_rejects_non_perfect_scores(self):
        """Threshold 1.0 should reject detections that score below 1.0."""
        engine = RedactionEngine(score_threshold=1.0)
        text = "Contact John Smith for details"
        result = engine.redact(text)
        # GLiNER name detection scores below 1.0, so should be filtered out
        assert result["entities_found"] == 0
        assert result["redacted_text"] == text

    def test_custom_threshold_via_property(self):
        """score_threshold should be readable and writable."""
        engine = RedactionEngine(score_threshold=0.6)
        assert engine.score_threshold == 0.6
        engine.score_threshold = 0.3
        assert engine.score_threshold == 0.3

    def test_analyze_respects_threshold(self):
        """The analyze() method should also respect score_threshold."""
        engine = RedactionEngine(score_threshold=1.0)
        result = engine.analyze("Contact John Smith for details")
        # GLiNER name detection scores below 1.0, so should be filtered out
        assert len(result["entities"]) == 0


class TestEntityValidation:
    def test_validate_swift_code_accepts_valid(self):
        assert RedactionEngine._validate_entity("DEUTDEFF", "SWIFT_CODE") is True
        assert RedactionEngine._validate_entity("DEUTDEFF500", "SWIFT_CODE") is True

    def test_validate_swift_code_rejects_lowercase(self):
        assert RedactionEngine._validate_entity("document", "SWIFT_CODE") is False
        assert RedactionEngine._validate_entity("credentials", "SWIFT_CODE") is False
        assert RedactionEngine._validate_entity("separate", "SWIFT_CODE") is False

    def test_validate_iban_accepts_valid(self):
        assert RedactionEngine._validate_entity("GB29NWBK60161331926819", "IBAN") is True

    def test_validate_iban_rejects_words(self):
        assert RedactionEngine._validate_entity("something", "IBAN") is False

    def test_validate_email_accepts_valid(self):
        assert RedactionEngine._validate_entity("john@example.com", "EMAIL_ADDRESS") is True

    def test_validate_email_rejects_no_at(self):
        assert RedactionEngine._validate_entity("notanemail", "EMAIL_ADDRESS") is False

    def test_validate_ip_accepts_valid(self):
        assert RedactionEngine._validate_entity("192.168.1.1", "IP_ADDRESS") is True

    def test_validate_ip_rejects_words(self):
        assert RedactionEngine._validate_entity("localhost", "IP_ADDRESS") is False

    def test_validate_ssn_accepts_valid(self):
        assert RedactionEngine._validate_entity("123-45-6789", "US_SSN") is True
        assert RedactionEngine._validate_entity("123456789", "US_SSN") is True

    def test_validate_ssn_rejects_short(self):
        assert RedactionEngine._validate_entity("12345", "US_SSN") is False

    def test_validate_phone_accepts_valid(self):
        assert RedactionEngine._validate_entity("555-123-4567", "PHONE_NUMBER") is True

    def test_validate_phone_rejects_short(self):
        assert RedactionEngine._validate_entity("12", "PHONE_NUMBER") is False

    def test_validate_unknown_type_passes_through(self):
        """Entity types without validation rules should always pass."""
        assert RedactionEngine._validate_entity("anything", "PERSON") is True
        assert RedactionEngine._validate_entity("anything", "ORGANIZATION") is True
        assert RedactionEngine._validate_entity("anything", "LOCATION") is True
