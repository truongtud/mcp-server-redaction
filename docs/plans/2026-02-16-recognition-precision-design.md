# Recognition Precision Improvement

## Problem

GLiNER (L2 detection layer) produces excessive false positives on common English words. The engine has no confidence threshold, so every detection — no matter how low-confidence — becomes a redaction. Examples from a blog post:

- "credentials" → `[SWIFT_CODE_132]`
- "document" → `[SWIFT_CODE_130]`
- "separate" → `[SWIFT_CODE_129]`
- "Claude" (product name) → `[PERSON_48]`
- "twenty minutes" → `[DATE_TIME_4]`
- "I need an LLM" → `[PERSON_47]`

Placeholder numbers (PERSON_48, SWIFT_CODE_132) indicate 100+ false detections in a single document.

## Root Causes

1. **No score threshold.** `AnalyzerEngine.analyze()` is called without `score_threshold`, accepting every detection at any confidence level.
2. **GLiNER detects too many entity types.** 35 labels including structured types (IBAN, SWIFT, credit card) that GLiNER cannot reliably detect from context alone — these need pattern matching, not ML.
3. **No post-detection validation.** GLiNER labels "document" as SWIFT_CODE with no check that the text actually looks like a SWIFT code.

## Approach: Score Threshold + Entity Validation + GLiNER Tuning

### 1. Score Threshold (engine.py)

Add `score_threshold: float = 0.4` to `RedactionEngine.__init__()`. Pass it to `self._analyzer.analyze()` in both `redact()` and `analyze()`. Make it configurable via the `configure` tool at runtime.

Default 0.4 filters out lowest-confidence detections (POSTAL_CODE 0.2, MRN 0.2, US_BANK_ROUTING 0.3, NPI 0.3) while keeping legitimate detections (most score 0.5+).

### 2. Per-Entity-Type Validation (engine.py)

New `_validate_entity(text: str, entity_type: str) -> bool` static method. Called after `_remove_overlaps()` to reject detections that fail basic format checks.

| Entity Type | Validation | Rationale |
|---|---|---|
| SWIFT_CODE | `^[A-Z]{6}[A-Z0-9]{2,5}$` | Rejects lowercase words |
| IBAN | `^[A-Z]{2}\d{2}[A-Z0-9]{4,}$` | Rejects common words |
| CREDIT_CARD | 13-19 digits + Luhn | Rejects random numbers |
| US_SSN | `^\d{3}-?\d{2}-?\d{4}$` | Tight pattern |
| EMAIL_ADDRESS | Contains `@` with domain | Basic sanity |
| IP_ADDRESS | `\d{1,3}(\.\d{1,3}){3}` | Rejects words |
| PHONE_NUMBER | 7+ digits present | Rejects short strings |

Entity types like PERSON, ORGANIZATION, LOCATION rely on score threshold only (no regex validation possible).

### 3. GLiNER Entity Label Restriction (gliner_setup.py)

Reduce GLiNER from 35 labels to ~10 semantic types that benefit from ML context awareness:

**Keep:** person, organization, address, email, phone number, mobile phone number, date of birth, medication, medical condition, username

**Remove:** passport number, credit card number, social security number, bank account number, driver's license number, tax identification number, identity card number, national id number, ip address, iban, health insurance number, insurance number, registration number, postal code, license plate number

Removed types are already covered by L1 regex recognizers with deterministic pattern matching.

### 4. Configure Tool (tools/configure.py)

Add `score_threshold` parameter to the configure tool. Accepts float 0.0-1.0. Updates `engine._score_threshold` at runtime.

## Testing

1. **False positive regression tests** — Blog post text asserting common words are NOT redacted.
2. **Threshold behavior tests** — Higher threshold = fewer detections.
3. **Validation unit tests** — `_validate_entity()` rejects "document" as SWIFT_CODE, etc.
4. **Configure tool test** — `score_threshold` is settable and persists.
5. **Real PII regression** — Existing PII-heavy tests still pass with new threshold.

## Files Modified

- `src/mcp_server_redaction/engine.py` — threshold param, validation method, filter loop
- `src/mcp_server_redaction/recognizers/gliner_setup.py` — reduce entity mapping
- `src/mcp_server_redaction/tools/configure.py` — expose threshold setting
- `tests/test_engine.py` — threshold + validation tests
- `tests/test_recognizers.py` — false positive regression
- `tests/test_integration.py` — end-to-end precision tests

## Decision Record

- **Priority:** Precision over recall
- **Default threshold:** 0.4
- **Configurable:** Yes, via configure tool at runtime
- **Approach:** Combined threshold + validation + GLiNER tuning
