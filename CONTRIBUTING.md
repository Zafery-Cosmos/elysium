# Contributing to Elysium

Thanks for considering a contribution! Elysium is in early development
(v0.1 foundation), which means there is a lot of surface to help with — and
also that structure and rules matter more than usual.

## Before you start

Read, in this order:

1. [`docs/VISION.md`](docs/VISION.md) — what we are building and for whom.
2. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — layers, process model and
   the ADRs. If your change conflicts with an ADR, open an issue first.
3. [`docs/DEVELOPMENT_RULES.md`](docs/DEVELOPMENT_RULES.md) — **binding** for
   every contributor, human or AI agent.

## Getting a dev environment

Prerequisites: Node 20+, pnpm, Rust (stable, rustup), Python 3.11+ and the
[Tauri v2 system dependencies](https://v2.tauri.app/start/prerequisites/).

```sh
git clone https://github.com/elysium-ide/elysium
cd elysium
scripts/setup.sh                 # frontend deps + engine virtualenv

pnpm --dir frontend tauri dev    # full desktop app
scripts/dev.sh                   # or: engine + frontend in a browser
```

## Where things live

- `frontend/` — React + TypeScript + Tailwind. UI only; never performs
  privileged actions itself.
- `src-tauri/` — Rust core: window lifecycle, engine sidecar supervision
  (`src/engine/`), the permission broker and audit log (`src/security/`),
  IPC commands (`src/commands/`).
- `ai-engine/` — Python FastAPI engine (`elysium_engine`): agents, model
  providers, memory, storage (SQLAlchemy + Alembic).
- `docs/` — the documentation set; structural changes must update
  `ARCHITECTURE.md`.

## Making a change

1. Open or find an issue describing the problem/feature.
2. Fork and branch from `main`: `feat/<topic>`, `fix/<topic>` or
   `docs/<topic>`.
3. Keep pull requests small and focused; one logical change per PR.
4. Follow the code standards in `docs/DEVELOPMENT_RULES.md` — highlights:
   - TypeScript strict mode; Python fully type-hinted; no `unwrap()` on
     fallible Rust paths in production code.
   - Deny by default: privileged actions go through the Rust permission
     broker; never remove a security check to make something work.
   - No new dependency without justification in the PR description.
   - Critical logic ships with tests.
5. Make the quality gates pass locally:

   ```sh
   pnpm --dir frontend build && pnpm --dir frontend lint
   (cd ai-engine && pytest)
   (cd src-tauri && cargo clippy --all-targets -- -D warnings && cargo test && cargo fmt --check)
   ```

6. Update the docs your change touches (`ARCHITECTURE.md` for structure,
   `docs/SECURITY.md` for threat-relevant changes; record significant
   decisions as ADRs).
7. Open the PR using the template. CI runs the same three gates.

## Commit style

Short imperative subject lines ("add scope check for fs_list"), body when the
*why* is not obvious. Reference issues (`Fixes #42`).

## Reporting security issues

Do **not** open a public issue — see [`SECURITY.md`](SECURITY.md).

## Questions

Open a GitHub Discussion or an issue with the `question` label.
