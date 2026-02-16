from presidio_analyzer import AnalyzerEngine

from .llm_reviewer import LLMReviewer
from .recognizers import build_registry
from .state import StateManager


class RedactionEngine:
    def __init__(
        self,
        state_manager: StateManager | None = None,
        use_llm: bool = True,
        score_threshold: float = 0.4,
    ):
        self._registry = build_registry()
        self._analyzer = AnalyzerEngine(registry=self._registry)
        self._state = state_manager or StateManager()
        self._llm = LLMReviewer(enabled=use_llm and LLMReviewer.is_available())
        self.score_threshold = score_threshold  # uses the validated setter

    @property
    def score_threshold(self) -> float:
        return self._score_threshold

    @score_threshold.setter
    def score_threshold(self, value: float) -> None:
        if not (0.0 <= value <= 1.0):
            raise ValueError(f"score_threshold must be between 0.0 and 1.0, got {value}")
        self._score_threshold = value

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

        # --- L1 + L2: Presidio (regex recognizers + GLiNER) ---
        kwargs: dict = {"text": text, "language": "en", "score_threshold": self._score_threshold}
        if entity_types:
            kwargs["entities"] = entity_types

        results = self._analyzer.analyze(**kwargs)
        results = self._remove_overlaps(results)

        # --- L3: LLM review (find what L1+L2 missed) ---
        already_found = [text[r.start:r.end] for r in results]
        llm_entities = self._llm.review(text, already_found)

        # Convert LLM results to RecognizerResult for merging
        if llm_entities:
            from presidio_analyzer import RecognizerResult

            for ent in llm_entities:
                # Skip if overlaps with existing result
                if any(
                    ent["start"] < r.end and ent["end"] > r.start
                    for r in results
                ):
                    continue
                results.append(
                    RecognizerResult(
                        entity_type=ent["entity_type"],
                        start=ent["start"],
                        end=ent["end"],
                        score=0.7,
                    )
                )
            results = self._remove_overlaps(results)

        if not results:
            session_id = self._state.create_session()
            return {
                "redacted_text": text,
                "session_id": session_id,
                "entities_found": 0,
                "entities": [],
            }

        # Sort by start position (descending) so we can replace right-to-left
        results.sort(key=lambda r: r.start, reverse=True)

        type_counters: dict[str, int] = {}
        replacements: list[tuple[int, int, str, str, str]] = []  # start, end, placeholder, original_value, entity_type

        for result in results:
            entity_type = result.entity_type
            type_counters.setdefault(entity_type, 0)
            type_counters[entity_type] += 1
            placeholder = f"[{entity_type}_{type_counters[entity_type]}]"
            original_value = text[result.start : result.end]
            replacements.append((result.start, result.end, placeholder, original_value, entity_type))

        redacted_text = text
        session_id = self._state.create_session()
        entity_list = []
        for start, end, placeholder, original_value, entity_type in replacements:
            redacted_text = redacted_text[:start] + placeholder + redacted_text[end:]
            self._state.add_mapping(session_id, placeholder, original_value)
            entity_list.append({
                "type": entity_type,
                "original_start": start,
                "original_end": end,
                "placeholder": placeholder,
            })

        # Reverse so entities are in forward (left-to-right) order
        entity_list.reverse()

        return {
            "redacted_text": redacted_text,
            "session_id": session_id,
            "entities_found": len(results),
            "entities": entity_list,
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
        kwargs: dict = {"text": text, "language": "en", "score_threshold": self._score_threshold}
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
