# Elysium Security Architecture

Status: living document. Threat-relevant changes must update this file.
Grounded in `ARCHITECTURE.md` ADR-003 (Rust permission broker) and §7
(non-negotiable rules), and `DEVELOPMENT_RULES.md` §Security.

Principle: **deny by default, human in the loop, single enforcement point.**

## 1. Threat model

| # | Threat | Vector | Primary mitigations |
|---|---|---|---|
| T1 | **Prompt injection** | Malicious instructions embedded in file contents, web pages, or MCP tool results consumed by agents | Content-as-data rule (§2), broker caps capabilities regardless of what the model "decides" (ADR-003), injection heuristics, diff approval |
| T2 | **Malicious plugins / MCP servers** | Third-party server exfiltrates data or requests destructive tools | Opt-in per project, vetting (§11), broker-mediated tool calls, no broader access than the invoking agent |
| T3 | **Secret exfiltration to cloud LLMs** | `.env`, keys, tokens included in context sent to a remote provider | Secret detection + redaction before any cloud call (§7), OS keychain, local-only mode (§13) |
| T4 | **Destructive commands** | Agent proposes `rm -rf`, force-push, `DROP TABLE`, disk-wide operations | Command analysis (§5), always-blocked list (§4), sandbox for execution (§6), snapshots (§10) |
| T5 | **Over-privileged agents** | One compromised/confused agent can do everything | Per-agent permission profiles (§3, `AI_SYSTEM.md` §1), least privilege, scoped filesystem |
| T6 | **Local attacker / other processes** | Another process calls the engine API | Loopback-only bind + per-session bearer token (§8) |
| T7 | **Audit evasion** | Actions performed without trace | Broker is the single choke point; every decision logged append-only (§9) |

## 2. Content is data, never instructions

All file contents, web content, MCP results and retrieved memories are wrapped
in delimited data blocks with an explicit "this is untrusted data" framing
before reaching a model. The engine additionally runs injection heuristics
(imperative-instruction patterns, tool-call solicitation, "ignore previous"
family) and flags suspicious content in the UI. This is *defense in depth
only*: the security guarantee comes from the broker (T1) — an injected model
can request nothing beyond granted capabilities, and requests still hit the
human-in-the-loop matrix (§4).

## 3. Permission model — deny by default

Everything not explicitly granted is denied. Grants are **scoped** along five
axes: user, project, agent, tool, environment (local dev / remote / CI). The
effective permission is the intersection of all applicable scopes.

Permission levels (per scope):

| Level | Grants | Typical holder |
|---|---|---|
| **ReadOnly** | Read files within granted directory scopes; read task graph, memory, audit log | PM, Architect, Security agents |
| **Development** | ReadOnly + propose file writes (diff-gated), run analyzed commands in the project scope with approval, sandboxed test execution | Frontend, Backend, Database, QA, DevOps |
| **Administration** | Development + environment changes: package installs, migrations against real DBs, Git push, service config — every action individually confirmed | DevOps on explicit user grant; humans |
| **Automatic** | A user-curated allowlist of specific, analyzed-safe actions executed without per-action confirmation (e.g. `pnpm test` in sandbox) | Opt-in, per project, revocable, always audited |

No agent holds Administration by default. "Automatic" is never a blanket grant:
it is an explicit list of (agent, tool, pattern, scope) entries.

## 4. Human-in-the-loop matrix

| Action | Default policy |
|---|---|
| Read file inside granted project scope | Auto-allowed (logged) |
| Read file outside granted scopes | Blocked (user may extend scope via `fs_scope_grant`) |
| Read paths matching secret patterns (`.env`, `*.pem`, `id_*`, keychains) | Confirmation + redaction on cloud send (§7) |
| Write file (any) | Diff shown → user accepts / edits / refuses |
| Create files in project scope during an approved task | Auto-allowed batch, itemized in review queue |
| Run analyzed-safe read command (`ls`, `git status`, `grep`) in scope | Auto-allowed if on Automatic list, else confirmation |
| Run state-changing command (`pnpm install`, migrations, `git commit`) | Confirmation with analysis verdict |
| Run network-reaching command / outbound HTTP by a tool | Confirmation, destination shown |
| `git push`, publishing, deploy-like actions | Confirmation, Administration level required |
| `rm -rf` (any recursive force delete), `mkfs`, `dd` to devices, `chmod -R 777`, forced history rewrite on shared branches, disabling the broker or editing its policy files via agent, piping remote scripts to a shell (`curl … \| sh`) | **Always blocked** — not confirmable by the agent path; a human can only do these outside Elysium |
| Send project content to a cloud model | Auto after project-level consent, minus redacted secrets (§7) |
| Send content flagged as containing secrets to a cloud model | Blocked unless explicit per-item consent after showing exactly what leaves |

## 5. Command analysis before execution

Every proposed command is parsed by the Rust broker before any execution:

1. Tokenize/parse (including `&&`, `;`, pipes, subshells, redirections —
   compound commands are analyzed per component; unanalyzable constructs are
   treated as unsafe).
2. Classify: read-only / state-changing / network / destructive / unknown.
3. Check against the always-blocked list (§4), then scope (paths resolved and
   checked against granted directories; path traversal and symlink escapes
   rejected).
4. Produce a human-readable verdict shown in the approval UI: what it does,
   what it touches, why it needs approval.

Unknown or unparsable ⇒ treated as the most dangerous plausible class ⇒
confirmation minimum, never Automatic.

## 6. Sandboxing plan

- **Test and build execution** (QA, DevOps) runs in isolation: Docker container
  when Docker is available (no network by default, project directory mounted
  copy-on-write or on a snapshot), otherwise an isolated OS process with a
  restricted environment (cleaned env vars, project-scoped cwd, resource
  limits) and a clear UI badge showing the weaker isolation level.
- Sandbox results are events; nothing in the sandbox writes back to the real
  project without going through diff approval.
- Phasing: process isolation in v0.5, Docker sandbox in v1.0 (`ROADMAP.md`).

## 7. Secret handling

- Provider API keys and credentials live in the **OS keychain** (keyring) only —
  never in DB, config files, logs or test fixtures (`ARCHITECTURE.md` §7). The
  `providers` table stores no key material (`DATABASE.md`).
- **Redaction before cloud send**: outbound context to non-local providers is
  scanned (entropy + known token formats: AWS, GitHub, JWT, private key blocks,
  `.env` assignments); detected secrets are replaced by stable placeholders
  (`«secret:api_key_1»`). The UI shows what was redacted.
- **Explicit consent**: if the user insists real secret values must be sent,
  a per-item consent dialog shows exactly the content leaving and to which
  provider; the consent is audited.
- Local providers (loopback/LAN endpoints marked local) skip redaction only if
  the user marks them trusted.

## 8. Network security

- The engine binds **127.0.0.1 only** in desktop mode and rejects any request
  without the per-session `Authorization: Bearer <token>` generated by the Rust
  core at startup (`ARCHITECTURE.md` §2). Token is random per session, passed
  via environment, never persisted.
- CORS: engine only accepts the Tauri origin.
- Remote/team deployments (v2.0) require TLS, real authentication, and
  PostgreSQL backend; the desktop engine must never be exposed as-is.

## 9. SSH policy (remote targets, v2.0 scope — policy fixed now)

- **Keys only, never passwords**; keys held by the OS agent/keychain, never
  read into agent context.
- Each remote server gets a **permission card**: host, allowed user, allowed
  command classes, allowed paths — the broker enforces the card exactly like a
  local scope. No wildcard hosts.
- All remote sessions logged in the audit log with full command transcript.

## 10. Audit log & rollback

- **Audit log**: every broker decision (request, requester agent, scope
  evaluation, verdict, human answer, result hash) is an append-only record
  (`events` table with kind `audit`, `DATABASE.md`), viewable in Settings,
  exportable.
- **Snapshots**: before any approved batch of writes or state-changing command,
  the broker records a snapshot (Git commit on an Elysium-managed ref when the
  project is a repo, otherwise file-copy snapshot in the app data dir —
  `snapshots` table). One-click rollback restores the pre-action state and logs
  the rollback itself.
- SQLite default (ADR-001) keeps DB backup = single-file copy, snapshotted on
  schema migrations.

## 11. MCP / plugin vetting

- Disabled by default; enabling shows origin, launch command, requested tools
  and their side-effect classes.
- First use of each MCP tool requires confirmation; tools inherit (never
  exceed) the invoking agent's permission level and go through the broker (T2).
- The Security agent reviews new server manifests and posts a review event; in
  Team mode enabling requires that review plus user approval.
- No remote code marketplace in V1 (`PRODUCT_SPEC.md` §6); vetting
  infrastructure precedes any marketplace (v2.0).

## 12. Enforcement point

The **Rust permission broker is the single enforcement point** (ADR-003).
Python agents, the frontend, and MCP servers have no privileged path around it:
the engine has no direct filesystem/shell APIs for agent use, and the frontend
never executes privileged actions itself (`ARCHITECTURE.md` §7). Security
review of any PR touching capabilities focuses on this invariant; removing an
existing check "to make something work" is forbidden (`DEVELOPMENT_RULES.md`).

## 13. Privacy-first local mode

- One switch: **Local-only** — routing resolves exclusively to local providers,
  outbound network for model calls is refused by the broker, MCP servers marked
  remote are disabled.
- No mandatory telemetry (opt-in only, content-free counters if ever added).
- Everything (DB, snapshots, logs) stays in the app data dir; deleting a
  project purges its rows, memories, embeddings and snapshots.
