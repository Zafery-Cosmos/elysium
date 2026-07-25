# Elysium

> **Project status: early development (v0.1 foundation).** APIs, schemas and
> UI are unstable and will change. Feedback and contributions are welcome —
> production use is not recommended yet.

**Elysium is an open source AI Development Environment.**

It is not a chatbot, and not only a code generator. Elysium is a collaborative
workspace where multiple specialized AI agents — project manager, architect,
frontend and backend developers, database engineer, DevOps, security auditor,
QA — work together to transform a human idea into functional software, while
the user keeps full control at every step.

> A chatbot answers. An assistant codes. **A team builds.**

## Features

- **A real agent team** — explicit roles, permissions, memory and debate,
  orchestrated by a Project Manager agent over a persisted task graph, not one
  prompt doing everything.
- **From sentence to software** — start with "I want an app to book
  restaurants"; Elysium asks adaptive questions, writes a specification,
  plans, develops and tests.
- **User in control, deny by default** — every privileged action goes through
  a Rust permission broker with scoped filesystem access, per-action approval
  and an audit log. Prompt injection cannot exceed granted capabilities.
- **Multi-model, no lock-in** — Anthropic, OpenAI, Google, Mistral, DeepSeek,
  OpenRouter, and fully local models (Ollama, LM Studio, any OpenAI-compatible
  server). Usable with zero external API key.
- **Privacy first** — runs 100% locally; SQLite by default, no mandatory
  telemetry; secrets live in the OS keychain.
- **Extensible** — agents, model providers, tools, MCP servers and plugins are
  pluggable. Elysium is a platform.

## Architecture

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

The Tauri (Rust) core is the single entry point: it spawns the Python engine
as a supervised sidecar bound to `127.0.0.1` with a random per-session bearer
token, and brokers every privileged operation (filesystem today; shell,
network and deploy later). See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
for the full picture and the ADRs.

## Quickstart

### Prerequisites

- **Node.js 20+** and **pnpm**
- **Rust** (stable, via [rustup](https://rustup.rs)) + the
  [Tauri v2 system dependencies](https://v2.tauri.app/start/prerequisites/)
- **Python 3.11+**

### Setup and run

```sh
git clone https://github.com/elysium-ide/elysium
cd elysium
scripts/setup.sh            # frontend deps + engine virtualenv

# Full desktop app (recommended): spawns and supervises its own engine
pnpm --dir frontend tauri dev

# Or: engine + frontend in a plain browser (UI/API iteration)
scripts/dev.sh
```

## Project structure

```
elysium/
├── frontend/     React + TypeScript + Tailwind (Vite)
├── src-tauri/    Rust core: windows, permission broker, sidecar lifecycle
├── ai-engine/    Python engine (FastAPI), package `elysium_engine`
├── database/     schema notes (SQLAlchemy models + Alembic live in ai-engine)
├── docs/         vision, architecture, development rules
├── scripts/      setup.sh, dev.sh
└── .github/      CI and issue/PR templates
```

## Documentation

| Document | Contents |
|---|---|
| [`docs/VISION.md`](docs/VISION.md) | What Elysium is, core principles, positioning |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Layers, process model, ADRs, API and IPC contracts |
| [`docs/DEVELOPMENT_RULES.md`](docs/DEVELOPMENT_RULES.md) | Binding rules for every contributor, human or AI |
| [`docs/PRODUCT_SPEC.md`](docs/PRODUCT_SPEC.md) | Personas, UI modes, core user flow, V1 features and non-goals |
| [`docs/AI_SYSTEM.md`](docs/AI_SYSTEM.md) | Agent roster, adaptive questioning, orchestration, model routing, memory |
| [`docs/SECURITY.md`](docs/SECURITY.md) | Threat model, permission levels, human-in-the-loop matrix, sandboxing |
| [`docs/UI_UX.md`](docs/UI_UX.md) | Design system, components, accessibility, Simple/Advanced/Team modes |
| [`docs/DATABASE.md`](docs/DATABASE.md) | Data model, SQLite/PostgreSQL strategy, migrations, vector memory |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Phases v0.1 → v2.0 → Cloud, milestones and exit criteria |

## Contributing

Contributions are welcome — see [`CONTRIBUTING.md`](CONTRIBUTING.md). Please
read `docs/VISION.md` and `docs/ARCHITECTURE.md` first;
`docs/DEVELOPMENT_RULES.md` is binding for every pull request. Security
issues: see [`SECURITY.md`](SECURITY.md).

## Roadmap (summary)

- **v0.1 — Foundation (current):** desktop shell, supervised engine sidecar,
  permission broker + audit log, project/conversation storage, single
  assistant conversation with streaming.
- **v0.2 — Providers & memory:** multi-provider routing (Anthropic, OpenAI,
  OpenAI-compatible/local), keychain-backed secrets, project memory with
  vector search.
- **v0.3 — The team:** Project Manager orchestration over an explicit task
  graph, role agents, requirements elicitation → specification, human
  approval flows.
- **Later:** tool/MCP plugin system, QA & security agents, deploy to your own
  NAS/VPS, team/cloud mode on PostgreSQL.

## License

Apache License 2.0 — see [`LICENSE`](LICENSE).
Copyright 2026 Elysium Contributors.
