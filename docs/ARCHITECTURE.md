# Elysium Architecture

Status: living document. Every structural change must update this file.

## 1. Layered overview

```
┌──────────────────────────────────────────────┐
│  Frontend — React + TypeScript + Tailwind    │
│  (UI only, no critical logic)                │
└───────────────┬──────────────────────────────┘
                │ Tauri IPC (invoke/events)          HTTP+SSE (localhost, token)
┌───────────────▼──────────────────────────────┐   ┌─────────────────────────┐
│  Rust Core (src-tauri)                       │   │  Python AI Engine       │
│  windows · permission broker · secrets ·     │──▶│  FastAPI on 127.0.0.1   │
│  sidecar lifecycle · scoped filesystem       │   │  agents · providers ·   │
└──────────────────────────────────────────────┘   │  memory · workflows     │
                                                   └───────────┬─────────────┘
                                                   ┌───────────▼─────────────┐
                                                   │  Storage                │
                                                   │  SQLite (default)       │
                                                   │  PostgreSQL + pgvector  │
                                                   │  (optional / cloud)     │
                                                   └─────────────────────────┘
```

## 2. Process model

- The **Tauri app** is the single entry point. On startup, the Rust core:
  1. generates a random session token,
  2. spawns the **AI Engine** as a sidecar process (dev: `uvicorn`; release: a
     PyInstaller-built binary) with `ELYSIUM_TOKEN` and `ELYSIUM_PORT` in its env,
  3. waits for `/health`, then passes `{ port, token }` to the frontend via IPC
     (`get_engine_endpoint`).
- The engine binds **127.0.0.1 only** and rejects any request without
  `Authorization: Bearer <token>`.
- The frontend talks to the engine directly over HTTP + SSE for AI features, and to
  Rust over Tauri IPC for anything touching the OS.

## 3. Architecture Decision Records

### ADR-001 — Storage: SQLite by default, PostgreSQL as first-class option
The original master specification mandated PostgreSQL everywhere. Requiring every desktop user to install and run
a Postgres server would kill onboarding for the "complete beginner" persona, which is
persona #1. Decision:
- All persistence goes through **SQLAlchemy** with a repository layer; no raw SQL in
  business code.
- **Default: SQLite** in the app data dir (zero-setup, single file, easy backup/snapshot).
- **PostgreSQL + pgvector** is auto-detected/configurable and is the recommended and
  required backend for team/cloud mode. Migrations (Alembic) target both.
- Vector memory: pgvector on Postgres; on SQLite, embeddings stored as BLOB with
  brute-force cosine search (fine at project scale), upgradeable to sqlite-vec.

### ADR-002 — AI engine stays in Python, shipped as a sidecar
Rust-only was considered (single binary, simpler packaging). Python wins because the
AI/agent ecosystem (SDKs, MCP, embeddings) iterates there first and the open source
community can contribute agents without knowing Rust. Cost: packaging. Mitigation:
PyInstaller sidecar per-platform, spawned and supervised by the Rust core.

### ADR-003 — The permission broker lives in Rust, not Python
Agents (Python) never touch the user's filesystem, shell or network targets directly.
Every privileged action is a **capability request** sent to the Rust core, which checks
the policy (per user / project / agent / tool), asks the human when required, executes,
and returns the result + an audit log entry. Prompt-injected instructions can therefore
never exceed the granted capabilities. Deny by default.

### ADR-004 — Provider abstraction, OpenAI-compatible as the lingua franca
One `ModelProvider` interface (chat, stream, tool-calls, embeddings, cost metadata).
Native adapters for Anthropic and OpenAI; a generic OpenAI-compatible adapter covers
Ollama, LM Studio, OpenRouter, DeepSeek, Mistral, vLLM, etc. Model routing is a pure
function over (task class, context size, cost budget, availability) → provider+model.

### ADR-005 — Agent orchestration is an explicit task graph, not free chat
The Project Manager agent produces/updates a persisted task graph (DB), assigns tasks
to role agents, and every inter-agent message is an event on an append-only event log.
The UI renders decisions/summaries from that log — not raw model output. The
"understanding %" shown to users is a **coverage heuristic** over a requirements
checklist, not a model probability.

## 4. HTTP API contract (engine, v0)

All routes require `Authorization: Bearer <token>`. JSON in/out.

| Method | Route | Purpose |
|---|---|---|
| GET  | `/health` | liveness + version |
| GET/POST | `/projects` | list / create project |
| GET/PATCH/DELETE | `/projects/{id}` | read / update / archive |
| GET  | `/projects/{id}/conversations` | list conversations |
| POST | `/projects/{id}/conversations` | create conversation |
| GET  | `/conversations/{id}/messages` | message history |
| POST | `/conversations/{id}/messages` | send user message (returns message id) |
| GET  | `/conversations/{id}/stream` | **SSE**: assistant tokens + agent events |
| GET  | `/models` | providers + models with `release_date`, `context_window`, costs, `cost_tier` (1–4), `tier`; local providers probed live for installed models |
| PUT  | `/models/providers/{name}` | configure a known provider (key stored via keyring) |
| POST | `/models/providers` | add a custom OpenAI-compatible provider `{name, base_url, api_key?, default_model?}` |
| POST | `/models/providers/{name}/test` | live connectivity probe → `{reachable, detail?}` |
| GET  | `/agents` | agent roster for the active project |
| GET  | `/mcp/catalog` | curated marketplace of known MCP servers |
| GET/POST | `/mcp/servers` | installed MCP servers (v0: persisted config; runtime client lands in a later phase) |
| PATCH/DELETE | `/mcp/servers/{id}` | enable/disable / remove an installed server |

`POST /conversations/{id}/messages` body: `{content, mode?: "discuss"|"plan"|"edit",
model?: "provider:model_id", effort?: "low"|"medium"|"high"}` — mode selects the
agent system prompt, model/effort override the routing for that turn.

SSE event types: `token`, `agent_status`, `decision`, `action_request`, `done`, `error`.

## 5. Tauri IPC commands (v0)

| Command | Purpose |
|---|---|
| `get_engine_endpoint` | `{ port, token }` once the sidecar is healthy |
| `engine_status` | running / starting / failed (+ last stderr lines) |
| `pick_directory` | native folder picker (project location) |
| `fs_scope_grant` | user grants a directory scope to the current project |
| `fs_read` / `fs_write` / `fs_list` | scoped, policy-checked file operations |

## 6. Repository layout

```
elysium/
├── frontend/     React + TS + Tailwind (Vite)
├── src-tauri/    Rust core
├── ai-engine/    Python engine (FastAPI), package name `elysium_engine`
├── database/     schema notes + Alembic lives in ai-engine
├── docs/         this documentation set
├── scripts/      dev/setup scripts
└── .github/      CI, templates
```

## 7. Non-negotiable rules

- The frontend never executes privileged actions itself.
- The engine never binds to non-loopback interfaces in desktop mode.
- Secrets go through the OS keychain (keyring) — never plaintext in DB or config.
- Every module addition updates this document and `docs/` accordingly.
