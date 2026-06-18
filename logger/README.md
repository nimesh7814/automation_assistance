# Logger

Small live log viewer for the GeoJSON Viewer Docker Compose stack.

It reads rotating log files from the project `logs` folder and shows two live-updating tables:

- API: `logs/api/api.log`
- UI: `logs/ui/ui.log`

Unlike Dozzle, this service does not need access to the Docker socket. It only mounts the `logs` folder as read-only.

## Run

From the project root:

```bash
docker compose up logs -d
```

Open:

```text
http://localhost:8888
```

## Compose Setup

The service is configured in `docker-compose.yml`:

```yaml
logs:
  build:
    context: .
    dockerfile: logger/Dockerfile
  image: geojson-log-viewer:latest
  environment:
    - LOG_ROOT=/logs
    - TAIL_LINES=300
  volumes:
    - ./logs:/logs:ro
  ports:
    - "8888:8888"
  restart: unless-stopped
```

## Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `LOG_ROOT` | `/logs` | Root folder where service log folders are mounted. |
| `TAIL_LINES` | `300` | Number of existing lines shown when the page loads. |
| `POLL_SECONDS` | `1` | How often the server checks for new log lines. |

## Notes

- The viewer expects `api/api.log` and `ui/ui.log` under `LOG_ROOT`.
- The browser updates live using Server-Sent Events.
- If port `8888` is already in use, stop the old service or change the host port mapping in `docker-compose.yml`.
