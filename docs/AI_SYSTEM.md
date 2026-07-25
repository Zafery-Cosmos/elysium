# Elysium AI System

Status: living document. Agent/model behavior changes must update this file.
Grounded in `ARCHITECTURE.md` ADR-002 (Python engine), ADR-004 (provider
abstraction), ADR-005 (task-graph orchestration).

## 1. Agent roster (V1)

All agents run inside the Python engine. None has direct OS access: every
privileged action is a capability request to the Rust broker (ADR-003).
Permission profiles below are *defaults*; effective policy is scoped per
user/project/agent/tool/environment (`SECURITY.md` §3).

| Agent | Responsibilities | Default tools | Permission profile |
|---|---|---|---|
| **Project Manager** | Requirements elicitation, spec generation, task graph creation/updates, assignment, arbitration of debates, user communication | memory read/write, task graph CRUD, question engine | ReadOnly (never writes files or runs commands) |
| **Architect** | System design, tech stack proposals, ADR-style decision drafts, module boundaries | fs_read, memory read/write, web search (opt-in) | ReadOnly |
| **Frontend** | UI code, components, styling, client state | fs_read, fs_write (diff-gated), package scripts (approved) | Development |
| **Backend** | APIs, business logic, services | fs_read, fs_write (diff-gated), test runner (sandboxed) | Development |
| **Database** | Schema design, migrations, queries | fs_read, fs_write (migrations dir), migration runner (approved) | Development |
| **DevOps** | Build config, CI, Docker files, environment setup | fs_read, fs_write, command proposals (always confirmed) | Development, elevated actions always confirmed |
| **Security** | Reviews diffs and dependencies, flags secrets/injection risks, vets MCP/tool additions | fs_read, dependency metadata, audit log read | ReadOnly (a reviewer must not modify what it reviews) |
| **QA** | Test plans, test code, executes tests in sandbox, reports failures | fs_read, fs_write (tests dirs), sandboxed test execution | Development, execution sandbox-only |

Roster is fixed in V1; custom agents are a v2.0 platform feature.

## 2. Adaptive questioning

Driven by a **requirements checklist** owned by the PM agent, persisted per
project. V1 checklist dimensions:

| Dimension | Weight | Example question (Simple mode phrasing) |
|---|---|---|
| Goal & problem | 0.20 | "Who is this for, and what problem does it solve?" |
| Core features | 0.20 | "What are the 3 things a user must be able to do?" |
| Users & roles | 0.10 | "Do different people use it differently (admin, client…)?" |
| Data | 0.15 | "What information does the app need to remember?" |
| Platform & UI | 0.10 | "Website, desktop app, or both?" |
| Integrations | 0.10 | "Does it talk to anything else (payments, maps, email…)?" |
| Constraints | 0.10 | "Budget, deadline, language, hosting preferences?" |
| Non-goals | 0.05 | "Anything you explicitly don't want?" |

Rules:
- Questions are **adaptive**: the PM asks only about uncovered or contradictory
  items, one topic at a time, phrased for the active UI mode.
- The user can skip any question or delegate ("decide for me"); delegated items
  are marked `assumed` and surfaced in the spec.
- **Understanding %** = Σ(weight × item coverage). It is a **weighted checklist
  coverage heuristic, not a probability** (ADR-005) and the UI must label it as
  such in tooltips. It never reaches 100% from assumptions alone; `assumed`
  items cap at 0.5 coverage.
- Spec generation unlocks at ≥ 70% coverage or on explicit user request.

## 3. Spec generation

- The PM compiles checklist answers + assumptions into a structured spec:
  summary, users, features (must/should/won't), data, constraints, non-goals,
  open assumptions.
- The spec is rendered as an editable document; the user **accepts / edits /
  refuses** (`PRODUCT_SPEC.md` §3). Acceptance is recorded as an event and the
  accepted spec becomes long-term memory.
- Edits and refusals re-open the affected checklist items; understanding %
  recomputes.

## 4. Orchestration (ADR-005)

- The PM produces and maintains a **persisted task graph** (`tasks` table,
  `DATABASE.md`): nodes = tasks with role, status, dependencies, originating
  requirement; edges = dependencies.
- Execution is graph-driven: an agent is activated only when a task assigned to
  its role has all dependencies satisfied. No free-running chat loops.
- Every inter-agent message, status change, decision, and tool result is an
  **event on an append-only event log** (`events` table). Events are never
  updated or deleted.
- The UI renders decisions and summaries **from the event log**, not raw model
  output. Crash recovery = replaying graph state + log; no in-memory-only state.

## 5. Inter-agent communication & debate protocol

Agents never talk directly; all messages are events addressed via the log.

Debate/decision protocol for contested choices (e.g. tech stack):

1. **Proposals** — each concerned agent posts a proposal event (option,
   rationale, cost/risk).
2. **Challenge round** — one bounded round of counter-argument events (hard cap:
   1 round in V1 to bound cost).
3. **PM decision** — the PM decides (optionally after multi-model comparison,
   §6) and posts a decision event.
4. **Recorded as ADR-style memory** — the decision (context, options,
   choice, consequences) is written to long-term memory and shown in the
   Overview decisions feed. Major decisions (stack, storage, external services)
   additionally require user approval before taking effect.

## 6. Model routing (ADR-004)

Routing is a pure function over `(task class, context size, cost budget,
availability) → provider + model`, using the tier table below. Users can pin
providers/models per project (Advanced/Team modes); Simple mode is automatic.

| Task class | Tier | Rationale |
|---|---|---|
| Requirements dialogue, spec, arbitration, ADRs | **Top** (frontier reasoning) | Errors here compound downstream |
| Architecture & security review | **Top** | High blast radius |
| Code generation (feature work) | **Mid** (strong coder) | Volume vs quality balance |
| Boilerplate, renames, formatting, commit messages | **Small/local** | Cheap, latency-sensitive |
| Embeddings | Dedicated embedding model (local by default) | Privacy + cost |
| Summarization for memory | **Small/local** | High volume |

Rules:
- **Cost estimation before large operations**: any operation whose estimated
  cost exceeds a configurable threshold (default: $0.50) shows an estimate and
  requires confirmation before running (skippable per project in Team mode).
- **Fallback chains**: each tier has an ordered chain (e.g. native Anthropic →
  native OpenAI → OpenAI-compatible/OpenRouter → local). On provider error,
  rate limit or unreachability, routing falls through and posts an event.
- **Zero-key operation**: with no cloud key configured, all tiers resolve to
  local models (Ollama/LM Studio/any OpenAI-compatible server), with a UI
  notice about capability limits.
- **Multi-model comparison for major decisions**: for decisions flagged major
  (§5), the PM may query 2–3 models across providers, compare answers, and
  record the comparison in the decision event. Off by default in Simple mode
  (cost); estimate shown first.

## 7. Cost & token accounting

Every provider call event carries tokens in/out and cost (from provider cost
metadata, ADR-004). Aggregated per task, per agent, per project; surfaced in
the Models screen and in pre-operation estimates.

## 8. Memory system

| Layer | Contents | Storage | Lifetime |
|---|---|---|---|
| **Short-term** | Active conversation window, current task context, recent events | Assembled per call from `messages`/`events` | Per task/session |
| **Long-term** | Accepted spec, ADR-style decisions, user preferences ("no TypeScript", "UI in French"), project conventions | `memories` table, typed rows | Project lifetime |
| **Vector** | Embedded chunks of spec, decisions, code summaries, conversation summaries for semantic recall | pgvector on PostgreSQL; on SQLite, embedding BLOB column + brute-force cosine search, upgradeable to sqlite-vec (ADR-001) | Project lifetime |

- Context assembly per agent call: role system prompt + task node + relevant
  long-term memories + top-k vector recall + short-term window, under the
  model's context budget.
- All retrieved file/tool/memory content is injected as **data, never
  instructions** (`DEVELOPMENT_RULES.md` §Security), with structural delimiting
  and injection heuristics (`SECURITY.md` §2).

## 9. MCP integration plan

- The engine acts as an **MCP client**; servers are configured per project
  (opt-in) in the MCP/Tools screen.
- Every MCP tool call is wrapped as a capability request: tool name, arguments
  and declared side-effect class go through the Rust broker like native tools
  (ADR-003). An MCP server never gets broader access than the agent invoking it.
- MCP tool *results* are treated as untrusted data (prompt-injection surface,
  `SECURITY.md` §2) and are scanned for secrets before being forwarded to cloud
  models.
- Vetting: servers are disabled by default, show origin/command/permissions on
  install, and require Security-agent review notes + user approval in Team mode
  (`SECURITY.md` §11).
- Phase: MCP lands in v1.0 (`ROADMAP.md`); no MCP code before the broker is
  wired end-to-end (v0.2).
