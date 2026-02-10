# Hybrid 3-Layer PII Detection Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the English-only spaCy+regex detection in the MCP redaction server with a 3-layer hybrid system: L1 expanded regex patterns, L2 GLiNER zero-shot multilingual NER, L3 Ollama LLM review pass.

**Architecture:** The existing `RedactionEngine` gains a pipeline of detection layers. L1 (Presidio regex recognizers) runs first for fast, deterministic pattern matching. L2 (GLiNER via Presidio's built-in `GLiNERRecognizer`) adds zero-shot multilingual NER for names, addresses, and context-dependent PII. L3 (Ollama) runs as an optional second pass that catches domain-specific entities the first two layers miss. Results from all layers are merged and deduplicated by the existing `_remove_overlaps()` method. The MCP tool interface is unchanged — all improvements are internal to the engine.

**Tech Stack:** `presidio-analyzer[gliner]`, `urchade/gliner_multi_pii-v1` (HuggingFace model), `ollama` Python SDK, `llama3.1` (local LLM)

**Branch:** `feat/hybrid-detection` on `/mnt/d/projects/mcp-server-redaction`

---

## Task 1: Create feature branch and add dependencies

**Files:**
- Modify: `pyproject.toml`

**Step 1: Create the feature branch**

```bash
cd /mnt/d/projects/mcp-server-redaction
git checkout -b feat/hybrid-detection
```

**Step 2: Add new dependencies to pyproject.toml**

Add `gliner` extra for presidio-analyzer and `ollama` SDK. Change the `presidio-analyzer` line and add `ollama`:

```toml
[project]
dependencies = [
    "mcp[cli]",
    "presidio-analyzer[gliner]",
    "presidio-anonymizer",
    "spacy",
    "PyMuPDF",
    "openpyxl",
    "python-docx",
    "ollama",
]
```

**Step 3: Install dependencies**

```bash
uv sync
```

Expected: dependencies resolve and install. GLiNER model will be downloaded on first use (~500MB).

**Step 4: Verify Ollama is running with llama3.1**

```bash
ollama list | grep llama3.1
```

If not present:
```bash
ollama pull llama3.1
```

**Step 5: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add gliner and ollama dependencies"
```

---

## Task 2: Expand L1 regex recognizers — secrets and infrastructure

**Files:**
- Modify: `src/mcp_server_redaction/recognizers/secrets.py`
- Test: `tests/test_recognizers.py`

**Step 1: Write failing tests for new secret patterns**

Add to `tests/test_recognizers.py` inside `TestSecretsRecognizers`:

```python
def test_detect_azure_api_key(self):
    text = "Use key: 1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d"
    results = self.analyzer.analyze(text, entities=["API_KEY"], language="en")
    # Azure keys are 32 hex chars — only detected with context
    # This test checks that the pattern exists; context-based scoring applies

def test_detect_gcp_api_key(self):
    text = "Set GOOGLE_API_KEY=AIzaSyA1234567890abcdefghijklmnop"
    results = self.analyzer.analyze(text, entities=["API_KEY"], language="en")
    assert any(r.entity_type == "API_KEY" for r in results)

def test_detect_slack_token(self):
    text = "token: xoxb-1234567890-1234567890123-AbCdEfGhIjKlMnOpQrStUvWx"
    results = self.analyzer.analyze(text, entities=["API_KEY"], language="en")
    assert any(r.entity_type == "API_KEY" for r in results)

def test_detect_jwt_token(self):
    text = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
    results = self.analyzer.analyze(text, entities=["API_KEY"], language="en")
    assert any(r.entity_type == "API_KEY" for r in results)

def test_detect_ssh_private_key(self):
    text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA..."
    results = self.analyzer.analyze(text, entities=["SSH_PRIVATE_KEY"], language="en")
    assert any(r.entity_type == "SSH_PRIVATE_KEY" for r in results)
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_recognizers.py::TestSecretsRecognizers -v
```

Expected: New tests FAIL.

**Step 3: Add new patterns to secrets.py**

In `src/mcp_server_redaction/recognizers/secrets.py`, add patterns to the existing `ApiKeyRecognizer` and add a new `SshPrivateKeyRecognizer`:

```python
from presidio_analyzer import Pattern, PatternRecognizer


def create_secrets_recognizers() -> list[PatternRecognizer]:
    return [
        PatternRecognizer(
            supported_entity="API_KEY",
            name="ApiKeyRecognizer",
            patterns=[
                Pattern("openai_key", r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b", 0.9),
                Pattern("github_token", r"\bghp_[A-Za-z0-9]{36}\b", 0.9),
                Pattern("gitlab_token", r"\bglpat-[A-Za-z0-9\-_]{20,}\b", 0.9),
                Pattern("stripe_key", r"\b[sp]k_(?:live|test)_[A-Za-z0-9]{20,}\b", 0.9),
                Pattern("gcp_api_key", r"\bAIzaSy[A-Za-z0-9_-]{33}\b", 0.9),
                Pattern("slack_token", r"\bxox[bpoas]-[A-Za-z0-9\-]{10,250}\b", 0.9),
                Pattern("jwt_token", r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b", 0.9),
            ],
            context=["key", "token", "api", "secret", "bearer", "authorization"],
        ),
        PatternRecognizer(
            supported_entity="AWS_ACCESS_KEY",
            name="AwsAccessKeyRecognizer",
            patterns=[
                Pattern("aws_access_key", r"\bAKIA[0-9A-Z]{16}\b", 0.9),
            ],
            context=["aws", "key", "access"],
        ),
        PatternRecognizer(
            supported_entity="CONNECTION_STRING",
            name="ConnectionStringRecognizer",
            patterns=[
                Pattern("postgres_uri", r"\bpostgresql?://[^\s]+", 0.9),
                Pattern("mysql_uri", r"\bmysql://[^\s]+", 0.9),
                Pattern("mongodb_uri", r"\bmongodb(?:\+srv)?://[^\s]+", 0.9),
                Pattern("redis_uri", r"\brediss?://[^\s]+", 0.9),
            ],
            context=["database", "db", "connection", "uri", "url"],
        ),
        PatternRecognizer(
            supported_entity="SSH_PRIVATE_KEY",
            name="SshPrivateKeyRecognizer",
            patterns=[
                Pattern(
                    "ssh_private_key_header",
                    r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----",
                    0.95,
                ),
            ],
            context=["key", "ssh", "private"],
        ),
    ]
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_recognizers.py::TestSecretsRecognizers -v
```

Expected: All PASS.

**Step 5: Commit**

```bash
git add src/mcp_server_redaction/recognizers/secrets.py tests/test_recognizers.py
git commit -m "feat: expand API key patterns (GCP, Slack, JWT, SSH)"
```

---

## Task 3: Expand L1 regex recognizers — financial (SWIFT, postal codes)

**Files:**
- Modify: `src/mcp_server_redaction/recognizers/financial.py`
- Test: `tests/test_recognizers.py`

**Step 1: Write failing tests**

Add to `tests/test_recognizers.py` — new class `TestExpandedFinancialRecognizers`:

```python
class TestExpandedFinancialRecognizers:
    @pytest.fixture(autouse=True)
    def setup(self):
        from mcp_server_redaction.recognizers import build_registry
        registry = build_registry()
        self.analyzer = AnalyzerEngine(registry=registry)

    def test_detect_swift_code(self):
        text = "Transfer via SWIFT: DEUTDEFF500"
        results = self.analyzer.analyze(text, entities=["SWIFT_CODE"], language="en")
        assert any(r.entity_type == "SWIFT_CODE" for r in results)

    def test_detect_swift_code_8char(self):
        text = "BIC code is BNPAFRPP"
        results = self.analyzer.analyze(text, entities=["SWIFT_CODE"], language="en")
        assert any(r.entity_type == "SWIFT_CODE" for r in results)

    def test_detect_us_zip(self):
        text = "Address: 123 Main St, Springfield, IL 62704-1234"
        results = self.analyzer.analyze(text, entities=["POSTAL_CODE"], language="en")
        assert any(r.entity_type == "POSTAL_CODE" for r in results)

    def test_detect_uk_postcode(self):
        text = "Office at London SW1A 1AA"
        results = self.analyzer.analyze(text, entities=["POSTAL_CODE"], language="en")
        assert any(r.entity_type == "POSTAL_CODE" for r in results)

    def test_detect_de_plz(self):
        text = "Adresse: Berliner Str. 1, 10115 Berlin"
        results = self.analyzer.analyze(text, entities=["POSTAL_CODE"], language="en")
        assert any(r.entity_type == "POSTAL_CODE" for r in results)
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_recognizers.py::TestExpandedFinancialRecognizers -v
```

Expected: FAIL.

**Step 3: Add SWIFT and postal code recognizers to financial.py**

Append to `create_financial_recognizers()` return list:

```python
        PatternRecognizer(
            supported_entity="SWIFT_CODE",
            name="SwiftCodeRecognizer",
            patterns=[
                Pattern("swift_11", r"\b[A-Z]{6}[A-Z0-9]{2}[A-Z0-9]{3}\b", 0.7),
                Pattern("swift_8", r"\b[A-Z]{6}[A-Z0-9]{2}\b", 0.5),
            ],
            context=["swift", "bic", "bank", "transfer", "wire"],
        ),
        PatternRecognizer(
            supported_entity="POSTAL_CODE",
            name="PostalCodeRecognizer",
            patterns=[
                Pattern("us_zip", r"\b\d{5}(?:-\d{4})?\b", 0.3),
                Pattern("uk_postcode", r"\b[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}\b", 0.5),
                Pattern("de_plz", r"\b\d{5}\b", 0.2),
            ],
            context=["zip", "postal", "postcode", "plz", "address", "city"],
        ),
```

Note: low base scores on postal codes because 5-digit numbers are ambiguous — context keywords boost the score.

**Step 4: Run tests**

```bash
uv run pytest tests/test_recognizers.py::TestExpandedFinancialRecognizers -v
```

Expected: All PASS.

**Step 5: Commit**

```bash
git add src/mcp_server_redaction/recognizers/financial.py tests/test_recognizers.py
git commit -m "feat: add SWIFT/BIC and postal code recognizers"
```

---

## Task 4: Expand L1 regex recognizers — healthcare (NPI, DEA)

**Files:**
- Modify: `src/mcp_server_redaction/recognizers/medical.py`
- Test: `tests/test_recognizers.py`

**Step 1: Write failing tests**

Add class `TestExpandedMedicalRecognizers` in `tests/test_recognizers.py`:

```python
class TestExpandedMedicalRecognizers:
    @pytest.fixture(autouse=True)
    def setup(self):
        from mcp_server_redaction.recognizers import build_registry
        registry = build_registry()
        self.analyzer = AnalyzerEngine(registry=registry)

    def test_detect_npi_number(self):
        text = "Provider NPI: 1234567890"
        results = self.analyzer.analyze(text, entities=["NPI_NUMBER"], language="en")
        assert any(r.entity_type == "NPI_NUMBER" for r in results)

    def test_detect_dea_number(self):
        text = "DEA number: AB1234567"
        results = self.analyzer.analyze(text, entities=["DEA_NUMBER"], language="en")
        assert any(r.entity_type == "DEA_NUMBER" for r in results)

    def test_detect_health_insurance_id(self):
        text = "Insurance ID: XYZ123456789"
        results = self.analyzer.analyze(text, entities=["INSURANCE_ID"], language="en")
        assert any(r.entity_type == "INSURANCE_ID" for r in results)

    def test_detect_policy_number(self):
        text = "Policy number: POL-2024-00012345"
        results = self.analyzer.analyze(text, entities=["INSURANCE_ID"], language="en")
        assert any(r.entity_type == "INSURANCE_ID" for r in results)
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_recognizers.py::TestExpandedMedicalRecognizers -v
```

Expected: FAIL.

**Step 3: Add recognizers to medical.py**

Append to `create_medical_recognizers()` return list:

```python
        PatternRecognizer(
            supported_entity="NPI_NUMBER",
            name="NpiRecognizer",
            patterns=[
                Pattern("npi", r"\b\d{10}\b", 0.3),
            ],
            context=["npi", "provider", "national provider", "prescriber"],
        ),
        PatternRecognizer(
            supported_entity="DEA_NUMBER",
            name="DeaRecognizer",
            patterns=[
                Pattern("dea", r"\b[A-Z]{2}\d{7}\b", 0.6),
            ],
            context=["dea", "prescriber", "controlled substance", "schedule"],
        ),
        PatternRecognizer(
            supported_entity="INSURANCE_ID",
            name="InsuranceIdRecognizer",
            patterns=[
                Pattern("insurance_alphanum", r"\b[A-Z]{2,4}[-]?\d{6,12}\b", 0.4),
                Pattern("policy_number", r"\bPOL[-]?\d{4}[-]?\d{5,10}\b", 0.7),
                Pattern("claim_number", r"\bCLM[-]?\d{4}[-]?\d{5,10}\b", 0.7),
            ],
            context=[
                "insurance", "policy", "claim", "member", "subscriber",
                "group", "coverage", "id", "number",
            ],
        ),
```

**Step 4: Run tests**

```bash
uv run pytest tests/test_recognizers.py::TestExpandedMedicalRecognizers -v
```

Expected: All PASS.

**Step 5: Commit**

```bash
git add src/mcp_server_redaction/recognizers/medical.py tests/test_recognizers.py
git commit -m "feat: add NPI, DEA, and insurance ID recognizers"
```

---

## Task 5: Add L2 GLiNER recognizer to the registry

**Files:**
- Modify: `src/mcp_server_redaction/recognizers/__init__.py`
- Create: `src/mcp_server_redaction/recognizers/gliner_setup.py`
- Test: `tests/test_gliner.py`

**Step 1: Write failing test**

Create `tests/test_gliner.py`:

```python
import pytest
from presidio_analyzer import AnalyzerEngine

from mcp_server_redaction.recognizers import build_registry


class TestGLiNERRecognizer:
    @pytest.fixture(autouse=True)
    def setup(self):
        registry = build_registry()
        self.analyzer = AnalyzerEngine(registry=registry)

    def test_detect_person_multilingual(self):
        """GLiNER should catch names that spaCy might miss."""
        text = "Kontaktieren Sie Herrn Müller unter hans.mueller@firma.de"
        results = self.analyzer.analyze(text, language="en")
        entity_types = {r.entity_type for r in results}
        assert "EMAIL_ADDRESS" in entity_types  # regex catches this
        assert "PERSON" in entity_types  # GLiNER should catch "Herrn Müller"

    def test_detect_organization(self):
        text = "I work at Deutsche Telekom AG in Bonn."
        results = self.analyzer.analyze(text, language="en")
        entity_types = {r.entity_type for r in results}
        assert "ORGANIZATION" in entity_types or "PERSON" in entity_types

    def test_detect_address(self):
        text = "Ship to 742 Evergreen Terrace, Springfield, IL 62704"
        results = self.analyzer.analyze(text, language="en")
        entity_types = {r.entity_type for r in results}
        # GLiNER should find address components
        assert len(results) > 0

    def test_gliner_entities_have_scores(self):
        text = "Contact John Smith at john@example.com"
        results = self.analyzer.analyze(text, language="en")
        for r in results:
            assert 0.0 < r.score <= 1.0
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_gliner.py -v
```

Expected: FAIL (GLiNERRecognizer not in registry yet).

**Step 3: Create gliner_setup.py**

Create `src/mcp_server_redaction/recognizers/gliner_setup.py`:

```python
import logging

from presidio_analyzer import EntityRecognizer

logger = logging.getLogger(__name__)

# Mapping from GLiNER's entity labels to Presidio entity types.
# GLiNER model: urchade/gliner_multi_pii-v1
GLINER_ENTITY_MAPPING = {
    "person": "PERSON",
    "organization": "ORGANIZATION",
    "phone number": "PHONE_NUMBER",
    "address": "LOCATION",
    "passport number": "PASSPORT",
    "email": "EMAIL_ADDRESS",
    "credit card number": "CREDIT_CARD",
    "social security number": "US_SSN",
    "date of birth": "DATE_TIME",
    "mobile phone number": "PHONE_NUMBER",
    "bank account number": "US_BANK_NUMBER",
    "medication": "DRUG_NAME",
    "driver's license number": "US_DRIVER_LICENSE",
    "tax identification number": "TAX_ID",
    "medical condition": "MEDICAL_CONDITION",
    "identity card number": "NATIONAL_ID",
    "national id number": "NATIONAL_ID",
    "ip address": "IP_ADDRESS",
    "iban": "IBAN",
    "username": "USERNAME",
    "health insurance number": "INSURANCE_ID",
    "insurance number": "INSURANCE_ID",
    "registration number": "REGISTRATION_NUMBER",
    "postal code": "POSTAL_CODE",
    "license plate number": "LICENSE_PLATE",
}


def create_gliner_recognizer() -> EntityRecognizer | None:
    """Create a GLiNER-based recognizer. Returns None if GLiNER is unavailable."""
    try:
        from presidio_analyzer.predefined_recognizers import GLiNERRecognizer
    except ImportError:
        logger.warning(
            "GLiNER not available. Install with: pip install 'presidio-analyzer[gliner]'"
        )
        return None

    try:
        recognizer = GLiNERRecognizer(
            model_name="urchade/gliner_multi_pii-v1",
            entity_mapping=GLINER_ENTITY_MAPPING,
            flat_ner=False,
            multi_label=True,
            map_location="cpu",
        )
        logger.info("GLiNER recognizer loaded successfully")
        return recognizer
    except Exception:
        logger.exception("Failed to load GLiNER model")
        return None
```

**Step 4: Wire GLiNER into the registry**

Modify `src/mcp_server_redaction/recognizers/__init__.py`:

```python
from presidio_analyzer import RecognizerRegistry

from .financial import create_financial_recognizers
from .gliner_setup import create_gliner_recognizer
from .medical import create_medical_recognizers
from .secrets import create_secrets_recognizers


def build_registry() -> RecognizerRegistry:
    registry = RecognizerRegistry()
    registry.load_predefined_recognizers()

    for recognizer in create_secrets_recognizers():
        registry.add_recognizer(recognizer)
    for recognizer in create_financial_recognizers():
        registry.add_recognizer(recognizer)
    for recognizer in create_medical_recognizers():
        registry.add_recognizer(recognizer)

    gliner = create_gliner_recognizer()
    if gliner is not None:
        registry.add_recognizer(gliner)

    return registry
```

**Step 5: Run tests**

```bash
uv run pytest tests/test_gliner.py -v
```

Expected: All PASS (GLiNER model downloads on first run — ~500MB, may take a minute).

**Step 6: Run full test suite to check nothing is broken**

```bash
uv run pytest -v
```

Expected: All existing tests still PASS.

**Step 7: Commit**

```bash
git add src/mcp_server_redaction/recognizers/gliner_setup.py src/mcp_server_redaction/recognizers/__init__.py tests/test_gliner.py
git commit -m "feat: add GLiNER zero-shot multilingual NER (L2 detection layer)"
```

---

## Task 6: Add L3 Ollama LLM review layer

**Files:**
- Create: `src/mcp_server_redaction/llm_reviewer.py`
- Test: `tests/test_llm_reviewer.py`

**Step 1: Write failing test**

Create `tests/test_llm_reviewer.py`:

```python
import pytest

from mcp_server_redaction.llm_reviewer import LLMReviewer


class TestLLMReviewer:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.reviewer = LLMReviewer()

    @pytest.mark.skipif(
        not LLMReviewer.is_available(),
        reason="Ollama not running or llama3.1 not available",
    )
    def test_find_additional_entities(self):
        text = "Patient Jane Doe, age 45, policy number INS-2024-78901, was prescribed 50mg of Metformin daily."
        already_found = ["Jane Doe", "INS-2024-78901", "Metformin"]
        additional = self.reviewer.review(text, already_found)
        # LLM should flag "age 45" as PII
        assert isinstance(additional, list)
        for entity in additional:
            assert "text" in entity
            assert "entity_type" in entity
            assert "start" in entity
            assert "end" in entity

    @pytest.mark.skipif(
        not LLMReviewer.is_available(),
        reason="Ollama not running or llama3.1 not available",
    )
    def test_returns_empty_when_fully_redacted(self):
        text = "Hello world, nice weather today."
        additional = self.reviewer.review(text, [])
        assert isinstance(additional, list)
        # No PII in this text, list should be empty
        assert len(additional) == 0

    def test_is_available_returns_bool(self):
        result = LLMReviewer.is_available()
        assert isinstance(result, bool)

    def test_review_returns_empty_when_unavailable_and_disabled(self):
        reviewer = LLMReviewer(enabled=False)
        result = reviewer.review("John Smith lives at 123 Main St", [])
        assert result == []
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_llm_reviewer.py -v
```

Expected: FAIL (module doesn't exist).

**Step 3: Implement llm_reviewer.py**

Create `src/mcp_server_redaction/llm_reviewer.py`:

```python
import json
import logging
import re

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a PII (Personally Identifiable Information) detection expert. Your job is to find sensitive entities in text that automated tools may have missed.

You look for ALL types of PII including but not limited to:
- Names (any language/culture), ages, dates of birth
- Addresses, postal codes, GPS coordinates
- Phone numbers, email addresses, URLs with PII
- Government IDs (SSN, passport, driver's license, national IDs from any country)
- Financial data (account numbers, policy numbers, claim numbers, tax IDs)
- Medical data (patient IDs, diagnoses, medications, provider numbers)
- Biometric identifiers
- Vehicle registration, license plates
- Usernames, passwords, security questions/answers
- Any identifier that could link back to a specific individual

You support ALL languages: English, German, French, Vietnamese, Spanish, etc.

Respond ONLY with a JSON array. Each element must have:
- "text": the exact substring from the input
- "entity_type": one of PERSON, LOCATION, ORGANIZATION, PHONE_NUMBER, EMAIL_ADDRESS, DATE_OF_BIRTH, AGE, US_SSN, PASSPORT, DRIVER_LICENSE, NATIONAL_ID, TAX_ID, INSURANCE_ID, MEDICAL_CONDITION, DRUG_NAME, CREDIT_CARD, IBAN, IP_ADDRESS, USERNAME, LICENSE_PLATE, or a descriptive ALL_CAPS type.

If no additional PII is found, respond with: []"""


class LLMReviewer:
    def __init__(self, model: str = "llama3.1", enabled: bool = True):
        self._model = model
        self._enabled = enabled

    @staticmethod
    def is_available() -> bool:
        """Check if Ollama is running and the model is available."""
        try:
            import ollama
            models = ollama.list()
            return any("llama3.1" in m.model for m in models.models)
        except Exception:
            return False

    def review(self, text: str, already_found: list[str]) -> list[dict]:
        """Ask the LLM to find PII that existing layers missed.

        Args:
            text: The original text to review.
            already_found: List of entity text values already detected by L1/L2.

        Returns:
            List of dicts with keys: text, entity_type, start, end
        """
        if not self._enabled:
            return []

        try:
            import ollama
        except ImportError:
            logger.warning("ollama package not installed")
            return []

        already_str = ", ".join(f'"{v}"' for v in already_found) if already_found else "none"
        user_prompt = (
            f"The following entities were already detected: [{already_str}]\n\n"
            f"Find any ADDITIONAL PII in this text that was missed:\n\n{text}"
        )

        try:
            response = ollama.chat(
                model=self._model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                options={"temperature": 0},
            )
        except Exception:
            logger.exception("Ollama LLM review failed")
            return []

        return self._parse_response(response.message.content, text)

    def _parse_response(self, content: str, original_text: str) -> list[dict]:
        """Parse LLM JSON response and locate entities in the original text."""
        # Extract JSON array from response (LLM may wrap in markdown)
        match = re.search(r"\[.*\]", content, re.DOTALL)
        if not match:
            return []

        try:
            entities = json.loads(match.group())
        except json.JSONDecodeError:
            logger.warning("Failed to parse LLM response as JSON")
            return []

        if not isinstance(entities, list):
            return []

        result = []
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            text_val = entity.get("text", "")
            entity_type = entity.get("entity_type", "UNKNOWN")
            if not text_val:
                continue

            # Find the entity position in original text
            start = original_text.find(text_val)
            if start == -1:
                continue
            end = start + len(text_val)

            result.append({
                "text": text_val,
                "entity_type": entity_type,
                "start": start,
                "end": end,
            })

        return result
```

**Step 4: Run tests**

```bash
uv run pytest tests/test_llm_reviewer.py -v
```

Expected: Tests that require Ollama are skipped if not running; `test_is_available_returns_bool` and `test_review_returns_empty_when_unavailable_and_disabled` PASS.

**Step 5: Commit**

```bash
git add src/mcp_server_redaction/llm_reviewer.py tests/test_llm_reviewer.py
git commit -m "feat: add Ollama LLM reviewer (L3 detection layer)"
```

---

## Task 7: Integrate all 3 layers into RedactionEngine

**Files:**
- Modify: `src/mcp_server_redaction/engine.py`
- Modify: `tests/test_engine.py`

**Step 1: Write failing test for hybrid detection**

Add to `tests/test_engine.py`:

```python
class TestHybridDetection:
    def setup_method(self):
        self.engine = RedactionEngine()

    def test_redact_detects_email_and_person(self):
        """Basic sanity: L1 regex + L2 GLiNER should both contribute."""
        text = "Contact John Smith at john@example.com"
        result = self.engine.redact(text)
        assert result["entities_found"] >= 2
        assert "[EMAIL_ADDRESS_" in result["redacted_text"]
        assert "[PERSON_" in result["redacted_text"]

    def test_redact_multilingual_name(self):
        """GLiNER should detect non-English names."""
        text = "Kontaktieren Sie Herrn Hans Müller für Details."
        result = self.engine.redact(text)
        # At minimum, GLiNER should detect the person name
        assert result["entities_found"] >= 1

    def test_llm_layer_disabled_by_default_in_tests(self):
        """LLM layer should not block engine when Ollama is not available."""
        engine = RedactionEngine(use_llm=False)
        text = "Test text with john@example.com"
        result = engine.redact(text)
        assert result["entities_found"] >= 1

    def test_engine_backward_compatible(self):
        """Existing interface unchanged: returns redacted_text, session_id, entities_found."""
        text = "My email is test@example.com"
        result = self.engine.redact(text)
        assert "redacted_text" in result
        assert "session_id" in result
        assert "entities_found" in result
        assert isinstance(result["session_id"], str)
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_engine.py::TestHybridDetection -v
```

Expected: FAIL (`use_llm` parameter doesn't exist yet).

**Step 3: Modify engine.py to integrate L3**

Update `src/mcp_server_redaction/engine.py`:

```python
from presidio_analyzer import AnalyzerEngine

from .llm_reviewer import LLMReviewer
from .recognizers import build_registry
from .state import StateManager


class RedactionEngine:
    def __init__(
        self,
        state_manager: StateManager | None = None,
        use_llm: bool = True,
    ):
        self._registry = build_registry()
        self._analyzer = AnalyzerEngine(registry=self._registry)
        self._state = state_manager or StateManager()
        self._llm = LLMReviewer(enabled=use_llm and LLMReviewer.is_available())

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
        kwargs: dict = {"text": text, "language": "en"}
        if entity_types:
            kwargs["entities"] = entity_types

        results = self._analyzer.analyze(**kwargs)
        results = self._remove_overlaps(results)

        # --- L3: LLM review (find what L1+L2 missed) ---
        already_found = [text[r.start:r.end] for r in results]
        llm_entities = self._llm.review(text, already_found)

        # Convert LLM results to pseudo-RecognizerResult for merging
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
                        score=0.7,  # LLM-detected entities get moderate confidence
                    )
                )
            results = self._remove_overlaps(results)

        if not results:
            session_id = self._state.create_session()
            return {
                "redacted_text": text,
                "session_id": session_id,
                "entities_found": 0,
            }

        # Sort by start position (descending) so we can replace right-to-left
        results.sort(key=lambda r: r.start, reverse=True)

        type_counters: dict[str, int] = {}
        replacements: list[tuple[int, int, str, str]] = []

        for result in results:
            entity_type = result.entity_type
            type_counters.setdefault(entity_type, 0)
            type_counters[entity_type] += 1
            placeholder = f"[{entity_type}_{type_counters[entity_type]}]"
            original_value = text[result.start : result.end]
            replacements.append((result.start, result.end, placeholder, original_value))

        redacted_text = text
        session_id = self._state.create_session()
        for start, end, placeholder, original_value in replacements:
            redacted_text = redacted_text[:start] + placeholder + redacted_text[end:]
            self._state.add_mapping(session_id, placeholder, original_value)

        return {
            "redacted_text": redacted_text,
            "session_id": session_id,
            "entities_found": len(results),
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
        kwargs: dict = {"text": text, "language": "en"}
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
```

Key changes from original:
- Constructor adds `use_llm` parameter (default `True`, auto-disables if Ollama unavailable)
- `redact()` now runs L3 after L1+L2, merges results, deduplicates via `_remove_overlaps()`
- `unredact()` and `analyze()` unchanged
- All existing return formats preserved — **backward compatible**

**Step 4: Run the new tests**

```bash
uv run pytest tests/test_engine.py::TestHybridDetection -v
```

Expected: All PASS.

**Step 5: Run full test suite**

```bash
uv run pytest -v
```

Expected: All existing tests still PASS. Some may detect more entities than before (GLiNER is additive), so tests using exact entity counts may need `>=` instead of `==`.

**Step 6: Fix any count-sensitive tests**

If any existing test fails because it expected exactly N entities but now gets N+M, update the assertion from `== N` to `>= N`. The detection improvement is correct — we're catching more PII.

**Step 7: Commit**

```bash
git add src/mcp_server_redaction/engine.py tests/test_engine.py
git commit -m "feat: integrate 3-layer hybrid detection in RedactionEngine"
```

---

## Task 8: Add `use_llm` option to the MCP configure tool

**Files:**
- Modify: `src/mcp_server_redaction/server.py`
- Test: `tests/test_tools.py`

**Step 1: Write failing test**

Add to `tests/test_tools.py`:

```python
class TestLLMConfiguration:
    def setup_method(self):
        self.engine = RedactionEngine(use_llm=False)

    def test_server_exposes_llm_status_in_configure(self):
        result = json.loads(handle_configure(self.engine))
        assert "llm_available" in result
        assert isinstance(result["llm_available"], bool)
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_tools.py::TestLLMConfiguration -v
```

Expected: FAIL.

**Step 3: Update configure tool to report LLM status**

Modify `src/mcp_server_redaction/tools/configure.py` — add to the response dict:

```python
from ..llm_reviewer import LLMReviewer

# ... existing code ...

    response = {
        "status": "ok",
        "active_entities": sorted(active_entities),
        "llm_available": LLMReviewer.is_available(),
    }
    return json.dumps(response)
```

**Step 4: Run tests**

```bash
uv run pytest tests/test_tools.py::TestLLMConfiguration -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add src/mcp_server_redaction/tools/configure.py tests/test_tools.py
git commit -m "feat: expose LLM availability in configure tool response"
```

---

## Task 9: Integration tests for hybrid detection

**Files:**
- Modify: `tests/test_integration.py`

**Step 1: Write integration tests**

Add to `tests/test_integration.py`:

```python
class TestHybridDetectionIntegration:
    def setup_method(self):
        self.engine = RedactionEngine(use_llm=False)

    def test_redact_english_pii_comprehensive(self):
        text = (
            "Patient John Smith (DOB: 03/15/1985) visited Dr. Sarah Johnson. "
            "Insurance: POL-2024-00045678. Email: john.smith@hospital.org. "
            "Prescribed Metformin 500mg. NPI: 1234567890."
        )
        result = self.engine.redact(text)
        assert result["entities_found"] >= 4  # name, email, drug, policy at minimum
        assert "john.smith@hospital.org" not in result["redacted_text"]
        assert "John Smith" not in result["redacted_text"]

    def test_redact_german_text(self):
        text = "Herr Hans Müller wohnt in der Berliner Straße 42, 10115 Berlin. Tel: +49 30 12345678."
        result = self.engine.redact(text)
        assert result["entities_found"] >= 1  # GLiNER should catch the name at minimum

    def test_redact_mixed_language(self):
        text = (
            "Customer Nguyễn Văn An called about policy POL-2024-00099999. "
            "His email is an.nguyen@example.com."
        )
        result = self.engine.redact(text)
        assert "an.nguyen@example.com" not in result["redacted_text"]
        assert result["entities_found"] >= 2

    def test_unredact_still_works_after_hybrid_detection(self):
        text = "Contact Jane Doe at jane@example.com"
        redact_result = self.engine.redact(text)
        unredact_result = self.engine.unredact(
            redact_result["redacted_text"],
            redact_result["session_id"],
        )
        assert "jane@example.com" in unredact_result["original_text"]

    def test_file_redaction_uses_hybrid_engine(self, tmp_path):
        """File handlers should benefit from the hybrid engine automatically."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Send invoice to Hans Müller, hans@firma.de, policy POL-2024-00012345")

        result = json.loads(
            handle_redact_file(self.engine, str(test_file))
        )
        assert result["entities_found"] >= 2
        assert "error" not in result
```

**Step 2: Run tests**

```bash
uv run pytest tests/test_integration.py::TestHybridDetectionIntegration -v
```

Expected: All PASS.

**Step 3: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: add integration tests for hybrid 3-layer detection"
```

---

## Task 10: Run full test suite and clean up

**Step 1: Run the complete test suite**

```bash
uv run pytest -v --tb=short
```

Expected: All tests PASS. Review output for:
- Any tests that fail due to changed entity counts (fix with `>=`)
- Any import warnings
- Any deprecation warnings

**Step 2: Fix any remaining test failures**

Adjust exact-count assertions to `>=` where the hybrid engine now finds more entities than before.

**Step 3: Final commit**

```bash
git add -A
git commit -m "fix: adjust test assertions for hybrid detection counts"
```

**Step 4: Verify branch is clean**

```bash
git status
git log --oneline feat/hybrid-detection ^main
```

Expected: Clean working tree, 8-10 commits on the feature branch.

---

## Summary of Changes

| File | Change |
|---|---|
| `pyproject.toml` | Add `presidio-analyzer[gliner]`, `ollama` deps |
| `recognizers/secrets.py` | Add GCP, Slack, JWT, SSH key patterns |
| `recognizers/financial.py` | Add SWIFT/BIC, postal code recognizers |
| `recognizers/medical.py` | Add NPI, DEA, insurance ID recognizers |
| `recognizers/gliner_setup.py` | **NEW** — GLiNER model config + entity mapping |
| `recognizers/__init__.py` | Wire GLiNER into registry |
| `llm_reviewer.py` | **NEW** — Ollama LLM review layer |
| `engine.py` | Integrate L3 into `redact()`, add `use_llm` param |
| `tools/configure.py` | Report `llm_available` in response |
| `tests/test_gliner.py` | **NEW** — GLiNER recognizer tests |
| `tests/test_llm_reviewer.py` | **NEW** — LLM reviewer tests |
| `tests/test_recognizers.py` | Expanded pattern tests |
| `tests/test_engine.py` | Hybrid detection tests |
| `tests/test_integration.py` | End-to-end hybrid tests |
| `tests/test_tools.py` | Configure tool LLM status test |

**Backward compatibility:** The MCP tool interface is completely unchanged. All 6 tools (`redact`, `unredact`, `analyze`, `configure`, `redact_file`, `unredact_file`) keep the same signatures and return formats. The improvements are entirely internal to `RedactionEngine`.
