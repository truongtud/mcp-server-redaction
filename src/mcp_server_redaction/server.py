import logging

from mcp.server.fastmcp import FastMCP

from .engine import RedactionEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("redaction")
engine = RedactionEngine()


@mcp.tool()
def redact(text: str, entity_types: list[str] | None = None) -> str:
    """Redact sensitive data from text, replacing entities with indexed placeholders like [EMAIL_ADDRESS_1].

    Args:
        text: The text to redact.
        entity_types: Optional list of entity types to redact (e.g. ["EMAIL_ADDRESS", "PERSON"]).
                      If not provided, all known entity types are checked.
    """
    from .tools.redact import handle_redact
    return handle_redact(engine, text=text, entity_types=entity_types)


@mcp.tool()
def unredact(redacted_text: str, session_id: str) -> str:
    """Restore redacted text to the original using a session ID from a previous redact call.

    Args:
        redacted_text: Text containing placeholders like [EMAIL_ADDRESS_1].
        session_id: The session ID returned by the redact tool.
    """
    from .tools.unredact import handle_unredact
    return handle_unredact(engine, redacted_text=redacted_text, session_id=session_id)


@mcp.tool()
def analyze(text: str, entity_types: list[str] | None = None) -> str:
    """Analyze text for sensitive data without modifying it. Returns detected entities with partial masking.

    Args:
        text: The text to analyze.
        entity_types: Optional list of entity types to look for.
    """
    from .tools.analyze import handle_analyze
    return handle_analyze(engine, text=text, entity_types=entity_types)


@mcp.tool()
def configure(
    custom_patterns: list[dict] | None = None,
    disabled_entities: list[str] | None = None,
) -> str:
    """Configure the redaction engine at runtime. Add custom patterns or disable entity types.

    Args:
        custom_patterns: List of pattern dicts with keys: name, pattern, score.
                         Example: [{"name": "INTERNAL_ID", "pattern": "ID-\\\\d{6}", "score": 0.9}]
        disabled_entities: List of entity type names to disable.
    """
    from .tools.configure import handle_configure
    return handle_configure(engine, custom_patterns=custom_patterns, disabled_entities=disabled_entities)


@mcp.tool()
def redact_file(file_path: str, entity_types: list[str] | None = None) -> str:
    """Redact sensitive data in a file. Writes a new file with '_redacted' suffix.

    Args:
        file_path: Absolute path to the file to redact.
        entity_types: Optional list of entity types to redact.
    """
    from .tools.redact_file import handle_redact_file
    return handle_redact_file(engine, file_path=file_path, entity_types=entity_types)


def main():
    mcp.run(transport="stdio")
