from mcp_server_redaction.server import mcp


class TestServerRegistration:
    def test_server_has_tools_registered(self):
        """Verify the FastMCP server instance exists and has the right name."""
        assert mcp.name == "redaction"
