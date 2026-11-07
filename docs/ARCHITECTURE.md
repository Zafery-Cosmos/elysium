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

#### ADR-004 addendum — CLI-backed providers (`claude-code`, `codex`)
Besides API-key providers, the engine can chat through the user's **own vendor
CLI**, signed in with their **personal account** (Claude subscription / ChatGPT).
`kind: "cli"` providers run `claude -p` / `codex exec --json` as a subprocess and
normalize the output to the same chunks as every other adapter.
- Elysium never reads, stores or forwards OAuth tokens: the CLI owns its login
  (`POST /models/providers/{name}/login` just launches `claude auth login` /
  `codex login`, which open the system browser). Nothing goes in the keychain.
- **Elysium is a separate instance from the user's own Claude Code / Codex.**
  Every CLI child process runs with `CLAUDE_CONFIG_DIR` / `CODEX_HOME` pointing at
  `<data dir>/cli/{claude,codex}`, so its login lives in a folder private to
  Elysium. It never reuses, replaces or signs out the session of the user's
  terminal (and vice versa). A fresh install therefore always asks to sign in.
  If an Elysium session already exists, `login` reports whose account it is
  (`already_signed_in` + `account`) instead of silently continuing; `force: true`
  signs it out first to switch account. `POST .../logout` signs the Elysium
  session out.
- **Chat-only by construction** (ADR-003 stays intact): Claude runs with
  `--tools ""`, no user settings, no MCP; Codex runs `-s read-only --ephemeral`.
  Both run in an empty sandbox directory, so neither sees the user's files.
  Tool definitions passed by agents are ignored for these providers.
- "Configured" = CLI binary found; "reachable" (`/test`) = installed **and**
  signed in. Costs are `0` (covered by the user's plan); `cost_usd` from the CLI
  is forwarded on the `done` chunk for the usage dashboard only.
- Env vars `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` are stripped from the child so
  the subscription login is always the one used.

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
| GET  | `/projects/{id}/tasks` | task-graph nodes (Kanban board), ordered by `status` then `order_index` |
| POST | `/projects/{id}/tasks` | create a task `{title, description?, agent_role, status?, depends_on?}` (`agent_role` validated against the project roster; `depends_on` ids must exist in the project) |
| PATCH | `/tasks/{id}` | partial update `{title?, description?, agent_role?, status?, order_index?, result_summary?, depends_on?}` — a drag-and-drop card move sends `status`/`order_index` |
| DELETE | `/tasks/{id}` | delete a task |
| GET  | `/models` | providers + models with `release_date`, `context_window`, costs, `cost_tier` (1–4), `tier`; local providers probed live for installed models |
| PUT  | `/models/providers/{name}` | configure a known provider (key stored via keyring) |
| POST | `/models/providers` | add a custom OpenAI-compatible provider `{name, base_url, api_key?, default_model?}` |
| POST | `/models/providers/{name}/test` | live connectivity probe → `{reachable, detail?}` (CLI providers: installed **and** signed in) |
| POST | `/models/providers/{name}/login` | CLI providers only (`claude-code`, `codex`): save the provider, start the vendor CLI's sign-in (browser opens by itself) → `{state, reachable, detail?, auth_url?, device_code?, accepts_input}`. Body `{mode?: "browser"\|"device"}` (`device` = Codex link + one-time code for another device) |
| GET | `/models/providers/{name}/login` | poll the sign-in: `state` = `pending` \| `signed_in` \| `failed` \| `not_installed` |
| POST | `/models/providers/{name}/login/code` | finish a pending sign-in with `{code}`: the vendor code, or the redirect address (`http://127.0.0.1:<port>/…?code=…&state=…`) from a browser on another machine. Loopback addresses are only replayed if their `state` matches this very sign-in |
| DELETE | `/models/providers/{name}/login` | cancel the pending sign-in |
| POST | `/models/providers/{name}/logout` | sign Elysium's own CLI session out → `{state: "signed_out"}` (does not touch the user's terminal session) |
| GET  | `/admin/overview?days=30` | admin dashboard in one call: AI connections (CLI sign-in state), plan quotas (Claude 5 h / 7 d windows), usage totals + by provider / model / agent / day, latest errors, latest agent action requests, engine version + uptime. Usage comes from the `usage` table (one row per model call, written by `AgentRuntime` and the orchestrator; no foreign keys so history outlives deleted conversations) |
| GET  | `/agents` | agent roster for the active project (each with `enabled`, `custom`, permission profile) |
| POST | `/agents` | create a custom agent `{name, role, system_prompt, model_ref?, filesystem?, shell?, network?}` (name slugified + unique per project) → `custom:true` |
| PATCH | `/agents/{role}` | enable/disable + adjust policy `{enabled?, filesystem?, shell?, network?}` (role = built-in role or custom name slug) |
| PATCH | `/agents/{role}/permissions` | retained: adjust permission profile `{filesystem?, shell?, network?, allowed_tools?}` |
| DELETE | `/agents/{role}` | delete a **custom** agent (422 for built-ins — disable them instead) |
| GET  | `/mcp/catalog` | curated marketplace of known MCP servers, each with a `config_schema` (fields `{key,label,type: string\|secret\|number,required}`) |
| GET/POST | `/mcp/servers` | installed MCP servers with `config` (non-secret) + `config_schema` |
| POST | `/mcp/servers/{id}/test` | **really start** the server (command from `url_or_command`, `<placeholders>` and env from the saved config, secrets from the keyring, minimal inherited environment), run the MCP handshake over stdio and list its tools → `{ok, tools[], server_name, server_version, error?, duration_ms}`. Missing runtimes (Node `npx`, `uvx`, Docker) and missing config fields are reported with an actionable message. Letting agents *call* MCP tools is not enabled yet: it must go through the permission broker (ADR-003) |
| DELETE | `/conversations/{id}/plan` | refuse a proposed plan: remove its tasks that nobody has started (`todo`); started and hand-made tasks are kept → `{deleted}`. A new plan in the same conversation REPLACES the previous unstarted one (no duplicates) |
| PATCH/DELETE | `/mcp/servers/{id}` | update `{enabled?, name?, url_or_command?, config?}` / remove; `type:"secret"` config fields go to the keyring (keyed by `mcp:{id}:{field}`), never the DB |

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

- **Every setting has a real effect.** A setting is added together with the
  feature it controls, never before. The frontend sends the engine only the
  settings the engine reads (nested `PATCH /settings` document, mapping in
  `frontend/src/stores/settings.ts`); a rejected change is shown to the user,
  never swallowed. Currently engine-backed: `ai.*` (default model/effort,
  routing, streaming, tokens, timeout, retries), `prompt_caching.*`,
  `general.ai_response_language`, `developer.log_level`,
  `privacy.redact_secrets_before_send`, `privacy.local_only`. Not yet backed
  (so not in the UI): memory/context, agent debates/parallelism/snapshots,
  human-approval scope, cost guard, multi-model compare, automatic fallback,
  encryption, telemetry, raw events, live cost, devtools.

- The frontend never executes privileged actions itself.
- The engine never binds to non-loopback interfaces in desktop mode.
- Secrets go through the OS keychain (keyring) — never plaintext in DB or config.
- Every module addition updates this document and `docs/` accordingly.
