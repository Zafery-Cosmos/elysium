import { useEffect, useRef, useState, type ComponentType, type SVGProps } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { engine } from "../../services/engine";
import { useProjectsStore } from "../../stores/projects";
import { useT, type MessageKey } from "../../i18n";
import { cx } from "../../lib/cx";
import { ConfirmDialog } from "../ui/ConfirmDialog";
import { LogoChip } from "./LogoChip";
import {
  IconAgents,
  IconDashboard,
  IconMcp,
  IconModels,
  IconMore,
  IconPlus,
  IconSettings,
} from "./icons";
import type { Project } from "../../types/engine";

interface NavItem {
  to: string;
  labelKey: MessageKey;
  icon: ComponentType<SVGProps<SVGSVGElement>>;
}

const SECONDARY_NAV: NavItem[] = [
  { to: "/dashboard", labelKey: "nav.dashboard", icon: IconDashboard },
  { to: "/agents", labelKey: "nav.agents", icon: IconAgents },
  { to: "/models", labelKey: "nav.models", icon: IconModels },
  { to: "/mcp", labelKey: "nav.mcp", icon: IconMcp },
  { to: "/settings", labelKey: "nav.settings", icon: IconSettings },
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

const HEALTH_META: Record<EngineHealth, { dot: string; labelKey: MessageKey }> = {
  checking: { dot: "bg-neutral animate-pulse-dot", labelKey: "nav.engineChecking" },
  up: { dot: "bg-ok", labelKey: "nav.engineUp" },
  down: { dot: "bg-danger", labelKey: "nav.engineDown" },
};

function ConversationItem({ project, delay }: { project: Project; delay: number }) {
  const t = useT();
  const navigate = useNavigate();
  const location = useLocation();
  const remove = useProjectsStore((s) => s.remove);
  const [menuOpen, setMenuOpen] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [removing, setRemoving] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const onOutside = (e: MouseEvent): void => {
      if (!menuRef.current?.contains(e.target as Node)) setMenuOpen(false);
    };
    document.addEventListener("mousedown", onOutside);
    return () => {
      document.removeEventListener("mousedown", onOutside);
    };
  }, [menuOpen]);

  return (
    <li
      className="group relative animate-rise-in"
      style={{ animationDelay: `${String(delay)}ms` }}
    >
      <NavLink
        to={`/chat/${encodeURIComponent(project.id)}`}
        title={project.name}
        className={({ isActive }) =>
          cx(
            "flex h-9 items-center rounded-md px-2.5 pr-8 text-sm text-ink",
            "transition-colors duration-[var(--dur-fast)] ease-[var(--ease-out)]",
            isActive ? "bg-active" : "hover:bg-paper-3",
          )
        }
      >
        <span className="truncate">{project.name}</span>
      </NavLink>
      <button
        type="button"
        aria-label={t("nav.conversationOptions")}
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setMenuOpen((v) => !v);
        }}
        className={cx(
          "absolute right-1 top-1/2 flex size-6 -translate-y-1/2 items-center justify-center rounded-sm text-neutral",
          "opacity-0 transition-opacity duration-[var(--dur-fast)] group-hover:opacity-100 hover:bg-paper-3 hover:text-ink",
          menuOpen && "opacity-100 bg-paper-3",
        )}
      >
        <IconMore width={14} height={14} />
      </button>
      {menuOpen && (
        <div
          ref={menuRef}
          className="absolute right-1 top-9 z-10 min-w-32 rounded-md border border-rule bg-paper py-1 shadow-lg"
        >
          <button
            type="button"
            onClick={() => {
              setMenuOpen(false);
              setConfirmOpen(true);
            }}
            className="flex h-8 w-full items-center px-3 text-left text-sm text-danger hover:bg-paper-3"
          >
            {t("common.delete")}
          </button>
        </div>
      )}
      <ConfirmDialog
        open={confirmOpen}
        title={t("nav.conversationDelete.title")}
        body={t("nav.conversationDelete.body")}
        confirmLabel={t("common.delete")}
        cancelLabel={t("common.cancel")}
        busy={removing}
        onConfirm={() => {
          setRemoving(true);
          const wasOpen = location.pathname === `/chat/${project.id}`;
          void remove(project.id).finally(() => {
            setRemoving(false);
            setConfirmOpen(false);
            if (wasOpen) void navigate("/");
          });
        }}
        onCancel={() => {
          setConfirmOpen(false);
        }}
      />
    </li>
  );
}

function ConversationList() {
  const t = useT();
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
        {t("nav.conversations")}
      </p>
      {status === "loading" && projects.length === 0 && (
        <p className="px-2.5 py-2 text-xs text-neutral" role="status">
          {t("nav.conversationsLoading")}
        </p>
      )}
      {status === "error" && error !== null && (
        <div className="flex flex-col items-start gap-1.5 px-2.5 py-2">
          <p className="text-xs text-neutral">{t("nav.conversationsError")}</p>
          <button
            type="button"
            onClick={() => void fetch()}
            className="rounded-sm text-xs text-muted underline underline-offset-2 hover:text-ink"
          >
            {t("common.retry")}
          </button>
        </div>
      )}
      {status === "ready" && visible.length === 0 && (
        <p className="px-2.5 py-2 text-xs text-neutral">
          {t("nav.conversationsEmpty")}
        </p>
      )}
      <ul className="flex flex-col gap-0.5">
        {visible.map((project, index) => (
          <ConversationItem
            key={project.id}
            project={project}
            delay={Math.min(index, 8) * 30}
          />
        ))}
      </ul>
    </div>
  );
}

export function Sidebar() {
  const navigate = useNavigate();
  const t = useT();
  const health = useEngineHealth();
  const healthMeta = HEALTH_META[health];
  const healthLabel = t(healthMeta.labelKey);

  return (
    <nav
      aria-label={t("nav.main")}
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
          {t("nav.newConversation")}
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
                <span className="truncate">{t(item.labelKey)}</span>
              </NavLink>
            </li>
          ))}
        </ul>
        <div
          className="flex h-8 items-center gap-2.5 px-2.5 text-xs text-neutral"
          title={healthLabel}
        >
          <span
            aria-hidden="true"
            className={cx("size-1.5 shrink-0 rounded-full", healthMeta.dot)}
          />
          <span className="truncate">{healthLabel}</span>
        </div>
      </div>
    </nav>
  );
}
