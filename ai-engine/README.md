# Elysium AI Engine

The Python sidecar of Elysium (`elysium_engine`): a FastAPI service hosting the
agent team, model providers, routing and memory. In production it is spawned by
the Rust core with a per-session token and only ever binds `127.0.0.1`
(see `docs/ARCHITECTURE.md` §2 and §4 for the process model and API contract).

## Setup (development)

Requires Python 3.11+.

```bash
cd ai-engine
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Run

```bash
ELYSIUM_TOKEN=dev-secret .venv/bin/python -m elysium_engine
# -> http://127.0.0.1:8791  (loopback only, always)
curl http://127.0.0.1:8791/health
curl -H "Authorization: Bearer dev-secret" http://127.0.0.1:8791/projects
```

Environment variables (all optional except the token):

| Variable | Default | Purpose |
|---|---|---|
| `ELYSIUM_TOKEN` | — (required) | Bearer token; every route except `/health` requires it |
| `ELYSIUM_PORT` | `8791` | Listen port on 127.0.0.1 |
| `ELYSIUM_DATA_DIR` | `~/.local/share/elysium` (platform equivalent on macOS/Windows) | App data directory |
| `ELYSIUM_DB_URL` | SQLite file in the data dir | Use `postgresql://...` for the Postgres backend |

## Database

- Default backend is SQLite (zero setup); PostgreSQL is first-class via
  `ELYSIUM_DB_URL` (ADR-001).
- Schema is bootstrapped automatically on first run. Alembic owns upgrades:

```bash
ELYSIUM_DB_URL=sqlite:////path/to/elysium.db .venv/bin/alembic upgrade head
```

## Secrets

Provider API keys are stored in the OS keychain via `keyring` (service
`"elysium"`) — never in the database, config files or logs. On headless
machines/CI with no keychain backend the engine falls back to an **in-memory**
store with a logged warning: keys then have to be re-entered after a restart.

## API

The engine implements the contract table in `docs/ARCHITECTURE.md` §4:
projects/conversations/messages CRUD, `GET /conversations/{id}/stream` (SSE
with event types `token`, `agent_status`, `decision`, `action_request`,
`done`, `error`), `GET /models`, `PUT /models/providers/{name}` and
`GET /agents`.

Notes:

- `POST /conversations/{id}/messages` returns `202` with the message id and
  starts the Project Manager agent run in the background; the stream endpoint
  replays persisted events (use `?after=<last event id>` as cursor) and then
  relays live events until the run finishes.
- `GET /models` reports `configured` per provider; `reachable` is `null`
  unless you pass `?probe=1`, because probing performs live network calls.
- A provider becomes routable once saved via `PUT /models/providers/{name}`
  (plus an `api_key` for remote providers; local ones like Ollama need none).

## Model routing

`elysium_engine/routing.py` is a pure, deterministic function over
`(task class, estimated context, budget, available options)`: simple tasks go
to fast/cheap models, architecture work to the most capable ones, with a tier
fallback chain when a provider is unavailable (ADR-004).

The "Compréhension %" shown in the UI comes from
`elysium_engine/agents/understanding.py`: a weighted coverage **heuristic**
over the PM's requirements checklist — not a model probability (ADR-005).

## Tests

```bash
.venv/bin/pytest
```

The suite never calls a real LLM API: provider adapters are tested against
`httpx.MockTransport`, and API tests run on a temp SQLite database.
