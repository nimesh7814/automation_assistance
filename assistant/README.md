# Assistant

The Assistant tab is a Gemini function-calling assistant grounded in the GeoJSON data loaded in the current dashboard session. It is rendered from `ui/app.py` through `render_assistant_tab`, re-exported by `assistant/__init__.py`.

It is intentionally a separate top-level package so the LLM logic stays separate from the normal dashboard UI code.

## What The Assistant Can Do

The assistant can answer questions such as:

- How many geometries are in this file?
- What is the total area in hectares?
- List invalid geometries.
- Are there duplicate geometries?
- What attributes exist in the uploaded file?
- Which features have a specific attribute value?

It cannot edit, delete, fix, or export data. Those actions remain normal dashboard workflows controlled by the user.

## How It Is Constrained To Real Data

The assistant does not receive broad access to the database, filesystem, or application internals. It gets a fixed list of read-only tools:

| Tool | What it does |
| --- | --- |
| `get_feature_count` | Counts loaded features and geometry types from the current session cache. |
| `get_total_area_hectares` | Calls the API's `/stats/area` endpoint. |
| `run_validation_scan` | Calls the API's `/validate` endpoint. |
| `run_duplicate_scan` | Calls the API's `/duplicates` endpoint without removing anything. |
| `list_property_keys` | Lists real attribute names, types, null counts, and values from the loaded features. |
| `get_feature_properties` | Returns the properties for one feature ID. |
| `search_features_by_property` | Searches features by exact property value. |

The system prompt tells the model to use only these tools for facts. It must not guess feature counts, areas, IDs, validation status, duplicate groups, or property names.

The tool trace is shown in the UI under "Tool calls used". This is important because a human reviewer can see whether the answer came from a real structured query or from model text generation.

## Agentic Architecture

This is a small controlled agent loop, not a free-form chatbot.

1. The user asks a question in the Assistant tab.
2. The code sends the question, conversation history, system instruction, and tool declarations to Gemini.
3. Gemini can either answer directly or request a tool call.
4. The Python code executes only the requested tool if it is in the allow-list.
5. The tool result is sent back to Gemini.
6. Gemini writes the final answer based on the tool result.
7. The UI displays the final answer and the tool trace.

Automatic SDK function calling is disabled. The application handles every tool call itself so it can log calls, show traces, limit loops, and prevent hidden behavior.

The loop is capped at `MAX_TOOL_CALLS = 5`. If the model cannot answer within that limit, the user is asked to rephrase instead of allowing an infinite or expensive loop.

## Prompt Injection Mitigation

Uploaded GeoJSON attributes are untrusted data. A property value could contain text such as "ignore previous instructions". The system instruction explicitly tells the model to treat all tool-returned values as data only, never as instructions.

This is not a complete security boundary by itself. For production, I would also add output filtering, stricter tool result schemas, monitoring for suspicious prompts, and tests with malicious sample files.

## Configuration

| Variable | Purpose |
| --- | --- |
| `GEMINI_API_KEY` | Required for the Assistant tab. Without it, the tab shows a warning and returns early. |
| `GEMINI_MODEL` | Optional. Defaults to `gemini-2.5-flash`. |
| `LIMIT` | Optional. Defaults to `100`. Limits assistant questions per session to control API spend. |

The code reads environment variables at call time where practical, so configuration changes are less likely to be frozen at import time.

## Error Handling

Gemini API errors are caught and shown as user-friendly Streamlit errors. Tool failures are also caught. A failed tool call appears in the tool trace and does not crash the whole chat loop.

The assistant is optional. If it is unavailable, the rest of the dashboard still works.

## Production Risks And Mitigations

| Risk | Why it matters | Mitigation |
| --- | --- | --- |
| Hallucinated answer | The model might answer without enough evidence. | Keep factual questions tool-based. Show tool traces. Instruct the model not to guess. |
| Prompt injection through uploaded attributes | GeoJSON property values may contain malicious instructions. | Treat tool output as data only. Add prompt-injection tests and result sanitization. |
| Data leakage to an external LLM | Uploaded attributes and summaries may be sent to Gemini. | Review data policy, redact sensitive fields, use approved enterprise LLM settings, or run a self-hosted model. |
| Unexpected cost | Repeated questions can create API cost. | Keep `LIMIT`, add user-level rate limits, and monitor usage. |
| Write-capable agent risk | If edit/delete tools are added later, the model could make harmful changes. | Require explicit human confirmation, dry-run previews, permission checks, and audit logs for every write. |
| Tool result overload | Large attribute tables could exceed context or expose too much data. | Summarize high-cardinality fields, page results, and cap returned rows. |
| Availability dependency | Assistant depends on Gemini and network access. | Keep core QA workflow independent, as it is now. Add clear degraded-mode messaging. |

## Current Limitations

- The assistant is read-only. It can guide the user but cannot run cleanup actions.
- It cannot answer questions that require data not exposed by its tools.
- It uses exact-match property search, not semantic search.
- It does not keep a separate audit record beyond normal application logs and the visible tool trace.
- It does not redact uploaded property values before sending tool results to Gemini.

## Packaging

The assistant is included in both Docker options:

- Split UI image: `ui/Dockerfile` copies `assistant/` beside the UI code.
- Single app image: the root `Dockerfile` copies `api/`, `ui/`, and `assistant/` into one container.

Dependencies such as `google-genai` live in `ui/requirements.txt`.
