import docx as python_docx

from ..engine import RedactionEngine
from .base import FileHandler


class DocxHandler(FileHandler):
    def redact(
        self,
        engine: RedactionEngine,
        input_path: str,
        output_path: str,
        entity_types: list[str] | None = None,
        use_placeholders: bool = True,
    ) -> dict:
        doc = python_docx.Document(input_path)
        total_found = 0
        session_id = None

        # Process paragraphs
        for para in doc.paragraphs:
            if not para.text.strip():
                continue
            result = engine.redact(para.text, entity_types=entity_types)
            if result["entities_found"] > 0:
                total_found += result["entities_found"]
                if session_id is None:
                    session_id = result["session_id"]
                else:
                    self._merge_session(engine, session_id, result["session_id"])
                self._replace_paragraph_text(para, result["redacted_text"])

        # Process tables
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        if not para.text.strip():
                            continue
                        result = engine.redact(para.text, entity_types=entity_types)
                        if result["entities_found"] > 0:
                            total_found += result["entities_found"]
                            if session_id is None:
                                session_id = result["session_id"]
                            else:
                                self._merge_session(engine, session_id, result["session_id"])
                            self._replace_paragraph_text(para, result["redacted_text"])

        if session_id is None:
            session_id = engine.state.create_session()

        doc.save(output_path)
        return {"session_id": session_id, "entities_found": total_found}

    def unredact(
        self,
        input_path: str,
        output_path: str,
        mappings: dict[str, str],
    ) -> dict:
        doc = python_docx.Document(input_path)
        entities_restored = 0

        for para in doc.paragraphs:
            new_text, count = self._apply_mappings(para.text, mappings)
            if count > 0:
                entities_restored += count
                self._replace_paragraph_text(para, new_text)

        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        new_text, count = self._apply_mappings(para.text, mappings)
                        if count > 0:
                            entities_restored += count
                            self._replace_paragraph_text(para, new_text)

        doc.save(output_path)
        return {"entities_restored": entities_restored}

    @staticmethod
    def _replace_paragraph_text(para, new_text: str) -> None:
        """Replace paragraph text while preserving the first run's formatting."""
        if not para.runs:
            para.text = new_text
            return
        first_run = para.runs[0]
        for run in para.runs[1:]:
            run.text = ""
        first_run.text = new_text

    @staticmethod
    def _apply_mappings(text: str, mappings: dict[str, str]) -> tuple[str, int]:
        count = 0
        for placeholder, original in mappings.items():
            if placeholder in text:
                text = text.replace(placeholder, original)
                count += 1
        return text, count

    @staticmethod
    def _merge_session(engine: RedactionEngine, target_id: str, source_id: str) -> None:
        """Copy all mappings from source session into target session."""
        source_mappings = engine.state.get_mappings(source_id)
        if source_mappings:
            for placeholder, original in source_mappings.items():
                engine.state.add_mapping(target_id, placeholder, original)
