# Surgical File Redaction — Formatting Preservation

**Date**: 2026-02-14
**Status**: Approved

## Problem

The current file handlers degrade formatting when redacting:

- **DOCX**: `_replace_paragraph_text` collapses all runs into the first run, losing mixed formatting (bold, italic, font changes) within paragraphs.
- **PDF**: `add_redact_annot` uses a hardcoded `fontsize=10` and default font, ignoring the original text's appearance.
- **XLSX**: Already preserves cell formatting (no changes needed).

## Approach: Surgical In-Place Replacement

Fix the replacement logic in DOCX and PDF handlers to preserve formatting, rather than rethinking the architecture. The current approach of modifying the original document object in-place is sound — the problem is localized to how text gets swapped.

## Design

### 1. Engine: Entity Position Tracking

Add an `entities` field to the `engine.redact()` return value:

```python
{
    "redacted_text": "Hello [PERSON_1], your card is [CREDIT_CARD_1]",
    "session_id": "abc-123",
    "entities_found": 2,
    "entities": [
        {
            "type": "PERSON",
            "placeholder": "[PERSON_1]",
            "original_start": 6,
            "original_end": 14
        },
        {
            "type": "CREDIT_CARD",
            "placeholder": "[CREDIT_CARD_1]",
            "original_start": 31,
            "original_end": 47
        }
    ]
}
```

- `original_start`/`original_end` — character positions in the **input** text, needed for mapping PII to DOCX runs.
- Backward-compatible — existing callers that ignore `entities` are unaffected.

### 2. DOCX: Run-Aware Replacement

Replace `_replace_paragraph_text` with surgical per-run editing:

1. **Build a run-text map** — concatenate all runs, tracking character offset ranges per run (e.g., run 0 = chars 0-5, run 1 = chars 6-9 bold, run 2 = chars 10-15 italic).

2. **Map PII spans to runs** — use `original_start`/`original_end` from the engine to find which run(s) each entity falls in.

3. **Three replacement cases**:
   - **PII within a single run**: Replace only those characters in that run. All formatting preserved.
   - **PII spans the entire run**: Replace the run's text with the placeholder. Formatting preserved.
   - **PII crosses run boundaries**: Replace text in the first affected run with the placeholder, clear text in subsequent affected runs (keep empty runs to preserve document structure). Placeholder takes the first run's formatting.

4. **Unredact**: Same run-aware approach in reverse — find placeholder text within runs and replace surgically.

**Preserves**: Bold, italic, underline, font name, font size, color, hyperlinks, paragraph styles.

**Acceptable trade-off**: If PII crosses a bold-to-italic boundary, the placeholder takes the first run's formatting.

### 3. PDF: Font-Matched Redaction

Replace hardcoded font parameters with matched properties:

1. **Extract font info** — use `page.get_text("dict")` to get text blocks with font metadata (name, size, color, flags) per span.

2. **Match PII to spans** — for each entity, locate the corresponding span to capture its font properties.

3. **Apply with matched properties**:
   ```python
   page.add_redact_annot(
       rect,
       text=placeholder,
       fontname=original_fontname,  # fallback to "helv"
       fontsize=original_fontsize,
       text_color=original_color,
   )
   ```

4. **Font fallback** — if the original font isn't embeddable, fall back to a standard family (serif -> "tiro", sans -> "helv", mono -> "cour") at the correct size.

**Limitation**: PDF redaction is inherently destructive (`apply_redactions()` permanently removes content). Pixel-perfect positioning isn't guaranteed. This is acceptable.

### 4. Error Handling

- **DOCX**: If run-mapping fails (unusual DOCX structure where concatenated runs don't match paragraph text), fall back to current `_replace_paragraph_text` behavior. Degraded formatting is better than a crash.
- **PDF**: If font extraction fails for a span, fall back to `fontsize=10, fontname="helv"` (current behavior).

## Scope

**In scope**:
- Engine entity position tracking
- DOCX surgical run-aware replacement
- PDF font-matched redaction

**Out of scope**:
- DOC handler (converts to DOCX, inherits the fix)
- XLSX handler (already preserves formatting)
- PlainText handler (no formatting concept)

## Testing

- **DOCX formatting tests**: Mixed-format paragraphs (bold + italic + normal). Verify runs retain formatting after redaction. Test cross-run PII edge case.
- **PDF font matching tests**: Known font sizes. Verify placeholder uses similar font size via `get_text("dict")`.
- **Engine position tests**: Verify `original_start`/`original_end` correctness for single and multiple entities.
- **Regression**: Existing roundtrip tests (redact -> unredact -> compare) continue to pass.
