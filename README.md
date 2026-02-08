# MCP Server Redaction

A Python MCP server for redacting, analyzing, and un-redacting sensitive data from text using [Microsoft Presidio](https://microsoft.github.io/presidio/). Produces reversible indexed placeholders like `[EMAIL_ADDRESS_1]`, `[PERSON_2]`.

## Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) package manager

## Setup

```bash
# Clone the repository
git clone <repo-url>
cd mcp-server-redaction

# Create virtual environment and install dependencies
uv venv
uv sync

# Install the spaCy language model
uv pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_lg-3.8.0/en_core_web_lg-3.8.0-py3-none-any.whl
```

## Running the Server

### With MCP Inspector (development)

```bash
uv run mcp dev run_dev.py
```

This opens the MCP Inspector in your browser where you can test all tools interactively. The `run_dev.py` wrapper is needed because `mcp dev` loads the file directly (not as a package).

### As a stdio server

```bash
uv run mcp-server-redaction
```

### Claude Desktop / Claude Code integration

```bash
claude mcp add redaction -- uv --directory /absolute/path/to/mcp-server-redaction run mcp-server-redaction
```

This works for both Claude Desktop and Claude Code. Replace `/absolute/path/to/mcp-server-redaction` with the actual path to this project.

## Tools

### `redact`

Redact sensitive data from text, replacing entities with indexed placeholders.

```json
{"text": "Contact john@example.com", "entity_types": ["EMAIL_ADDRESS"]}
```

Returns redacted text, a `session_id` for later un-redaction, and count of entities found.

### `unredact`

Restore redacted text to the original using a session ID from a previous `redact` call.

```json
{"redacted_text": "Contact [EMAIL_ADDRESS_1]", "session_id": "uuid-from-redact"}
```

### `analyze`

Analyze text for sensitive data without modifying it. Returns detected entities with partial masking.

```json
{"text": "Contact john@example.com"}
```

### `configure`

Add custom patterns or list active entity types at runtime.

```json
{
  "custom_patterns": [
    {"name": "INTERNAL_ID", "pattern": "ID-\\d{6}", "score": 0.9}
  ]
}
```

### `redact_file`

Redact sensitive data in a file. Writes a new file with `_redacted` suffix.

```json
{"file_path": "/path/to/document.txt"}
```

## Supported Entity Types

**Built-in (Presidio):** PERSON, EMAIL_ADDRESS, PHONE_NUMBER, CREDIT_CARD, US_SSN, URL, IP_ADDRESS, and more.

**Secrets:** API_KEY (OpenAI, GitHub, GitLab, Stripe), AWS_ACCESS_KEY, CONNECTION_STRING (PostgreSQL, MySQL, MongoDB).

**Financial:** IBAN, US_BANK_ROUTING.

**Medical:** ICD10_CODE, MEDICAL_RECORD_NUMBER, DRUG_NAME.

## Running Tests

```bash
# Install dev dependencies
uv sync --group dev

# Run all tests
uv run pytest tests/ -v
```
