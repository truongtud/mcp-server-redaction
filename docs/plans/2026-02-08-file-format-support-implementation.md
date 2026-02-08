# File Format Support Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extend `redact_file` to handle PDF, XLSX, DOCX, and legacy DOC files with same-format output, plus add an `unredact_file` tool for reversing placeholder-based file redactions.

**Architecture:** Handler-based dispatch — each file format gets a handler class implementing a common interface. The existing `redact_file` tool becomes a thin dispatcher that picks the right handler by file extension. A new `unredact_file` tool reverses placeholder-mode redactions.

**Tech Stack:** PyMuPDF (PDF), openpyxl (XLSX), python-docx (DOCX), LibreOffice headless (legacy DOC conversion)

---

### Task 1: Add new dependencies

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add PyMuPDF, openpyxl, and python-docx to pyproject.toml**

In `pyproject.toml`, add to the `dependencies` list:

```toml
dependencies = [
    "mcp[cli]",
    "presidio-analyzer",
    "presidio-anonymizer",
    "spacy",
    "PyMuPDF",
    "openpyxl",
    "python-docx",
]
```

**Step 2: Install dependencies**

Run: `uv sync`
Expected: All three new packages install successfully.

**Step 3: Verify imports work**

Run: `uv run python -c "import fitz; import openpyxl; import docx; print('OK')"`
Expected: Prints `OK`

**Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: add PyMuPDF, openpyxl, python-docx dependencies"
```

---

### Task 2: Create base handler interface and PlainTextHandler

**Files:**
- Create: `src/mcp_server_redaction/handlers/__init__.py`
- Create: `src/mcp_server_redaction/handlers/base.py`
- Create: `src/mcp_server_redaction/handlers/plain_text.py`
- Create: `tests/test_handlers.py`

**Step 1: Write the test for PlainTextHandler**

Create `tests/test_handlers.py`:

```python
import json
import os
import tempfile

from mcp_server_redaction.engine import RedactionEngine
from mcp_server_redaction.handlers.plain_text import PlainTextHandler


class TestPlainTextHandler:
    def setup_method(self):
        self.engine = RedactionEngine()
        self.handler = PlainTextHandler()

    def test_redact_creates_output_file(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as f:
            f.write("Contact john@example.com for details.\n")
            input_path = f.name

        base, ext = os.path.splitext(input_path)
        output_path = f"{base}_redacted{ext}"

        try:
            result = self.handler.redact(
                self.engine, input_path, output_path
            )
            assert result["entities_found"] >= 1
            assert "session_id" in result

            with open(output_path) as rf:
                content = rf.read()
            assert "john@example.com" not in content
            assert "[EMAIL_ADDRESS_1]" in content
        finally:
            os.unlink(input_path)
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_unredact_restores_file(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as f:
            f.write("Contact john@example.com for details.\n")
            input_path = f.name

        base, ext = os.path.splitext(input_path)
        redacted_path = f"{base}_redacted{ext}"
        unredacted_path = f"{base}_redacted_unredacted{ext}"

        try:
            result = self.handler.redact(
                self.engine, input_path, redacted_path
            )
            session_id = result["session_id"]
            mappings = self.engine.state.get_mappings(session_id)

            undo_result = self.handler.unredact(
                redacted_path, unredacted_path, mappings
            )
            assert undo_result["entities_restored"] >= 1

            with open(unredacted_path) as rf:
                content = rf.read()
            assert "john@example.com" in content
        finally:
            for p in [input_path, redacted_path, unredacted_path]:
                if os.path.exists(p):
                    os.unlink(p)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_handlers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mcp_server_redaction.handlers'`

**Step 3: Create the base handler class**

Create `src/mcp_server_redaction/handlers/base.py`:

```python
from abc import ABC, abstractmethod

from ..engine import RedactionEngine


class FileHandler(ABC):
    @abstractmethod
    def redact(
        self,
        engine: RedactionEngine,
        input_path: str,
        output_path: str,
        entity_types: list[str] | None = None,
        use_placeholders: bool = True,
    ) -> dict:
        """Redact sensitive data in the file. Write result to output_path.

        Returns dict with keys: session_id (str or None), entities_found (int).
        session_id is None when use_placeholders=False (irreversible redaction).
        """

    @abstractmethod
    def unredact(
        self,
        input_path: str,
        output_path: str,
        mappings: dict[str, str],
    ) -> dict:
        """Replace placeholders in the file using mappings.

        Returns dict with keys: entities_restored (int).
        """
```

**Step 4: Create PlainTextHandler**

Create `src/mcp_server_redaction/handlers/plain_text.py`:

```python
import re

from ..engine import RedactionEngine
from .base import FileHandler


class PlainTextHandler(FileHandler):
    def redact(
        self,
        engine: RedactionEngine,
        input_path: str,
        output_path: str,
        entity_types: list[str] | None = None,
        use_placeholders: bool = True,
    ) -> dict:
        with open(input_path) as f:
            content = f.read()

        result = engine.redact(content, entity_types=entity_types)

        with open(output_path, "w") as f:
            f.write(result["redacted_text"])

        return {
            "session_id": result["session_id"],
            "entities_found": result["entities_found"],
        }

    def unredact(
        self,
        input_path: str,
        output_path: str,
        mappings: dict[str, str],
    ) -> dict:
        with open(input_path) as f:
            content = f.read()

        entities_restored = 0
        for placeholder, original in mappings.items():
            if placeholder in content:
                content = content.replace(placeholder, original)
                entities_restored += 1

        with open(output_path, "w") as f:
            f.write(content)

        return {"entities_restored": entities_restored}
```

**Step 5: Create handlers `__init__.py`**

Create `src/mcp_server_redaction/handlers/__init__.py`:

```python
from .base import FileHandler
from .plain_text import PlainTextHandler

_HANDLER_MAP: dict[str, type[FileHandler]] = {
    ".txt": PlainTextHandler,
    ".csv": PlainTextHandler,
    ".log": PlainTextHandler,
    ".md": PlainTextHandler,
}


def get_handler(extension: str) -> FileHandler:
    """Return a handler instance for the given file extension.

    Raises ValueError if the extension is not supported.
    """
    ext = extension.lower()
    handler_cls = _HANDLER_MAP.get(ext)
    if handler_cls is None:
        supported = ", ".join(sorted(_HANDLER_MAP.keys()))
        raise ValueError(
            f"Unsupported file extension: '{ext}'. Supported: {supported}"
        )
    return handler_cls()
```

**Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_handlers.py -v`
Expected: 2 passed

**Step 7: Commit**

```bash
git add src/mcp_server_redaction/handlers/ tests/test_handlers.py
git commit -m "feat: add handler base class and PlainTextHandler"
```

---

### Task 3: Refactor redact_file to use handler dispatch

**Files:**
- Modify: `src/mcp_server_redaction/tools/redact_file.py`
- Modify: `src/mcp_server_redaction/server.py` (add `use_placeholders` param)

**Step 1: Write a test for unsupported extension**

Add to `tests/test_handlers.py`:

```python
import pytest
from mcp_server_redaction.handlers import get_handler


class TestHandlerDispatch:
    def test_get_handler_txt(self):
        handler = get_handler(".txt")
        assert isinstance(handler, PlainTextHandler)

    def test_get_handler_unsupported(self):
        with pytest.raises(ValueError, match="Unsupported file extension"):
            get_handler(".xyz")
```

**Step 2: Run test to verify it passes** (handler dispatch was already implemented)

Run: `uv run pytest tests/test_handlers.py::TestHandlerDispatch -v`
Expected: 2 passed

**Step 3: Refactor `tools/redact_file.py` to use handler dispatch**

Replace the contents of `src/mcp_server_redaction/tools/redact_file.py` with:

```python
import json
import os

from ..engine import RedactionEngine
from ..handlers import get_handler


def handle_redact_file(
    engine: RedactionEngine,
    file_path: str,
    entity_types: list[str] | None = None,
    use_placeholders: bool = True,
) -> str:
    if not os.path.isfile(file_path):
        return json.dumps({"error": f"File not found: {file_path}"})

    _, ext = os.path.splitext(file_path)

    try:
        handler = get_handler(ext)
    except ValueError as e:
        return json.dumps({"error": str(e)})

    base, ext = os.path.splitext(file_path)
    output_ext = ext
    # .doc files get converted to .docx
    if ext.lower() == ".doc":
        output_ext = ".docx"
    redacted_path = f"{base}_redacted{output_ext}"

    try:
        result = handler.redact(
            engine,
            file_path,
            redacted_path,
            entity_types=entity_types,
            use_placeholders=use_placeholders,
        )
    except Exception as e:
        return json.dumps({"error": f"Redaction failed: {e}"})

    response = {
        "redacted_file_path": redacted_path,
        "entities_found": result["entities_found"],
    }
    if result.get("session_id"):
        response["session_id"] = result["session_id"]

    return json.dumps(response)
```

**Step 4: Update `server.py` to add `use_placeholders` parameter**

In `src/mcp_server_redaction/server.py`, update the `redact_file` tool:

```python
@mcp.tool()
def redact_file(
    file_path: str,
    entity_types: list[str] | None = None,
    use_placeholders: bool = True,
) -> str:
    """Redact sensitive data in a file. Writes a new file with '_redacted' suffix.

    Supports: .txt, .csv, .log, .md, .pdf, .xlsx, .docx, .doc

    Args:
        file_path: Absolute path to the file to redact.
        entity_types: Optional list of entity types to redact.
        use_placeholders: If True (default), use [ENTITY_TYPE_N] placeholders (reversible).
                          If False, use black-box redaction for PDFs (irreversible).
    """
    from .tools.redact_file import handle_redact_file
    return handle_redact_file(
        engine,
        file_path=file_path,
        entity_types=entity_types,
        use_placeholders=use_placeholders,
    )
```

**Step 5: Run all existing tests to verify nothing broke**

Run: `uv run pytest tests/ -v`
Expected: All tests pass (existing `TestRedactFileTool` tests still work)

**Step 6: Commit**

```bash
git add src/mcp_server_redaction/tools/redact_file.py src/mcp_server_redaction/server.py
git commit -m "refactor: redact_file uses handler dispatch, add use_placeholders flag"
```

---

### Task 4: Create DocxHandler

**Files:**
- Create: `src/mcp_server_redaction/handlers/docx_handler.py`
- Modify: `src/mcp_server_redaction/handlers/__init__.py`
- Modify: `tests/test_handlers.py`

**Step 1: Write failing tests for DOCX redaction**

Add to `tests/test_handlers.py`:

```python
import docx as python_docx

from mcp_server_redaction.handlers.docx_handler import DocxHandler


def _create_test_docx(path: str, paragraphs: list[str]) -> None:
    """Helper: create a DOCX file with the given paragraph texts."""
    doc = python_docx.Document()
    for text in paragraphs:
        doc.add_paragraph(text)
    doc.save(path)


class TestDocxHandler:
    def setup_method(self):
        self.engine = RedactionEngine()
        self.handler = DocxHandler()

    def test_redact_docx(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "test.docx")
            output_path = os.path.join(tmpdir, "test_redacted.docx")

            _create_test_docx(input_path, [
                "Contact john@example.com for details.",
                "No sensitive data here.",
            ])

            result = self.handler.redact(
                self.engine, input_path, output_path
            )
            assert result["entities_found"] >= 1
            assert result["session_id"] is not None

            doc = python_docx.Document(output_path)
            all_text = "\n".join(p.text for p in doc.paragraphs)
            assert "john@example.com" not in all_text
            assert "[EMAIL_ADDRESS_1]" in all_text
            assert "No sensitive data here." in all_text

    def test_unredact_docx(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "test.docx")
            redacted_path = os.path.join(tmpdir, "test_redacted.docx")
            unredacted_path = os.path.join(tmpdir, "test_unredacted.docx")

            _create_test_docx(input_path, [
                "Contact john@example.com for details.",
            ])

            result = self.handler.redact(
                self.engine, input_path, redacted_path
            )
            mappings = self.engine.state.get_mappings(result["session_id"])

            undo = self.handler.unredact(
                redacted_path, unredacted_path, mappings
            )
            assert undo["entities_restored"] >= 1

            doc = python_docx.Document(unredacted_path)
            assert "john@example.com" in doc.paragraphs[0].text

    def test_redact_docx_with_table(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "test.docx")
            output_path = os.path.join(tmpdir, "test_redacted.docx")

            doc = python_docx.Document()
            doc.add_paragraph("Header text")
            table = doc.add_table(rows=1, cols=2)
            table.cell(0, 0).text = "Name"
            table.cell(0, 1).text = "john@example.com"
            doc.save(input_path)

            result = self.handler.redact(
                self.engine, input_path, output_path
            )
            assert result["entities_found"] >= 1

            out_doc = python_docx.Document(output_path)
            cell_text = out_doc.tables[0].cell(0, 1).text
            assert "john@example.com" not in cell_text
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_handlers.py::TestDocxHandler -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement DocxHandler**

Create `src/mcp_server_redaction/handlers/docx_handler.py`:

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

        # Process paragraphs
        for para in doc.paragraphs:
            if not para.text.strip():
                continue
            result = engine.redact(para.text, entity_types=entity_types)
            if result["entities_found"] > 0:
                total_found += result["entities_found"]
                session_id = session_id or result["session_id"]
                # Merge session mappings if we got a new session
                if session_id != result["session_id"]:
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
                            elif session_id != result["session_id"]:
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
        # Keep the first run's formatting, clear the rest
        first_run = para.runs[0]
        for run in para.runs[1:]:
            run.text = ""
        first_run.text = new_text

    @staticmethod
    def _apply_mappings(
        text: str, mappings: dict[str, str]
    ) -> tuple[str, int]:
        count = 0
        for placeholder, original in mappings.items():
            if placeholder in text:
                text = text.replace(placeholder, original)
                count += 1
        return text, count

    @staticmethod
    def _merge_session(
        engine: RedactionEngine, target_id: str, source_id: str
    ) -> None:
        """Copy all mappings from source session into target session."""
        source_mappings = engine.state.get_mappings(source_id)
        if source_mappings:
            for placeholder, original in source_mappings.items():
                engine.state.add_mapping(target_id, placeholder, original)
```

**Step 4: Register DocxHandler in `handlers/__init__.py`**

Add to `src/mcp_server_redaction/handlers/__init__.py`:

```python
from .base import FileHandler
from .plain_text import PlainTextHandler
from .docx_handler import DocxHandler

_HANDLER_MAP: dict[str, type[FileHandler]] = {
    ".txt": PlainTextHandler,
    ".csv": PlainTextHandler,
    ".log": PlainTextHandler,
    ".md": PlainTextHandler,
    ".docx": DocxHandler,
}
```

(Keep the `get_handler` function unchanged.)

**Step 5: Run tests**

Run: `uv run pytest tests/test_handlers.py::TestDocxHandler -v`
Expected: 3 passed

**Step 6: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: All pass

**Step 7: Commit**

```bash
git add src/mcp_server_redaction/handlers/ tests/test_handlers.py
git commit -m "feat: add DocxHandler for DOCX file redaction"
```

---

### Task 5: Create XlsxHandler

**Files:**
- Create: `src/mcp_server_redaction/handlers/xlsx.py`
- Modify: `src/mcp_server_redaction/handlers/__init__.py`
- Modify: `tests/test_handlers.py`

**Step 1: Write failing tests for XLSX redaction**

Add to `tests/test_handlers.py`:

```python
import openpyxl

from mcp_server_redaction.handlers.xlsx import XlsxHandler


class TestXlsxHandler:
    def setup_method(self):
        self.engine = RedactionEngine()
        self.handler = XlsxHandler()

    def test_redact_xlsx(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "test.xlsx")
            output_path = os.path.join(tmpdir, "test_redacted.xlsx")

            wb = openpyxl.Workbook()
            ws = wb.active
            ws["A1"] = "Name"
            ws["B1"] = "Email"
            ws["A2"] = "John Smith"
            ws["B2"] = "john@example.com"
            wb.save(input_path)

            result = self.handler.redact(
                self.engine, input_path, output_path
            )
            assert result["entities_found"] >= 1
            assert result["session_id"] is not None

            wb_out = openpyxl.load_workbook(output_path)
            ws_out = wb_out.active
            assert "john@example.com" not in str(ws_out["B2"].value)
            # Header should be untouched
            assert ws_out["A1"].value == "Name"

    def test_redact_xlsx_multiple_sheets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "test.xlsx")
            output_path = os.path.join(tmpdir, "test_redacted.xlsx")

            wb = openpyxl.Workbook()
            ws1 = wb.active
            ws1.title = "Sheet1"
            ws1["A1"] = "john@example.com"
            ws2 = wb.create_sheet("Sheet2")
            ws2["A1"] = "jane@example.com"
            wb.save(input_path)

            result = self.handler.redact(
                self.engine, input_path, output_path
            )
            assert result["entities_found"] >= 2

    def test_unredact_xlsx(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "test.xlsx")
            redacted_path = os.path.join(tmpdir, "test_redacted.xlsx")
            unredacted_path = os.path.join(tmpdir, "test_unredacted.xlsx")

            wb = openpyxl.Workbook()
            ws = wb.active
            ws["A1"] = "john@example.com"
            wb.save(input_path)

            result = self.handler.redact(
                self.engine, input_path, redacted_path
            )
            mappings = self.engine.state.get_mappings(result["session_id"])

            undo = self.handler.unredact(
                redacted_path, unredacted_path, mappings
            )
            assert undo["entities_restored"] >= 1

            wb_out = openpyxl.load_workbook(unredacted_path)
            assert wb_out.active["A1"].value == "john@example.com"
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_handlers.py::TestXlsxHandler -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement XlsxHandler**

Create `src/mcp_server_redaction/handlers/xlsx.py`:

```python
import openpyxl

from ..engine import RedactionEngine
from .base import FileHandler


class XlsxHandler(FileHandler):
    def redact(
        self,
        engine: RedactionEngine,
        input_path: str,
        output_path: str,
        entity_types: list[str] | None = None,
        use_placeholders: bool = True,
    ) -> dict:
        wb = openpyxl.load_workbook(input_path)
        total_found = 0
        session_id = None

        for ws in wb.worksheets:
            for row in ws.iter_rows():
                for cell in row:
                    if cell.value is None or not isinstance(cell.value, str):
                        continue
                    if not cell.value.strip():
                        continue
                    result = engine.redact(cell.value, entity_types=entity_types)
                    if result["entities_found"] > 0:
                        total_found += result["entities_found"]
                        if session_id is None:
                            session_id = result["session_id"]
                        elif session_id != result["session_id"]:
                            self._merge_session(engine, session_id, result["session_id"])
                        cell.value = result["redacted_text"]

        if session_id is None:
            session_id = engine.state.create_session()

        wb.save(output_path)
        return {"session_id": session_id, "entities_found": total_found}

    def unredact(
        self,
        input_path: str,
        output_path: str,
        mappings: dict[str, str],
    ) -> dict:
        wb = openpyxl.load_workbook(input_path)
        entities_restored = 0

        for ws in wb.worksheets:
            for row in ws.iter_rows():
                for cell in row:
                    if cell.value is None or not isinstance(cell.value, str):
                        continue
                    new_value = cell.value
                    for placeholder, original in mappings.items():
                        if placeholder in new_value:
                            new_value = new_value.replace(placeholder, original)
                            entities_restored += 1
                    if new_value != cell.value:
                        cell.value = new_value

        wb.save(output_path)
        return {"entities_restored": entities_restored}

    @staticmethod
    def _merge_session(
        engine: RedactionEngine, target_id: str, source_id: str
    ) -> None:
        source_mappings = engine.state.get_mappings(source_id)
        if source_mappings:
            for placeholder, original in source_mappings.items():
                engine.state.add_mapping(target_id, placeholder, original)
```

**Step 4: Register XlsxHandler in `handlers/__init__.py`**

Add to the imports and `_HANDLER_MAP`:

```python
from .xlsx import XlsxHandler

# Add to _HANDLER_MAP:
    ".xlsx": XlsxHandler,
```

**Step 5: Run tests**

Run: `uv run pytest tests/test_handlers.py::TestXlsxHandler -v`
Expected: 3 passed

**Step 6: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: All pass

**Step 7: Commit**

```bash
git add src/mcp_server_redaction/handlers/ tests/test_handlers.py
git commit -m "feat: add XlsxHandler for Excel file redaction"
```

---

### Task 6: Create PdfHandler

**Files:**
- Create: `src/mcp_server_redaction/handlers/pdf.py`
- Modify: `src/mcp_server_redaction/handlers/__init__.py`
- Modify: `tests/test_handlers.py`

**Step 1: Write failing tests for PDF redaction**

Add to `tests/test_handlers.py`:

```python
import fitz  # PyMuPDF

from mcp_server_redaction.handlers.pdf import PdfHandler


def _create_test_pdf(path: str, pages: list[str]) -> None:
    """Helper: create a PDF with one text block per page."""
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        page.insert_text((72, 72), text, fontsize=12)
    doc.save(path)
    doc.close()


class TestPdfHandler:
    def setup_method(self):
        self.engine = RedactionEngine()
        self.handler = PdfHandler()

    def test_redact_pdf_placeholder_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "test.pdf")
            output_path = os.path.join(tmpdir, "test_redacted.pdf")

            _create_test_pdf(input_path, [
                "Contact john@example.com for details."
            ])

            result = self.handler.redact(
                self.engine, input_path, output_path,
                use_placeholders=True,
            )
            assert result["entities_found"] >= 1
            assert result["session_id"] is not None

            doc = fitz.open(output_path)
            page_text = doc[0].get_text()
            doc.close()
            assert "john@example.com" not in page_text
            assert "[EMAIL_ADDRESS_1]" in page_text

    def test_redact_pdf_blackbox_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "test.pdf")
            output_path = os.path.join(tmpdir, "test_redacted.pdf")

            _create_test_pdf(input_path, [
                "Contact john@example.com for details."
            ])

            result = self.handler.redact(
                self.engine, input_path, output_path,
                use_placeholders=False,
            )
            assert result["entities_found"] >= 1
            assert result["session_id"] is None

            doc = fitz.open(output_path)
            page_text = doc[0].get_text()
            doc.close()
            assert "john@example.com" not in page_text

    def test_unredact_pdf(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "test.pdf")
            redacted_path = os.path.join(tmpdir, "test_redacted.pdf")
            unredacted_path = os.path.join(tmpdir, "test_unredacted.pdf")

            _create_test_pdf(input_path, [
                "Contact john@example.com for details."
            ])

            result = self.handler.redact(
                self.engine, input_path, redacted_path,
                use_placeholders=True,
            )
            mappings = self.engine.state.get_mappings(result["session_id"])

            undo = self.handler.unredact(
                redacted_path, unredacted_path, mappings
            )
            assert undo["entities_restored"] >= 1

            doc = fitz.open(unredacted_path)
            page_text = doc[0].get_text()
            doc.close()
            assert "john@example.com" in page_text
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_handlers.py::TestPdfHandler -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement PdfHandler**

Create `src/mcp_server_redaction/handlers/pdf.py`:

```python
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

            # Use analyze to find entity positions in the page text
            analysis = engine.analyze(page_text, entity_types=entity_types)
            entities = analysis["entities"]
            if not entities:
                continue

            # Create a redaction session for placeholder tracking
            if use_placeholders:
                result = engine.redact(page_text, entity_types=entity_types)
                total_found += result["entities_found"]
                if session_id is None:
                    session_id = result["session_id"]
                elif session_id != result["session_id"]:
                    self._merge_session(engine, session_id, result["session_id"])

            # For each entity, find its text on the page and add redaction annotation
            for entity in entities:
                # Unmask the entity text to get the original for searching
                original_text = page_text[entity["start"]:entity["end"]]
                rects = page.search_for(original_text)
                for rect in rects:
                    if use_placeholders:
                        # Find the placeholder for this entity
                        placeholder = self._find_placeholder(
                            engine, session_id, original_text
                        )
                        page.add_redact_annot(
                            rect,
                            text=placeholder or "",
                            fontsize=10,
                        )
                    else:
                        page.add_redact_annot(rect)
                    total_found += 1 if not use_placeholders else 0

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
            for placeholder, original in mappings.items():
                rects = page.search_for(placeholder)
                for rect in rects:
                    page.add_redact_annot(rect, text=original, fontsize=10)
                    entities_restored += 1
            if entities_restored > 0:
                page.apply_redactions()

        doc.save(output_path)
        doc.close()
        return {"entities_restored": entities_restored}

    @staticmethod
    def _find_placeholder(
        engine: RedactionEngine, session_id: str, original_text: str
    ) -> str | None:
        """Look up the placeholder for a given original text value."""
        mappings = engine.state.get_mappings(session_id)
        if not mappings:
            return None
        for placeholder, original in mappings.items():
            if original == original_text:
                return placeholder
        return None

    @staticmethod
    def _merge_session(
        engine: RedactionEngine, target_id: str, source_id: str
    ) -> None:
        source_mappings = engine.state.get_mappings(source_id)
        if source_mappings:
            for placeholder, original in source_mappings.items():
                engine.state.add_mapping(target_id, placeholder, original)
```

**Step 4: Register PdfHandler in `handlers/__init__.py`**

Add to imports and `_HANDLER_MAP`:

```python
from .pdf import PdfHandler

# Add to _HANDLER_MAP:
    ".pdf": PdfHandler,
```

**Step 5: Run tests**

Run: `uv run pytest tests/test_handlers.py::TestPdfHandler -v`
Expected: 3 passed

**Step 6: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: All pass

**Step 7: Commit**

```bash
git add src/mcp_server_redaction/handlers/ tests/test_handlers.py
git commit -m "feat: add PdfHandler with black-box and placeholder modes"
```

---

### Task 7: Create DocHandler (LibreOffice conversion)

**Files:**
- Create: `src/mcp_server_redaction/handlers/doc.py`
- Modify: `src/mcp_server_redaction/handlers/__init__.py`
- Modify: `tests/test_handlers.py`

**Step 1: Write the test**

Add to `tests/test_handlers.py`:

```python
import shutil
import subprocess

from mcp_server_redaction.handlers.doc import DocHandler

# Skip all .doc tests if LibreOffice is not installed
LIBREOFFICE_AVAILABLE = shutil.which("libreoffice") is not None


class TestDocHandler:
    def setup_method(self):
        self.engine = RedactionEngine()
        self.handler = DocHandler()

    @pytest.mark.skipif(
        not LIBREOFFICE_AVAILABLE, reason="LibreOffice not installed"
    )
    def test_redact_doc(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a .docx first, then use LibreOffice to convert to .doc
            docx_path = os.path.join(tmpdir, "test.docx")
            _create_test_docx(docx_path, [
                "Contact john@example.com for details."
            ])
            subprocess.run(
                ["libreoffice", "--headless", "--convert-to", "doc",
                 "--outdir", tmpdir, docx_path],
                check=True, capture_output=True,
            )
            input_path = os.path.join(tmpdir, "test.doc")
            output_path = os.path.join(tmpdir, "test_redacted.docx")

            result = self.handler.redact(
                self.engine, input_path, output_path
            )
            assert result["entities_found"] >= 1

    def test_doc_handler_without_libreoffice_errors(self):
        handler = DocHandler()
        # Temporarily override the check
        original_which = shutil.which

        def fake_which(name):
            if name == "libreoffice":
                return None
            return original_which(name)

        shutil.which = fake_which
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                input_path = os.path.join(tmpdir, "test.doc")
                output_path = os.path.join(tmpdir, "test_redacted.docx")
                # Create a dummy .doc file
                with open(input_path, "w") as f:
                    f.write("dummy")
                with pytest.raises(
                    RuntimeError, match="LibreOffice is required"
                ):
                    handler.redact(self.engine, input_path, output_path)
        finally:
            shutil.which = original_which
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_handlers.py::TestDocHandler -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement DocHandler**

Create `src/mcp_server_redaction/handlers/doc.py`:

```python
import os
import shutil
import subprocess
import tempfile

from ..engine import RedactionEngine
from .base import FileHandler
from .docx_handler import DocxHandler


class DocHandler(FileHandler):
    """Handles legacy .doc files by converting to .docx via LibreOffice."""

    def __init__(self):
        self._docx_handler = DocxHandler()

    def redact(
        self,
        engine: RedactionEngine,
        input_path: str,
        output_path: str,
        entity_types: list[str] | None = None,
        use_placeholders: bool = True,
    ) -> dict:
        self._check_libreoffice()
        docx_path = self._convert_to_docx(input_path)
        try:
            return self._docx_handler.redact(
                engine, docx_path, output_path,
                entity_types=entity_types,
                use_placeholders=use_placeholders,
            )
        finally:
            os.unlink(docx_path)

    def unredact(
        self,
        input_path: str,
        output_path: str,
        mappings: dict[str, str],
    ) -> dict:
        # Input will be a .docx (from a previous redact), delegate directly
        return self._docx_handler.unredact(input_path, output_path, mappings)

    @staticmethod
    def _check_libreoffice() -> None:
        if shutil.which("libreoffice") is None:
            raise RuntimeError(
                "LibreOffice is required for .doc file support. "
                "Install it: https://www.libreoffice.org/download/"
            )

    @staticmethod
    def _convert_to_docx(doc_path: str) -> str:
        """Convert a .doc file to .docx using LibreOffice. Returns path to the .docx."""
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(
                [
                    "libreoffice", "--headless", "--convert-to", "docx",
                    "--outdir", tmpdir, doc_path,
                ],
                check=True,
                capture_output=True,
            )
            base = os.path.splitext(os.path.basename(doc_path))[0]
            converted = os.path.join(tmpdir, f"{base}.docx")
            # Move to a stable temp file so tmpdir can be cleaned
            stable_path = converted + ".tmp"
            shutil.move(converted, stable_path)
        return stable_path
```

**Step 4: Register DocHandler in `handlers/__init__.py`**

Add to imports and `_HANDLER_MAP`:

```python
from .doc import DocHandler

# Add to _HANDLER_MAP:
    ".doc": DocHandler,
```

**Step 5: Run tests**

Run: `uv run pytest tests/test_handlers.py::TestDocHandler -v`
Expected: 1 passed, 1 skipped (or 2 passed if LibreOffice is installed)

**Step 6: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: All pass

**Step 7: Commit**

```bash
git add src/mcp_server_redaction/handlers/ tests/test_handlers.py
git commit -m "feat: add DocHandler for legacy .doc via LibreOffice conversion"
```

---

### Task 8: Add unredact_file tool

**Files:**
- Create: `src/mcp_server_redaction/tools/unredact_file.py`
- Modify: `src/mcp_server_redaction/tools/__init__.py`
- Modify: `src/mcp_server_redaction/server.py`
- Modify: `tests/test_tools.py`

**Step 1: Write failing test**

Add to `tests/test_tools.py`:

```python
from mcp_server_redaction.tools.unredact_file import handle_unredact_file


class TestUnredactFileTool:
    def setup_method(self):
        self.engine = RedactionEngine()

    def test_unredact_file_roundtrip(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as f:
            f.write("Contact john@example.com for details.\n")
            input_path = f.name

        try:
            # First redact
            redact_result = json.loads(
                handle_redact_file(self.engine, file_path=input_path)
            )
            session_id = redact_result["session_id"]
            redacted_path = redact_result["redacted_file_path"]

            # Then unredact
            result = json.loads(
                handle_unredact_file(
                    self.engine,
                    file_path=redacted_path,
                    session_id=session_id,
                )
            )
            assert "unredacted_file_path" in result
            assert result["entities_restored"] >= 1

            with open(result["unredacted_file_path"]) as rf:
                content = rf.read()
            assert "john@example.com" in content

            os.unlink(result["unredacted_file_path"])
            os.unlink(redacted_path)
        finally:
            os.unlink(input_path)

    def test_unredact_file_bad_session(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as f:
            f.write("[EMAIL_ADDRESS_1]\n")
            path = f.name

        try:
            result = json.loads(
                handle_unredact_file(
                    self.engine, file_path=path, session_id="bad-id"
                )
            )
            assert "error" in result
        finally:
            os.unlink(path)
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools.py::TestUnredactFileTool -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement `handle_unredact_file`**

Create `src/mcp_server_redaction/tools/unredact_file.py`:

```python
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
```

**Step 4: Update `tools/__init__.py`**

Add to `src/mcp_server_redaction/tools/__init__.py`:

```python
from .unredact_file import handle_unredact_file

# Add to __all__:
    "handle_unredact_file",
```

**Step 5: Register the tool in `server.py`**

Add to `src/mcp_server_redaction/server.py`:

```python
@mcp.tool()
def unredact_file(file_path: str, session_id: str) -> str:
    """Restore a previously redacted file to the original using a session ID.

    Only works on files redacted with use_placeholders=True.

    Args:
        file_path: Absolute path to the redacted file.
        session_id: The session ID returned by the redact_file tool.
    """
    from .tools.unredact_file import handle_unredact_file
    return handle_unredact_file(engine, file_path=file_path, session_id=session_id)
```

**Step 6: Run tests**

Run: `uv run pytest tests/test_tools.py::TestUnredactFileTool -v`
Expected: 2 passed

**Step 7: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: All pass

**Step 8: Commit**

```bash
git add src/mcp_server_redaction/tools/ src/mcp_server_redaction/server.py tests/test_tools.py
git commit -m "feat: add unredact_file tool for reversing file redactions"
```

---

### Task 9: Integration tests for file format roundtrips

**Files:**
- Modify: `tests/test_integration.py`

**Step 1: Write roundtrip integration tests**

Add to `tests/test_integration.py`:

```python
import os
import tempfile

import docx as python_docx
import fitz
import openpyxl

from mcp_server_redaction.tools.redact_file import handle_redact_file
from mcp_server_redaction.tools.unredact_file import handle_unredact_file


class TestFileFormatRoundtrips:
    def setup_method(self):
        self.engine = RedactionEngine()

    def test_docx_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "test.docx")
            doc = python_docx.Document()
            doc.add_paragraph("Contact john@example.com for details.")
            doc.save(input_path)

            redact_result = json.loads(
                handle_redact_file(self.engine, file_path=input_path)
            )
            assert redact_result["entities_found"] >= 1

            unredact_result = json.loads(
                handle_unredact_file(
                    self.engine,
                    file_path=redact_result["redacted_file_path"],
                    session_id=redact_result["session_id"],
                )
            )
            assert unredact_result["entities_restored"] >= 1

            doc_out = python_docx.Document(unredact_result["unredacted_file_path"])
            assert "john@example.com" in doc_out.paragraphs[0].text

    def test_xlsx_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "test.xlsx")
            wb = openpyxl.Workbook()
            wb.active["A1"] = "john@example.com"
            wb.save(input_path)

            redact_result = json.loads(
                handle_redact_file(self.engine, file_path=input_path)
            )
            assert redact_result["entities_found"] >= 1

            unredact_result = json.loads(
                handle_unredact_file(
                    self.engine,
                    file_path=redact_result["redacted_file_path"],
                    session_id=redact_result["session_id"],
                )
            )
            assert unredact_result["entities_restored"] >= 1

            wb_out = openpyxl.load_workbook(unredact_result["unredacted_file_path"])
            assert wb_out.active["A1"].value == "john@example.com"

    def test_pdf_placeholder_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "test.pdf")
            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((72, 72), "Contact john@example.com for details.", fontsize=12)
            doc.save(input_path)
            doc.close()

            redact_result = json.loads(
                handle_redact_file(
                    self.engine, file_path=input_path, use_placeholders=True
                )
            )
            assert redact_result["entities_found"] >= 1

            unredact_result = json.loads(
                handle_unredact_file(
                    self.engine,
                    file_path=redact_result["redacted_file_path"],
                    session_id=redact_result["session_id"],
                )
            )
            assert unredact_result["entities_restored"] >= 1

            doc_out = fitz.open(unredact_result["unredacted_file_path"])
            assert "john@example.com" in doc_out[0].get_text()
            doc_out.close()
```

**Step 2: Run tests**

Run: `uv run pytest tests/test_integration.py::TestFileFormatRoundtrips -v`
Expected: 3 passed

**Step 3: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All pass

**Step 4: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: add file format roundtrip integration tests"
```

---

### Task 10: Update README

**Files:**
- Modify: `README.md`

**Step 1: Update the README**

Update the `redact_file` section to mention new formats and `use_placeholders`. Add the `unredact_file` tool section. Add `LibreOffice` to prerequisites (optional, for .doc support). Add `PyMuPDF`, `openpyxl`, `python-docx` to the implicit dependency list.

Key additions:
- In Prerequisites: "LibreOffice (optional, for .doc support)"
- Update `redact_file` example to show `use_placeholders` parameter
- Add `unredact_file` tool documentation
- Update Supported Formats section with: `.txt`, `.csv`, `.log`, `.md`, `.pdf`, `.xlsx`, `.docx`, `.doc`

**Step 2: Commit**

```bash
git add README.md
git commit -m "docs: update README with file format support and unredact_file tool"
```
