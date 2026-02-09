import json

from presidio_analyzer import Pattern, PatternRecognizer

from ..engine import RedactionEngine
from ..llm_reviewer import LLMReviewer


def handle_configure(
    engine: RedactionEngine,
    custom_patterns: list[dict] | None = None,
    disabled_entities: list[str] | None = None,
) -> str:
    if custom_patterns:
        for pattern_def in custom_patterns:
            recognizer = PatternRecognizer(
                supported_entity=pattern_def["name"],
                name=f"{pattern_def['name']}Recognizer",
                patterns=[
                    Pattern(
                        name=pattern_def["name"].lower(),
                        regex=pattern_def["pattern"],
                        score=pattern_def.get("score", 0.8),
                    )
                ],
            )
            engine.registry.add_recognizer(recognizer)

    active_entities = engine.registry.get_supported_entities()

    if disabled_entities:
        active_entities = [e for e in active_entities if e not in disabled_entities]

    return json.dumps({
        "status": "ok",
        "active_entities": sorted(active_entities),
        "llm_available": LLMReviewer.is_available(),
    })
