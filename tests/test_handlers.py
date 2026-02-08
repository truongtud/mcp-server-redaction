import os
import tempfile

from mcp_server_redaction.engine import RedactionEngine
from mcp_server_redaction.handlers.plain_text import PlainTextHandler


class TestPlainTextHandler:
    def setup_method(self):
        self.engine = RedactionEngine()
        self.handler = PlainTextHandler()

    def test_redact_creates_output_file(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as f:
            f.write("Contact john@example.com for details.\n")
            input_path = f.name

        base, ext = os.path.splitext(input_path)
        output_path = f"{base}_redacted{ext}"

        try:
            result = self.handler.redact(
                self.engine, input_path, output_path
            )
            assert result["entities_found"] >= 1
            assert "session_id" in result

            with open(output_path) as rf:
                content = rf.read()
            assert "john@example.com" not in content
            assert "[EMAIL_ADDRESS_1]" in content
        finally:
            os.unlink(input_path)
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_unredact_restores_file(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as f:
            f.write("Contact john@example.com for details.\n")
            input_path = f.name

        base, ext = os.path.splitext(input_path)
        redacted_path = f"{base}_redacted{ext}"
        unredacted_path = f"{base}_redacted_unredacted{ext}"

        try:
            result = self.handler.redact(
                self.engine, input_path, redacted_path
            )
            session_id = result["session_id"]
            mappings = self.engine.state.get_mappings(session_id)

            undo_result = self.handler.unredact(
                redacted_path, unredacted_path, mappings
            )
            assert undo_result["entities_restored"] >= 1

            with open(unredacted_path) as rf:
                content = rf.read()
            assert "john@example.com" in content
        finally:
            for p in [input_path, redacted_path, unredacted_path]:
                if os.path.exists(p):
                    os.unlink(p)
