import json

from ..engine import RedactionEngine


def handle_analyze(
    engine: RedactionEngine,
    text: str,
    entity_types: list[str] | None = None,
) -> str:
    result = engine.analyze(text, entity_types=entity_types)
    return json.dumps(result)
