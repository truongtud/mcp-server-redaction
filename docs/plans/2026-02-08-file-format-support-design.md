# File Format Support — Design Document

## Overview

Extend `redact_file` to handle PDF, XLSX, DOCX, and legacy DOC files with same-format output. Add an `unredact_file` tool for reversing placeholder-based redactions in these formats.

## Decisions

- **Output format:** Same as input (PDF in → redacted PDF out, XLSX → XLSX, etc.)
- **DOC handling:** Convert to DOCX via LibreOffice headless; output is always DOCX
- **PDF redaction modes:** Black-box (default) and placeholder, controlled by `use_placeholders` flag
- **Unredaction:** Supported in placeholder mode only; black-box is irreversible

## Architecture

### Handler-based dispatch

```
redact_file(file_path, ...)
    ├── .txt, .csv, .log  → PlainTextHandler (existing behavior)
    ├── .pdf              → PdfHandler (PyMuPDF)
    ├── .xlsx             → XlsxHandler (openpyxl)
    ├── .docx             → DocxHandler (python-docx)
    └── .doc              → DocHandler (LibreOffice convert → DocxHandler)
```

Each handler implements a common interface:
- `extract_text()` — pull text content with positional metadata
- `redact_and_write(redaction_result, output_path)` — apply redactions back into the original format

The redaction engine stays unchanged. Handlers extract text, pass it to the engine, then map results back.

### New module structure

```
src/mcp_server_redaction/
    handlers/
        __init__.py          # handler registry/dispatcher
        base.py              # abstract base class
        plain_text.py        # existing logic extracted here
        pdf.py               # PyMuPDF handler
        xlsx.py              # openpyxl handler
        docx.py              # python-docx handler
        doc.py               # LibreOffice conversion + delegates to docx
```

## Format-specific details

### PDF (PyMuPDF)

- Iterate pages, extract text spans with bounding boxes
- Run concatenated text through the redaction engine
- Map redacted entities back to page/bbox positions
- **Black-box mode (default):** Use `add_redact_annot()` + `apply_redactions()` to permanently remove text and draw black rectangles
- **Placeholder mode:** Remove original text and insert placeholder string at the same position

### XLSX (openpyxl)

- Iterate all sheets → rows → cells
- Collect cell values as text, tracking source cell coordinates
- Run through engine, write redacted values back to corresponding cells
- Preserves formatting, formulas in non-redacted cells, sheet structure

### DOCX (python-docx)

- Iterate paragraphs and tables → runs (text segments)
- Concatenate text per paragraph, run through engine
- Map redacted spans back to correct runs and replace text
- Preserves fonts, styles, and layout

### DOC (legacy)

- Shell out to `libreoffice --headless --convert-to docx`
- Pass resulting DOCX to DocxHandler
- Output is always `.docx`

## Tool interface changes

### Updated `redact_file`

```python
def redact_file(
    file_path: str,
    entity_types: list[str] | None = None,
    use_placeholders: bool = True,
) -> str:
```

- `use_placeholders=True` (default): Replaces entities with `[EMAIL_ADDRESS_1]`-style placeholders. Returns a `session_id` for unredaction.
- `use_placeholders=False`: PDF only — applies black-box redaction. No `session_id` returned (irreversible).

### New `unredact_file`

```python
def unredact_file(
    file_path: str,
    session_id: str,
) -> str:
```

- Takes a previously redacted file (with placeholders) and a session ID
- Dispatches to appropriate handler based on extension
- Handler scans document for placeholder patterns, looks up originals via session mapping, writes them back
- Output file gets `_unredacted` suffix

### Output path conventions

| Input | Output |
|-------|--------|
| `report.pdf` | `report_redacted.pdf` |
| `data.xlsx` | `data_redacted.xlsx` |
| `memo.docx` | `memo_redacted.docx` |
| `old.doc` | `old_redacted.docx` |
| `report_redacted.pdf` (unredact) | `report_redacted_unredacted.pdf` |

## Dependencies

### Python packages (new)

- `PyMuPDF` — PDF reading and redaction
- `openpyxl` — Excel reading/writing
- `python-docx` — Word DOCX reading/writing

### System dependencies (optional)

- `libreoffice` — Required only for legacy `.doc` support

## Error handling

- **Unsupported extension:** Clear error listing supported formats
- **`.doc` without LibreOffice:** Error with install instructions (no silent fallback)
- **Corrupted/password-protected files:** Catch library-specific exceptions, return descriptive errors
- **Scanned PDF (no selectable text):** Warning that no text was found to redact (OCR is out of scope)

## Testing strategy

- Unit tests per handler with small fixture files (1-page PDF, 2-sheet XLSX, short DOCX)
- Roundtrip test: redact with placeholders → unredact → compare to original
- Black-box PDF test: verify output contains no original sensitive text
- `.doc` conversion test (skipped in CI if LibreOffice not available)
