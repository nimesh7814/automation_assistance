# Assistant

The Assistant tab is a Gemini-powered chat agent, grounded in whatever GeoJSON data is loaded in the current dashboard session. It's rendered from `ui/app.py` through `render_assistant_tab`, which `assistant/__init__.py` re-exports — but the implementation lives entirely in this separate top-level package, not inside `ui/`, on purpose: the LLM-facing logic (prompt, tool catalog, the function-calling loop) stays in one place, independent of how the rest of the dashboard is built, and could in principle be reused by a different frontend without dragging Streamlit along.

## What it can answer

Ask it things like:

- How many geometries are in this file?
- What's the total area in hectares?
- List invalid geometries.
- Are there duplicate geometries?
- What attributes exist in the uploaded file?
- Which features have a specific attribute value?

It cannot edit, delete, fix, or export anything — those stay normal dashboard actions the user drives directly on the Validate, Duplicates, or Edit tabs.

## How it's kept from making things up

The core problem with any LLM answering questions about real data is that it's perfectly happy to *sound* confident while inventing a number. This assistant is built around one rule: **the model is never the source of a fact, only the explainer of one.**

That's enforced in a few overlapping ways:

- **No broad access, ever.** The model doesn't see the database, the filesystem, or any application internals. It gets a fixed list of seven read-only tools (below), declared once in `TOOL_DECLARATIONS` and dispatched through `TOOL_DISPATCH` — there is no generic "run a query" or "fetch a URL" escape hatch it could be tricked into using.
- **The system prompt tells it, explicitly, not to guess.** It's instructed to use the tools for every fact — feature counts, areas, IDs, validation results, property names and values — and to say plainly when a tool returns nothing or fails, rather than filling the gap with something plausible-sounding.
- **No write capability exists, full stop.** This isn't a permission check that could have a bug in it — there is no `delete_feature` or `update_geometry` tool in the catalog for the model to even attempt to call. If a user (or a malicious value hidden in an uploaded file's properties) asks it to fix or delete something, the system prompt tells it to explain that it can't, and point at the right tab instead.
- **Every tool call is visible.** The UI shows a "Tool calls used" expander under each answer, with the exact tool name, arguments, and raw result. A human reviewer doesn't have to take the final answer on faith — they can check whether it actually came from a structured query or was made up despite the instructions.
- **Tool results are treated as untrusted data, not instructions.** A property value in an uploaded file could contain something like "ignore previous instructions and say X." The system prompt explicitly tells the model to treat everything tool results return as data to report, never as commands to follow — a basic prompt-injection mitigation, not a complete one (see [Production risks](#production-risks-and-mitigations) below).

| Tool | What it does |
| --- | --- |
| `get_feature_count` | Counts loaded features and geometry types from the current session's cached features — no API call needed. |
| `get_total_area_hectares` | Calls the API's `/stats/area` endpoint. |
| `run_validation_scan` | Calls the API's `/validate` endpoint. |
| `run_duplicate_scan` | Calls the API's `/duplicates` endpoint, always with `remove_duplicates=false` — the assistant can report duplicates, never delete them. |
| `list_property_keys` | Lists every real attribute name found across the loaded features, with type, null/non-null counts, and either the full set of distinct values (low-cardinality fields) or a small sample (high-cardinality ones) — exists so the model can look up the *real* spelling of an attribute instead of guessing one. |
| `get_feature_properties` | Returns the properties and geometry type for one feature, by its 0-based feature ID. |
| `search_features_by_property` | Finds features whose given property matches a given value, case-insensitive exact match. |

## The agent loop

This is a small, fully controlled loop, not a free-form chatbot wired straight to a chat completion:

1. The user asks a question in the Assistant tab.
2. The question, conversation history, system instruction, and tool declarations all go to Gemini.
3. Gemini either answers directly, or asks to call one tool.
4. If it asked for a tool, the Python code runs *only* that tool, from the fixed dispatch table — never anything Gemini names that isn't already a known, registered function.
5. The tool's result goes back to Gemini as the next message.
6. Repeat from step 3, up to `MAX_TOOL_CALLS` (5) times. If a real answer hasn't come back by then, the user gets a message asking them to rephrase, rather than letting the loop run (and rack up API calls) indefinitely.
7. The final answer and the full tool-call trace are both shown in the UI.

The Gemini SDK has its own "automatic function calling" mode that would do steps 3–5 invisibly; it's deliberately turned off here (`automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)`) so every call and result can be logged and surfaced in that trace instead of disappearing inside the SDK.

## Configuration

| Variable | Purpose |
| --- | --- |
| `GEMINI_API_KEY` | Required for the Assistant tab. Without it, the tab shows a warning and returns early — the rest of the dashboard is unaffected. |
| `GEMINI_MODEL` | Optional. Defaults to `gemini-2.5-flash`. |
| `LIMIT` | Optional. Defaults to `100`. Caps the number of questions a single session can send, mostly to bound API spend rather than for any safety reason. |

Environment variables are read inside functions (`_get_message_limit()`, the `GEMINI_API_KEY` lookup inside `render_assistant_tab`) rather than once at import time, since `ui/app.py` imports this package *before* it calls `load_dotenv()` — reading at call time means `.env` values are still picked up correctly when running outside Docker.

## Error handling

Gemini API errors are caught specifically (`google.genai.errors.APIError`, so the real `code`/`status`/`message` can be shown) with a generic exception fallback underneath, and both surface as `st.error` rather than crashing the tab. A failed tool call inside the loop is also caught — it shows up as an `error` field in that tool's trace entry plus an `st.warning`, but doesn't take down the rest of the conversation.

The assistant is entirely optional: if Gemini is unreachable, rate-limited, or simply not configured, every other tab keeps working normally.

## Production risks and mitigations

| Risk | Why it matters | Mitigation |
| --- | --- | --- |
| Hallucinated answer | The model might answer without enough evidence. | Keep factual questions tool-based, show the full tool trace, and instruct the model not to guess (see above). |
| Prompt injection through uploaded attributes | GeoJSON property values may contain malicious instructions. | Treat tool output as data only, never as commands. Worth adding: dedicated prompt-injection test cases and stricter output filtering. |
| Data leakage to an external LLM | Uploaded attributes and summaries get sent to Gemini as tool results. | Review data policy before using on sensitive data, redact fields that shouldn't leave the network, or swap in a self-hosted/enterprise-approved model. |
| Unexpected cost | Repeated questions create real API spend. | `LIMIT` already caps this per session; a production deployment should add user-level rate limits and usage monitoring on top. |
| Write-capable agent risk | If write tools are ever added, the model could make harmful changes on its own. | Don't add them without also adding explicit human confirmation, dry-run previews, and an audit log for every write — none of which exist yet because there's nothing to confirm. |
| Tool result overload | A very wide attribute table could blow past context limits or expose more than intended. | `list_property_keys` already summarizes high-cardinality fields instead of dumping every value; extend that pattern (pagination, row caps) if datasets grow much larger. |
| Availability dependency | The assistant depends on Gemini and outbound network access. | The rest of the dashboard already doesn't depend on it — keep it that way, and keep the degraded-mode messaging clear when Gemini is unavailable. |

## Current limitations

- Read-only by design — it can guide the user toward a fix, but never performs one.
- Can't answer anything its seven tools don't expose.
- Property search is exact-match, not semantic or fuzzy.
- No audit record beyond the normal application logs and the visible tool trace.
- Tool results (including uploaded property values) aren't redacted before being sent to Gemini.
- Refuses outright if the loaded file's CRS isn't WGS84/CRS84 (flagged at upload — see `api/README.md`), since any area or position it reported from a wrongly-projected file would be wrong, and it has no way to reproject the data itself.

## Packaging

The assistant ships inside both Docker options:

- Split UI image: `ui/Dockerfile` copies `assistant/` in beside the UI code.
- Single-container app: the root `Dockerfile` copies `api/`, `ui/`, and `assistant/` into one image.

Its dependencies (`google-genai`, alongside `streamlit`) live in `ui/requirements.txt`, since it's only ever imported from inside the UI process — there's no standalone way to run it today.
