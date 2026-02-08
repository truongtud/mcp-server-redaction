import fitz  # PyMuPDF

from ..engine import RedactionEngine
from .base import FileHandler


class PdfHandler(FileHandler):
    def redact(
        self,
        engine: RedactionEngine,
        input_path: str,
        output_path: str,
        entity_types: list[str] | None = None,
        use_placeholders: bool = True,
    ) -> dict:
        doc = fitz.open(input_path)
        total_found = 0
        session_id = None

        for page in doc:
            page_text = page.get_text()
            if not page_text.strip():
                continue

            # Run engine to get redacted text and entity mappings
            result = engine.redact(page_text, entity_types=entity_types)
            if result["entities_found"] == 0:
                continue

            total_found += result["entities_found"]
            if use_placeholders:
                if session_id is None:
                    session_id = result["session_id"]
                else:
                    self._merge_session(engine, session_id, result["session_id"])

            # Get the mappings to find original text -> placeholder pairs
            mappings = engine.state.get_mappings(result["session_id"])
            if not mappings:
                continue

            # For each placeholder->original pair, find original text on page and redact
            for placeholder, original_text in mappings.items():
                rects = page.search_for(original_text)
                for rect in rects:
                    if use_placeholders:
                        page.add_redact_annot(
                            rect,
                            text=placeholder,
                            fontsize=10,
                        )
                    else:
                        page.add_redact_annot(rect)

            page.apply_redactions()

        if use_placeholders and session_id is None:
            session_id = engine.state.create_session()

        doc.save(output_path)
        doc.close()

        return {
            "session_id": session_id if use_placeholders else None,
            "entities_found": total_found,
        }

    def unredact(
        self,
        input_path: str,
        output_path: str,
        mappings: dict[str, str],
    ) -> dict:
        doc = fitz.open(input_path)
        entities_restored = 0

        for page in doc:
            page_had_changes = False
            for placeholder, original in mappings.items():
                rects = page.search_for(placeholder)
                for rect in rects:
                    page.add_redact_annot(rect, text=original, fontsize=10)
                    entities_restored += 1
                    page_had_changes = True
            if page_had_changes:
                page.apply_redactions()

        doc.save(output_path)
        doc.close()
        return {"entities_restored": entities_restored}

    @staticmethod
    def _merge_session(engine: RedactionEngine, target_id: str, source_id: str) -> None:
        source_mappings = engine.state.get_mappings(source_id)
        if source_mappings:
            for placeholder, original in source_mappings.items():
                engine.state.add_mapping(target_id, placeholder, original)
