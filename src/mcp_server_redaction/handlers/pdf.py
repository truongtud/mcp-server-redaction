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

            result = engine.redact(page_text, entity_types=entity_types)
            if result["entities_found"] == 0:
                continue

            total_found += result["entities_found"]
            if use_placeholders:
                if session_id is None:
                    session_id = result["session_id"]
                else:
                    self._merge_session(engine, session_id, result["session_id"])

            mappings = engine.state.get_mappings(result["session_id"])
            if not mappings:
                continue

            # Extract font info before redacting
            spans = self._get_spans(page) if use_placeholders else []

            for placeholder, original_text in mappings.items():
                rects = page.search_for(original_text)
                font_info = self._find_font_info(spans, original_text) if spans else None

                for rect in rects:
                    if use_placeholders:
                        annot_kwargs = {"text": placeholder}
                        if font_info:
                            annot_kwargs["fontsize"] = font_info["fontsize"]
                            annot_kwargs["fontname"] = font_info.get("fontname", "helv")
                            if font_info.get("color") is not None:
                                annot_kwargs["text_color"] = font_info["color"]
                        else:
                            annot_kwargs["fontsize"] = 10
                        page.add_redact_annot(rect, **annot_kwargs)
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
            spans = self._get_spans(page)

            for placeholder, original in mappings.items():
                rects = page.search_for(placeholder)
                font_info = self._find_font_info(spans, placeholder) if spans else None

                for rect in rects:
                    annot_kwargs = {"text": original}
                    if font_info:
                        annot_kwargs["fontsize"] = font_info["fontsize"]
                        annot_kwargs["fontname"] = font_info.get("fontname", "helv")
                    else:
                        annot_kwargs["fontsize"] = 10
                    page.add_redact_annot(rect, **annot_kwargs)
                    entities_restored += 1
                    page_had_changes = True
            if page_had_changes:
                page.apply_redactions()

        doc.save(output_path)
        doc.close()
        return {"entities_restored": entities_restored}

    @staticmethod
    def _get_spans(page) -> list[dict]:
        """Extract all text spans with font metadata from a page."""
        spans = []
        try:
            blocks = page.get_text("dict")["blocks"]
        except Exception:
            return spans

        for block in blocks:
            if "lines" not in block:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    if span.get("text"):
                        spans.append(span)
        return spans

    @staticmethod
    def _find_font_info(spans: list[dict], text: str) -> dict | None:
        """Find font info for text that may be a substring of a span."""
        for span in spans:
            if text in span["text"]:
                fontname = span.get("font", "helv")
                # Map to PDF base-14 font if custom font not embeddable
                if fontname not in ("helv", "tiro", "cour", "Helvetica", "Times-Roman", "Courier"):
                    flags = span.get("flags", 0)
                    is_mono = bool(flags & (1 << 0))
                    is_serif = bool(flags & (1 << 1))
                    if is_mono:
                        fontname = "cour"
                    elif is_serif:
                        fontname = "tiro"
                    else:
                        fontname = "helv"
                return {
                    "fontsize": span.get("size", 10),
                    "fontname": fontname,
                    "color": span.get("color"),
                }
        return None

    @staticmethod
    def _merge_session(engine: RedactionEngine, target_id: str, source_id: str) -> None:
        """Copy all mappings from source session into target session."""
        source_mappings = engine.state.get_mappings(source_id)
        if source_mappings:
            for placeholder, original in source_mappings.items():
                engine.state.add_mapping(target_id, placeholder, original)
