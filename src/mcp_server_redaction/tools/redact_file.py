import json
import os

from ..engine import RedactionEngine


def handle_redact_file(
    engine: RedactionEngine,
    file_path: str,
    entity_types: list[str] | None = None,
) -> str:
    if not os.path.isfile(file_path):
        return json.dumps({"error": f"File not found: {file_path}"})

    with open(file_path) as f:
        content = f.read()

    result = engine.redact(content, entity_types=entity_types)

    base, ext = os.path.splitext(file_path)
    redacted_path = f"{base}_redacted{ext}"

    with open(redacted_path, "w") as f:
        f.write(result["redacted_text"])

    return json.dumps({
        "redacted_file_path": redacted_path,
        "session_id": result["session_id"],
        "entities_found": result["entities_found"],
    })
