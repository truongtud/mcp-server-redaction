import json
import os

from ..engine import RedactionEngine
from ..handlers import get_handler


def handle_redact_file(
    engine: RedactionEngine,
    file_path: str,
    entity_types: list[str] | None = None,
    use_placeholders: bool = True,
) -> str:
    if not os.path.isfile(file_path):
        return json.dumps({"error": f"File not found: {file_path}"})

    _, ext = os.path.splitext(file_path)

    try:
        handler = get_handler(ext)
    except ValueError as e:
        return json.dumps({"error": str(e)})

    base, ext = os.path.splitext(file_path)
    output_ext = ext
    # .doc files get converted to .docx
    if ext.lower() == ".doc":
        output_ext = ".docx"
    redacted_path = f"{base}_redacted{output_ext}"

    try:
        result = handler.redact(
            engine,
            file_path,
            redacted_path,
            entity_types=entity_types,
            use_placeholders=use_placeholders,
        )
    except Exception as e:
        return json.dumps({"error": f"Redaction failed: {e}"})

    response = {
        "redacted_file_path": redacted_path,
        "entities_found": result["entities_found"],
    }
    if result.get("session_id"):
        response["session_id"] = result["session_id"]

    return json.dumps(response)
