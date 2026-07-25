# Pull request

## What does this change?

Short summary of the change and the motivation. Link related issues
(`Closes #123`).

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Refactor / internal
- [ ] Documentation
- [ ] CI / tooling

## Checklist

- [ ] I read `docs/DEVELOPMENT_RULES.md` and `docs/ARCHITECTURE.md`
- [ ] Security-relevant paths still go through the Rust permission broker
  (deny by default; no check removed "to make something work")
- [ ] No secrets in code, config, logs or test fixtures
- [ ] Tests added/updated for critical logic
- [ ] `pnpm build` + `pnpm lint` pass (frontend), `pytest` passes (ai-engine),
  `cargo clippy -- -D warnings` + `cargo test` pass (src-tauri) — as applicable
- [ ] Docs updated (`ARCHITECTURE.md` for structure, `SECURITY.md` for
  threat-relevant changes, ADR added for significant decisions)

## How was this tested?

Describe manual and automated testing.
