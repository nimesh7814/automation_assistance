import asyncio
import json
import os
from pathlib import Path
from typing import Iterable

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse


LOG_ROOT = Path(os.getenv("LOG_ROOT", "/logs")).resolve()
TAIL_LINES = int(os.getenv("TAIL_LINES", "300"))
POLL_SECONDS = float(os.getenv("POLL_SECONDS", "1"))

app = FastAPI(title="GeoJSON Viewer Logs")


def log_files() -> dict[str, list[str]]:
    if not LOG_ROOT.exists():
        return {}

    services: dict[str, list[str]] = {}
    for service_dir in sorted(path for path in LOG_ROOT.iterdir() if path.is_dir()):
        files = sorted(
            file.name
            for file in service_dir.iterdir()
            if file.is_file() and (file.suffix == ".log" or ".log." in file.name)
        )
        if files:
            services[service_dir.name] = files
    return services


def resolve_log_path(service: str, filename: str) -> Path:
    if not service or service in {".", ".."} or "/" in service or "\\" in service:
        raise HTTPException(status_code=400, detail="Invalid service")
    if not filename or filename in {".", ".."} or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid file")

    path = (LOG_ROOT / service / filename).resolve()
    try:
        path.relative_to(LOG_ROOT)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid log path") from exc

    if not path.is_file():
        raise HTTPException(status_code=404, detail="Log file not found")
    return path


def read_tail(path: Path, lines: int) -> list[str]:
    lines = max(1, min(lines, 5000))
    with path.open("rb") as file:
        file.seek(0, os.SEEK_END)
        end = file.tell()
        block_size = 8192
        chunks: list[bytes] = []
        newline_count = 0

        while end > 0 and newline_count <= lines:
            read_size = min(block_size, end)
            end -= read_size
            file.seek(end)
            chunk = file.read(read_size)
            chunks.append(chunk)
            newline_count += chunk.count(b"\n")

    data = b"".join(reversed(chunks))
    return data.decode("utf-8", errors="replace").splitlines()[-lines:]


def sse_event(event: str, payload: object) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


async def stream_log(path: Path, initial_lines: int) -> Iterable[str]:
    yield sse_event("snapshot", read_tail(path, initial_lines))

    position = path.stat().st_size
    while True:
        await asyncio.sleep(POLL_SECONDS)

        try:
            size = path.stat().st_size
        except FileNotFoundError:
            yield sse_event("error", "Log file disappeared")
            return

        if size < position:
            position = 0
            yield sse_event("snapshot", read_tail(path, initial_lines))
            continue

        if size == position:
            continue

        with path.open("rb") as file:
            file.seek(position)
            chunk = file.read()
            position = file.tell()

        text = chunk.decode("utf-8", errors="replace")
        if text:
            yield sse_event("append", text.splitlines())


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return HTML


@app.get("/api/files")
def files() -> JSONResponse:
    return JSONResponse(log_files())


@app.get("/api/logs/{service}/{filename}")
def tail(
    service: str,
    filename: str,
    lines: int = Query(default=TAIL_LINES, ge=1, le=5000),
) -> JSONResponse:
    path = resolve_log_path(service, filename)
    return JSONResponse({"service": service, "file": filename, "lines": read_tail(path, lines)})


@app.get("/stream/{service}/{filename}")
def stream(
    service: str,
    filename: str,
    lines: int = Query(default=TAIL_LINES, ge=1, le=5000),
) -> StreamingResponse:
    path = resolve_log_path(service, filename)
    return StreamingResponse(
        stream_log(path, lines),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


HTML = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>GeoJSON Viewer Logs</title>
  <style>
    :root {{
      color-scheme: dark;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #0f172a;
      color: #e5e7eb;
    }}
    body {{ margin: 0; min-height: 100vh; background: #111827; }}
    header {{
      display: flex; align-items: center; justify-content: space-between; gap: 16px;
      padding: 16px 20px; border-bottom: 1px solid #263244; background: #0b1220;
    }}
    h1 {{ margin: 0; font-size: 20px; font-weight: 700; }}
    .status-list {{ display: flex; gap: 16px; flex-wrap: wrap; color: #9ca3af; font-size: 14px; }}
    .status {{ display: inline-flex; align-items: center; gap: 8px; }}
    .dot {{ width: 10px; height: 10px; border-radius: 50%; background: #ef4444; }}
    .dot.live {{ background: #22c55e; box-shadow: 0 0 12px #22c55e; }}
    main {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; padding: 16px; }}
    section {{
      min-width: 0; height: calc(100vh - 98px); display: flex; flex-direction: column;
      border: 1px solid #263244; border-radius: 8px; background: #0b1220; overflow: hidden;
    }}
    .table-head {{
      display: flex; align-items: center; justify-content: space-between; gap: 12px;
      padding: 12px 14px; border-bottom: 1px solid #263244;
    }}
    h2 {{ margin: 0; font-size: 16px; }}
    .meta {{ color: #94a3b8; font-size: 13px; }}
    .table-wrap {{ flex: 1; overflow: auto; background: #030712; }}
    table {{ width: 100%; border-collapse: collapse; table-layout: fixed; font-size: 13px; }}
    th, td {{ border-bottom: 1px solid #1f2937; padding: 8px 10px; vertical-align: top; }}
    th {{ position: sticky; top: 0; z-index: 1; background: #111827; color: #cbd5e1; text-align: left; font-size: 12px; text-transform: uppercase; }}
    td {{ font-family: "Cascadia Mono", "SFMono-Regular", Consolas, monospace; color: #d1d5db; }}
    .time {{ width: 165px; color: #93c5fd; }}
    .level {{ width: 78px; color: #fbbf24; }}
    .message {{ white-space: pre-wrap; overflow-wrap: anywhere; }}
    .empty td {{ color: #94a3b8; font-family: inherit; }}
    @media (max-width: 1000px) {{ main {{ grid-template-columns: 1fr; }} section {{ height: 52vh; }} }}
  </style>
</head>
<body>
  <header>
    <h1>GeoJSON Viewer Logs</h1>
    <div class="status-list">
      <span class="status"><span id="api-dot" class="dot"></span><span id="api-state">API disconnected</span></span>
      <span class="status"><span id="ui-dot" class="dot"></span><span id="ui-state">UI disconnected</span></span>
    </div>
  </header>
  <main>
    <section>
      <div class="table-head">
        <h2>API</h2>
        <span class="meta">api/api.log</span>
      </div>
      <div class="table-wrap" id="api-wrap">
        <table>
          <thead><tr><th class="time">Time</th><th class="level">Level</th><th>Message</th></tr></thead>
          <tbody id="api-body"><tr class="empty"><td colspan="3">Waiting for API logs...</td></tr></tbody>
        </table>
      </div>
    </section>
    <section>
      <div class="table-head">
        <h2>UI</h2>
        <span class="meta">ui/ui.log</span>
      </div>
      <div class="table-wrap" id="ui-wrap">
        <table>
          <thead><tr><th class="time">Time</th><th class="level">Level</th><th>Message</th></tr></thead>
          <tbody id="ui-body"><tr class="empty"><td colspan="3">Waiting for UI logs...</td></tr></tbody>
        </table>
      </div>
    </section>
  </main>
  <script>
    const MAX_ROWS = 1000;
    const TAIL_LINES = 300;
    const LOGS = [
      {{ service: "api", file: "api.log", body: "api-body", wrap: "api-wrap", dot: "api-dot", state: "api-state", label: "API" }},
      {{ service: "ui", file: "ui.log", body: "ui-body", wrap: "ui-wrap", dot: "ui-dot", state: "ui-state", label: "UI" }}
    ];

    function setState(config, text, live) {{
      document.getElementById(config.state).textContent = `${{config.label}} ${{text}}`;
      document.getElementById(config.dot).classList.toggle("live", live);
    }}

    function parseLine(line) {{
      const match = line.match(/^(\\d{{4}}-\\d{{2}}-\\d{{2}} \\d{{2}}:\\d{{2}}:\\d{{2}}(?:,\\d+)?) \\[([^\\]]+)\\]\\s?(.*)$/);
      if (!match) return {{ time: "", level: "", message: line }};
      return {{ time: match[1], level: match[2], message: match[3] }};
    }}

    function cell(text, className) {{
      const td = document.createElement("td");
      td.textContent = text;
      if (className) td.className = className;
      return td;
    }}

    function appendLines(config, lines, replace = false) {{
      const body = document.getElementById(config.body);
      const wrap = document.getElementById(config.wrap);
      if (replace) body.textContent = "";

      if (!Array.isArray(lines) || lines.length === 0) {{
        if (replace) {{
          const row = document.createElement("tr");
          row.className = "empty";
          row.appendChild(cell(`${{config.label}} log file is empty.`, ""));
          row.firstChild.colSpan = 3;
          body.appendChild(row);
        }}
        return;
      }}

      body.querySelectorAll(".empty").forEach(row => row.remove());
      for (const line of lines) {{
        const parsed = parseLine(line);
        const row = document.createElement("tr");
        row.appendChild(cell(parsed.time, "time"));
        row.appendChild(cell(parsed.level, "level"));
        row.appendChild(cell(parsed.message, "message"));
        body.appendChild(row);
      }}

      while (body.rows.length > MAX_ROWS) body.deleteRow(0);
      wrap.scrollTop = wrap.scrollHeight;
    }}

    function connect(config) {{
      setState(config, "connecting", false);
      const url = `/stream/${{encodeURIComponent(config.service)}}/${{encodeURIComponent(config.file)}}?lines=${{TAIL_LINES}}`;
      const source = new EventSource(url);

      source.addEventListener("open", () => setState(config, "live", true));
      source.addEventListener("snapshot", event => appendLines(config, JSON.parse(event.data), true));
      source.addEventListener("append", event => appendLines(config, JSON.parse(event.data), false));
      source.addEventListener("error", () => setState(config, "reconnecting", false));
    }}

    for (const config of LOGS) connect(config);
  </script>
</body>
</html>
"""
