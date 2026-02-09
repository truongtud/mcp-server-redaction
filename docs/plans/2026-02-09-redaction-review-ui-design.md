# Redaction Review UI Design

## Problem

Non-technical users need a visual way to review redacted files before sending content to LLM models. They need to see exactly what's being redacted and have control over the process.

## Architecture

```
┌─────────────┐     REST/WS      ┌─────────────┐     stdio/MCP     ┌─────────────────┐
│   React UI  │ ◄──────────────► │   FastAPI    │ ◄───────────────► │  mcp-server-    │
│   (SPA)     │                  │   Backend    │                   │  redaction       │
└─────────────┘                  └──────┬───────┘                   └─────────────────┘
                                        │
                                        │ HTTPS (user API keys)
                                        ▼
                                 ┌──────────────┐
                                 │  LLM APIs    │
                                 │  (OpenAI,    │
                                 │   Anthropic) │
                                 └──────────────┘
```

- **Frontend**: React SPA. Handles all three flows.
- **Backend**: Python FastAPI. Bridges the frontend to the MCP redaction server and LLM providers.
- **MCP Redaction Server**: Existing `mcp-server-redaction`, unchanged. Backend spawns it as a subprocess and communicates over stdio.
- **LLM API keys**: User brings their own key (BYOK). Keys are stored in browser `localStorage`, sent per-request in headers, never persisted on the backend.

## Three Flows

### Flow 1: Upload & Review

The foundation for the other two flows.

1. User drags/drops or browses to select a file.
2. Frontend uploads the file to the backend (`POST /api/files/upload`).
3. Backend sends the file to the MCP server via `redact_file` tool, gets back the redacted file + session ID.
4. Backend extracts text from both original and redacted files for the text diff view.
5. Backend returns: original file URL, redacted file URL, text diff data, session ID.
6. Frontend renders the review screen with two view modes:
   - **Rendered preview**: side-by-side or overlay of original vs redacted document (PDF rendered as images, Excel as grid, text/markdown as formatted).
   - **Text diff**: inline or side-by-side diff with redacted entities highlighted in color (names in blue, emails in orange, SSNs in red).
7. User can toggle between view modes via tabs.
8. Each redacted entity is clickable -- shows a tooltip with the entity type and confidence score.
9. User clicks "Approve & Download" to save the redacted file.
10. User can click "Undo" on individual redactions (calls `unredact` with the session ID for that specific placeholder, then re-renders).

**Endpoints:**
- `POST /api/files/upload` -- upload + trigger redaction
- `GET /api/files/{id}/original` -- serve original for preview
- `GET /api/files/{id}/redacted` -- serve redacted for preview
- `GET /api/files/{id}/diff` -- text diff data with entity metadata

### Flow 2: Chat with Review Gate

Chat interface with an interception step when files are attached.

1. User configures their LLM API key in settings.
2. Plain text messages go straight through to the LLM via the backend (`POST /api/chat/message`).
3. When the user attaches a file, the flow pauses:
   - File uploads and redaction runs (same as Flow 1).
   - An inline card expands in the chat input area, above the send button.
   - The card shows: compact diff preview (first ~10 lines with highlights), entity count summary (e.g., "3 names, 2 emails, 1 SSN redacted"), and an "Expand full diff" link.
4. User reviews and either:
   - **Approves**: redacted file content is attached to the message and sent to the LLM.
   - **Edits**: expands full diff, undoes specific redactions, then approves.
   - **Cancels**: file is removed, user continues chatting without it.
5. Chat streams the LLM response back via WebSocket.
6. If the LLM response references redacted placeholders like `[PERSON_1]`, they display as-is.

**Additional endpoints:**
- `POST /api/chat/message` -- send message + optional redacted file to LLM
- `WS /api/chat/stream` -- WebSocket for streaming LLM responses
- `POST /api/settings/validate-key` -- verify an API key works

### Flow 3: Batch Review

Multiple file review with bulk download.

1. User drags/drops or selects multiple files (or a folder).
2. Frontend uploads all files to the backend (`POST /api/batch/upload`).
3. Backend processes files in parallel.
4. Frontend shows a file list panel on the left with status indicators:
   - Spinner while processing.
   - Green checkmark when ready to review.
   - Red icon if unsupported or failed.
5. User clicks a file to see its diff view on the right (same as Flow 1).
6. Each file has approve/edit/skip status. User works through the list.
7. Summary bar at the top: "5 of 12 files reviewed, 2 skipped".
8. "Download All Approved" zips the approved redacted files.

**Additional endpoints:**
- `POST /api/batch/upload` -- upload multiple files, returns batch ID
- `GET /api/batch/{id}/status` -- polling for processing progress
- `GET /api/batch/{id}/files` -- list files with review status
- `POST /api/batch/{id}/download` -- zip and download approved files

## Frontend Component Structure

**Core shared components:**
- `<DiffViewer>` -- renders two modes:
  - `<RenderedPreview>` -- PDF pages as images, Excel as HTML table, text/markdown formatted. Redacted regions highlighted with colored overlays.
  - `<TextDiff>` -- inline or side-by-side text diff. Each entity type gets a distinct color.
- `<EntityChip>` -- clickable pill on each redacted entity. Shows type, confidence score on hover, "Undo" button.
- `<FileUploader>` -- drag-and-drop zone, supports single and multi-file.
- `<ViewModeToggle>` -- tabs to switch between rendered preview, text diff, side-by-side, and inline.

**Flow-specific components:**
- `<UploadReviewPage>` -- Flow 1. FileUploader -> DiffViewer -> Download button.
- `<ChatPage>` -- Flow 2. Message list, input box, `<ReviewCard>` inline expansion.
- `<ReviewCard>` -- compact diff preview with entity summary, expand/approve/cancel actions.
- `<BatchPage>` -- Flow 3. File list sidebar + DiffViewer main panel + summary bar + bulk download.

**Layout:**
- Top nav with three tabs: Review, Chat, Batch.
- Settings page for API key configuration.

## Backend Structure

**`/api`** -- Route handlers:
- `files.py` -- upload, serve original/redacted, diff data (Flow 1)
- `chat.py` -- message relay, WebSocket streaming (Flow 2)
- `batch.py` -- multi-file upload, status polling, zip download (Flow 3)
- `settings.py` -- API key validation

**`/mcp`** -- MCP client:
- `client.py` -- spawns `mcp-server-redaction` as a subprocess, sends JSON-RPC over stdio. Wraps MCP tools as async Python methods. Maintains a single long-lived subprocess, reconnects if it dies.

**`/llm`** -- LLM provider abstraction:
- `provider.py` -- base interface with `chat()` and `stream()` methods.
- `openai.py`, `anthropic.py` -- provider implementations.
- API keys passed per-request, never stored.

**`/storage`** -- Temporary file management:
- `store.py` -- saves files to temp directory with TTL-based cleanup (1 hour expiry).
- Files referenced by unique IDs, mapped to original/redacted paths and session IDs.

**No database.** All state is in-memory and temporary.

## Tech Stack

- **Frontend**: React, TypeScript, Vite, Tailwind CSS, `react-diff-viewer`, `react-pdf`
- **Backend**: FastAPI, uvicorn, httpx, python-multipart
- **Desktop (later)**: Tauri wrapping the React frontend, Python backend as sidecar

## Build Order

### Phase 1: Foundation
Backend MCP client wrapper + file upload/redaction endpoint + `<DiffViewer>` with text diff mode. Result: upload a file and see a text diff.

### Phase 2: Flow 1 Complete
Rendered preview mode (PDF/Excel/text), `<EntityChip>` with undo, download. Result: full upload & review flow.

### Phase 3: Flow 2 (Chat)
LLM provider abstraction, chat API + WebSocket, `<ChatPage>` with `<ReviewCard>` inline expansion. Result: chat with file redaction gate.

### Phase 4: Flow 3 (Batch)
Batch upload endpoint, parallel processing, `<BatchPage>` with file list + bulk download. Result: all three flows complete.

Each phase is independently shippable.
