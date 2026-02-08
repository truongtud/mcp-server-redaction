# MCP Server Redaction — Design Document

## Overview

A Python MCP server that provides tools for redacting sensitive data from text before it reaches an LLM. Supports reversible redaction with indexed placeholders, enabling un-redaction after processing.

## Detection Strategy

Hybrid approach:
- **Microsoft Presidio** for NLP-based PII detection (names, addresses, etc.) backed by spaCy's `en_core_web_lg` model
- **Custom regex recognizers** registered with Presidio for structured patterns (API keys, secrets, connection strings) that Presidio doesn't cover out of the box

## Sensitive Data Categories

- **PII** — Names, emails, phone numbers, addresses, SSNs
- **Secrets** — API keys, passwords, tokens, connection strings
- **Financial** — Credit card numbers, bank accounts, routing numbers, IBAN
- **Medical** — Drug names, medical record numbers, ICD-10 codes
- **Custom patterns** — User-defined regex/keyword lists added at runtime

## Architecture

### Core Components

- **`server.py`** — MCP server setup, tool registration, request routing
- **`engine.py`** — Orchestrates Presidio's `AnalyzerEngine` and `AnonymizerEngine`, manages custom recognizers
- **`recognizers/`** — Custom Presidio recognizers for secrets, financial data, and medical patterns
- **`state.py`** — Manages redaction mappings (in-memory + optional file persistence)
- **`tools/`** — One module per tool

### Dependencies

- `mcp` — MCP Python SDK
- `presidio-analyzer` — Detection engine
- `presidio-anonymizer` — Anonymization engine
- `spacy` + `en_core_web_lg` — NLP model backend for Presidio
- `pytest` — Testing

## Tool Definitions

### `redact(text, entity_types?)`

Runs text through the hybrid detection engine. Replaces each entity with an indexed placeholder like `[EMAIL_1]`, `[PERSON_2]`.

**Parameters:**
- `text: str` — Text to redact
- `entity_types: list[str] | None` — Optional filter to limit which categories to redact

**Returns:**
```json
{ "redacted_text": "...", "session_id": "uuid", "entities_found": 3 }
```

### `unredact(redacted_text, session_id)`

Looks up the mapping by session ID and replaces placeholders back with originals.

**Parameters:**
- `redacted_text: str` — Text containing placeholders
- `session_id: str` — Session ID from a previous `redact` call

**Returns:**
```json
{ "original_text": "...", "entities_restored": 3 }
```

Errors if session ID not found or mapping expired.

### `analyze(text, entity_types?)`

Runs detection without modifying the text. Partially masks detected values in the response.

**Parameters:**
- `text: str` — Text to analyze
- `entity_types: list[str] | None` — Optional filter

**Returns:**
```json
{
  "entities": [
    { "type": "EMAIL", "start": 10, "end": 25, "score": 0.95, "text": "j***@example.com" }
  ]
}
```

### `configure(custom_patterns?, disabled_entities?, persistence?)`

Runtime configuration for the redaction engine.

**Parameters:**
- `custom_patterns: list[dict] | None` — e.g. `{ "name": "INTERNAL_ID", "pattern": "ID-\\d{6}", "score": 0.9 }`
- `disabled_entities: list[str] | None` — Entity types to disable
- `persistence: dict | None` — e.g. `{ "enabled": true, "path": "./redaction_state.json" }`

**Returns:**
```json
{ "status": "ok", "active_entities": ["EMAIL", "PERSON", "..."] }
```

### `redact_file(file_path, entity_types?)`

Reads a file from disk, runs `redact` on contents, writes redacted version.

**Parameters:**
- `file_path: str` — Path to file to redact
- `entity_types: list[str] | None` — Optional filter

**Returns:**
```json
{ "redacted_file_path": "<original>_redacted.<ext>", "session_id": "uuid", "entities_found": 12 }
```

## State Management

### Session Mappings

```json
{
  "session_id": "uuid",
  "created_at": "ISO timestamp",
  "mappings": {
    "[EMAIL_1]": "john@example.com",
    "[PERSON_1]": "John Smith",
    "[SSN_1]": "123-45-6789"
  }
}
```

### Storage Modes

- **In-memory (default)** — Plain dictionary keyed by session ID. Fast, zero config.
- **File-based (opt-in)** — Enabled via `configure`. Mappings written to JSON on disk after each `redact` call. Loaded from disk on startup. File created with restrictive permissions (600).

### Cleanup

Sessions older than 1 hour are pruned on each `redact` call (lazy expiration). TTL is configurable via `configure`. No background threads.

### Security

The mapping file contains original sensitive data. The server logs a warning when persistence is enabled. File permissions set to 600.

## Custom Recognizers

### Built-in (`recognizers/`)

**`secrets.py`:**
- API keys (prefixes: `sk-`, `pk_`, `AKIA`, `ghp_`, `glpat-`)
- Generic high-entropy tokens (base64 blocks 20+ chars preceded by keywords like `key`, `token`, `secret`)
- Connection strings (PostgreSQL, MySQL, MongoDB URI patterns)
- AWS access keys and secret keys

**`financial.py`:**
- Credit card numbers (Luhn-validated, Visa/MC/Amex/Discover)
- Bank account + routing numbers (US formats)
- IBAN numbers

**`medical.py`:**
- Common drug names (curated list)
- Medical record number formats
- ICD-10 diagnostic codes

Each extends Presidio's `PatternRecognizer` or `EntityRecognizer` and registers at startup.

### User-defined

Added at runtime via `configure` as `PatternRecognizer` instances. Held in memory, optionally persisted alongside session state.

## Project Structure

```
mcp-server-redaction/
├── pyproject.toml
├── README.md
├── src/
│   └── mcp_server_redaction/
│       ├── __init__.py
│       ├── server.py
│       ├── engine.py
│       ├── state.py
│       ├── recognizers/
│       │   ├── __init__.py
│       │   ├── secrets.py
│       │   ├── financial.py
│       │   └── medical.py
│       └── tools/
│           ├── __init__.py
│           ├── redact.py
│           ├── unredact.py
│           ├── analyze.py
│           ├── configure.py
│           └── redact_file.py
└── tests/
    ├── test_engine.py
    ├── test_state.py
    ├── test_recognizers.py
    └── test_tools.py
```

## Packaging

- `pyproject.toml` with `[project.scripts]` entry: `mcp-server-redaction`
- spaCy model (`en_core_web_lg`) installed as post-install step
