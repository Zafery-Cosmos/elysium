# Elysium Product Specification — V1

Status: living document. User-visible behavior changes must update this file
(see `DEVELOPMENT_RULES.md`). Consistent with `VISION.md`, `ARCHITECTURE.md`
(ADR-001…005) and `ROADMAP.md`.

## 1. Personas

| Persona | Profile | What they need | What must stay hidden by default |
|---|---|---|---|
| **Beginner** (persona #1) | No coding experience; has an idea | Type a sentence, answer plain-language questions, see progress, get working software | Frameworks, tokens, Docker, model names, API keys, terminals |
| **Indie dev** | Solo developer, side projects | Speed, multi-model choice, cost control, local models, full diff review | Nothing — but nothing forced open either |
| **Startup** | Small team, shipping fast | Repeatable specs, task board, agent roster tuning, Git integration | Enterprise policy machinery |
| **Enterprise** | Compliance-driven org | Audit log, strict permissions, on-prem/local models, PostgreSQL backend | — (Team mode exposes everything) |

Persona #1 drives defaults: zero-setup install, SQLite storage (ADR-001), usable
with zero external API key via local models (ADR-004).

## 2. UI modes

One product, three progressive disclosure levels. Mode is a per-user setting,
switchable at any time; it changes what is *shown*, never what is *enforced*
(permissions are enforced by the Rust broker regardless of mode, ADR-003).

| | **Simple** | **Advanced** | **Team** |
|---|---|---|---|
| Target | Beginner | Indie dev / startup | Startup / enterprise |
| Chat & questions | Plain language only | Full detail | Full detail |
| Agents | Shown as "the team is working" summary | Individual agent cards, statuses, logs | + per-agent permission profiles, roster editing |
| Tasks | Progress bars only | Kanban board, task graph | + assignment, priorities, dependencies editing |
| Models | Hidden ("automatic") | Provider/model selection, routing rules, cost estimates | + per-project routing policy |
| Files/diffs | Simplified "changes to approve" list | Full diff viewer (accept / edit / refuse per hunk) | Full diff viewer + review notes |
| Terminal & Git tabs | Hidden | Visible | Visible |
| Permissions | Confirmation dialogs only | Permission cards, scopes | Full policy editor, audit log |
| MCP/Tools | Hidden | Visible, opt-in per project | Visible + vetting status |

## 3. Core user flow

```
Idea → Adaptive questions → Generated specification → Plan → Agents work → Review
 (1)        (2)                     (3)               (4)       (5)         (6)
```

1. **Idea** — user types a free-form sentence in a new project
   ("I want an app to book restaurants").
2. **Adaptive questions** — the Project Manager agent asks targeted questions
   driven by a requirements checklist; an **understanding %** bar advances (a
   weighted checklist-coverage heuristic, not a probability — ADR-005). The user
   can answer, skip, or say "decide for me" at any point.
3. **Generated specification** — a structured, readable spec (goals, features,
   non-goals, constraints). The user can **accept**, **edit** (inline, re-validated),
   or **refuse** (back to questions with feedback). Nothing proceeds without
   explicit acceptance.
4. **Plan** — the PM produces the persisted task graph (ADR-005), shown as a plan
   summary (Simple) or full board (Advanced/Team). User approves the plan.
5. **Agents work** — role agents execute tasks; every privileged action (file
   write, command, network) goes through the permission broker (ADR-003) and the
   human-in-the-loop matrix (`SECURITY.md` §4).
6. **Review** — user reviews diffs (accept / edit / refuse), approves or denies
   action requests, and watches progress. Refused work returns to the task graph
   with the user's reason attached as an event.

Steps 2–6 loop: new ideas and change requests re-enter at step 2 with the
existing spec as context.

## 4. V1 feature list

| Feature | Description | Depends on |
|---|---|---|
| Project creation | Name + directory (native picker, `pick_directory`), scope grant (`fs_scope_grant`), template-free | Rust core IPC |
| Multi-model chat | Per-conversation chat, streaming (SSE), provider/model selection or automatic routing | ADR-004 |
| Agent team | Fixed V1 roster of 8 role agents orchestrated by the PM (see `AI_SYSTEM.md`) | ADR-005 |
| File read/write | All agent file access via broker-checked `fs_read`/`fs_write`/`fs_list`, scoped to granted directories | ADR-003 |
| Diff approval | Every write proposed as a diff; user accepts / edits / refuses | ADR-003 |
| Task board | Kanban view of the persisted task graph; statuses, assignee agent, dependencies | ADR-005 |
| Project memory | Short-term context, long-term decisions/preferences, vector recall (`AI_SYSTEM.md` §8) | ADR-001 |
| Progress tracking | Understanding %, architecture %, planning % bars + per-task progress, all derived from checklist coverage and task-graph state | ADR-005 |
| Terminal (supervised) | Command proposals with analysis + approval UI; never free shell for agents | `SECURITY.md` |
| Git integration | Init/status/diff/commit via broker; commit messages proposed, user approves | ADR-003 |
| MCP tools (opt-in) | Connect vetted MCP servers per project, tools routed through the broker | `SECURITY.md` §11 |

## 5. Screen inventory

| Screen | Key elements |
|---|---|
| **Dashboard** | Recent projects, resume-where-you-left cards, engine status, quick "new idea" input |
| **Projects** | Project list (status, last activity, storage backend badge), create/archive |
| **Project view** | Tab strip: Overview · Agents · Tasks · Files · Terminal · Git (tab visibility per UI mode) |
| — Overview | Chat + adaptive questions, spec panel (accept/edit/refuse), progress bars, recent decisions feed (from event log, not raw model output — ADR-005) |
| — Agents | Agent cards with status (thinking / analyzing / generating / waiting / done / error), current task, recent messages |
| — Tasks | Kanban board (Backlog / In progress / Review / Done), task detail drawer with dependencies and originating requirement |
| — Files | Scoped file tree, diff viewer with accept / edit / refuse per change, pending-changes queue |
| — Terminal | Command approval queue (command, analysis verdict, scope), output panel, history |
| — Git | Status, staged diff, proposed commit message, history |
| **Agents** (global) | Roster, role descriptions, default permission profiles (editable in Team mode) |
| **Models** | Providers (configured/reachable status), model list, routing rules, cost overview; keys entered here go to the OS keychain, never displayed back |
| **MCP / Tools** | Connected servers, exposed tools, vetting status, enable per project |
| **Settings** | UI mode, language (French default, see `UI_UX.md`), storage backend (SQLite default / PostgreSQL — ADR-001), privacy (local-only toggle), permissions defaults, audit log viewer |

## 6. Non-goals for V1

Explicitly out of scope — do not build ahead (see `DEVELOPMENT_RULES.md` §Process):

- **No plugin/agent marketplace** (v2.0).
- **No cloud sync** of projects or settings; everything stays on the machine.
- **No team collaboration** — Team *mode* is a disclosure level for one user, not
  multi-user; shared spaces come with v2.0.
- **No mobile** app or mobile-responsive target; desktop window sizes only.
- **No deployment** to NAS/VPS (differentiator retained for v2.0 per `ROADMAP.md`).
- **No fine-tuning / training** of models.

## 7. Acceptance criteria (V1)

- A beginner in Simple mode can go from one sentence to reviewed, generated code
  without ever seeing a model name, token count or terminal.
- No agent action ever bypasses the broker: killing the engine mid-task leaves
  the filesystem exactly as last approved.
- The app is fully usable offline with a local model configured.
- Every screen above reachable within two clicks from the Dashboard.
