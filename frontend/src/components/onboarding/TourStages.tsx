import { useEffect, useMemo, useRef, useState, type ComponentType, type ReactNode } from "react";
import { useT, type MessageKey } from "../../i18n";
import { cx } from "../../lib/cx";
import { groupByBilling, type Billing } from "../../lib/billing";
import { IconCheck } from "../layout/icons";
import type { ProviderInfo } from "../../types/engine";

/**
 * Scènes du tutoriel. Tout est FAUX : aucune requête au moteur, aucune écriture.
 * Chaque scène signale `onDone` quand l'utilisateur a essayé ce qu'elle montre,
 * et respecte le mouvement réduit (les animations sautent à leur état final).
 */
export interface StageProps {
  reduced: boolean;
  onDone: () => void;
}

export interface TourStep {
  id: string;
  title: MessageKey;
  body: MessageKey;
  /** Consigne « À vous : … » (absente pour les écrans sans interaction). */
  action?: MessageKey;
  Stage: ComponentType<StageProps>;
}

/* ————— briques communes ————— */

function StageButton({
  children,
  onClick,
  primary = false,
  pulse = false,
  disabled = false,
}: {
  children: ReactNode;
  onClick: () => void;
  primary?: boolean;
  pulse?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={cx(
        "h-8 rounded-md px-3 text-sm transition-colors duration-[var(--dur-fast)] ease-[var(--ease-out)] active:translate-y-px",
        "disabled:cursor-not-allowed disabled:opacity-50",
        primary
          ? "bg-accent font-medium text-paper hover:bg-accent/90"
          : "border border-rule text-ink hover:border-rule-strong hover:bg-paper-3",
        pulse && "ring-2 ring-ink/30 ring-offset-2 ring-offset-paper-2",
      )}
    >
      {children}
    </button>
  );
}

function ReplayButton({ onClick }: { onClick: () => void }) {
  const t = useT();
  return (
    <button
      type="button"
      onClick={onClick}
      className="h-8 rounded-md px-2 text-xs text-muted underline-offset-4 hover:text-ink hover:underline"
    >
      ↺ {t("tour.replay")}
    </button>
  );
}

function Bubble({ role, children }: { role: "user" | "assistant"; children: ReactNode }) {
  return (
    <div
      className={cx(
        "max-w-[85%] animate-rise-in rounded-lg px-3 py-2 text-sm",
        role === "user"
          ? "self-end bg-accent text-paper"
          : "self-start border border-rule bg-paper text-ink",
      )}
    >
      {children}
    </div>
  );
}

/** Appelle `onDone` une seule fois, la première fois que `ready` devient vrai. */
function useDoneOnce(ready: boolean, onDone: () => void): void {
  const fired = useRef(false);
  useEffect(() => {
    if (ready && !fired.current) {
      fired.current = true;
      onDone();
    }
  }, [ready, onDone]);
}

/* ————— 0. Accueil : l'équipe ————— */

const AGENT_KEYS: MessageKey[] = [
  "tour.agent.pm",
  "tour.agent.architect",
  "tour.agent.frontend",
  "tour.agent.backend",
  "tour.agent.db",
  "tour.agent.devops",
  "tour.agent.security",
  "tour.agent.qa",
];

export function TeamStage({ reduced, onDone }: StageProps) {
  const t = useT();
  useDoneOnce(true, onDone);
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {AGENT_KEYS.map((key, i) => (
        <div
          key={key}
          style={reduced ? undefined : { animationDelay: `${String(i * 70)}ms` }}
          className="flex animate-rise-in flex-col items-center gap-2 rounded-lg border border-rule bg-paper p-3 text-center"
        >
          <span
            aria-hidden="true"
            className="grid size-9 place-items-center rounded-full bg-accent text-sm font-medium text-paper"
          >
            {t(key).charAt(0)}
          </span>
          <span className="text-xs text-ink">{t(key)}</span>
        </div>
      ))}
    </div>
  );
}

/* ————— 1. Fausse conversation ————— */

export function ChatStage({ reduced, onDone }: StageProps) {
  const t = useT();
  const userText = t("tour.s1.user");
  const assistantWords = useMemo(() => t("tour.s1.assistant").split(" "), [t]);
  const [phase, setPhase] = useState<"typing" | "ready" | "sent" | "done">(reduced ? "ready" : "typing");
  const [typed, setTyped] = useState(reduced ? userText : "");
  const [shown, setShown] = useState(0);
  const [run, setRun] = useState(0);

  useEffect(() => {
    if (phase !== "typing") return;
    let n = 0;
    const id = setInterval(() => {
      n += 1;
      setTyped(userText.slice(0, n));
      if (n >= userText.length) {
        clearInterval(id);
        setPhase("ready");
      }
    }, 28);
    return () => {
      clearInterval(id);
    };
  }, [phase, userText, run]);

  useEffect(() => {
    if (phase !== "sent") return;
    if (reduced) {
      setShown(assistantWords.length);
      setPhase("done");
      return;
    }
    let n = 0;
    const id = setInterval(() => {
      n += 1;
      setShown(n);
      if (n >= assistantWords.length) {
        clearInterval(id);
        setPhase("done");
      }
    }, 85);
    return () => {
      clearInterval(id);
    };
  }, [phase, reduced, assistantWords.length, run]);

  useDoneOnce(phase === "done", onDone);

  const sent = phase === "sent" || phase === "done";
  const progress = phase === "done" ? 35 : phase === "sent" ? 18 : 0;

  const replay = (): void => {
    setRun((r) => r + 1);
    setShown(0);
    setTyped(reduced ? userText : "");
    setPhase(reduced ? "ready" : "typing");
  };

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="flex min-h-40 flex-1 flex-col gap-2" aria-live="polite">
        {sent && <Bubble role="user">{userText}</Bubble>}
        {sent && shown > 0 && (
          <Bubble role="assistant">{assistantWords.slice(0, shown).join(" ")}</Bubble>
        )}
      </div>

      <div className="rounded-lg border border-rule bg-paper p-2">
        <div className="flex items-center justify-between text-xs text-neutral">
          <span>{t("tour.s1.understanding")}</span>
          <span className="tabular-nums">{String(progress)} %</span>
        </div>
        <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-paper-3" aria-hidden="true">
          <div
            className="h-full rounded-full bg-ink transition-[width] duration-700 ease-[var(--ease-out)]"
            style={{ width: `${String(progress)}%` }}
          />
        </div>
        <p className="mt-1 text-xs text-neutral">{t("tour.s1.hint")}</p>
      </div>

      <div className="flex items-center gap-2 rounded-lg border border-rule bg-paper p-2">
        <p className="min-h-6 flex-1 px-1 py-0.5 text-sm text-ink" aria-label={t("tour.s1.placeholder")}>
          {sent ? (
            <span className="text-neutral">{t("tour.s1.placeholder")}</span>
          ) : (
            <>
              {typed}
              {!reduced && phase === "typing" && (
                <span
                  aria-hidden="true"
                  className="ml-0.5 inline-block h-4 w-px translate-y-0.5 animate-caret-blink bg-ink"
                />
              )}
            </>
          )}
        </p>
        <StageButton
          primary
          pulse={phase === "ready"}
          disabled={sent}
          onClick={() => {
            setTyped(userText);
            setPhase("sent");
          }}
        >
          {t("tour.s1.send")}
        </StageButton>
      </div>
      {phase === "done" && (
        <div className="flex justify-end">
          <ReplayButton onClick={replay} />
        </div>
      )}
    </div>
  );
}

/* ————— 2. Modes ————— */

type ModeId = "discuss" | "plan" | "edit";
type ExecId = "simple" | "analyse" | "complet";

const MODES: Array<{ id: ModeId; label: MessageKey; demo: MessageKey }> = [
  { id: "discuss", label: "chat.mode.discuss", demo: "tour.mode.discuss.demo" },
  { id: "plan", label: "chat.mode.plan", demo: "tour.mode.plan.demo" },
  { id: "edit", label: "chat.mode.edit", demo: "tour.mode.edit.demo" },
];
const EXECS: Array<{ id: ExecId; label: MessageKey; demo: MessageKey }> = [
  { id: "simple", label: "chat.exec.simple", demo: "tour.exec.simple.demo" },
  { id: "analyse", label: "chat.exec.expertAnalyse", demo: "tour.exec.analyse.demo" },
  { id: "complet", label: "chat.exec.expertComplete", demo: "tour.exec.complet.demo" },
];

function Choice({
  label,
  selected,
  visited,
  onClick,
}: {
  label: string;
  selected: boolean;
  visited: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onClick}
      className={cx(
        "flex h-8 items-center gap-1.5 rounded-md border px-3 text-sm transition-colors duration-[var(--dur-fast)] ease-[var(--ease-out)]",
        selected
          ? "border-ink bg-ink font-medium text-paper"
          : "border-rule text-muted hover:border-rule-strong hover:text-ink",
      )}
    >
      {label}
      {visited && !selected && <IconCheck width={11} height={11} aria-hidden="true" />}
    </button>
  );
}

export function ModesStage({ onDone }: StageProps) {
  const t = useT();
  const [mode, setMode] = useState<ModeId>("discuss");
  const [exec, setExec] = useState<ExecId>("simple");
  const [seenModes, setSeenModes] = useState<ReadonlySet<ModeId>>(new Set<ModeId>(["discuss"]));
  const [seenExecs, setSeenExecs] = useState<ReadonlySet<ExecId>>(new Set<ExecId>(["simple"]));
  useDoneOnce(seenModes.size === MODES.length && seenExecs.size === EXECS.length, onDone);

  const modeDemo = MODES.find((m) => m.id === mode)?.demo ?? "tour.mode.discuss.demo";
  const execDemo = EXECS.find((e) => e.id === exec)?.demo ?? "tour.exec.simple.demo";

  return (
    <div className="flex flex-col gap-4">
      <div>
        <p className="mb-1.5 text-xs font-medium text-neutral">{t("tour.s2.modes")}</p>
        <div role="radiogroup" aria-label={t("tour.s2.modes")} className="flex flex-wrap gap-2">
          {MODES.map((m) => (
            <Choice
              key={m.id}
              label={t(m.label)}
              selected={mode === m.id}
              visited={seenModes.has(m.id)}
              onClick={() => {
                setMode(m.id);
                setSeenModes((s) => new Set(s).add(m.id));
              }}
            />
          ))}
        </div>
        <p key={mode} className="mt-2 min-h-10 animate-fade-in text-sm text-muted" aria-live="polite">
          {t(modeDemo)}
        </p>
      </div>
      <div>
        <p className="mb-1.5 text-xs font-medium text-neutral">{t("tour.s2.exec")}</p>
        <div role="radiogroup" aria-label={t("tour.s2.exec")} className="flex flex-wrap gap-2">
          {EXECS.map((e) => (
            <Choice
              key={e.id}
              label={t(e.label)}
              selected={exec === e.id}
              visited={seenExecs.has(e.id)}
              onClick={() => {
                setExec(e.id);
                setSeenExecs((s) => new Set(s).add(e.id));
              }}
            />
          ))}
        </div>
        <p key={exec} className="mt-2 min-h-10 animate-fade-in text-sm text-muted" aria-live="polite">
          {t(execDemo)}
        </p>
      </div>
    </div>
  );
}

/* ————— 3. Valider le plan ————— */

type TaskStatus = "todo" | "doing" | "done";
const TASKS: Array<{ title: MessageKey; role: MessageKey }> = [
  { title: "tour.s3.task1", role: "tour.agent.architect" },
  { title: "tour.s3.task2", role: "tour.agent.db" },
  { title: "tour.s3.task3", role: "tour.agent.frontend" },
  { title: "tour.s3.task4", role: "tour.agent.qa" },
];
const STATUS_KEY: Record<TaskStatus, MessageKey> = {
  todo: "tour.status.todo",
  doing: "tour.status.doing",
  done: "tour.status.done",
};

export function PlanStage({ reduced, onDone }: StageProps) {
  const t = useT();
  const [phase, setPhase] = useState<"proposed" | "running" | "finished" | "refused">("proposed");
  const [status, setStatus] = useState<TaskStatus[]>(TASKS.map(() => "todo"));
  const [run, setRun] = useState(0);

  useEffect(() => {
    if (phase !== "running") return;
    if (reduced) {
      setStatus(TASKS.map(() => "done"));
      setPhase("finished");
      return;
    }
    const timers: Array<ReturnType<typeof setTimeout>> = [];
    TASKS.forEach((_, i) => {
      timers.push(
        setTimeout(() => {
          setStatus((s) => s.map((v, k) => (k === i ? "doing" : v)));
        }, i * 1400),
      );
      timers.push(
        setTimeout(() => {
          setStatus((s) => s.map((v, k) => (k === i ? "done" : v)));
        }, i * 1400 + 900),
      );
    });
    timers.push(setTimeout(() => { setPhase("finished"); }, TASKS.length * 1400));
    return () => {
      timers.forEach(clearTimeout);
    };
  }, [phase, reduced, run]);

  useDoneOnce(phase === "finished" || phase === "refused", onDone);

  const replay = (): void => {
    setRun((r) => r + 1);
    setStatus(TASKS.map(() => "todo"));
    setPhase("proposed");
  };

  return (
    <div className="flex flex-col gap-3">
      {phase === "refused" ? (
        <p className="animate-fade-in rounded-lg border border-rule bg-paper p-4 text-sm text-muted" role="status">
          {t("tour.s3.refused")}
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {TASKS.map((task, i) => {
            const s = status[i] ?? "todo";
            return (
              <li
                key={task.title}
                className="flex items-center gap-3 rounded-lg border border-rule bg-paper px-3 py-2"
              >
                <span
                  aria-hidden="true"
                  className={cx(
                    "grid size-5 shrink-0 place-items-center rounded-full border text-paper",
                    s === "done" && "border-ink bg-ink",
                    s === "doing" && "animate-pulse-dot border-ink",
                    s === "todo" && "border-rule-strong",
                  )}
                >
                  {s === "done" && <IconCheck width={11} height={11} />}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm text-ink">{t(task.title)}</span>
                  <span className="block text-xs text-neutral">{t(task.role)}</span>
                </span>
                <span className="shrink-0 text-xs text-muted">{t(STATUS_KEY[s])}</span>
              </li>
            );
          })}
        </ul>
      )}
      <div className="flex items-center gap-2">
        {phase === "proposed" && (
          <>
            <StageButton primary pulse onClick={() => { setPhase("running"); }}>
              {t("tour.s3.validate")}
            </StageButton>
            <StageButton onClick={() => { setPhase("refused"); }}>{t("tour.s3.refuse")}</StageButton>
          </>
        )}
        {(phase === "finished" || phase === "refused") && <ReplayButton onClick={replay} />}
      </div>
    </div>
  );
}

/* ————— 4. Relire un diff, appliquer, annuler ————— */

const DIFF: Array<{ kind: "ctx" | "del" | "add"; text: string }> = [
  { kind: "ctx", text: "<body>" },
  { kind: "del", text: '  <h1>Mon site</h1>' },
  { kind: "add", text: '  <h1>Réservez votre table</h1>' },
  { kind: "add", text: '  <button>Réserver</button>' },
  { kind: "ctx", text: "</body>" },
];

export function DiffStage({ reduced, onDone }: StageProps) {
  const t = useT();
  const [state, setState] = useState<"proposed" | "applied" | "reverted" | "rejected">("proposed");
  useDoneOnce(state === "reverted" || state === "rejected", onDone);
  const checks: MessageKey[] = ["tour.s4.check1", "tour.s4.check2", "tour.s4.check3"];

  return (
    <div className="flex flex-col gap-3">
      <div className="overflow-hidden rounded-lg border border-rule bg-paper">
        <p className="border-b border-rule px-3 py-1.5 font-mono text-xs text-muted">index.html</p>
        <pre className="overflow-x-auto py-1 font-mono text-xs leading-5" aria-label="diff">
          {DIFF.map((line) => (
            <div
              key={line.text}
              className={cx(
                "px-3 whitespace-pre",
                line.kind === "add" && state !== "reverted" && state !== "rejected" && "bg-ok/10 text-ink",
                line.kind === "del" && state !== "reverted" && state !== "rejected" && "bg-danger/10 text-ink",
                (state === "reverted" || state === "rejected") && line.kind === "add" && "text-neutral line-through",
                line.kind === "ctx" && "text-muted",
              )}
            >
              {line.kind === "add" ? "+ " : line.kind === "del" ? "- " : "  "}
              {line.text}
            </div>
          ))}
        </pre>
      </div>

      <ul className="flex flex-wrap gap-2">
        {checks.map((key, i) => (
          <li
            key={key}
            style={reduced ? undefined : { animationDelay: `${String(300 + i * 250)}ms` }}
            className="flex animate-rise-in items-center gap-1.5 rounded-full border border-rule bg-paper px-2.5 py-1 text-xs text-muted"
          >
            <IconCheck width={11} height={11} aria-hidden="true" className="text-ok" />
            {t(key)}
          </li>
        ))}
      </ul>

      <div className="min-h-5 text-sm text-muted" role="status">
        {state === "applied" && <span className="animate-fade-in">{t("tour.s4.applied")}</span>}
        {state === "reverted" && <span className="animate-fade-in">{t("tour.s4.reverted")}</span>}
        {state === "rejected" && <span className="animate-fade-in">{t("tour.s4.rejected")}</span>}
      </div>

      <div className="flex items-center gap-2">
        {state === "proposed" && (
          <>
            <StageButton primary pulse onClick={() => { setState("applied"); }}>
              {t("tour.s4.apply")}
            </StageButton>
            <StageButton onClick={() => { setState("rejected"); }}>{t("tour.s4.reject")}</StageButton>
          </>
        )}
        {state === "applied" && (
          <StageButton pulse onClick={() => { setState("reverted"); }}>
            {t("tour.s4.undo")}
          </StageButton>
        )}
        {(state === "reverted" || state === "rejected") && (
          <ReplayButton onClick={() => { setState("proposed"); }} />
        )}
      </div>
    </div>
  );
}

/* ————— 5. Choix du modèle, rangé par mode de connexion ————— */

const DEMO_PROVIDERS: ProviderInfo[] = [
  { name: "anthropic", label: "Anthropic", kind: "anthropic", configured: true, models: [{ id: "claude", display_name: "Claude" }] },
  { name: "claude-code", label: "Claude Code", kind: "cli", configured: true, models: [{ id: "claude", display_name: "Claude" }] },
  { name: "ollama", label: "Ollama", kind: "openai", is_local: true, configured: true, models: [{ id: "llama", display_name: "Llama" }] },
  { name: "codex", label: "Codex", kind: "cli", configured: true, models: [{ id: "gpt", display_name: "GPT" }] },
  { name: "openai", label: "OpenAI", kind: "openai", configured: true, models: [{ id: "gpt", display_name: "GPT" }] },
];
const GROUP_LABEL: Record<Billing, MessageKey> = {
  subscription: "chat.model.group.subscription",
  api: "chat.model.group.api",
  local: "chat.model.group.local",
};
const GROUP_HINT: Record<Billing, MessageKey> = {
  subscription: "chat.model.group.subscription.hint",
  api: "chat.model.group.api.hint",
  local: "chat.model.group.local.hint",
};

export function ModelStage({ onDone }: StageProps) {
  const t = useT();
  const [picked, setPicked] = useState<string | null>(null);
  const sections = useMemo(() => groupByBilling(DEMO_PROVIDERS), []);
  useDoneOnce(picked !== null, onDone);

  return (
    <div className="flex flex-col gap-3">
      <div className="rounded-lg border border-rule bg-paper p-2">
        {sections.map((section) => (
          <section key={section.billing} aria-label={t(GROUP_LABEL[section.billing])} className="mt-2 first:mt-0">
            <div className="flex items-baseline justify-between border-b border-rule px-2 pb-1">
              <h4 className="text-xs font-semibold tracking-wide text-ink uppercase">
                {t(GROUP_LABEL[section.billing])}
              </h4>
              <span className="text-xs text-neutral">{t(GROUP_HINT[section.billing])}</span>
            </div>
            {section.providers.map((p) => {
              const value = `${p.name}`;
              const selected = picked === value;
              return (
                <button
                  key={p.name}
                  type="button"
                  aria-pressed={selected}
                  onClick={() => { setPicked(value); }}
                  className={cx(
                    "mt-1 flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors duration-[var(--dur-fast)] ease-[var(--ease-out)] hover:bg-paper-3",
                    selected && "bg-paper-3 font-medium",
                  )}
                >
                  <span className="flex-1 truncate text-ink">{p.label ?? p.name}</span>
                  {selected && <IconCheck width={13} height={13} aria-hidden="true" />}
                </button>
              );
            })}
          </section>
        ))}
      </div>
      <p className="min-h-5 text-sm text-muted" role="status">
        {picked !== null && (
          <span className="animate-fade-in">
            {t("tour.s5.picked", { name: DEMO_PROVIDERS.find((p) => p.name === picked)?.label ?? picked })}
          </span>
        )}
      </p>
    </div>
  );
}

/* ————— 6. Le reste ————— */

const TOUR_TOPICS: Array<{ glyph: string; title: MessageKey; text: MessageKey }> = [
  { glyph: "▣", title: "tour.s6.preview.t", text: "tour.s6.preview.d" },
  { glyph: "◎", title: "tour.s6.memory.t", text: "tour.s6.memory.d" },
  { glyph: "▤", title: "tour.s6.admin.t", text: "tour.s6.admin.d" },
  { glyph: "⌘", title: "tour.s6.mcp.t", text: "tour.s6.mcp.d" },
  { glyph: "■", title: "tour.s6.stop.t", text: "tour.s6.stop.d" },
];

export function MoreStage({ reduced, onDone }: StageProps) {
  const t = useT();
  useDoneOnce(true, onDone);
  return (
    <div className="flex flex-col gap-2">
      {TOUR_TOPICS.map((topic, i) => (
        <div
          key={topic.title}
          style={reduced ? undefined : { animationDelay: `${String(i * 90)}ms` }}
          className="flex animate-rise-in items-start gap-3 rounded-lg border border-rule bg-paper px-3 py-2"
        >
          <span aria-hidden="true" className="mt-0.5 w-5 shrink-0 text-center text-ink">
            {topic.glyph}
          </span>
          <span className="min-w-0">
            <span className="block text-sm font-medium text-ink">{t(topic.title)}</span>
            <span className="block text-xs text-muted">{t(topic.text)}</span>
          </span>
        </div>
      ))}
      <p className="mt-1 text-xs text-neutral">{t("tour.s6.replay")}</p>
    </div>
  );
}
