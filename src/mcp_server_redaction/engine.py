from presidio_analyzer import AnalyzerEngine

from .recognizers import build_registry
from .state import StateManager


class RedactionEngine:
    def __init__(self, state_manager: StateManager | None = None):
        self._registry = build_registry()
        self._analyzer = AnalyzerEngine(registry=self._registry)
        self._state = state_manager or StateManager()

    @property
    def state(self) -> StateManager:
        return self._state

    @property
    def registry(self):
        return self._registry

    def redact(
        self,
        text: str,
        entity_types: list[str] | None = None,
    ) -> dict:
        self._state.prune_expired()

        kwargs: dict = {"text": text, "language": "en"}
        if entity_types:
            kwargs["entities"] = entity_types

        results = self._analyzer.analyze(**kwargs)
        results = self._remove_overlaps(results)

        if not results:
            session_id = self._state.create_session()
            return {
                "redacted_text": text,
                "session_id": session_id,
                "entities_found": 0,
            }

        # Sort by start position (descending) so we can replace right-to-left
        results.sort(key=lambda r: r.start, reverse=True)

        # Track counters per entity type for indexed placeholders
        type_counters: dict[str, int] = {}
        # We'll build replacements in reverse order, then flip for the mapping
        replacements: list[tuple[int, int, str, str]] = []  # start, end, placeholder, original

        for result in results:
            entity_type = result.entity_type
            type_counters.setdefault(entity_type, 0)
            type_counters[entity_type] += 1
            placeholder = f"[{entity_type}_{type_counters[entity_type]}]"
            original_value = text[result.start : result.end]
            replacements.append((result.start, result.end, placeholder, original_value))

        # Apply replacements right-to-left
        redacted_text = text
        session_id = self._state.create_session()
        for start, end, placeholder, original_value in replacements:
            redacted_text = redacted_text[:start] + placeholder + redacted_text[end:]
            self._state.add_mapping(session_id, placeholder, original_value)

        return {
            "redacted_text": redacted_text,
            "session_id": session_id,
            "entities_found": len(results),
        }

    def unredact(self, redacted_text: str, session_id: str) -> dict:
        mappings = self._state.get_mappings(session_id)
        if mappings is None:
            return {"error": f"Session '{session_id}' not found or expired"}

        restored_text = redacted_text
        entities_restored = 0
        for placeholder, original in mappings.items():
            if placeholder in restored_text:
                restored_text = restored_text.replace(placeholder, original)
                entities_restored += 1

        return {
            "original_text": restored_text,
            "entities_restored": entities_restored,
        }

    def analyze(
        self,
        text: str,
        entity_types: list[str] | None = None,
    ) -> dict:
        kwargs: dict = {"text": text, "language": "en"}
        if entity_types:
            kwargs["entities"] = entity_types

        results = self._analyzer.analyze(**kwargs)
        results = self._remove_overlaps(results)

        entities = []
        for result in results:
            original = text[result.start : result.end]
            masked = self._partial_mask(original)
            entities.append({
                "type": result.entity_type,
                "start": result.start,
                "end": result.end,
                "score": round(result.score, 2),
                "text": masked,
            })

        return {"entities": entities}

    @staticmethod
    def _remove_overlaps(results: list) -> list:
        if not results:
            return results
        # Sort by score desc, then by span length desc (prefer higher score, longer span)
        results.sort(key=lambda r: (-r.score, -(r.end - r.start)))
        kept = []
        for result in results:
            if not any(
                result.start < k.end and result.end > k.start for k in kept
            ):
                kept.append(result)
        return kept

    @staticmethod
    def _partial_mask(value: str) -> str:
        if len(value) <= 4:
            return "*" * len(value)
        visible = max(1, len(value) // 4)
        return value[:visible] + "*" * (len(value) - visible * 2) + value[-visible:]
