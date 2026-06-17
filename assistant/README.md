# Assistant

A Gemini function-calling assistant, grounded in the GeoJSON data loaded in the current dashboard session. Rendered as the UI's "Assistant" tab via `render_assistant_tab`, re-exported from `assistant/__init__.py` and imported by `ui/app.py` as `from assistant import render_assistant_tab`.

It's a separate top-level package (not under `ui/`) so it's a clearly distinct concern from the dashboard UI, even though it's only ever rendered from there.

## How it works

This is a manual function-calling loop against `google-genai`, not the SDK's automatic loop — every tool call and result is captured so it can be shown in the UI's "Tool calls used" trace.

- The model can only call the tools declared in `TOOL_DECLARATIONS`/`TOOL_DISPATCH`: feature count, total area, validation scan, duplicate scan, list every property/attribute name with its types and value breakdown, get one feature's properties, search features by property value. **None of them can write, fix, or delete data** — that capability simply doesn't exist in the tool catalog, so it isn't something that can be bypassed at runtime.
- The `list_property_keys` tool exists specifically to stop the model from guessing attribute names: the system prompt tells it to call this before filtering/searching by a property it isn't sure about, since an invented property name would otherwise just silently find nothing.
- The loop is capped at `MAX_TOOL_CALLS` (5) round-trips per question; if it's not resolved by then, the user gets a "please rephrase" message instead of an infinite loop.
- Tool results are scoped to the same session as the rest of the dashboard — tools take the UI's already session-bound `features` list and `api_request` function, so the assistant never widens the session boundary.
- The system prompt explicitly tells the model to treat tool-returned data (including property values copied straight from the uploaded file) as data only, never as instructions — a mitigation against prompt injection via a malicious property value.

See `docs/agentic_ai_assistant.md` (if present in your checkout) for the full architecture writeup and an OWASP-LLM-Top-10-mapped risk/mitigation table.

## Configuration

Read from the environment at call time, not module import time — `os.getenv()` calls live inside functions (`_get_message_limit()`, the `GEMINI_API_KEY` lookup in `render_assistant_tab`), not at module scope. That matters because env vars need to already be loaded before they're read; `ui/app.py` calls `load_dotenv()` near the top of the file, before importing this package, so this isn't actually load-bearing today — but reading lazily means the order could change later without silently breaking config:

| Variable | Purpose |
| --- | --- |
| `GEMINI_API_KEY` | Required. Without it, `render_assistant_tab` shows a warning and returns early — the rest of the dashboard is unaffected. |
| `GEMINI_MODEL` | Optional, defaults to `gemini-2.5-flash`. |
| `LIMIT` | Optional, defaults to `100`. Per-session cap on the number of questions a user can send, to bound API spend. |

## Error handling

`google.genai.errors.APIError` is caught specifically (to surface `code`/`status`/`message`) with a generic `Exception` fallback; both show `st.error` with the real error. Backend tool-call errors (e.g. a failed `/validate` call) surface as `st.warning` in addition to appearing in the collapsed tool-call trace — a failed tool never crashes the chat loop.

## Packaging

Shipped as part of the `ui` Docker image: `ui/Dockerfile` has a `COPY assistant/ ./assistant/` step alongside `COPY ui/ ./`, so this package ends up next to `ui/app.py` inside the container. Its dependencies (`streamlit`, `google-genai`) live in `ui/requirements.txt`, not a requirements file of its own. When running the UI directly on the host (`cd ui && streamlit run app.py`), `ui/app.py` inserts the repo root onto `sys.path` before importing this package, since `assistant/` otherwise wouldn't be on Python's import path from inside `ui/`.
