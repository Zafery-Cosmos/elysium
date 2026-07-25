import { useEffect, useState, type ComponentType, type SVGProps } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { engine } from "../../services/engine";
import { useProjectsStore } from "../../stores/projects";
import { cx } from "../../lib/cx";
import { LogoChip } from "./LogoChip";
import {
  IconAgents,
  IconDashboard,
  IconModels,
  IconPlus,
  IconSettings,
} from "./icons";

interface NavItem {
  to: string;
  label: string;
  icon: ComponentType<SVGProps<SVGSVGElement>>;
}

const SECONDARY_NAV: NavItem[] = [
  { to: "/dashboard", label: "Tableau de bord", icon: IconDashboard },
  { to: "/agents", label: "Agents", icon: IconAgents },
  { to: "/models", label: "Modèles", icon: IconModels },
  { to: "/settings", label: "Réglages", icon: IconSettings },
];

type EngineHealth = "checking" | "up" | "down";

function useEngineHealth(): EngineHealth {
  const [health, setHealth] = useState<EngineHealth>("checking");
  useEffect(() => {
    let cancelled = false;
    const check = (): void => {
      engine
        .health()
        .then(() => {
          if (!cancelled) setHealth("up");
        })
        .catch(() => {
          if (!cancelled) setHealth("down");
        });
    };
    check();
    const timer = window.setInterval(check, 30_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);
  return health;
}

const HEALTH_META: Record<EngineHealth, { dot: string; label: string }> = {
  checking: { dot: "bg-neutral animate-pulse-dot", label: "Vérification du moteur IA…" },
  up: { dot: "bg-ok", label: "Moteur IA en ligne" },
  down: { dot: "bg-danger", label: "Moteur IA injoignable" },
};

function ConversationList() {
  const { projects, status, error, fetch } = useProjectsStore();

  useEffect(() => {
    void fetch();
    // Chargement au montage uniquement ; la liste se met à jour via le store.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const visible = projects.filter((p) => p.status !== "archived");

  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2">
      <p className="px-2.5 pb-1.5 text-xs font-medium text-neutral">
        Conversations
      </p>
      {status === "loading" && projects.length === 0 && (
        <p className="px-2.5 py-2 text-xs text-neutral" role="status">
          Chargement…
        </p>
      )}
      {status === "error" && error !== null && (
        <div className="flex flex-col items-start gap-1.5 px-2.5 py-2">
          <p className="text-xs text-neutral">Conversations indisponibles.</p>
          <button
            type="button"
            onClick={() => void fetch()}
            className="rounded-sm text-xs text-muted underline underline-offset-2 hover:text-ink"
          >
            Réessayer
          </button>
        </div>
      )}
      {status === "ready" && visible.length === 0 && (
        <p className="px-2.5 py-2 text-xs text-neutral">
          Aucune conversation pour l'instant.
        </p>
      )}
      <ul className="flex flex-col gap-0.5">
        {visible.map((project, index) => (
          <li
            key={project.id}
            className="animate-rise-in"
            style={{ animationDelay: `${Math.min(index, 8) * 30}ms` }}
          >
            <NavLink
              to={`/chat/${encodeURIComponent(project.id)}`}
              title={project.name}
              className={({ isActive }) =>
                cx(
                  "flex h-9 items-center rounded-md px-2.5 text-sm text-ink",
                  "transition-colors duration-[var(--dur-fast)] ease-[var(--ease-out)]",
                  isActive ? "bg-active" : "hover:bg-paper-3",
                )
              }
            >
              <span className="truncate">{project.name}</span>
            </NavLink>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function Sidebar() {
  const navigate = useNavigate();
  const health = useEngineHealth();
  const healthMeta = HEALTH_META[health];

  return (
    <nav
      aria-label="Navigation principale"
      className="flex h-full w-[260px] shrink-0 flex-col border-r border-rule bg-paper-2"
    >
      <div className="flex h-14 shrink-0 items-center gap-2.5 px-4">
        <LogoChip />
        <span className="text-sm font-semibold tracking-tight text-ink">
          Elysium
        </span>
      </div>

      <div className="px-3 pb-2">
        <button
          type="button"
          onClick={() => {
            void navigate("/");
          }}
          className={cx(
            "flex h-9 w-full items-center justify-center gap-2 rounded-md bg-ink px-3 text-sm font-medium text-paper",
            "transition-colors duration-[var(--dur-fast)] ease-[var(--ease-out)]",
            "hover:bg-ink/85 active:translate-y-px",
          )}
        >
          <IconPlus width={14} height={14} />
          Nouvelle conversation
        </button>
      </div>

      <ConversationList />

      <div className="shrink-0 border-t border-rule p-3">
        <ul className="flex flex-col gap-0.5">
          {SECONDARY_NAV.map((item) => (
            <li key={item.to}>
              <NavLink
                to={item.to}
                className={({ isActive }) =>
                  cx(
                    "flex h-8 items-center gap-2.5 rounded-md px-2.5 text-sm",
                    "transition-colors duration-[var(--dur-fast)] ease-[var(--ease-out)]",
                    isActive
                      ? "bg-active text-ink"
                      : "text-muted hover:bg-paper-3 hover:text-ink",
                  )
                }
              >
                <item.icon width={16} height={16} className="shrink-0" />
                <span className="truncate">{item.label}</span>
              </NavLink>
            </li>
          ))}
        </ul>
        <div
          className="flex h-8 items-center gap-2.5 px-2.5 text-xs text-neutral"
          title={healthMeta.label}
        >
          <span
            aria-hidden="true"
            className={cx("size-1.5 shrink-0 rounded-full", healthMeta.dot)}
          />
          <span className="truncate">{healthMeta.label}</span>
        </div>
      </div>
    </nav>
  );
}
