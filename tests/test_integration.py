import json

from mcp_server_redaction.engine import RedactionEngine
from mcp_server_redaction.tools import (
    handle_redact,
    handle_unredact,
    handle_analyze,
    handle_configure,
)


class TestEndToEnd:
    def setup_method(self):
        self.engine = RedactionEngine()

    def test_full_redact_unredact_cycle(self):
        original = (
            "John Smith's email is john@example.com "
            "and you can call him at 555-123-4567."
        )

        # Redact
        redact_result = json.loads(handle_redact(self.engine, text=original))
        redacted = redact_result["redacted_text"]
        session_id = redact_result["session_id"]

        assert "john@example.com" not in redacted
        assert "John Smith" not in redacted
        assert redact_result["entities_found"] >= 2

        # Unredact
        unredact_result = json.loads(
            handle_unredact(self.engine, redacted_text=redacted, session_id=session_id)
        )
        assert unredact_result["original_text"] == original

    def test_analyze_then_selective_redact(self):
        text = "Dr. Jane Doe prescribed Metformin for patient MRN: 123-456-789"

        # First analyze to see what's in the text
        analysis = json.loads(handle_analyze(self.engine, text=text))
        found_types = {e["type"] for e in analysis["entities"]}
        assert len(found_types) >= 1

        # Then redact only PERSON entities
        redact_result = json.loads(
            handle_redact(self.engine, text=text, entity_types=["PERSON"])
        )
        # PERSON should be redacted
        assert "[PERSON_" in redact_result["redacted_text"]

    def test_configure_custom_pattern_then_redact(self):
        # Add a custom pattern
        config_result = json.loads(
            handle_configure(
                self.engine,
                custom_patterns=[
                    {"name": "PROJECT_CODE", "pattern": r"PRJ-\d{4}", "score": 0.95}
                ],
            )
        )
        assert "PROJECT_CODE" in config_result["active_entities"]

        # Now redact text containing the custom pattern
        text = "Assign this to PRJ-1234 immediately"
        redact_result = json.loads(handle_redact(self.engine, text=text))
        assert "[PROJECT_CODE_1]" in redact_result["redacted_text"]
        assert "PRJ-1234" not in redact_result["redacted_text"]
