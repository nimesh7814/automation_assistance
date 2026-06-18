# Logger

Live log viewer for the GeoJSON Viewer Docker Compose stack.

It reads rotating log files from the project `logs` folder and shows two live-updating tables:

- API: `logs/api/api.log`
- UI: `logs/ui/ui.log`

## Run

From the project root:

```bash
docker compose up logs -d
```

Open:

```text
http://localhost:8888
```

## Environment Variables

| Variable       | Default | Description                                         |
| -------------- | ------- | --------------------------------------------------- |
| `LOG_ROOT`     | `/logs` | Root folder where service log folders are mounted.  |
| `TAIL_LINES`   | `300`   | Number of existing lines shown when the page loads. |
| `POLL_SECONDS` | `1`     | How often the server checks for new log lines.      |

## Notes

- The viewer expects `api/api.log` and `ui/ui.log` under `LOG_ROOT`.
- The browser updates live using Server-Sent Events.
