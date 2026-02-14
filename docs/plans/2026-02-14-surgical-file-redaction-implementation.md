# Surgical File Redaction Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix DOCX and PDF file handlers to preserve formatting during redaction by replacing text surgically within runs/spans instead of collapsing all text.

**Architecture:** Add entity position tracking to the engine return value. Use those positions in the DOCX handler to do per-run surgical replacement. Use PyMuPDF's font metadata extraction in the PDF handler to match original text appearance.

**Tech Stack:** Python, python-docx, PyMuPDF (fitz), presidio-analyzer, pytest

---

### Task 1: Engine — Return Entity Positions

**Files:**
- Modify: `src/mcp_server_redaction/engine.py:67-99`
- Test: `tests/test_engine.py`

**Step 1: Write the failing test**

Add to `tests/test_engine.py` in `TestRedactionEngine`:

```python
def test_redact_returns_entity_positions(self):
    result = self.engine.redact("Contact john@example.com for info")
    assert "entities" in result
    assert len(result["entities"]) >= 1
    entity = result["entities"][0]
    assert "original_start" in entity
    assert "original_end" in entity
    assert "placeholder" in entity
    assert "type" in entity
    # Verify positions point to actual PII in original text
    original_text = "Contact john@example.com for info"
    assert original_text[entity["original_start"]:entity["original_end"]] == "john@example.com"

def test_redact_no_entities_returns_empty_list(self):
    result = self.engine.redact("Hello world")
    assert "entities" in result
    assert result["entities"] == []
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_engine.py::TestRedactionEngine::test_redact_returns_entity_positions tests/test_engine.py::TestRedactionEngine::test_redact_no_entities_returns_empty_list -v`
Expected: FAIL with `KeyError: 'entities'`

**Step 3: Write minimal implementation**

In `src/mcp_server_redaction/engine.py`, modify the `redact` method:

In the no-results branch (line 67-73), add `"entities": []`:

```python
if not results:
    session_id = self._state.create_session()
    return {
        "redacted_text": text,
        "session_id": session_id,
        "entities_found": 0,
        "entities": [],
    }
```

In the main branch, collect entity info from the `replacements` list before applying them. The `replacements` list is built in reverse order, so reverse it for the output:

```python
# Build entity position list (in forward order for callers)
entity_list = [
    {
        "type": original_value,  # will fix below
        "original_start": start,
        "original_end": end,
        "placeholder": placeholder,
    }
    for start, end, placeholder, original_value in reversed(replacements)
]
# Fix: we need entity_type, not original_value. Capture it during the loop.
```

Actually, restructure the replacements loop to also capture entity_type. Change lines 78-93 to:

```python
type_counters: dict[str, int] = {}
replacements: list[tuple[int, int, str, str, str]] = []  # added entity_type

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
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_engine.py -v`
Expected: ALL PASS (including existing tests — backward compatible)

**Step 5: Commit**

```bash
git add src/mcp_server_redaction/engine.py tests/test_engine.py
git commit -m "feat(engine): return entity positions in redact result"
```

---

### Task 2: DOCX Handler — Surgical Run-Aware Redaction

**Files:**
- Modify: `src/mcp_server_redaction/handlers/docx_handler.py`
- Test: `tests/test_handlers.py`

**Step 1: Write the failing test**

Add to `tests/test_handlers.py` after the `_create_test_docx` helper:

```python
def _create_formatted_docx(path: str) -> None:
    """Create a DOCX with mixed formatting: 'Contact <bold>John Smith</bold> at <italic>john@example.com</italic> today.'"""
    doc = python_docx.Document()
    para = doc.add_paragraph()
    run1 = para.add_run("Contact ")
    run2 = para.add_run("John Smith")
    run2.bold = True
    run3 = para.add_run(" at ")
    run4 = para.add_run("john@example.com")
    run4.italic = True
    run5 = para.add_run(" today.")
    doc.save(path)
```

Add to `TestDocxHandler`:

```python
def test_redact_preserves_run_formatting(self):
    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = os.path.join(tmpdir, "formatted.docx")
        output_path = os.path.join(tmpdir, "formatted_redacted.docx")

        _create_formatted_docx(input_path)

        result = self.handler.redact(self.engine, input_path, output_path)
        assert result["entities_found"] >= 1

        doc = python_docx.Document(output_path)
        para = doc.paragraphs[0]
        all_text = para.text
        assert "john@example.com" not in all_text
        assert "John Smith" not in all_text

        # Verify formatting is preserved on non-redacted runs
        # Find the run containing "Contact " — it should NOT be bold
        # Find the run containing " today." — it should NOT be bold or italic
        runs_text = [(r.text, r.bold, r.italic) for r in para.runs if r.text.strip()]
        # At minimum, "Contact" should exist without bold, "today." without italic
        contact_runs = [r for r in runs_text if "Contact" in r[0]]
        assert len(contact_runs) >= 1
        assert contact_runs[0][1] is not True  # not bold

        today_runs = [r for r in runs_text if "today" in r[0]]
        assert len(today_runs) >= 1
        assert today_runs[0][2] is not True  # not italic
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_handlers.py::TestDocxHandler::test_redact_preserves_run_formatting -v`
Expected: FAIL — current implementation collapses all runs into first run's formatting

**Step 3: Write minimal implementation**

Replace the paragraph processing in `DocxHandler.redact` and `_replace_paragraph_text` with surgical replacement.

In `src/mcp_server_redaction/handlers/docx_handler.py`:

```python
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
                self._surgical_replace(para, result["entities"])

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
                            self._surgical_replace(para, result["entities"])

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
            count = self._surgical_unredact(para, mappings)
            entities_restored += count

        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        count = self._surgical_unredact(para, mappings)
                        entities_restored += count

        doc.save(output_path)
        return {"entities_restored": entities_restored}

    @staticmethod
    def _surgical_replace(para, entities: list[dict]) -> None:
        """Replace PII in paragraph runs surgically, preserving formatting.

        Falls back to full-paragraph replacement if run mapping fails.
        """
        if not entities:
            return

        runs = para.runs
        if not runs:
            # No runs — simple text-only paragraph, just replace
            text = para.text
            for ent in sorted(entities, key=lambda e: e["original_start"], reverse=True):
                text = text[:ent["original_start"]] + ent["placeholder"] + text[ent["original_end"]:]
            para.text = text
            return

        # Build run offset map
        concatenated = "".join(r.text for r in runs)
        if concatenated != para.text:
            # Run text doesn't match paragraph text — fall back
            text = para.text
            for ent in sorted(entities, key=lambda e: e["original_start"], reverse=True):
                text = text[:ent["original_start"]] + ent["placeholder"] + text[ent["original_end"]:]
            runs[0].text = text
            for r in runs[1:]:
                r.text = ""
            return

        # Map each run to its character range
        run_ranges = []
        offset = 0
        for run in runs:
            end = offset + len(run.text)
            run_ranges.append((offset, end))
            offset = end

        # Process entities right-to-left to preserve positions
        for ent in sorted(entities, key=lambda e: e["original_start"], reverse=True):
            orig_start = ent["original_start"]
            orig_end = ent["original_end"]
            placeholder = ent["placeholder"]

            for i, (run_start, run_end) in enumerate(run_ranges):
                if orig_start >= run_end:
                    continue
                if orig_start < run_start:
                    break

                local_start = orig_start - run_start

                if orig_end <= run_end:
                    # Case 1: PII fits entirely within this single run
                    local_end = orig_end - run_start
                    runs[i].text = runs[i].text[:local_start] + placeholder + runs[i].text[local_end:]
                else:
                    # Case 2: PII crosses run boundaries
                    runs[i].text = runs[i].text[:local_start] + placeholder
                    for j in range(i + 1, len(run_ranges)):
                        sub_start, sub_end = run_ranges[j]
                        if sub_end <= orig_end:
                            runs[j].text = ""
                        else:
                            local_trim = orig_end - sub_start
                            runs[j].text = runs[j].text[local_trim:]
                            break
                break

    @staticmethod
    def _surgical_unredact(para, mappings: dict[str, str]) -> int:
        """Replace placeholders in runs surgically, preserving formatting."""
        count = 0
        for run in para.runs:
            for placeholder, original in mappings.items():
                if placeholder in run.text:
                    run.text = run.text.replace(placeholder, original)
                    count += 1
        if count == 0:
            # Check if placeholder spans runs (unlikely but possible)
            full_text = para.text
            for placeholder, original in mappings.items():
                if placeholder in full_text:
                    full_text = full_text.replace(placeholder, original)
                    count += 1
            if count > 0 and para.runs:
                para.runs[0].text = full_text
                for r in para.runs[1:]:
                    r.text = ""
        return count

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
        source_mappings = engine.state.get_mappings(source_id)
        if source_mappings:
            for placeholder, original in source_mappings.items():
                engine.state.add_mapping(target_id, placeholder, original)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_handlers.py::TestDocxHandler -v`
Expected: ALL PASS (new formatting test + existing redact/unredact/table tests)

**Step 5: Commit**

```bash
git add src/mcp_server_redaction/handlers/docx_handler.py tests/test_handlers.py
git commit -m "feat(docx): surgical run-aware redaction preserving formatting"
```

---

### Task 3: PDF Handler — Font-Matched Redaction

**Files:**
- Modify: `src/mcp_server_redaction/handlers/pdf.py`
- Test: `tests/test_handlers.py`

**Step 1: Write the failing test**

Add to `tests/test_handlers.py`, replace `_create_test_pdf` helper:

```python
def _create_test_pdf(path: str, pages: list[str], fontsize: float = 12) -> None:
    """Helper: create a PDF with one text block per page."""
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        page.insert_text((72, 72), text, fontsize=fontsize)
    doc.save(path)
    doc.close()
```

Add to `TestPdfHandler`:

```python
def test_redact_pdf_preserves_font_size(self):
    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = os.path.join(tmpdir, "test.pdf")
        output_path = os.path.join(tmpdir, "test_redacted.pdf")

        _create_test_pdf(input_path, [
            "Contact john@example.com for details."
        ], fontsize=18)

        result = self.handler.redact(
            self.engine, input_path, output_path,
            use_placeholders=True,
        )
        assert result["entities_found"] >= 1

        doc = fitz.open(output_path)
        blocks = doc[0].get_text("dict")["blocks"]
        doc.close()

        # Find the span containing the placeholder
        placeholder_fontsize = None
        for block in blocks:
            if "lines" not in block:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    if "[EMAIL_ADDRESS_1]" in span["text"]:
                        placeholder_fontsize = span["size"]

        # Font size should be close to 18, not the hardcoded 10
        assert placeholder_fontsize is not None
        assert abs(placeholder_fontsize - 18) < 3  # within 3pt tolerance
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_handlers.py::TestPdfHandler::test_redact_pdf_preserves_font_size -v`
Expected: FAIL — current code uses hardcoded `fontsize=10`, so placeholder will be ~10pt not ~18pt

**Step 3: Write minimal implementation**

In `src/mcp_server_redaction/handlers/pdf.py`:

```python
import fitz  # PyMuPDF

from ..engine import RedactionEngine
from .base import FileHandler

# Standard PDF base-14 font fallbacks
_FONT_FALLBACKS = {
    "serif": "tiro",
    "sans": "helv",
    "mono": "cour",
}


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
            font_map = self._build_font_map(page) if use_placeholders else {}

            for placeholder, original_text in mappings.items():
                rects = page.search_for(original_text)
                font_info = font_map.get(original_text)

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
            font_map = self._build_font_map(page)

            for placeholder, original in mappings.items():
                rects = page.search_for(placeholder)
                font_info = font_map.get(placeholder)

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
    def _build_font_map(page) -> dict[str, dict]:
        """Extract font info for text spans on a page.

        Returns a dict mapping text content to its font properties.
        For duplicate text, the first occurrence wins.
        """
        font_map = {}
        try:
            blocks = page.get_text("dict")["blocks"]
        except Exception:
            return font_map

        for block in blocks:
            if "lines" not in block:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    text = span["text"]
                    if text and text not in font_map:
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
                        font_map[text] = {
                            "fontsize": span.get("size", 10),
                            "fontname": fontname,
                            "color": span.get("color"),
                        }
        return font_map

    @staticmethod
    def _merge_session(engine: RedactionEngine, target_id: str, source_id: str) -> None:
        source_mappings = engine.state.get_mappings(source_id)
        if source_mappings:
            for placeholder, original in source_mappings.items():
                engine.state.add_mapping(target_id, placeholder, original)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_handlers.py::TestPdfHandler -v`
Expected: ALL PASS (new font size test + existing placeholder/blackbox/unredact tests)

**Step 5: Commit**

```bash
git add src/mcp_server_redaction/handlers/pdf.py tests/test_handlers.py
git commit -m "feat(pdf): font-matched redaction preserving text appearance"
```

---

### Task 4: Full Regression Test Pass

**Files:**
- No changes — just verify everything works together

**Step 1: Run the full test suite**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

**Step 2: If any failures, fix them**

Common issues to watch for:
- Existing tests that relied on the old `_replace_paragraph_text` behavior
- Engine tests that assert exact dict keys (new `entities` key added)
- Import issues from changed signatures

**Step 3: Commit any fixes**

```bash
git add -u
git commit -m "fix: resolve regression test failures from surgical redaction"
```

Only if there were fixes needed; skip if all passed.

---

### Task 5: Edge Case Tests

**Files:**
- Test: `tests/test_handlers.py`

**Step 1: Write edge case tests**

Add to `TestDocxHandler`:

```python
def test_redact_preserves_formatting_cross_run_pii(self):
    """PII that spans two runs — placeholder takes first run's format."""
    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = os.path.join(tmpdir, "cross_run.docx")
        output_path = os.path.join(tmpdir, "cross_run_redacted.docx")

        doc = python_docx.Document()
        para = doc.add_paragraph()
        # Split "john@example.com" across two runs: "john@exam" (bold) + "ple.com" (normal)
        run1 = para.add_run("Contact ")
        run2 = para.add_run("john@exam")
        run2.bold = True
        run3 = para.add_run("ple.com")
        run4 = para.add_run(" for details.")
        doc.save(input_path)

        result = self.handler.redact(self.engine, input_path, output_path)
        assert result["entities_found"] >= 1

        out_doc = python_docx.Document(output_path)
        para = out_doc.paragraphs[0]
        assert "john@example.com" not in para.text
        assert "john@exam" not in para.text
        assert "ple.com" not in para.text

def test_unredact_preserves_formatting(self):
    """Unredact should also preserve run formatting."""
    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = os.path.join(tmpdir, "test.docx")
        redacted_path = os.path.join(tmpdir, "test_redacted.docx")
        unredacted_path = os.path.join(tmpdir, "test_unredacted.docx")

        _create_formatted_docx(input_path)

        result = self.handler.redact(self.engine, input_path, redacted_path)
        mappings = self.engine.state.get_mappings(result["session_id"])

        undo = self.handler.unredact(redacted_path, unredacted_path, mappings)
        assert undo["entities_restored"] >= 1

        doc = python_docx.Document(unredacted_path)
        para = doc.paragraphs[0]
        assert "john@example.com" in para.text
        # Non-redacted run formatting should be preserved
        runs_text = [(r.text, r.bold, r.italic) for r in para.runs if r.text.strip()]
        today_runs = [r for r in runs_text if "today" in r[0]]
        assert len(today_runs) >= 1
```

**Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/test_handlers.py::TestDocxHandler -v`
Expected: ALL PASS

**Step 3: Commit**

```bash
git add tests/test_handlers.py
git commit -m "test: add edge case tests for cross-run PII and unredact formatting"
```
