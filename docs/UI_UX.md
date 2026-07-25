# Elysium UI/UX Design System

Status: living document. Applies to `frontend/` (React + TypeScript + Tailwind).
UI never contains critical logic (`ARCHITECTURE.md` §1); everything here is
presentation over engine/broker state.

## 1. Art direction

- **Dark, near-black, sober.** This is a professional tool people stare at for
  hours — no gradients-everywhere, no glassmorphism, no toy design, no mascots.
- Surfaces: a small ladder of near-black grays; elevation expressed by surface
  step + 1px border, not heavy shadows.
- **Single accent color** used only for primary actions, active states and
  focus. Semantic colors (success/warning/danger) reserved for status — danger
  red appears exclusively on destructive/permission-critical UI so it never
  loses meaning.
- High contrast text; no low-contrast "aesthetic" gray-on-gray body text.
- Motion is informative (state change, progress), never decorative.

Reference tokens (Tailwind theme; final values may be tuned but must keep the
contrast requirements of §7):

| Token | Value | Use |
|---|---|---|
| `bg-base` | `#0B0C0E` | App background |
| `bg-surface` | `#121316` | Panels, sidebar |
| `bg-raised` | `#1A1C20` | Cards, inputs |
| `border` | `#26282E` | 1px separators |
| `text-primary` | `#E8EAED` | Body/headings |
| `text-secondary` | `#9BA1AB` | Metadata, labels |
| `accent` | `#4F7CFF` | Primary actions, focus, active |
| `success / warning / danger` | `#3DBE7B` / `#E0A83C` / `#E5484D` | Statuses only |

## 2. Typography & spacing

- UI font: Inter (variable); code/diff/terminal: JetBrains Mono.
- Type scale (px): 12 (meta) · 13 (dense UI) · 14 (body, default) · 16 (section
  title) · 20 (page title) · 28 (dashboard hero). Line height 1.5 body, 1.3
  titles. No font below 12px.
- Spacing on a 4px grid: 4 / 8 / 12 / 16 / 24 / 32 / 48. Cards pad 16, page
  gutters 24, section gaps 32.
- Radius: 6px controls, 10px cards. Border width: 1px everywhere.

## 3. Component inventory

| Component | Spec |
|---|---|
| **Sidebar** | 240px fixed (collapsible to 64px icon rail); sections: Dashboard, Projects, Agents, Models, MCP/Tools, Settings; engine status dot at bottom (running/starting/failed from `engine_status`) |
| **Cards** | `bg-raised`, 1px border, 10px radius; header (title + meta) / body / optional footer actions |
| **Agent card** | Avatar-less role glyph, role name, status chip, current task (1 line), last event summary. Statuses: `thinking` (pulsing dot, accent) · `analyzing` (dot, accent) · `generating` (animated bar, accent) · `waiting` (hollow dot, warning — waiting on user or dependency) · `done` (check, success) · `error` (cross, danger + retry action). Status text always accompanies color (§7) |
| **Kanban board** | Columns Backlog / In progress / Review / Done; task cards show title, assignee agent glyph, dependency count, originating requirement tag; drag allowed in Advanced/Team, read-only in Simple |
| **Diff viewer** | Side-by-side ≥1280px, unified below; per-file and per-hunk **Accept / Refuse / Modify** (Modify opens inline editor, result re-diffed); pending-changes queue with batch accept of already-reviewed hunks; mono font, syntax highlight, no red/green as the only signal (+/- gutters) |
| **Terminal panel** | Two zones: **approval queue** (command in mono, broker analysis verdict in plain language, touched paths/scope, Approve / Refuse buttons — Approve is never the default-focused button for state-changing commands) and read-only output/history below |
| **Progress bars** | Three project bars: Understanding / Architecture / Planning. Determinate, labeled with %, tooltip: "weighted checklist coverage — an estimate, not a probability" (ADR-005). Never fake progress animation |
| **Permission dialog** | Modal, danger-accented for destructive class; shows requester agent, action, scope, verdict; explicit verbs ("Allow write to src/…"), never bare OK/Cancel |
| **Spec panel** | Rendered structured spec with `assumed` items badged; sticky footer Accept / Edit / Refuse |
| **Decisions feed** | ADR-style entries from the event log (context → decision → consequences), newest first |
| **Toast/inline errors** | Explain what failed and the recovery action (`DEVELOPMENT_RULES.md`: errors explained, never swallowed) |

## 4. Mode behavior (Simple / Advanced / Team)

Same component system; modes change disclosure, not enforcement
(`PRODUCT_SPEC.md` §2):

- **Simple** — sidebar reduces to Dashboard/Projects/Settings; project view
  shows Overview only (progress bars, chat, simplified change list); agents
  summarized as one team status line; model/terminal/Git UI hidden; permission
  dialogs use fully plain language.
- **Advanced** — all tabs and panels visible; agent cards, kanban, full diff
  viewer, terminal approval queue, model routing and cost estimates.
- **Team** — Advanced + policy editor surfaces (permission cards, per-agent
  profiles, audit log viewer, MCP vetting status).
- Switching modes is instant (a view-state concern) and per-user; components
  must not duplicate logic per mode — one component, disclosure props.

## 5. Accessibility

- **Keyboard**: every action reachable by keyboard; visible focus ring (accent,
  2px); logical tab order; approval dialogs operable with explicit keys —
  Enter never auto-approves destructive actions; `Esc` = refuse/close.
- **Contrast**: WCAG 2.1 AA minimum (4.5:1 body text, 3:1 large text/UI
  glyphs) verified against the dark tokens in CI lint of the token file.
- **Not color-only**: every status pairs color with icon/text (agent statuses,
  diff gutters, progress).
- **Reduced motion**: honor `prefers-reduced-motion` — replace pulses/animated
  bars with static state changes.
- Screen readers: semantic landmarks, `aria-live=polite` for agent status
  changes, `aria-live=assertive` only for permission requests and errors.

## 6. Responsive behavior (desktop only)

Desktop window sizes only — no mobile in V1 (`PRODUCT_SPEC.md` §6).

| Width | Behavior |
|---|---|
| ≥ 1440px | Sidebar expanded, project view can show two panels (e.g. chat + diff) side by side |
| 1024–1439px | Sidebar expanded, single panel + tab strip; diff switches to unified below 1280px |
| 800–1023px (min supported) | Sidebar collapses to icon rail; panels stack; kanban horizontally scrollable |
| < 800px | Not supported; window min-size set in Tauri config |

## 7. Language & i18n

- **French is the first UI language** and the default locale; all strings
  externalized from day one (i18n catalog — no hardcoded UI strings, enforced
  by lint).
- English catalog maintained in parallel; further locales community-driven
  post-V1. Locale switch in Settings.
- Dates/numbers via `Intl` with the active locale; agent/log content follows
  the user's working language, technical identifiers stay untranslated.
