"""Dev entry point for `mcp dev`. Use: uv run mcp dev run_dev.py"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from mcp_server_redaction.server import mcp  # noqa: E402, F401
