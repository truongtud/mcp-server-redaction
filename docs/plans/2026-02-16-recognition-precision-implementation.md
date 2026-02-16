# Recognition Precision Improvement — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Dramatically reduce false positives in PII detection by adding score thresholds, per-entity validation, and restricting GLiNER to semantic entity types.

**Architecture:** Three changes to the existing 3-layer detection pipeline: (1) pass a configurable `score_threshold` to Presidio's `AnalyzerEngine.analyze()` to filter low-confidence results, (2) add a post-detection `_validate_entity()` method that rejects detections failing basic format checks, (3) restrict GLiNER's entity mapping to ~10 semantic types that benefit from ML.

**Tech Stack:** Python 3.10+, presidio-analyzer, pytest

---

### Task 1: Score Threshold — Failing Tests

**Files:**
- Modify: `tests/test_engine.py` (append new test class)

**Step 1: Write the failing tests**

Add to end of `tests/test_engine.py`:

```python
class TestScoreThreshold:
    def test_default_threshold_filters_low_confidence(self):
        """Engine with default threshold (0.4) should not redact plain prose."""
        engine = RedactionEngine()
        text = "The sky is blue and the grass is green."
        result = engine.redact(text)
        assert result["entities_found"] == 0
        assert result["redacted_text"] == text

    def test_threshold_zero_accepts_everything(self):
        """Threshold 0.0 should behave like the old no-filter mode."""
        engine = RedactionEngine(score_threshold=0.0)
        text = "Contact john@example.com for info"
        result = engine.redact(text)
        assert result["entities_found"] >= 1

    def test_threshold_one_rejects_everything(self):
        """Threshold 1.0 should reject all detections (none score exactly 1.0)."""
        engine = RedactionEngine(score_threshold=1.0)
        text = "Contact john@example.com for info"
        result = engine.redact(text)
        assert result["entities_found"] == 0

    def test_custom_threshold_via_property(self):
        """score_threshold should be readable and writable."""
        engine = RedactionEngine(score_threshold=0.6)
        assert engine.score_threshold == 0.6
        engine.score_threshold = 0.3
        assert engine.score_threshold == 0.3

    def test_analyze_respects_threshold(self):
        """The analyze() method should also respect score_threshold."""
        engine = RedactionEngine(score_threshold=1.0)
        result = engine.analyze("Contact john@example.com")
        assert len(result["entities"]) == 0
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_engine.py::TestScoreThreshold -v`
Expected: FAIL — `RedactionEngine` doesn't accept `score_threshold` parameter yet.

**Step 3: Commit failing tests**

```bash
git add tests/test_engine.py
git commit -m "test: add failing tests for score_threshold parameter"
```

---

### Task 2: Score Threshold — Implementation

**Files:**
- Modify: `src/mcp_server_redaction/engine.py:9-17` (`__init__` signature + body)
- Modify: `src/mcp_server_redaction/engine.py:35-39` (`redact` method analyze call)
- Modify: `src/mcp_server_redaction/engine.py:135-139` (`analyze` method analyze call)

**Step 1: Add `score_threshold` to `__init__`**

In `engine.py`, change the `__init__` method:

```python
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
        self._score_threshold = score_threshold

    @property
    def score_threshold(self) -> float:
        return self._score_threshold

    @score_threshold.setter
    def score_threshold(self, value: float) -> None:
        self._score_threshold = value
```

**Step 2: Pass threshold in `redact()`**

In the `redact` method, change the analyze call (around line 35-39):

```python
        # --- L1 + L2: Presidio (regex recognizers + GLiNER) ---
        kwargs: dict = {
            "text": text,
            "language": "en",
            "score_threshold": self._score_threshold,
        }
        if entity_types:
            kwargs["entities"] = entity_types
```

**Step 3: Pass threshold in `analyze()`**

In the `analyze` method, change the analyze call (around line 135-139):

```python
        kwargs: dict = {
            "text": text,
            "language": "en",
            "score_threshold": self._score_threshold,
        }
        if entity_types:
            kwargs["entities"] = entity_types
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_engine.py::TestScoreThreshold -v`
Expected: ALL PASS

**Step 5: Run all existing tests to check for regressions**

Run: `python -m pytest tests/ -v`
Expected: ALL PASS. Some existing tests might need `score_threshold=0.0` if they relied on low-confidence detections getting through. If any fail, investigate and adjust.

**Step 6: Commit**

```bash
git add src/mcp_server_redaction/engine.py
git commit -m "feat(engine): add configurable score_threshold to filter low-confidence detections"
```

---

### Task 3: Entity Validation — Failing Tests

**Files:**
- Modify: `tests/test_engine.py` (append new test class)

**Step 1: Write the failing tests**

Add to end of `tests/test_engine.py`:

```python
class TestEntityValidation:
    def test_validate_swift_code_accepts_valid(self):
        assert RedactionEngine._validate_entity("DEUTDEFF", "SWIFT_CODE") is True
        assert RedactionEngine._validate_entity("DEUTDEFF500", "SWIFT_CODE") is True

    def test_validate_swift_code_rejects_lowercase(self):
        assert RedactionEngine._validate_entity("document", "SWIFT_CODE") is False
        assert RedactionEngine._validate_entity("credentials", "SWIFT_CODE") is False
        assert RedactionEngine._validate_entity("separate", "SWIFT_CODE") is False

    def test_validate_iban_accepts_valid(self):
        assert RedactionEngine._validate_entity("GB29NWBK60161331926819", "IBAN") is True

    def test_validate_iban_rejects_words(self):
        assert RedactionEngine._validate_entity("something", "IBAN") is False

    def test_validate_email_accepts_valid(self):
        assert RedactionEngine._validate_entity("john@example.com", "EMAIL_ADDRESS") is True

    def test_validate_email_rejects_no_at(self):
        assert RedactionEngine._validate_entity("notanemail", "EMAIL_ADDRESS") is False

    def test_validate_ip_accepts_valid(self):
        assert RedactionEngine._validate_entity("192.168.1.1", "IP_ADDRESS") is True

    def test_validate_ip_rejects_words(self):
        assert RedactionEngine._validate_entity("localhost", "IP_ADDRESS") is False

    def test_validate_ssn_accepts_valid(self):
        assert RedactionEngine._validate_entity("123-45-6789", "US_SSN") is True
        assert RedactionEngine._validate_entity("123456789", "US_SSN") is True

    def test_validate_ssn_rejects_short(self):
        assert RedactionEngine._validate_entity("12345", "US_SSN") is False

    def test_validate_phone_accepts_valid(self):
        assert RedactionEngine._validate_entity("555-123-4567", "PHONE_NUMBER") is True

    def test_validate_phone_rejects_short(self):
        assert RedactionEngine._validate_entity("12", "PHONE_NUMBER") is False

    def test_validate_unknown_type_passes_through(self):
        """Entity types without validation rules should always pass."""
        assert RedactionEngine._validate_entity("anything", "PERSON") is True
        assert RedactionEngine._validate_entity("anything", "ORGANIZATION") is True
        assert RedactionEngine._validate_entity("anything", "LOCATION") is True
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_engine.py::TestEntityValidation -v`
Expected: FAIL — `_validate_entity` doesn't exist yet.

**Step 3: Commit failing tests**

```bash
git add tests/test_engine.py
git commit -m "test: add failing tests for per-entity-type validation"
```

---

### Task 4: Entity Validation — Implementation

**Files:**
- Modify: `src/mcp_server_redaction/engine.py` (add `_validate_entity` static method, wire into `redact` and `analyze`)

**Step 1: Add `_validate_entity` method**

Add this static method to `RedactionEngine` (after `_remove_overlaps`):

```python
    @staticmethod
    def _validate_entity(text: str, entity_type: str) -> bool:
        """Check if detected text plausibly matches its entity type."""
        import re

        validators = {
            "SWIFT_CODE": lambda t: bool(re.fullmatch(r"[A-Z]{6}[A-Z0-9]{2,5}", t)),
            "IBAN": lambda t: bool(re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{4,}", t)),
            "CREDIT_CARD": lambda t: len(re.sub(r"\D", "", t)) in range(13, 20),
            "US_SSN": lambda t: bool(re.fullmatch(r"\d{3}-?\d{2}-?\d{4}", t)),
            "EMAIL_ADDRESS": lambda t: "@" in t and "." in t.split("@")[-1],
            "IP_ADDRESS": lambda t: bool(re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", t)),
            "PHONE_NUMBER": lambda t: len(re.sub(r"\D", "", t)) >= 7,
        }

        validator = validators.get(entity_type)
        if validator is None:
            return True  # No rule = pass through
        return validator(text)
```

**Step 2: Wire validation into `redact()`**

After `results = self._remove_overlaps(results)` (line 40 in current code), add filtering:

```python
        results = self._remove_overlaps(results)
        results = [
            r for r in results
            if self._validate_entity(text[r.start:r.end], r.entity_type)
        ]
```

Also apply after the LLM merge + final dedup (after line 65):

```python
            results = self._remove_overlaps(results)
            results = [
                r for r in results
                if self._validate_entity(text[r.start:r.end], r.entity_type)
            ]
```

**Step 3: Wire validation into `analyze()`**

After `results = self._remove_overlaps(results)` in the `analyze` method:

```python
        results = self._remove_overlaps(results)
        results = [
            r for r in results
            if self._validate_entity(text[r.start:r.end], r.entity_type)
        ]
```

**Step 4: Run validation tests**

Run: `python -m pytest tests/test_engine.py::TestEntityValidation -v`
Expected: ALL PASS

**Step 5: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add src/mcp_server_redaction/engine.py
git commit -m "feat(engine): add per-entity-type validation to reject format mismatches"
```

---

### Task 5: GLiNER Entity Restriction — Failing Test

**Files:**
- Modify: `tests/test_gliner.py` (add test for restricted labels)

**Step 1: Read current GLiNER tests**

Read `tests/test_gliner.py` for context.

**Step 2: Write the failing test**

Add to `tests/test_gliner.py`:

```python
class TestGlinerEntityMapping:
    def test_mapping_excludes_structured_types(self):
        """GLiNER should NOT try to detect types better handled by regex."""
        from mcp_server_redaction.recognizers.gliner_setup import GLINER_ENTITY_MAPPING
        structured_types = {
            "passport number", "credit card number", "social security number",
            "bank account number", "driver's license number",
            "tax identification number", "identity card number",
            "national id number", "ip address", "iban",
            "health insurance number", "insurance number",
            "registration number", "postal code", "license plate number",
        }
        for label in structured_types:
            assert label not in GLINER_ENTITY_MAPPING, (
                f"'{label}' should not be in GLiNER mapping — use L1 regex instead"
            )

    def test_mapping_keeps_semantic_types(self):
        """GLiNER should still detect types that need ML context awareness."""
        from mcp_server_redaction.recognizers.gliner_setup import GLINER_ENTITY_MAPPING
        semantic_types = {
            "person", "organization", "address", "email",
            "phone number", "mobile phone number",
            "date of birth", "medication", "medical condition", "username",
        }
        for label in semantic_types:
            assert label in GLINER_ENTITY_MAPPING, (
                f"'{label}' should remain in GLiNER mapping"
            )
```

**Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_gliner.py::TestGlinerEntityMapping -v`
Expected: FAIL — `test_mapping_excludes_structured_types` will fail because those labels are still present.

**Step 4: Commit failing tests**

```bash
git add tests/test_gliner.py
git commit -m "test: add failing tests for restricted GLiNER entity mapping"
```

---

### Task 6: GLiNER Entity Restriction — Implementation

**Files:**
- Modify: `src/mcp_server_redaction/recognizers/gliner_setup.py:9-35` (trim GLINER_ENTITY_MAPPING)

**Step 1: Replace the entity mapping**

Replace `GLINER_ENTITY_MAPPING` in `gliner_setup.py` with:

```python
GLINER_ENTITY_MAPPING = {
    "person": "PERSON",
    "organization": "ORGANIZATION",
    "phone number": "PHONE_NUMBER",
    "address": "LOCATION",
    "email": "EMAIL_ADDRESS",
    "date of birth": "DATE_TIME",
    "mobile phone number": "PHONE_NUMBER",
    "medication": "DRUG_NAME",
    "medical condition": "MEDICAL_CONDITION",
    "username": "USERNAME",
}
```

**Step 2: Run GLiNER mapping tests**

Run: `python -m pytest tests/test_gliner.py::TestGlinerEntityMapping -v`
Expected: ALL PASS

**Step 3: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add src/mcp_server_redaction/recognizers/gliner_setup.py
git commit -m "feat(gliner): restrict entity labels to semantic types only"
```

---

### Task 7: Configure Tool — Failing Test

**Files:**
- Modify: `tests/test_integration.py` (add test for threshold configuration)

**Step 1: Write the failing test**

Add a new test class to `tests/test_integration.py`:

```python
class TestConfigureThreshold:
    def setup_method(self):
        self.engine = RedactionEngine()

    def test_configure_sets_score_threshold(self):
        result = json.loads(
            handle_configure(self.engine, score_threshold=0.7)
        )
        assert result["status"] == "ok"
        assert result["score_threshold"] == 0.7
        assert self.engine.score_threshold == 0.7

    def test_configure_reports_current_threshold(self):
        result = json.loads(handle_configure(self.engine))
        assert "score_threshold" in result
        assert result["score_threshold"] == 0.4  # default
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_integration.py::TestConfigureThreshold -v`
Expected: FAIL — `handle_configure` doesn't accept `score_threshold` parameter yet.

**Step 3: Commit failing tests**

```bash
git add tests/test_integration.py
git commit -m "test: add failing tests for score_threshold in configure tool"
```

---

### Task 8: Configure Tool — Implementation

**Files:**
- Modify: `src/mcp_server_redaction/tools/configure.py` (add `score_threshold` parameter)
- Modify: `src/mcp_server_redaction/server.py:52-64` (pass `score_threshold` to handler)

**Step 1: Update `handle_configure` in `tools/configure.py`**

Replace the entire file:

```python
import json

from presidio_analyzer import Pattern, PatternRecognizer

from ..engine import RedactionEngine
from ..llm_reviewer import LLMReviewer


def handle_configure(
    engine: RedactionEngine,
    custom_patterns: list[dict] | None = None,
    disabled_entities: list[str] | None = None,
    score_threshold: float | None = None,
) -> str:
    if custom_patterns:
        for pattern_def in custom_patterns:
            recognizer = PatternRecognizer(
                supported_entity=pattern_def["name"],
                name=f"{pattern_def['name']}Recognizer",
                patterns=[
                    Pattern(
                        name=pattern_def["name"].lower(),
                        regex=pattern_def["pattern"],
                        score=pattern_def.get("score", 0.8),
                    )
                ],
            )
            engine.registry.add_recognizer(recognizer)

    if score_threshold is not None:
        engine.score_threshold = score_threshold

    active_entities = engine.registry.get_supported_entities()

    if disabled_entities:
        active_entities = [e for e in active_entities if e not in disabled_entities]

    return json.dumps({
        "status": "ok",
        "active_entities": sorted(active_entities),
        "score_threshold": engine.score_threshold,
        "llm_available": LLMReviewer.is_available(),
    })
```

**Step 2: Update the MCP tool in `server.py`**

Change the `configure` function in `server.py`:

```python
@mcp.tool()
def configure(
    custom_patterns: list[dict] | None = None,
    disabled_entities: list[str] | None = None,
    score_threshold: float | None = None,
) -> str:
    """Configure the redaction engine at runtime. Add custom patterns, disable entity types, or adjust sensitivity.

    Args:
        custom_patterns: List of pattern dicts with keys: name, pattern, score.
                         Example: [{"name": "INTERNAL_ID", "pattern": "ID-\\\\d{6}", "score": 0.9}]
        disabled_entities: List of entity type names to disable.
        score_threshold: Minimum confidence score (0.0-1.0) for entity detections.
                         Lower = more detections (more false positives).
                         Higher = fewer detections (more precise). Default: 0.4.
    """
    from .tools.configure import handle_configure
    return handle_configure(
        engine,
        custom_patterns=custom_patterns,
        disabled_entities=disabled_entities,
        score_threshold=score_threshold,
    )
```

**Step 3: Run configure tests**

Run: `python -m pytest tests/test_integration.py::TestConfigureThreshold -v`
Expected: ALL PASS

**Step 4: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/mcp_server_redaction/tools/configure.py src/mcp_server_redaction/server.py
git commit -m "feat(configure): expose score_threshold as runtime setting"
```

---

### Task 9: False Positive Regression Tests

**Files:**
- Modify: `tests/test_integration.py` (add false positive regression class)

**Step 1: Write the regression tests**

Add to `tests/test_integration.py`:

```python
class TestFalsePositiveRegression:
    """Regression tests for known false positive patterns.

    These sentences previously triggered false detections. They should
    produce zero or minimal redactions with the precision improvements.
    """

    def setup_method(self):
        self.engine = RedactionEngine(use_llm=False)

    def test_blog_prose_not_over_redacted(self):
        text = (
            "I Built an MCP Server That Lets Claude Redact Your Documents "
            "Before Reading Them. The gap between 'I need an LLM' and "
            "'this data shouldn't leave my machine' is wider than it should be."
        )
        result = self.engine.redact(text)
        # This prose contains no real PII — should have very few or zero detections.
        # "Claude" might still be flagged as PERSON (acceptable), but nothing else.
        assert result["entities_found"] <= 2
        assert "SWIFT_CODE" not in result["redacted_text"]

    def test_common_words_not_flagged_as_swift(self):
        text = "The credentials in the document are separate from the database."
        result = self.engine.redact(text)
        assert "SWIFT_CODE" not in result["redacted_text"]

    def test_time_expressions_not_over_flagged(self):
        text = "They spend twenty minutes manually scrubbing names and account numbers."
        result = self.engine.redact(text)
        # "twenty minutes" should not become [DATE_TIME_N]
        assert "twenty minutes" in result["redacted_text"] or result["entities_found"] <= 1

    def test_product_names_not_flagged(self):
        text = "Something where Claude could clean the document itself."
        result = self.engine.redact(text)
        assert "SWIFT_CODE" not in result["redacted_text"]

    def test_real_pii_still_detected(self):
        """Ensure precision improvements don't kill recall on real PII."""
        text = (
            "Patient John Smith (DOB: 03/15/1985) visited Dr. Sarah Johnson. "
            "Email: john.smith@hospital.org. Insurance: POL-2024-00045678."
        )
        result = self.engine.redact(text)
        assert "john.smith@hospital.org" not in result["redacted_text"]
        assert "John Smith" not in result["redacted_text"]
        assert result["entities_found"] >= 3
```

**Step 2: Run regression tests**

Run: `python -m pytest tests/test_integration.py::TestFalsePositiveRegression -v`
Expected: ALL PASS (these should pass now that threshold + validation are in place)

**Step 3: Run full suite**

Run: `python -m pytest tests/ -v`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: add false positive regression tests for recognition precision"
```

---

### Task 10: Final Verification and Cleanup

**Step 1: Run the full test suite**

Run: `python -m pytest tests/ -v --tb=short`
Expected: ALL PASS

**Step 2: Verify the user's original false positive scenario**

Run a quick manual test in Python REPL:

```bash
python -c "
from mcp_server_redaction.engine import RedactionEngine
engine = RedactionEngine(use_llm=False)
text = '''I Built an MCP Server That Lets Claude Redact Your Documents Before Reading Them.
The gap between I need an LLM and this data should not leave my machine is wider than it should be.
There is an awkward tension at the center of how most people use LLMs for work.
The documents where you need the most help - medical records, legal contracts, financial reports, codebases with real credentials - are exactly the documents you should not be pasting into a chat window.
So people either take the risk and paste anyway, or they spend twenty minutes manually scrubbing names and account numbers.
I wanted a third option. Something where Claude could clean the document itself, work with the sanitized version, and put the real values back when it is done. No extra step, no separate app, no hoping you caught every SSN buried in a table.'''
result = engine.redact(text)
print(f'Entities found: {result[\"entities_found\"]}')
print(f'Redacted text preview: {result[\"redacted_text\"][:200]}')
for e in result['entities']:
    print(f'  {e[\"type\"]}: {e[\"placeholder\"]}')
"
```

Expected: Very few entities (maybe "Claude" as PERSON, possibly some others). No SWIFT_CODE, no bogus DATE_TIME on "twenty minutes", no PERSON on "LLM".

**Step 3: Commit anything remaining**

If all passes clean, no further commit needed.
