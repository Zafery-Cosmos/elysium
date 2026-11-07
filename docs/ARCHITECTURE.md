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

### ADR-006 — Live preview: a supervised dev server, never a command from the UI
Package `elysium_engine.preview` (Python). Projects had no folder; the user now links one
(native picker → `PUT /projects/{id}/preview`).
- **Detection** (`detect.py`) reads manifests/config only: Next, Nuxt, Astro, SvelteKit,
  Angular, Vue CLI, CRA, Vite (→ React / Vue / Svelte), plain HTML. It reports framework,
  package manager (lockfile / `packageManager`), script, real app root (one sub-folder level),
  missing `node_modules`. Unknown framework → explicit error + manual choice from a fixed list.
- **No command crosses the API.** `build_command` makes an argv list (no shell) from a fixed
  per-framework table + the project's own `package.json` script, pinning `127.0.0.1` and an
  OS-chosen free port. The child gets `mcp.client.safe_environment` (no Elysium token, no keys).
- **Trust.** Running a project's scripts is code execution: the first start of a Node project
  needs `trust: true` (stored per folder, reset if the folder changes). Plain HTML needs none.
- **Path safety** (`paths.py`): absolute, real path (symlinks/junctions resolved), existing
  folder, not a drive root / home / system folder / Elysium's data dir; sub-folders are
  re-resolved inside the root. The static server re-checks every request (real path inside
  the root, no dotfiles such as `.env`, no `node_modules`).
- **Readiness is observed, not assumed**: the URL is published only after `GET /` answers.
  States: `stopped, deps_missing, installing, starting, ready, compiling, compile_error,
  unreachable, stopping, failed`. Compile errors are read from the server output (secrets
  redacted). A crashed server is reported as `failed`; there is no automatic restart loop.
- **Hot update** is the framework's own (HMR / Fast Refresh); plain HTML gets a tiny live-reload
  poller injected by the loopback static server.
- **Lifecycle.** One session per project (no double start), several projects in parallel on
  distinct ports, whole process tree killed on stop (`taskkill /T` / process group), at engine
  exit, and when the desktop app disappears (`ELYSIUM_PARENT_PID` watchdog). State is stored
  in `preview_sessions` (migration 0009); at start `reconcile()` kills a recorded server only
  if its pid is alive **and** its port still answers, then clears the rows.
- **Isolation of the page.** The iframe (`sandbox`, `referrerPolicy=no-referrer`, white
  background) is on another origin (`127.0.0.1:<port>`) than the app and holds no token; the
  engine's CORS allow-list excludes it. The app's CSP allows only `frame-src http://127.0.0.1:*`.
  Residual risk: any local web page can reach other loopback ports; the engine itself still
  requires the bearer token.
- Designed for the future Expert "complet" mode: file edits made by agents are picked up by
  the same HMR / live-reload path; nothing in preview writes files.

### ADR-007 — Accounting, provider health and schema upgrades
- **Money** (`costing.py`): prices and CLI-reported costs are USD; EUR uses a stored, dated rate
  (`fx_rates`, append-only; built-in default is labelled `default`, never presented as live;
  the ECB fetch is an explicit user action). Each `usage` row keeps its `fx_rate` and `cost_eur`.
  A cost is `reported` | `estimated` | `none` — unknown is not zero. `billing` is `api` |
  `subscription` | `local`; only `api` spend counts against the EUR expert budgets.
  Cache tokens are stored separately and priced with documented factors (estimates).
  Writes are idempotent (`request_id`, unique index).
- **Health** (`providers/health.py`): states `not_installed, not_authenticated, authenticated,
  available, unavailable, auth_error, quota_exhausted, unknown`, derived from the CLI sign-in
  check (cached 60 s, 15 s timeout) and from call outcomes (auth / quota / outage with TTLs).
  Routing skips unusable providers; a replacement is emitted as a `provider_fallback` decision
  and a provider with no stand-in blocks only that task (`provider_unavailable`).
- **Quotas** (`providers/quota.py`): persisted in `quota_readings`; `assess()` returns
  `unknown | stale | exhausted | ok` (stale = old or its window has reset). API providers have no
  quota.
- **Analyse runs**: results are condensed by `summarize_result` (head + constraint/decision
  lines + tail, never "last 400 chars"); the context given to a task is bounded and puts direct
  dependencies first; a missing/blocked dependency blocks the task with a reason; an empty
  answer or an unexpected agent crash blocks that task only.
- **Schema upgrades** (`db/migrate.py`): `init_db` previously only ran `create_all`, so columns
  added in later versions never reached existing databases. `upgrade_schema` now adds missing
  tables/columns/indexes at every start (additive only, resumable). Alembic adopts a database
  created this way (`env.py`) and remains the path for PostgreSQL / non-additive changes.
- **CLI execution** (`providers/cli_common.py`): allow-listed environment (no tokens, no API
  keys), own process tree killed on timeout/cancel, stdout capped (16 MB), stderr bounded and
  redacted. **Folder scanning** (`importer.py`) uses the same path rules as the preview and
  never follows a symlink out of the project.

### ADR-008 — Project memory and token import
- **Memory** (`memory/`): `memory_items` (tier short|long, kind, pinned, `expires_at`, idempotent
  `source_ref`), `memory_folders`, `memory_files` (the graph). Short-term items expire after 14 days
  unless pinned or promoted. Task results are captured automatically (`remember_task_result`).
- **File graph** (`memory/filegraph.py`): static analysis only (no model call): `ast` for Python,
  patterns for JS/TS/Vue/Svelte/Astro, CSS, HTML, Markdown, Rust. A file with unchanged
  (size, mtime) is **not read again**; paths are re-checked with `preview.paths.is_inside` (no
  symlink leaving the project), dot-files / `node_modules` / lock files are skipped, caps at 3 000
  files and 200 KB per file. Imports are resolved to project files; a deleted file is removed from
  the graph and from its importers.
- **Agent context** (`memory/service.build_context`): bounded block (≈1 500 tokens for the PM,
  1 200 per task in analyse runs), items first (half the budget at most) then the file map ranked by
  how many files import each one. `GET /projects/{id}/memory/context` returns exactly that text.
- **Token import** (`providers/cli_token.py`): Claude `setup-token` token → OS keychain, handed to
  the `claude` child only (`env_for`); verified with one real call using an empty throw-away config
  folder (an existing session cannot vouch for a bad token). Codex `auth.json` → Elysium's private
  `CODEX_HOME` (0600), previous file restored if the CLI does not accept it. Signing out removes the
  stored token. Nothing returns or logs a token.

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
