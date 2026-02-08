import json

from ..engine import RedactionEngine


def handle_unredact(
    engine: RedactionEngine,
    redacted_text: str,
    session_id: str,
) -> str:
    result = engine.unredact(redacted_text, session_id)
    return json.dumps(result)
