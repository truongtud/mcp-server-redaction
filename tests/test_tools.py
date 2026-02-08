import json
import os
import tempfile
from mcp_server_redaction.engine import RedactionEngine
from mcp_server_redaction.tools.redact import handle_redact
from mcp_server_redaction.tools.unredact import handle_unredact
from mcp_server_redaction.tools.analyze import handle_analyze
from mcp_server_redaction.tools.configure import handle_configure
from mcp_server_redaction.tools.redact_file import handle_redact_file


class TestRedactTool:
    def setup_method(self):
        self.engine = RedactionEngine()

    def test_redact_tool_returns_valid_json(self):
        result = handle_redact(self.engine, text="Email me at john@example.com")
        data = json.loads(result)
        assert "redacted_text" in data
        assert "session_id" in data
        assert "entities_found" in data
        assert data["entities_found"] >= 1
        assert "john@example.com" not in data["redacted_text"]

    def test_redact_tool_with_entity_filter(self):
        result = handle_redact(
            self.engine,
            text="John Smith john@example.com",
            entity_types=["EMAIL_ADDRESS"],
        )
        data = json.loads(result)
        assert "[EMAIL_ADDRESS_1]" in data["redacted_text"]


class TestUnredactTool:
    def setup_method(self):
        self.engine = RedactionEngine()

    def test_unredact_restores_text(self):
        redact_result = json.loads(
            handle_redact(self.engine, text="Email john@example.com")
        )
        result = handle_unredact(
            self.engine,
            redacted_text=redact_result["redacted_text"],
            session_id=redact_result["session_id"],
        )
        data = json.loads(result)
        assert "original_text" in data
        assert "john@example.com" in data["original_text"]

    def test_unredact_bad_session(self):
        result = handle_unredact(
            self.engine, redacted_text="text", session_id="bad-id"
        )
        data = json.loads(result)
        assert "error" in data


class TestAnalyzeTool:
    def setup_method(self):
        self.engine = RedactionEngine()

    def test_analyze_returns_entities(self):
        result = handle_analyze(self.engine, text="Contact john@example.com")
        data = json.loads(result)
        assert "entities" in data
        assert len(data["entities"]) >= 1
        assert data["entities"][0]["type"] == "EMAIL_ADDRESS"

    def test_analyze_empty_text(self):
        result = handle_analyze(self.engine, text="Hello world")
        data = json.loads(result)
        assert data["entities"] == []


class TestConfigureTool:
    def setup_method(self):
        self.engine = RedactionEngine()

    def test_add_custom_pattern(self):
        result = handle_configure(
            self.engine,
            custom_patterns=[
                {"name": "INTERNAL_ID", "pattern": r"ID-\d{6}", "score": 0.9}
            ],
        )
        data = json.loads(result)
        assert data["status"] == "ok"
        assert "INTERNAL_ID" in data["active_entities"]

        # Verify the new pattern works
        redact_result = self.engine.redact("Reference ID-123456 in the system")
        assert "[INTERNAL_ID_1]" in redact_result["redacted_text"]

    def test_configure_returns_active_entities(self):
        result = handle_configure(self.engine)
        data = json.loads(result)
        assert data["status"] == "ok"
        assert "EMAIL_ADDRESS" in data["active_entities"]


class TestRedactFileTool:
    def setup_method(self):
        self.engine = RedactionEngine()

    def test_redact_file_creates_output(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as f:
            f.write("Contact john@example.com for details.\n")
            f.flush()
            input_path = f.name

        try:
            result = handle_redact_file(self.engine, file_path=input_path)
            data = json.loads(result)
            assert "redacted_file_path" in data
            assert data["entities_found"] >= 1

            # Verify the redacted file exists and has redacted content
            with open(data["redacted_file_path"]) as rf:
                content = rf.read()
            assert "john@example.com" not in content
            assert "[EMAIL_ADDRESS_1]" in content

            os.unlink(data["redacted_file_path"])
        finally:
            os.unlink(input_path)

    def test_redact_file_nonexistent_returns_error(self):
        result = handle_redact_file(self.engine, file_path="/tmp/nonexistent_file.txt")
        data = json.loads(result)
        assert "error" in data
