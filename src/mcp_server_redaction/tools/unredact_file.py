import json
import os

from ..engine import RedactionEngine
from ..handlers import get_handler


def handle_unredact_file(
    engine: RedactionEngine,
    file_path: str,
    session_id: str,
) -> str:
    if not os.path.isfile(file_path):
        return json.dumps({"error": f"File not found: {file_path}"})

    mappings = engine.state.get_mappings(session_id)
    if mappings is None:
        return json.dumps({"error": f"Session '{session_id}' not found or expired"})

    _, ext = os.path.splitext(file_path)

    try:
        handler = get_handler(ext)
    except ValueError as e:
        return json.dumps({"error": str(e)})

    base, ext = os.path.splitext(file_path)
    unredacted_path = f"{base}_unredacted{ext}"

    try:
        result = handler.unredact(file_path, unredacted_path, mappings)
    except Exception as e:
        return json.dumps({"error": f"Unredaction failed: {e}"})

    return json.dumps({
        "unredacted_file_path": unredacted_path,
        "entities_restored": result["entities_restored"],
    })
