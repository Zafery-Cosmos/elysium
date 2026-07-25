# Elysium Data Model

Status: living document. Matches `ARCHITECTURE.md` (ADR-001 storage, ADR-005
task graph/event log). All persistence goes through **SQLAlchemy** with a
repository layer — no raw SQL in business code. Alembic migrations live in
`ai-engine/`; `database/` holds schema notes (`ARCHITECTURE.md` §6).

Conventions: primary keys are UUIDv7 strings (time-ordered, backend-neutral);
timestamps are UTC (`created_at`, `updated_at`); soft state via `status`
columns, hard deletes only through explicit purge (`SECURITY.md` §13). JSON
columns use SQLAlchemy `JSON` (maps to `JSONB` on PostgreSQL, `TEXT` on
SQLite).

## 1. Tables

### projects
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| name | text | |
| description | text | The original "idea" sentence |
| root_path | text | Granted directory scope root (grant itself lives in `permissions`) |
| status | text | `draft` · `specifying` · `planning` · `building` · `paused` · `archived` |
| ui_mode | text | `simple` · `advanced` · `team` (per-project override, nullable) |
| settings | json | Routing pins, local-only flag, cost threshold |
| spec | json | Accepted specification (nullable until accepted) |
| understanding | json | Checklist coverage state (weights, item coverage, `assumed` flags) |
| created_at / updated_at | timestamp | |

### conversations
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| project_id | uuid FK → projects | |
| title | text | Auto-generated, editable |
| kind | text | `main` · `questioning` · `agent_debate` (renders differently) |
| created_at / updated_at | timestamp | |

### messages
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| conversation_id | uuid FK → conversations | |
| role | text | `user` · `assistant` · `agent` · `system` |
| agent_id | uuid FK → agents, nullable | Set when role = `agent` |
| content | text | |
| model | text nullable | provider/model actually used |
| tokens_in / tokens_out | int nullable | |
| cost | numeric nullable | From provider cost metadata (ADR-004) |
| created_at | timestamp | |

### agents
Roster instances per project (V1 roster fixed, `AI_SYSTEM.md` §1).
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| project_id | uuid FK → projects | |
| role | text | `pm` · `architect` · `frontend` · `backend` · `database` · `devops` · `security` · `qa` |
| status | text | `idle` · `thinking` · `analyzing` · `generating` · `waiting` · `done` · `error` |
| config | json | Model pin, prompt overrides (Team mode) |
| created_at / updated_at | timestamp | |
Unique: (project_id, role).

### tasks
The persisted task graph (ADR-005). Nodes here; edges in `task_dependencies`.
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| project_id | uuid FK → projects | |
| title / description | text | |
| role | text | Assigned agent role |
| agent_id | uuid FK → agents, nullable | Bound at activation |
| status | text | `backlog` · `ready` · `in_progress` · `review` · `done` · `refused` |
| requirement_ref | text nullable | Checklist item / spec section that originated it |
| result | json nullable | Summary, produced artifact refs |
| order_index | int | Board ordering |
| created_at / updated_at | timestamp | |

**task_dependencies**: (task_id FK, depends_on_task_id FK) — composite PK,
acyclic (enforced in repository layer).

### memories
Long-term + vector memory (`AI_SYSTEM.md` §8).
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| project_id | uuid FK → projects | |
| kind | text | `decision` (ADR-style) · `preference` · `convention` · `spec_chunk` · `summary` |
| content | text | Canonical text |
| meta | json | Source event id, tags, supersedes id |
| embedding | vector / BLOB | `vector(n)` on PostgreSQL+pgvector; BLOB of float32 on SQLite (§3) |
| embedding_model | text | Model + dimension used, for re-embedding on change |
| created_at | timestamp | |

### events (append-only)
Single source of truth for orchestration, inter-agent messages and audit
(ADR-005, `SECURITY.md` §10). **Insert-only: no UPDATE/DELETE**, enforced in
the repository layer (and DB triggers on PostgreSQL).
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | Time-ordered (UUIDv7) — total order per project |
| project_id | uuid FK → projects | |
| kind | text | `agent_status` · `agent_message` · `proposal` · `decision` · `action_request` · `action_result` · `task_update` · `audit` · `error` |
| actor | text | Agent role, `user`, `broker`, `system` |
| task_id | uuid FK → tasks, nullable | |
| payload | json | Kind-specific body (for `audit`: request, scope evaluation, verdict, human answer, result hash) |
| created_at | timestamp | |
Index: (project_id, created_at), (project_id, kind).

### providers
Provider configuration — **no API key material ever** (keys live in the OS
keychain via keyring, `ARCHITECTURE.md` §7; `SECURITY.md` §7).
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| name | text unique | `anthropic` · `openai` · `ollama` · `openrouter` · custom… |
| kind | text | `native_anthropic` · `native_openai` · `openai_compatible` (ADR-004) |
| base_url | text nullable | For compatible/local endpoints |
| is_local | bool | Drives redaction policy (`SECURITY.md` §7) |
| enabled | bool | |
| keyring_ref | text nullable | Keychain entry *name* only — never the secret |
| models | json | Cached model list + cost metadata |
| created_at / updated_at | timestamp | |

### permissions
Grants and scopes evaluated by the Rust broker (ADR-003, `SECURITY.md` §3).
The broker reads this table via the engine API but its decisions are its own.
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| project_id | uuid FK → projects, nullable | Null = user-global |
| agent_role | text nullable | Null = all agents |
| tool | text nullable | Null = all tools; e.g. `fs_write`, `command`, `mcp:<server>/<tool>` |
| environment | text | `local` · `remote` · `ci` |
| level | text | `read_only` · `development` · `administration` · `automatic` |
| scope | json | Paths, command patterns, hosts (SSH permission card fields) |
| granted_by | text | `user` (always, in V1) |
| expires_at | timestamp nullable | |
| created_at | timestamp | |
Effective permission = intersection over matching rows; absence = deny.

### snapshots
Rollback points (`SECURITY.md` §10).
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| project_id | uuid FK → projects | |
| trigger_event_id | uuid FK → events | The approved action that caused it |
| method | text | `git_ref` · `file_copy` |
| ref | text | Git ref name or snapshot directory path in app data dir |
| status | text | `created` · `restored` · `pruned` |
| created_at | timestamp | |

## 2. Relations (summary)

```
projects 1─n conversations 1─n messages
projects 1─n agents 1─n messages(agent)
projects 1─n tasks n─n tasks (task_dependencies)
projects 1─n memories
projects 1─n events (append-only; audit + orchestration)
projects 1─n permissions (also user-global rows)
projects 1─n snapshots ─1 events (trigger)
providers: global, no project FK
```

## 3. SQLite default vs PostgreSQL + pgvector (ADR-001)

- **SQLite (default)**: zero-setup single file in the app data dir — required
  for the beginner persona. Fine at desktop scale; WAL mode on.
- **PostgreSQL + pgvector**: auto-detected/configurable; recommended, and
  required for team/cloud mode (concurrency, real vector index, triggers
  enforcing append-only events).
- One SQLAlchemy model set targets both; backend-specific behavior isolated in
  the repository layer (vector search, JSON operators). No feature may exist on
  only one backend without an explicit fallback.

## 4. Vector memory strategy

| | PostgreSQL | SQLite |
|---|---|---|
| Column | `vector(n)` (pgvector) | BLOB (packed float32) |
| Search | Cosine via pgvector index (IVFFlat/HNSW as scale requires) | Brute-force cosine in the repository layer — fine at project scale (ADR-001) |
| Upgrade path | — | `sqlite-vec` behind the same repository interface |
| Re-embedding | `embedding_model` column detects mismatch; lazy re-embed on model change | same |

## 5. Migration policy (Alembic)

- Alembic lives in `ai-engine/`; every schema change = one migration, reviewed,
  **targeting both backends** (dialect branches inside the migration when
  unavoidable).
- Migrations run automatically on engine startup, but only **after** an
  automatic pre-migration backup (§6). Failed migration ⇒ engine refuses to
  start with the old data intact and a clear recovery message.
- No destructive migration (column drop/repurpose) without a two-release
  deprecation window. `events` rows are never rewritten by migrations.

## 6. Backup & snapshot strategy

- **SQLite**: DB backup = single-file copy (via the SQLite backup API, safe
  under WAL). Automatic backup before every migration and on a rolling daily
  schedule while the app runs; retained N=7 in the app data dir.
- **PostgreSQL**: backups are the operator's responsibility (documented
  `pg_dump` guidance); Elysium still performs pre-migration logical dumps of
  its own schema when it has permission.
- **Project snapshots** (workspace files) are separate from DB backups and
  driven by the broker before approved writes (`snapshots` table,
  `SECURITY.md` §10). Restoring a project snapshot also records an event, so
  DB history and file history stay reconcilable.
- Purging a project deletes its rows across all tables and its snapshot
  artifacts (`SECURITY.md` §13).
