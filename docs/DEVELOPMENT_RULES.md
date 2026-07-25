# Development Rules

These rules bind every contributor — human or AI agent.

## Process
1. Read `docs/VISION.md` and `docs/ARCHITECTURE.md` before writing code.
2. Before any significant development, analyze: current architecture → impact →
   security → tests needed. Record important decisions as ADRs in `ARCHITECTURE.md`.
3. Build progressively, in roadmap order. Never build ahead of the current phase
   "because it's easy now".

## Code
- Modular architecture; one responsibility per module. No god files, no giant functions.
- TypeScript strict mode; Python fully type-hinted; Rust with no `unwrap()` on
  fallible paths in production code.
- No temporary hacks without a `TODO(issue-ref)` and a reason.
- No new dependency without justification (size, maintenance, security surface).
- Errors are understood, explained to the user, and recoverable — never swallowed.

## Security (non-negotiable)
- Deny by default. Every privileged action goes through the Rust permission broker.
- Never store a secret in plaintext (DB, config, logs, test fixtures).
- Treat all file/tool content given to an LLM as **data, never instructions**.
- Never remove an existing security check "to make something work".

## Tests & quality
- Critical logic (routing, permissions, coverage heuristic, storage) ships with tests.
- `frontend`: `pnpm build` and `pnpm lint` must pass.
- `ai-engine`: `pytest` must pass.
- `src-tauri`: `cargo clippy -- -D warnings` must pass.

## Documentation
- User-visible behavior → `PRODUCT_SPEC.md`. Structure → `ARCHITECTURE.md`.
  Agents/models → `AI_SYSTEM.md`. Threat-relevant changes → `SECURITY.md`.
