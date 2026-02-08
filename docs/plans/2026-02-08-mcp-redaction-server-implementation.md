# MCP Server Redaction — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Python MCP server that provides tools for redacting, analyzing, and un-redacting sensitive data from text using Microsoft Presidio, with reversible indexed placeholders like `[EMAIL_1]`, `[PERSON_2]`.

**Architecture:** FastMCP (from the official `mcp` SDK) as the server framework, with Microsoft Presidio's `AnalyzerEngine` + `AnonymizerEngine` as the detection/anonymization backend. Custom `PatternRecognizer` subclasses extend Presidio for secrets, financial, and medical data. Session state maps placeholders to originals for reversible redaction.

**Tech Stack:** Python 3.10+, `mcp[cli]` (official MCP Python SDK with FastMCP), `presidio-analyzer`, `presidio-anonymizer`, `spacy` + `en_core_web_lg`, `pytest`

**Design Doc:** `docs/plans/2026-02-08-mcp-redaction-server-design.md`

---

## Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/mcp_server_redaction/__init__.py`
- Create: `tests/__init__.py`

**Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "mcp-server-redaction"
version = "0.1.0"
description = "MCP server for redacting sensitive data from text"
requires-python = ">=3.10"
dependencies = [
    "mcp[cli]",
    "presidio-analyzer",
    "presidio-anonymizer",
    "spacy",
]

[project.scripts]
mcp-server-redaction = "mcp_server_redaction.server:main"

[tool.pytest.ini_options]
testpaths = ["tests"]

[dependency-groups]
dev = [
    "pytest",
    "pytest-asyncio",
]
```

**Step 2: Create directory structure and empty `__init__.py` files**

```bash
mkdir -p src/mcp_server_redaction/recognizers src/mcp_server_redaction/tools tests
touch src/mcp_server_redaction/__init__.py
touch src/mcp_server_redaction/recognizers/__init__.py
touch src/mcp_server_redaction/tools/__init__.py
touch tests/__init__.py
```

**Step 3: Create virtual environment and install dependencies**

Run:
```bash
cd /mnt/d/projects/mcp-server-redaction
uv venv
uv sync
uv run python -m spacy download en_core_web_lg
```

Expected: Dependencies install successfully, spaCy model downloads.

**Step 4: Verify Presidio imports work**

Run: `uv run python -c "from presidio_analyzer import AnalyzerEngine; from presidio_anonymizer import AnonymizerEngine; print('OK')"`

Expected: Prints `OK`.

**Step 5: Commit**

```bash
git add pyproject.toml src/ tests/__init__.py
git commit -m "chore: scaffold project with pyproject.toml and directory structure"
```

---

## Task 2: State Manager — Session Mappings

**Files:**
- Create: `src/mcp_server_redaction/state.py`
- Create: `tests/test_state.py`

**Step 1: Write the failing tests**

```python
# tests/test_state.py
import time
from mcp_server_redaction.state import StateManager


class TestStateManager:
    def test_create_session_returns_uuid(self):
        sm = StateManager()
        session_id = sm.create_session()
        assert isinstance(session_id, str)
        assert len(session_id) == 36  # UUID4 format

    def test_store_and_retrieve_mapping(self):
        sm = StateManager()
        session_id = sm.create_session()
        sm.add_mapping(session_id, "[EMAIL_1]", "john@example.com")
        sm.add_mapping(session_id, "[PERSON_1]", "John Smith")

        mappings = sm.get_mappings(session_id)
        assert mappings == {
            "[EMAIL_1]": "john@example.com",
            "[PERSON_1]": "John Smith",
        }

    def test_get_mappings_unknown_session_returns_none(self):
        sm = StateManager()
        assert sm.get_mappings("nonexistent-id") is None

    def test_expired_sessions_are_pruned(self):
        sm = StateManager(ttl_seconds=0)
        session_id = sm.create_session()
        sm.add_mapping(session_id, "[EMAIL_1]", "test@test.com")
        time.sleep(0.01)
        sm.prune_expired()
        assert sm.get_mappings(session_id) is None

    def test_non_expired_sessions_survive_prune(self):
        sm = StateManager(ttl_seconds=3600)
        session_id = sm.create_session()
        sm.add_mapping(session_id, "[EMAIL_1]", "test@test.com")
        sm.prune_expired()
        assert sm.get_mappings(session_id) is not None
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_state.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'mcp_server_redaction.state'`

**Step 3: Implement StateManager**

```python
# src/mcp_server_redaction/state.py
import time
import uuid


class StateManager:
    def __init__(self, ttl_seconds: int = 3600):
        self._sessions: dict[str, dict] = {}
        self._ttl_seconds = ttl_seconds

    def create_session(self) -> str:
        session_id = str(uuid.uuid4())
        self._sessions[session_id] = {
            "created_at": time.time(),
            "mappings": {},
        }
        return session_id

    def add_mapping(self, session_id: str, placeholder: str, original: str) -> None:
        self._sessions[session_id]["mappings"][placeholder] = original

    def get_mappings(self, session_id: str) -> dict[str, str] | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        return dict(session["mappings"])

    def prune_expired(self) -> None:
        now = time.time()
        expired = [
            sid
            for sid, data in self._sessions.items()
            if now - data["created_at"] > self._ttl_seconds
        ]
        for sid in expired:
            del self._sessions[sid]
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_state.py -v`

Expected: All 5 tests PASS.

**Step 5: Commit**

```bash
git add src/mcp_server_redaction/state.py tests/test_state.py
git commit -m "feat: add StateManager for session-based redaction mappings"
```

---

## Task 3: Secrets Recognizer

**Files:**
- Create: `src/mcp_server_redaction/recognizers/secrets.py`
- Create: `tests/test_recognizers.py`

**Step 1: Write the failing tests**

```python
# tests/test_recognizers.py
from presidio_analyzer import AnalyzerEngine, RecognizerRegistry
from mcp_server_redaction.recognizers.secrets import create_secrets_recognizers


class TestSecretsRecognizers:
    def _make_analyzer(self):
        registry = RecognizerRegistry()
        registry.load_predefined_recognizers()
        for r in create_secrets_recognizers():
            registry.add_recognizer(r)
        return AnalyzerEngine(registry=registry)

    def test_detect_openai_api_key(self):
        analyzer = self._make_analyzer()
        text = "My key is sk-proj-abc123def456ghi789jkl012mno345pqr678"
        results = analyzer.analyze(text=text, language="en", entities=["API_KEY"])
        assert len(results) >= 1
        assert any(r.entity_type == "API_KEY" for r in results)

    def test_detect_github_token(self):
        analyzer = self._make_analyzer()
        text = "Use token ghp_1234567890abcdefghijklmnopqrstuv1234"
        results = analyzer.analyze(text=text, language="en", entities=["API_KEY"])
        assert len(results) >= 1

    def test_detect_aws_access_key(self):
        analyzer = self._make_analyzer()
        text = "AWS key: AKIAIOSFODNN7EXAMPLE"
        results = analyzer.analyze(text=text, language="en", entities=["AWS_ACCESS_KEY"])
        assert len(results) >= 1

    def test_detect_connection_string_postgres(self):
        analyzer = self._make_analyzer()
        text = "DB: postgresql://user:password@host:5432/dbname"
        results = analyzer.analyze(text=text, language="en", entities=["CONNECTION_STRING"])
        assert len(results) >= 1

    def test_detect_connection_string_mongodb(self):
        analyzer = self._make_analyzer()
        text = "DB: mongodb://admin:secret@mongo.host:27017/mydb"
        results = analyzer.analyze(text=text, language="en", entities=["CONNECTION_STRING"])
        assert len(results) >= 1

    def test_no_false_positive_on_normal_text(self):
        analyzer = self._make_analyzer()
        text = "The sky is blue and the grass is green."
        results = analyzer.analyze(
            text=text, language="en",
            entities=["API_KEY", "AWS_ACCESS_KEY", "CONNECTION_STRING"],
        )
        assert len(results) == 0
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_recognizers.py::TestSecretsRecognizers -v`

Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement secrets recognizers**

```python
# src/mcp_server_redaction/recognizers/secrets.py
from presidio_analyzer import Pattern, PatternRecognizer


def create_secrets_recognizers() -> list[PatternRecognizer]:
    api_key_recognizer = PatternRecognizer(
        supported_entity="API_KEY",
        name="ApiKeyRecognizer",
        patterns=[
            Pattern("openai_key", r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b", 0.9),
            Pattern("github_token", r"\bghp_[A-Za-z0-9]{36}\b", 0.9),
            Pattern("gitlab_token", r"\bglpat-[A-Za-z0-9\-_]{20,}\b", 0.9),
            Pattern("stripe_key", r"\b[sp]k_(?:live|test)_[A-Za-z0-9]{20,}\b", 0.9),
        ],
        context=["key", "token", "api", "secret", "bearer"],
    )

    aws_key_recognizer = PatternRecognizer(
        supported_entity="AWS_ACCESS_KEY",
        name="AwsAccessKeyRecognizer",
        patterns=[
            Pattern("aws_access_key", r"\bAKIA[0-9A-Z]{16}\b", 0.9),
        ],
        context=["aws", "key", "access"],
    )

    connection_string_recognizer = PatternRecognizer(
        supported_entity="CONNECTION_STRING",
        name="ConnectionStringRecognizer",
        patterns=[
            Pattern(
                "postgres_uri",
                r"\bpostgresql?://[^\s]+",
                0.9,
            ),
            Pattern(
                "mysql_uri",
                r"\bmysql://[^\s]+",
                0.9,
            ),
            Pattern(
                "mongodb_uri",
                r"\bmongodb(?:\+srv)?://[^\s]+",
                0.9,
            ),
        ],
        context=["database", "db", "connection", "uri", "url"],
    )

    return [api_key_recognizer, aws_key_recognizer, connection_string_recognizer]
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_recognizers.py::TestSecretsRecognizers -v`

Expected: All 6 tests PASS.

**Step 5: Commit**

```bash
git add src/mcp_server_redaction/recognizers/secrets.py tests/test_recognizers.py
git commit -m "feat: add secrets recognizers (API keys, AWS keys, connection strings)"
```

---

## Task 4: Financial Recognizer

**Files:**
- Create: `src/mcp_server_redaction/recognizers/financial.py`
- Modify: `tests/test_recognizers.py`

**Step 1: Write the failing tests**

Append to `tests/test_recognizers.py`:

```python
from mcp_server_redaction.recognizers.financial import create_financial_recognizers


class TestFinancialRecognizers:
    def _make_analyzer(self):
        registry = RecognizerRegistry()
        registry.load_predefined_recognizers()
        for r in create_financial_recognizers():
            registry.add_recognizer(r)
        return AnalyzerEngine(registry=registry)

    def test_detect_visa_card(self):
        analyzer = self._make_analyzer()
        text = "Card: 4111111111111111"
        results = analyzer.analyze(text=text, language="en", entities=["CREDIT_CARD"])
        assert len(results) >= 1

    def test_detect_iban(self):
        analyzer = self._make_analyzer()
        text = "IBAN: GB29 NWBK 6016 1331 9268 19"
        results = analyzer.analyze(text=text, language="en", entities=["IBAN"])
        assert len(results) >= 1

    def test_detect_us_bank_routing(self):
        analyzer = self._make_analyzer()
        text = "Routing number: 021000021"
        results = analyzer.analyze(text=text, language="en", entities=["US_BANK_ROUTING"])
        assert len(results) >= 1

    def test_no_false_positive_on_normal_number(self):
        analyzer = self._make_analyzer()
        text = "I have 42 apples."
        results = analyzer.analyze(
            text=text, language="en",
            entities=["CREDIT_CARD", "IBAN", "US_BANK_ROUTING"],
        )
        assert len(results) == 0
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_recognizers.py::TestFinancialRecognizers -v`

Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement financial recognizers**

```python
# src/mcp_server_redaction/recognizers/financial.py
from presidio_analyzer import Pattern, PatternRecognizer


def create_financial_recognizers() -> list[PatternRecognizer]:
    # Presidio has a built-in CREDIT_CARD recognizer, but we add IBAN and routing.
    iban_recognizer = PatternRecognizer(
        supported_entity="IBAN",
        name="IbanRecognizer",
        patterns=[
            Pattern(
                "iban",
                r"\b[A-Z]{2}\d{2}\s?[\dA-Z]{4}\s?(?:[\dA-Z]{4}\s?){2,7}[\dA-Z]{1,4}\b",
                0.8,
            ),
        ],
        context=["iban", "account", "bank", "transfer"],
    )

    routing_recognizer = PatternRecognizer(
        supported_entity="US_BANK_ROUTING",
        name="UsBankRoutingRecognizer",
        patterns=[
            Pattern("us_routing", r"\b\d{9}\b", 0.3),
        ],
        context=["routing", "aba", "bank", "transit"],
    )

    return [iban_recognizer, routing_recognizer]
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_recognizers.py::TestFinancialRecognizers -v`

Expected: All 4 tests PASS.

**Step 5: Commit**

```bash
git add src/mcp_server_redaction/recognizers/financial.py tests/test_recognizers.py
git commit -m "feat: add financial recognizers (IBAN, US bank routing)"
```

---

## Task 5: Medical Recognizer

**Files:**
- Create: `src/mcp_server_redaction/recognizers/medical.py`
- Modify: `tests/test_recognizers.py`

**Step 1: Write the failing tests**

Append to `tests/test_recognizers.py`:

```python
from mcp_server_redaction.recognizers.medical import create_medical_recognizers


class TestMedicalRecognizers:
    def _make_analyzer(self):
        registry = RecognizerRegistry()
        registry.load_predefined_recognizers()
        for r in create_medical_recognizers():
            registry.add_recognizer(r)
        return AnalyzerEngine(registry=registry)

    def test_detect_icd10_code(self):
        analyzer = self._make_analyzer()
        text = "Diagnosis: J45.20 mild intermittent asthma"
        results = analyzer.analyze(text=text, language="en", entities=["ICD10_CODE"])
        assert len(results) >= 1

    def test_detect_medical_record_number(self):
        analyzer = self._make_analyzer()
        text = "MRN: 123-456-789"
        results = analyzer.analyze(text=text, language="en", entities=["MEDICAL_RECORD_NUMBER"])
        assert len(results) >= 1

    def test_detect_drug_name(self):
        analyzer = self._make_analyzer()
        text = "Patient is taking Metformin 500mg daily"
        results = analyzer.analyze(text=text, language="en", entities=["DRUG_NAME"])
        assert len(results) >= 1

    def test_no_false_positive_on_normal_text(self):
        analyzer = self._make_analyzer()
        text = "The weather is nice today."
        results = analyzer.analyze(
            text=text, language="en",
            entities=["ICD10_CODE", "MEDICAL_RECORD_NUMBER", "DRUG_NAME"],
        )
        assert len(results) == 0
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_recognizers.py::TestMedicalRecognizers -v`

Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement medical recognizers**

```python
# src/mcp_server_redaction/recognizers/medical.py
from presidio_analyzer import Pattern, PatternRecognizer


_COMMON_DRUGS = [
    "Metformin", "Lisinopril", "Amlodipine", "Metoprolol", "Atorvastatin",
    "Omeprazole", "Losartan", "Albuterol", "Gabapentin", "Hydrochlorothiazide",
    "Sertraline", "Simvastatin", "Montelukast", "Escitalopram", "Rosuvastatin",
    "Bupropion", "Furosemide", "Pantoprazole", "Duloxetine", "Prednisone",
    "Amoxicillin", "Azithromycin", "Ibuprofen", "Acetaminophen", "Aspirin",
    "Warfarin", "Clopidogrel", "Insulin", "Levothyroxine", "Fluoxetine",
]


def create_medical_recognizers() -> list[PatternRecognizer]:
    icd10_recognizer = PatternRecognizer(
        supported_entity="ICD10_CODE",
        name="Icd10Recognizer",
        patterns=[
            Pattern("icd10", r"\b[A-TV-Z]\d{2}(?:\.\d{1,4})?\b", 0.6),
        ],
        context=["diagnosis", "icd", "code", "dx", "condition"],
    )

    mrn_recognizer = PatternRecognizer(
        supported_entity="MEDICAL_RECORD_NUMBER",
        name="MrnRecognizer",
        patterns=[
            Pattern("mrn_dashes", r"\b\d{3}-\d{3}-\d{3}\b", 0.4),
            Pattern("mrn_plain", r"\b\d{7,10}\b", 0.2),
        ],
        context=["mrn", "medical record", "patient id", "chart"],
    )

    drug_recognizer = PatternRecognizer(
        supported_entity="DRUG_NAME",
        name="DrugNameRecognizer",
        deny_list=_COMMON_DRUGS,
        context=["taking", "prescribed", "medication", "drug", "dose", "mg", "daily"],
    )

    return [icd10_recognizer, mrn_recognizer, drug_recognizer]
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_recognizers.py::TestMedicalRecognizers -v`

Expected: All 4 tests PASS.

**Step 5: Commit**

```bash
git add src/mcp_server_redaction/recognizers/medical.py tests/test_recognizers.py
git commit -m "feat: add medical recognizers (ICD-10, MRN, drug names)"
```

---

## Task 6: Recognizer Registry Initialization

**Files:**
- Modify: `src/mcp_server_redaction/recognizers/__init__.py`

**Step 1: Write the failing test**

Append to `tests/test_recognizers.py`:

```python
from mcp_server_redaction.recognizers import build_registry


class TestBuildRegistry:
    def test_registry_has_custom_entities(self):
        registry = build_registry()
        supported = registry.get_supported_entities()
        for entity in ["API_KEY", "AWS_ACCESS_KEY", "CONNECTION_STRING",
                       "IBAN", "US_BANK_ROUTING",
                       "ICD10_CODE", "MEDICAL_RECORD_NUMBER", "DRUG_NAME"]:
            assert entity in supported, f"{entity} not in registry"

    def test_registry_has_default_entities(self):
        registry = build_registry()
        supported = registry.get_supported_entities()
        for entity in ["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER"]:
            assert entity in supported, f"{entity} not in registry"
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_recognizers.py::TestBuildRegistry -v`

Expected: FAIL — `ImportError`

**Step 3: Implement build_registry**

```python
# src/mcp_server_redaction/recognizers/__init__.py
from presidio_analyzer import RecognizerRegistry

from .secrets import create_secrets_recognizers
from .financial import create_financial_recognizers
from .medical import create_medical_recognizers


def build_registry() -> RecognizerRegistry:
    registry = RecognizerRegistry()
    registry.load_predefined_recognizers()

    for recognizer in create_secrets_recognizers():
        registry.add_recognizer(recognizer)
    for recognizer in create_financial_recognizers():
        registry.add_recognizer(recognizer)
    for recognizer in create_medical_recognizers():
        registry.add_recognizer(recognizer)

    return registry
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_recognizers.py::TestBuildRegistry -v`

Expected: All 2 tests PASS.

**Step 5: Commit**

```bash
git add src/mcp_server_redaction/recognizers/__init__.py tests/test_recognizers.py
git commit -m "feat: add build_registry combining all recognizers"
```

---

## Task 7: Redaction Engine

**Files:**
- Create: `src/mcp_server_redaction/engine.py`
- Create: `tests/test_engine.py`

This is the core component: it runs Presidio analysis and produces indexed placeholders like `[EMAIL_ADDRESS_1]`, `[PERSON_1]`, storing the mapping in StateManager for reversibility.

**Step 1: Write the failing tests**

```python
# tests/test_engine.py
from mcp_server_redaction.engine import RedactionEngine


class TestRedactionEngine:
    def setup_method(self):
        self.engine = RedactionEngine()

    def test_redact_email(self):
        result = self.engine.redact("Contact john@example.com for info")
        assert "john@example.com" not in result["redacted_text"]
        assert "[EMAIL_ADDRESS_1]" in result["redacted_text"]
        assert result["entities_found"] >= 1
        assert "session_id" in result

    def test_redact_preserves_non_sensitive_text(self):
        result = self.engine.redact("Hello world")
        assert result["redacted_text"] == "Hello world"
        assert result["entities_found"] == 0

    def test_redact_multiple_same_type(self):
        result = self.engine.redact("Email a@b.com and c@d.com")
        text = result["redacted_text"]
        assert "[EMAIL_ADDRESS_1]" in text
        assert "[EMAIL_ADDRESS_2]" in text
        assert result["entities_found"] == 2

    def test_unredact_restores_original(self):
        original = "Contact john@example.com for info"
        redact_result = self.engine.redact(original)
        unredact_result = self.engine.unredact(
            redact_result["redacted_text"], redact_result["session_id"]
        )
        assert unredact_result["original_text"] == original
        assert unredact_result["entities_restored"] >= 1

    def test_unredact_unknown_session_raises(self):
        result = self.engine.unredact("some text", "nonexistent-session-id")
        assert "error" in result

    def test_analyze_returns_entities_with_partial_mask(self):
        result = self.engine.analyze("Contact john@example.com")
        assert len(result["entities"]) >= 1
        entity = result["entities"][0]
        assert entity["type"] == "EMAIL_ADDRESS"
        assert "score" in entity
        # Partially masked — should not show the full email
        assert entity["text"] != "john@example.com"

    def test_redact_with_entity_type_filter(self):
        text = "John Smith john@example.com"
        result = self.engine.redact(text, entity_types=["EMAIL_ADDRESS"])
        assert "[EMAIL_ADDRESS_1]" in result["redacted_text"]
        # PERSON should NOT be redacted since we filtered to EMAIL only
        assert "John Smith" in result["redacted_text"] or "[PERSON" not in result["redacted_text"]
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_engine.py -v`

Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement RedactionEngine**

```python
# src/mcp_server_redaction/engine.py
import re

from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine

from .recognizers import build_registry
from .state import StateManager


class RedactionEngine:
    def __init__(self, state_manager: StateManager | None = None):
        self._registry = build_registry()
        self._analyzer = AnalyzerEngine(registry=self._registry)
        self._anonymizer = AnonymizerEngine()
        self._state = state_manager or StateManager()

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

        kwargs: dict = {"text": text, "language": "en"}
        if entity_types:
            kwargs["entities"] = entity_types

        results = self._analyzer.analyze(**kwargs)

        if not results:
            session_id = self._state.create_session()
            return {
                "redacted_text": text,
                "session_id": session_id,
                "entities_found": 0,
            }

        # Sort by start position (descending) so we can replace right-to-left
        results.sort(key=lambda r: r.start, reverse=True)

        # Track counters per entity type for indexed placeholders
        type_counters: dict[str, int] = {}
        # We'll build replacements in reverse order, then flip for the mapping
        replacements: list[tuple[int, int, str, str]] = []  # start, end, placeholder, original

        for result in results:
            entity_type = result.entity_type
            type_counters.setdefault(entity_type, 0)
            type_counters[entity_type] += 1
            placeholder = f"[{entity_type}_{type_counters[entity_type]}]"
            original_value = text[result.start : result.end]
            replacements.append((result.start, result.end, placeholder, original_value))

        # Apply replacements right-to-left
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
    def _partial_mask(value: str) -> str:
        if len(value) <= 4:
            return "*" * len(value)
        visible = max(1, len(value) // 4)
        return value[:visible] + "*" * (len(value) - visible * 2) + value[-visible:]
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_engine.py -v`

Expected: All 7 tests PASS.

**Step 5: Commit**

```bash
git add src/mcp_server_redaction/engine.py tests/test_engine.py
git commit -m "feat: add RedactionEngine with redact, unredact, and analyze"
```

---

## Task 8: MCP Tool — `redact`

**Files:**
- Create: `src/mcp_server_redaction/tools/redact.py`
- Create: `tests/test_tools.py`

**Step 1: Write the failing test**

```python
# tests/test_tools.py
import json
from mcp_server_redaction.engine import RedactionEngine
from mcp_server_redaction.tools.redact import handle_redact


class TestRedactTool:
    def setup_method(self):
        self.engine = RedactionEngine()

    def test_redact_tool_returns_valid_json(self):
        result = handle_redact(self.engine, text="Email me at john@example.com")
        data = json.loads(result)
        assert "redacted_text" in data
        assert "session_id" in data
        assert "entities_found" in data
        assert data["entities_found"] >= 1
        assert "john@example.com" not in data["redacted_text"]

    def test_redact_tool_with_entity_filter(self):
        result = handle_redact(
            self.engine,
            text="John Smith john@example.com",
            entity_types=["EMAIL_ADDRESS"],
        )
        data = json.loads(result)
        assert "[EMAIL_ADDRESS_1]" in data["redacted_text"]
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools.py::TestRedactTool -v`

Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement the redact tool handler**

```python
# src/mcp_server_redaction/tools/redact.py
import json

from ..engine import RedactionEngine


def handle_redact(
    engine: RedactionEngine,
    text: str,
    entity_types: list[str] | None = None,
) -> str:
    result = engine.redact(text, entity_types=entity_types)
    return json.dumps(result)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools.py::TestRedactTool -v`

Expected: All 2 tests PASS.

**Step 5: Commit**

```bash
git add src/mcp_server_redaction/tools/redact.py tests/test_tools.py
git commit -m "feat: add redact tool handler"
```

---

## Task 9: MCP Tool — `unredact`

**Files:**
- Create: `src/mcp_server_redaction/tools/unredact.py`
- Modify: `tests/test_tools.py`

**Step 1: Write the failing test**

Append to `tests/test_tools.py`:

```python
from mcp_server_redaction.tools.unredact import handle_unredact


class TestUnredactTool:
    def setup_method(self):
        self.engine = RedactionEngine()

    def test_unredact_restores_text(self):
        redact_result = json.loads(
            handle_redact(self.engine, text="Email john@example.com")
        )
        result = handle_unredact(
            self.engine,
            redacted_text=redact_result["redacted_text"],
            session_id=redact_result["session_id"],
        )
        data = json.loads(result)
        assert "original_text" in data
        assert "john@example.com" in data["original_text"]

    def test_unredact_bad_session(self):
        result = handle_unredact(
            self.engine, redacted_text="text", session_id="bad-id"
        )
        data = json.loads(result)
        assert "error" in data
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools.py::TestUnredactTool -v`

Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement the unredact tool handler**

```python
# src/mcp_server_redaction/tools/unredact.py
import json

from ..engine import RedactionEngine


def handle_unredact(
    engine: RedactionEngine,
    redacted_text: str,
    session_id: str,
) -> str:
    result = engine.unredact(redacted_text, session_id)
    return json.dumps(result)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools.py::TestUnredactTool -v`

Expected: All 2 tests PASS.

**Step 5: Commit**

```bash
git add src/mcp_server_redaction/tools/unredact.py tests/test_tools.py
git commit -m "feat: add unredact tool handler"
```

---

## Task 10: MCP Tool — `analyze`

**Files:**
- Create: `src/mcp_server_redaction/tools/analyze.py`
- Modify: `tests/test_tools.py`

**Step 1: Write the failing test**

Append to `tests/test_tools.py`:

```python
from mcp_server_redaction.tools.analyze import handle_analyze


class TestAnalyzeTool:
    def setup_method(self):
        self.engine = RedactionEngine()

    def test_analyze_returns_entities(self):
        result = handle_analyze(self.engine, text="Contact john@example.com")
        data = json.loads(result)
        assert "entities" in data
        assert len(data["entities"]) >= 1
        assert data["entities"][0]["type"] == "EMAIL_ADDRESS"

    def test_analyze_empty_text(self):
        result = handle_analyze(self.engine, text="Hello world")
        data = json.loads(result)
        assert data["entities"] == []
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools.py::TestAnalyzeTool -v`

Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement the analyze tool handler**

```python
# src/mcp_server_redaction/tools/analyze.py
import json

from ..engine import RedactionEngine


def handle_analyze(
    engine: RedactionEngine,
    text: str,
    entity_types: list[str] | None = None,
) -> str:
    result = engine.analyze(text, entity_types=entity_types)
    return json.dumps(result)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools.py::TestAnalyzeTool -v`

Expected: All 2 tests PASS.

**Step 5: Commit**

```bash
git add src/mcp_server_redaction/tools/analyze.py tests/test_tools.py
git commit -m "feat: add analyze tool handler"
```

---

## Task 11: MCP Tool — `configure`

**Files:**
- Create: `src/mcp_server_redaction/tools/configure.py`
- Modify: `tests/test_tools.py`

**Step 1: Write the failing test**

Append to `tests/test_tools.py`:

```python
from mcp_server_redaction.tools.configure import handle_configure


class TestConfigureTool:
    def setup_method(self):
        self.engine = RedactionEngine()

    def test_add_custom_pattern(self):
        result = handle_configure(
            self.engine,
            custom_patterns=[
                {"name": "INTERNAL_ID", "pattern": r"ID-\d{6}", "score": 0.9}
            ],
        )
        data = json.loads(result)
        assert data["status"] == "ok"
        assert "INTERNAL_ID" in data["active_entities"]

        # Verify the new pattern works
        redact_result = self.engine.redact("Reference ID-123456 in the system")
        assert "[INTERNAL_ID_1]" in redact_result["redacted_text"]

    def test_configure_returns_active_entities(self):
        result = handle_configure(self.engine)
        data = json.loads(result)
        assert data["status"] == "ok"
        assert "EMAIL_ADDRESS" in data["active_entities"]
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools.py::TestConfigureTool -v`

Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement the configure tool handler**

```python
# src/mcp_server_redaction/tools/configure.py
import json

from presidio_analyzer import Pattern, PatternRecognizer

from ..engine import RedactionEngine


def handle_configure(
    engine: RedactionEngine,
    custom_patterns: list[dict] | None = None,
    disabled_entities: list[str] | None = None,
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

    active_entities = engine.registry.get_supported_entities()

    if disabled_entities:
        active_entities = [e for e in active_entities if e not in disabled_entities]

    return json.dumps({
        "status": "ok",
        "active_entities": sorted(active_entities),
    })
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools.py::TestConfigureTool -v`

Expected: All 2 tests PASS.

**Step 5: Commit**

```bash
git add src/mcp_server_redaction/tools/configure.py tests/test_tools.py
git commit -m "feat: add configure tool handler for custom patterns"
```

---

## Task 12: MCP Tool — `redact_file`

**Files:**
- Create: `src/mcp_server_redaction/tools/redact_file.py`
- Modify: `tests/test_tools.py`

**Step 1: Write the failing test**

Append to `tests/test_tools.py`:

```python
import os
import tempfile
from mcp_server_redaction.tools.redact_file import handle_redact_file


class TestRedactFileTool:
    def setup_method(self):
        self.engine = RedactionEngine()

    def test_redact_file_creates_output(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as f:
            f.write("Contact john@example.com for details.\n")
            f.flush()
            input_path = f.name

        try:
            result = handle_redact_file(self.engine, file_path=input_path)
            data = json.loads(result)
            assert "redacted_file_path" in data
            assert data["entities_found"] >= 1

            # Verify the redacted file exists and has redacted content
            with open(data["redacted_file_path"]) as rf:
                content = rf.read()
            assert "john@example.com" not in content
            assert "[EMAIL_ADDRESS_1]" in content

            os.unlink(data["redacted_file_path"])
        finally:
            os.unlink(input_path)

    def test_redact_file_nonexistent_returns_error(self):
        result = handle_redact_file(self.engine, file_path="/tmp/nonexistent_file.txt")
        data = json.loads(result)
        assert "error" in data
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools.py::TestRedactFileTool -v`

Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement the redact_file tool handler**

```python
# src/mcp_server_redaction/tools/redact_file.py
import json
import os

from ..engine import RedactionEngine


def handle_redact_file(
    engine: RedactionEngine,
    file_path: str,
    entity_types: list[str] | None = None,
) -> str:
    if not os.path.isfile(file_path):
        return json.dumps({"error": f"File not found: {file_path}"})

    with open(file_path) as f:
        content = f.read()

    result = engine.redact(content, entity_types=entity_types)

    base, ext = os.path.splitext(file_path)
    redacted_path = f"{base}_redacted{ext}"

    with open(redacted_path, "w") as f:
        f.write(result["redacted_text"])

    return json.dumps({
        "redacted_file_path": redacted_path,
        "session_id": result["session_id"],
        "entities_found": result["entities_found"],
    })
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools.py::TestRedactFileTool -v`

Expected: All 2 tests PASS.

**Step 5: Commit**

```bash
git add src/mcp_server_redaction/tools/redact_file.py tests/test_tools.py
git commit -m "feat: add redact_file tool handler"
```

---

## Task 13: Tools `__init__.py` Re-exports

**Files:**
- Modify: `src/mcp_server_redaction/tools/__init__.py`

**Step 1: Write the `__init__.py`**

```python
# src/mcp_server_redaction/tools/__init__.py
from .redact import handle_redact
from .unredact import handle_unredact
from .analyze import handle_analyze
from .configure import handle_configure
from .redact_file import handle_redact_file

__all__ = [
    "handle_redact",
    "handle_unredact",
    "handle_analyze",
    "handle_configure",
    "handle_redact_file",
]
```

**Step 2: Run all tests to ensure nothing broke**

Run: `uv run pytest tests/ -v`

Expected: All tests PASS.

**Step 3: Commit**

```bash
git add src/mcp_server_redaction/tools/__init__.py
git commit -m "chore: add tools __init__.py re-exports"
```

---

## Task 14: MCP Server — Wire Everything Together

**Files:**
- Create: `src/mcp_server_redaction/server.py`

**Step 1: Write the failing test**

Append a new test file `tests/test_server.py`:

```python
# tests/test_server.py
from mcp_server_redaction.server import mcp


class TestServerRegistration:
    def test_server_has_tools_registered(self):
        """Verify the FastMCP server instance exists and has the right name."""
        assert mcp.name == "redaction"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_server.py -v`

Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement the MCP server**

```python
# src/mcp_server_redaction/server.py
import logging

from mcp.server.fastmcp import FastMCP

from .engine import RedactionEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("redaction")
engine = RedactionEngine()


@mcp.tool()
def redact(text: str, entity_types: list[str] | None = None) -> str:
    """Redact sensitive data from text, replacing entities with indexed placeholders like [EMAIL_ADDRESS_1].

    Args:
        text: The text to redact.
        entity_types: Optional list of entity types to redact (e.g. ["EMAIL_ADDRESS", "PERSON"]).
                      If not provided, all known entity types are checked.
    """
    from .tools.redact import handle_redact
    return handle_redact(engine, text=text, entity_types=entity_types)


@mcp.tool()
def unredact(redacted_text: str, session_id: str) -> str:
    """Restore redacted text to the original using a session ID from a previous redact call.

    Args:
        redacted_text: Text containing placeholders like [EMAIL_ADDRESS_1].
        session_id: The session ID returned by the redact tool.
    """
    from .tools.unredact import handle_unredact
    return handle_unredact(engine, redacted_text=redacted_text, session_id=session_id)


@mcp.tool()
def analyze(text: str, entity_types: list[str] | None = None) -> str:
    """Analyze text for sensitive data without modifying it. Returns detected entities with partial masking.

    Args:
        text: The text to analyze.
        entity_types: Optional list of entity types to look for.
    """
    from .tools.analyze import handle_analyze
    return handle_analyze(engine, text=text, entity_types=entity_types)


@mcp.tool()
def configure(
    custom_patterns: list[dict] | None = None,
    disabled_entities: list[str] | None = None,
) -> str:
    """Configure the redaction engine at runtime. Add custom patterns or disable entity types.

    Args:
        custom_patterns: List of pattern dicts with keys: name, pattern, score.
                         Example: [{"name": "INTERNAL_ID", "pattern": "ID-\\\\d{6}", "score": 0.9}]
        disabled_entities: List of entity type names to disable.
    """
    from .tools.configure import handle_configure
    return handle_configure(engine, custom_patterns=custom_patterns, disabled_entities=disabled_entities)


@mcp.tool()
def redact_file(file_path: str, entity_types: list[str] | None = None) -> str:
    """Redact sensitive data in a file. Writes a new file with '_redacted' suffix.

    Args:
        file_path: Absolute path to the file to redact.
        entity_types: Optional list of entity types to redact.
    """
    from .tools.redact_file import handle_redact_file
    return handle_redact_file(engine, file_path=file_path, entity_types=entity_types)


def main():
    mcp.run(transport="stdio")
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_server.py -v`

Expected: PASS.

**Step 5: Run all tests**

Run: `uv run pytest tests/ -v`

Expected: All tests PASS.

**Step 6: Commit**

```bash
git add src/mcp_server_redaction/server.py tests/test_server.py
git commit -m "feat: add MCP server with all 5 tools wired up via FastMCP"
```

---

## Task 15: End-to-End Integration Test

**Files:**
- Create: `tests/test_integration.py`

**Step 1: Write the integration test**

```python
# tests/test_integration.py
import json

from mcp_server_redaction.engine import RedactionEngine
from mcp_server_redaction.tools import (
    handle_redact,
    handle_unredact,
    handle_analyze,
    handle_configure,
)


class TestEndToEnd:
    def setup_method(self):
        self.engine = RedactionEngine()

    def test_full_redact_unredact_cycle(self):
        original = (
            "John Smith's email is john@example.com and his SSN is 123-45-6789. "
            "Call him at 555-123-4567."
        )

        # Redact
        redact_result = json.loads(handle_redact(self.engine, text=original))
        redacted = redact_result["redacted_text"]
        session_id = redact_result["session_id"]

        assert "john@example.com" not in redacted
        assert "123-45-6789" not in redacted
        assert redact_result["entities_found"] >= 3

        # Unredact
        unredact_result = json.loads(
            handle_unredact(self.engine, redacted_text=redacted, session_id=session_id)
        )
        assert unredact_result["original_text"] == original

    def test_analyze_then_selective_redact(self):
        text = "Dr. Jane Doe prescribed Metformin for patient MRN: 123-456-789"

        # First analyze to see what's in the text
        analysis = json.loads(handle_analyze(self.engine, text=text))
        found_types = {e["type"] for e in analysis["entities"]}
        assert len(found_types) >= 1

        # Then redact only PERSON entities
        redact_result = json.loads(
            handle_redact(self.engine, text=text, entity_types=["PERSON"])
        )
        # PERSON should be redacted
        assert "[PERSON_" in redact_result["redacted_text"]

    def test_configure_custom_pattern_then_redact(self):
        # Add a custom pattern
        config_result = json.loads(
            handle_configure(
                self.engine,
                custom_patterns=[
                    {"name": "PROJECT_CODE", "pattern": r"PRJ-\d{4}", "score": 0.95}
                ],
            )
        )
        assert "PROJECT_CODE" in config_result["active_entities"]

        # Now redact text containing the custom pattern
        text = "Assign this to PRJ-1234 immediately"
        redact_result = json.loads(handle_redact(self.engine, text=text))
        assert "[PROJECT_CODE_1]" in redact_result["redacted_text"]
        assert "PRJ-1234" not in redact_result["redacted_text"]
```

**Step 2: Run the integration tests**

Run: `uv run pytest tests/test_integration.py -v`

Expected: All 3 tests PASS.

**Step 3: Run full test suite**

Run: `uv run pytest tests/ -v`

Expected: All tests PASS across all test files.

**Step 4: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: add end-to-end integration tests"
```

---

## Task 16: Manual Smoke Test via MCP Inspector

**Step 1: Run the server**

Run: `uv run mcp dev src/mcp_server_redaction/server.py`

Expected: MCP Inspector opens in browser. You should see all 5 tools listed:
- `redact`
- `unredact`
- `analyze`
- `configure`
- `redact_file`

**Step 2: Test `redact` tool in Inspector**

Input:
```json
{"text": "Contact john@example.com or call 555-123-4567"}
```

Expected: Response contains `redacted_text` with placeholders, a `session_id`, and `entities_found >= 2`.

**Step 3: Test `unredact` tool in Inspector**

Use the `session_id` from step 2 and the `redacted_text` from step 2.

Expected: Response restores the original text.

**Step 4: Test `analyze` tool in Inspector**

Input:
```json
{"text": "John Smith lives at 123 Main St, has SSN 123-45-6789"}
```

Expected: Returns entities list with types and partially masked values.

---

## Summary

| Task | Component | Tests |
|------|-----------|-------|
| 1 | Project scaffolding | — |
| 2 | StateManager | 5 |
| 3 | Secrets recognizers | 6 |
| 4 | Financial recognizers | 4 |
| 5 | Medical recognizers | 4 |
| 6 | Registry initialization | 2 |
| 7 | RedactionEngine | 7 |
| 8 | `redact` tool | 2 |
| 9 | `unredact` tool | 2 |
| 10 | `analyze` tool | 2 |
| 11 | `configure` tool | 2 |
| 12 | `redact_file` tool | 2 |
| 13 | Tools re-exports | — |
| 14 | MCP server wiring | 1 |
| 15 | Integration tests | 3 |
| 16 | Manual smoke test | — |

**Total: 16 tasks, ~42 automated tests**
