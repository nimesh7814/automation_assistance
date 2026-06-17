# Agentic AI Assistant

The Assistant tab lets a user ask natural-language questions about the
GeoJSON data currently loaded in their session ("how many geometries are
there?", "what's the total area in hectares?", "list any invalid
geometries", "are there duplicates?"). It is built on Gemini's function
calling so the model can only act through a fixed set of vetted tools,
instead of generating free-form answers from its own (untrustworthy, for
this purpose) knowledge of the data.

## Architecture

```
User question (st.chat_input)
   -> ui/assistant.py: manual function-calling loop against Gemini
        -> model picks a tool from a fixed, declared list (or answers directly)
        -> assistant.py executes the matching Python function
             -> reads the locally cached feature list (counts / lookups / search), or
             -> calls the existing FastAPI backend (/stats/area, /validate, /duplicates)
        -> result sent back to the model as a structured function_response
           (never as raw text) -> loop continues until the model returns
           a final answer, or 5 tool calls are used up
   -> final answer + an expandable "tool calls used" trace shown in the UI
```

Every tool call is scoped by the same `X-Session-ID` header the rest of the
dashboard already uses, so the assistant only ever sees the data belonging to
the user's own session - it inherits the app's existing session boundary
rather than introducing a new one.

### How grounding is enforced

- **Fixed tool catalog, explicitly allow-listed.** Tools are declared with
  `types.FunctionDeclaration` and passed via `tool_config.function_calling_config`
  with `mode="AUTO"` *and* an explicit `allowed_function_names` list. `AUTO`
  already restricts the model to declared tools; setting the allow-list too
  makes that constraint visible in the code rather than implicit.
- **Manual, not automatic, function calling.** The `google-genai` SDK can run
  the whole tool-call loop internally (`automatic_function_calling`). This
  app disables that (`AutomaticFunctionCallingConfig(disable=True)`) and
  drives the loop itself, so every call/argument/result triple can be
  intercepted, logged, and shown to the user in the "tool calls used"
  expander - the same answer a hidden automatic loop would have produced is
  not good enough here; the user needs to be able to check it.
- **Structured responses, not string concatenation.** Each tool result is
  sent back via `types.Part.from_function_response(name=..., response=...,
  id=...)`, matching the `id` of the originating `function_call` per the
  Gemini API's requirement for disambiguating calls. The result is a typed
  Python dict (counts, floats, short lists), never the raw GeoJSON
  coordinates or an unsanitized property blob.
- **System instruction.** Tells the model to answer only from tool results,
  never invent numbers or IDs, and refuse (pointing to the Validate/
  Duplicates/Edit tabs) if asked to change data - it has no write/fix/delete
  tool available, so it cannot do so even if it tried.
- **Bounded loop.** Capped at 5 tool-call round-trips per question.

### Tool catalog

| Tool | Reads | Mutates data? |
| --- | --- | --- |
| `get_feature_count` | local feature list | no |
| `get_total_area_hectares` | `GET /stats/area` (new) | no |
| `run_validation_scan` | `GET /validate` (existing) | no |
| `run_duplicate_scan` | `GET /duplicates?remove_duplicates=false` (existing) | no |
| `get_feature_properties` | local feature list | no |
| `search_features_by_property` | local feature list | no |

`run_validation_scan` and `run_duplicate_scan` double as both "answer a
question" and "trigger a scan" tools - in this API both are already
side-effect-free `GET` requests, so a separate "list" tool and "run scan"
tool would just be two names for the same call. Collapsing them keeps the
tool count low, which matters: agents tend to make more function-selection
mistakes as the number of similar, overlapping tools grows.

No tool can add, edit, delete, fix, or remove a feature. That is a
deliberate scope decision, not an oversight - see "Excessive Agency" below.

## Why a thin custom loop instead of a heavier agent framework

Frameworks considered: LangChain, LangGraph, and Google's Agent Development
Kit (ADK).

- **LangGraph** is the current production-grade choice when an agent needs
  durable state, branching/looping execution graphs, or multi-agent
  coordination - none of which this feature needs. It's also the
  lowest-latency of the major frameworks in published benchmarks, but that
  benefit shows up on multi-step, multi-agent workloads, not a single
  question-in/answer-out turn.
- **LangChain** is a more accessible starting point but adds measurable
  latency and token overhead on simple, single-tool-call flows compared to a
  direct SDK call.
- **Google ADK** is purpose-built for multi-agent, tool-rich Gemini
  applications with built-in evaluation and deployment tooling - valuable at
  a scale this assistant (six tools, no sub-agents, no persistent workflow)
  hasn't reached yet.

For a fixed, small set of read-only tools answering one question at a time,
a manual `google-genai` function-calling loop is more transparent (every
call is visible in application code, not inside a framework's internals),
has fewer dependencies, and is easier to audit line-by-line for a take-home
of this scope. The trade-off to revisit later: if the assistant grows many
more tools, needs multi-step planning, or needs to coordinate with other
agents (e.g. a second agent that proposes fixes), migrating the tool layer
into LangGraph or ADK would start to pay for itself.

## Production risks and mitigations

Mapped to the [OWASP Top 10 for LLM Applications
(2025)](https://genai.owasp.org/llm-top-10/) so this uses a recognized
framework rather than an ad-hoc list.

| Risk | How it could show up here | Mitigation in this build | Still needed for real production use |
| --- | --- | --- | --- |
| **LLM01 Prompt Injection** | A farm property value (e.g. `producttype`) could contain text trying to override the system instruction once it's echoed back through a tool result. | Tool results are passed back as structured `function_response` data, never concatenated into the prompt/system text; the system instruction tells the model to treat tool data as data, not instructions. | Defense-in-depth: output filtering on the final answer, periodic adversarial testing with crafted property values. |
| **LLM02 Sensitive Information Disclosure** | Sending raw geometry coordinates or full property blobs to a third-party API could leak a client's confidential farm-boundary data. | Tools return only derived/aggregated values (counts, hectares, issue/duplicate lists, one feature's properties on request) - raw coordinate arrays are never included in any tool response. | A data-processing agreement with the LLM vendor, or a self-hosted/open-weight model, if client contracts require it. |
| **LLM06 Excessive Agency** | An agent with delete/fix/edit tools could be talked into modifying data via a cleverly-phrased question. | No write/fix/delete tool is exposed to the model at all - "excessive functionality" is avoided by never giving it that functionality, rather than by trying to police it at runtime. | If write tools are ever added: human-in-the-loop confirmation before any tool with side effects executes (see below). |
| **LLM07 System Prompt Leakage** | A user could ask the model to repeat its system instruction. | The system instruction contains no secrets (no API keys, no internal infrastructure details), so leaking it has low impact. | None specific to this feature. |
| **LLM09 Misinformation** | The model could state a confident but wrong number. | Tool-only-answering instruction, plus the visible "tool calls used" trace, lets a user cross-check every number against the Validate/Duplicates/Export tabs directly. | Periodic eval suite of known question/answer pairs against the sample dataset to catch regressions when the model or prompt changes. |
| **LLM10 Unbounded Consumption** | A pathological question could trigger an unbounded chain of tool calls, or many users could rack up API cost. | Hard cap of 5 tool-call round-trips per question. | Per-session question rate limiting and a request timeout - not implemented yet, flagged here as a follow-up. |

This app's pre-existing risk profile (in-memory single-session storage, no
authentication - see the root `README.md`) is unchanged by the assistant:
every tool call is scoped by the same `X-Session-ID` the rest of the app
already uses, so the assistant does not widen that boundary.

## Natural next step

A "suggest, don't apply" pattern: let the model *propose* a fix or duplicate
removal in its answer, but require the user to click an explicit "Apply"
button that calls the existing `/fix` or `/duplicates?remove_duplicates=true`
endpoints - this follows OWASP's recommended mitigation for Excessive Agency
(human approval for high-impact actions) if write capability is ever added
to the assistant.

## Sources consulted

- [Function calling with the Gemini API](https://ai.google.dev/gemini-api/docs/function-calling) - manual vs. automatic function calling, `function_calling_config` modes, `id`-matched `function_response`.
- [OWASP Top 10 for LLM Applications (2025)](https://genai.owasp.org/llm-top-10/) - risk categories used in the table above.
- LangChain/LangGraph/ADK production-readiness comparisons (LangChain's own [AI agent frameworks](https://www.langchain.com/resources/ai-agent-frameworks) overview and independent 2026 framework benchmarks) - basis for the "why not a heavier framework" section.
