import { useEffect, useState, type ComponentType, type SVGProps } from "react";
import { NavLink } from "react-router-dom";
import { engine } from "../../services/engine";
import { useUiStore } from "../../stores/ui";
import { cx } from "../../lib/cx";
import {
  IconAgents,
  IconCollapse,
  IconDashboard,
  IconExpand,
  IconModels,
  IconProjects,
  IconSettings,
} from "./icons";

interface NavItem {
  to: string;
  label: string;
  icon: ComponentType<SVGProps<SVGSVGElement>>;
  end?: boolean;
}

const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Tableau de bord", icon: IconDashboard, end: true },
  { to: "/projects", label: "Projets", icon: IconProjects },
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

export function Sidebar() {
  const collapsed = useUiStore((s) => s.sidebarCollapsed);
  const toggleSidebar = useUiStore((s) => s.toggleSidebar);
  const health = useEngineHealth();
  const healthMeta = HEALTH_META[health];

  return (
    <nav
      aria-label="Navigation principale"
      className={cx(
        "flex h-full shrink-0 flex-col border-r border-rule bg-paper-2/40",
        "transition-[width] duration-[var(--dur-base)] ease-[var(--ease-out)]",
        collapsed ? "w-14" : "w-56",
      )}
    >
      <div
        className={cx(
          "flex h-14 items-center border-b border-rule",
          collapsed ? "justify-center" : "gap-2.5 px-4",
        )}
      >
        <img
          src="/logo.png"
          alt=""
          aria-hidden="true"
          className="size-7 shrink-0 select-none"
          draggable={false}
        />
        {!collapsed && (
          <span className="text-sm font-semibold tracking-tight text-ink">
            Elysium
          </span>
        )}
      </div>

      <ul className="flex flex-1 flex-col gap-1 p-2">
        {NAV_ITEMS.map((item) => (
          <li key={item.to}>
            <NavLink
              to={item.to}
              end={item.end}
              title={collapsed ? item.label : undefined}
              className={({ isActive }) =>
                cx(
                  "group relative flex h-9 items-center gap-3 rounded-md px-2.5 text-sm",
                  "transition-colors duration-[var(--dur-fast)] ease-[var(--ease-out)]",
                  collapsed && "justify-center px-0",
                  isActive
                    ? "bg-paper-3 text-ink"
                    : "text-neutral hover:bg-paper-2 hover:text-muted",
                )
              }
            >
              {({ isActive }) => (
                <>
                  <span
                    aria-hidden="true"
                    className={cx(
                      "absolute left-0 h-4 w-0.5 rounded-full bg-accent",
                      isActive ? "opacity-100" : "opacity-0",
                    )}
                  />
                  <item.icon className="shrink-0" />
                  {!collapsed && <span className="truncate">{item.label}</span>}
                </>
              )}
            </NavLink>
          </li>
        ))}
      </ul>

      <div className="flex flex-col gap-1 border-t border-rule p-2">
        <div
          className={cx(
            "flex h-8 items-center gap-2.5 px-2.5 text-xs text-neutral",
            collapsed && "justify-center px-0",
          )}
          title={healthMeta.label}
        >
          <span
            aria-hidden="true"
            className={cx("size-1.5 shrink-0 rounded-full", healthMeta.dot)}
          />
          {!collapsed && <span className="truncate">{healthMeta.label}</span>}
          <span className="sr-only">{healthMeta.label}</span>
        </div>
        <button
          type="button"
          onClick={toggleSidebar}
          aria-label={
            collapsed ? "Déployer la barre latérale" : "Replier la barre latérale"
          }
          aria-expanded={!collapsed}
          className={cx(
            "flex h-8 items-center gap-3 rounded-md px-2.5 text-sm text-neutral",
            "transition-colors duration-[var(--dur-fast)] ease-[var(--ease-out)]",
            "hover:bg-paper-2 hover:text-muted",
            collapsed && "justify-center px-0",
          )}
        >
          {collapsed ? <IconExpand /> : <IconCollapse />}
          {!collapsed && <span>Replier</span>}
        </button>
      </div>
    </nav>
  );
}
