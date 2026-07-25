# Elysium Roadmap

Status: living document. Phases are strictly ordered: never build ahead of the
current phase (`DEVELOPMENT_RULES.md` §Process). Each phase ships only when its
exit criteria pass.

## Phases

### v0.1 — Foundation  `IN PROGRESS`
The skeleton, end to end, with real plumbing and no AI cleverness.
- Tauri shell (Rust core): window, session token, sidecar spawn/supervision,
  `get_engine_endpoint` / `engine_status` IPC (`ARCHITECTURE.md` §2, §5).
- React + TS + Tailwind UI: Dashboard, Projects, Project view shell, Settings;
  dark design system tokens (`UI_UX.md`); French UI strings via i18n catalog.
- Python engine (FastAPI, loopback + bearer token) with **one provider**
  (native Anthropic adapter behind the `ModelProvider` interface, ADR-004).
- Projects + conversations + messages over SQLite (SQLAlchemy + repository
  layer + Alembic baseline, ADR-001). SSE streaming chat.

### v0.2 — Safe hands
The permission broker becomes real before any agent gets tools.
- Rust permission broker wired **end-to-end**: capability request path from
  engine → broker → policy check → (human) → execute → audit event (ADR-003).
- File tools: `fs_scope_grant`, scoped `fs_read` / `fs_write` / `fs_list`.
- Diff approval UI (accept / edit / refuse per hunk) gating every write.
- `permissions`, `events` (audit kind) and `snapshots` tables live; snapshot
  before approved writes; one-click rollback.

### v0.5 — First intelligence
The team exists and the core flow works.
- Full 8-agent roster with default permission profiles (`AI_SYSTEM.md` §1).
- Persisted task graph + append-only event log orchestration (ADR-005);
  task board UI.
- Memory system: long-term memories + vector recall (SQLite BLOB brute-force
  path first, ADR-001).
- Adaptive questioning with the requirements checklist, understanding %
  coverage heuristic, and **spec generation → accept/edit/refuse**.
- Debate/decision protocol with ADR-style decision memories.
- Process-level sandbox for QA test runs (`SECURITY.md` §6).

### v1.0 — Elysium Desktop
The product described in `PRODUCT_SPEC.md`, shippable.
- Multi-model routing: native OpenAI + generic OpenAI-compatible adapters
  (Ollama, LM Studio, OpenRouter, DeepSeek, Mistral, vLLM…), tier routing,
  fallback chains, cost estimation, multi-model comparison (ADR-004,
  `AI_SYSTEM.md` §6). Zero-external-key local mode.
- Git integration (status/diff/commit via broker) and supervised terminal with
  command analysis + approval queue (`SECURITY.md` §5).
- MCP client + vetting flow (`AI_SYSTEM.md` §9, `SECURITY.md` §11).
- Docker sandbox for test/build execution; secret redaction before cloud send.
- PostgreSQL + pgvector as first-class configurable backend.
- Cross-platform installers (Windows / macOS / Linux) with PyInstaller sidecar
  packaging (ADR-002); Simple/Advanced/Team modes complete; accessibility pass
  (`UI_UX.md` §5).

### v2.0 — Platform
Elysium as an extensible platform (`VISION.md` principle 6).
- Plugin & agent marketplace with the vetting pipeline built in v1.0 as a
  prerequisite (`SECURITY.md` §11); custom agent definitions.
- Remote deploy to user-owned NAS/VPS: SSH keys-only, per-server permission
  cards (`SECURITY.md` §9).
- Team spaces: multi-user collaboration, real authentication, TLS, PostgreSQL
  required (`SECURITY.md` §8).

### Future — Cloud / SaaS
Optional hosted Elysium (managed engine + Postgres, team billing) for users who
don't want to self-host. Strictly optional: the desktop app remains fully
functional standalone and local-only (`VISION.md` principle 5). No dates
committed.

## Milestones & exit criteria

| Phase | Exit criteria (all must pass) |
|---|---|
| **v0.1** | App installs and opens on dev machines (3 OS); sidecar spawns, `/health` handshake works; create project → chat with streaming responses; data persists in SQLite across restarts; `pnpm build`+`lint`, `pytest`, `cargo clippy -D warnings` green in CI |
| **v0.2** | Zero privileged paths bypassing the broker (code-reviewed invariant + tests); write outside granted scope is denied and audited; every write appears as a diff and only lands on accept; rollback restores pre-action state byte-identical; `rm -rf`-class commands blocked in tests |
| **v0.5** | "Restaurant booking" scenario: idea → questions → spec accepted → task graph generated → agents produce reviewable diffs, end to end; understanding % reproducible from checklist state; kill -9 the engine mid-run → resume from graph + event log with no lost/duplicated approved work |
| **v1.0** | Full flow with zero external API keys on a local model; provider outage triggers fallback chain with visible event; secret planted in `.env` never appears in any cloud-bound payload (automated test); installers signed and tested on Win/macOS/Linux; WCAG AA contrast + keyboard nav audit passed; French + English catalogs complete |
| **v2.0** | Third-party plugin installable and revocable without app restart; deploy of a sample project to a clean VPS via permission card; two users collaborating on one project on Postgres |

## License & business model

- **Open core.** The desktop application (this repository) is and remains
  **Apache-2.0**: the full V1 feature set, all providers, local mode, the
  broker — no crippleware, no telemetry requirement.
- Paid layers come **later and around** the open product, never inside its
  core: hosted Cloud/SaaS (managed infra, team billing), and enterprise
  add-ons (SSO, centralized policy/audit for team spaces).
- Contributor expectations: CLA-free (Apache-2.0 inbound = outbound);
  trademark "Elysium" name/logo usage policy documented separately before
  v1.0.
- Rationale: monetize operations and organizational features (v2.0+ surface),
  not the individual developer's tool — consistent with "open source, built to
  last" (`VISION.md` principle 7).
