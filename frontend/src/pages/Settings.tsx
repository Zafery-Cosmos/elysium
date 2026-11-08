import {
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { PageHeader } from "../components/layout/PageHeader";
import { LogoChip } from "../components/layout/LogoChip";
import { IconCheck } from "../components/layout/icons";
import { Button } from "../components/ui/Button";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";
import { Toggle } from "../components/ui/Toggle";
import { Segmented } from "../components/ui/Segmented";
import { Select } from "../components/ui/Select";
import { Spinner } from "../components/ui/Spinner";
import { DEFAULT_SETTINGS, useSettingsStore } from "../stores/settings";
import { useUiStore } from "../stores/ui";
import { useModelsStore } from "../stores/models";
import { activeAgentProject, useAgentsStore } from "../stores/agents";
import { engine, toHumanMessage } from "../services/engine";
import { isTauri } from "../services/endpoint";
import { DatabasePanel } from "../components/settings/DatabasePanel";
import { cx } from "../lib/cx";
import { groupedModelOptions } from "../lib/modelOptions";
import { roleLabelKey, DEFAULT_AGENT_ROLES } from "../lib/labels";
import { useT, type MessageKey, type TFunction } from "../i18n";
import type {
  AgentPermissions,
  FilesystemAccess,
  HealthInfo,
} from "../types/engine";

/* ————————————————————————————————————————————————
 * Primitives de présentation
 * ———————————————————————————————————————————————— */

function Row({
  label,
  hint,
  htmlFor,
  index = 0,
  children,
}: {
  label: string;
  hint?: string;
  htmlFor?: string;
  index?: number;
  children: ReactNode;
}) {
  return (
    <div
      style={{ animationDelay: `${String(Math.min(index, 10) * 30)}ms` }}
      className={cx(
        "flex animate-rise-in flex-col gap-2 border-b border-rule py-4 last:border-0",
        "sm:flex-row sm:items-center sm:justify-between sm:gap-8",
      )}
    >
      <div className="min-w-0 sm:max-w-md">
        <label htmlFor={htmlFor} className="block text-sm font-medium text-ink">
          {label}
        </label>
        {hint !== undefined && (
          <p className="mt-0.5 text-xs text-neutral">{hint}</p>
        )}
      </div>
      <div className="shrink-0 sm:min-w-40 sm:text-right">{children}</div>
    </div>
  );
}

function Panel({
  title,
  intro,
  children,
}: {
  title: string;
  intro?: string;
  children: ReactNode;
}) {
  return (
    <section aria-label={title} className="animate-rise-in">
      <h2 className="text-md text-ink">{title}</h2>
      {intro !== undefined && (
        <p className="mt-1 max-w-xl text-sm text-muted">{intro}</p>
      )}
      <div className="mt-3">{children}</div>
    </section>
  );
}

function NumberInput({
  value,
  onChange,
  placeholder,
  min,
  max,
  step,
  suffix,
  id,
}: {
  value: number | null;
  onChange: (value: number | null) => void;
  placeholder?: string;
  min?: number;
  max?: number;
  step?: number;
  suffix?: string;
  id?: string;
}) {
  return (
    <span className="inline-flex items-center gap-2">
      <input
        id={id}
        type="number"
        inputMode="numeric"
        value={value === null ? "" : String(value)}
        min={min}
        max={max}
        step={step}
        placeholder={placeholder}
        onChange={(e) => {
          const raw = e.target.value.trim();
          onChange(raw.length === 0 ? null : Number(raw));
        }}
        className={cx(
          "w-28 rounded-md border border-rule bg-paper px-3 py-1.5 text-sm text-ink",
          "text-left placeholder:text-neutral",
          "transition-colors duration-[var(--dur-fast)] ease-[var(--ease-out)] hover:border-rule-strong",
        )}
      />
      {suffix !== undefined && (
        <span className="text-xs text-neutral">{suffix}</span>
      )}
    </span>
  );
}

/* ————————————————————————————————————————————————
 * Matrice de permissions des agents (GET /agents + PATCH)
 * ———————————————————————————————————————————————— */

function canonicalRole(role: string): string {
  return role.toLowerCase();
}

function PermissionMatrix() {
  const t = useT();
  const agents = useAgentsStore((s) => s.agents);
  const status = useAgentsStore((s) => s.status);
  const fetch = useAgentsStore((s) => s.fetch);
  const [perms, setPerms] = useState<Record<string, AgentPermissions>>({});
  const [savingRole, setSavingRole] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    if (status === "idle") void fetch();
  }, [status, fetch]);

  const fsOptions: Array<{ value: FilesystemAccess; label: string }> = [
    { value: "none", label: t("perms.fs.none") },
    { value: "read", label: t("perms.fs.read") },
    { value: "read_write", label: t("perms.fs.read_write") },
  ];

  const rows = useMemo(() => {
    const byRole = new Map<string, AgentPermissions>();
    for (const meta of DEFAULT_AGENT_ROLES) {
      byRole.set(meta.role, { ...meta.permissions });
    }
    for (const agent of agents) {
      const role = agent.role;
      if (role === undefined || role === null || role.length === 0) continue;
      const key = canonicalRole(role);
      byRole.set(key, {
        ...(byRole.get(key) ?? {}),
        ...(agent.permissions ?? {}),
      });
    }
    return [...byRole.entries()].map(([role, permissions]) => ({
      role,
      permissions,
    }));
  }, [agents]);

  const permsFor = (role: string, fallback: AgentPermissions): AgentPermissions =>
    perms[role] ?? fallback;

  const update = (
    role: string,
    current: AgentPermissions,
    patch: Partial<AgentPermissions>,
  ): void => {
    const projectId = activeAgentProject();
    if (projectId === null) {
      setSaveError(t("agents.noProject"));
      return;
    }
    const next: AgentPermissions = { ...current, ...patch };
    setPerms((prev) => ({ ...prev, [role]: next }));
    setSavingRole(role);
    setSaveError(null);
    void engine
      .updateAgentPermissions(projectId, role, next)
      .catch((err: unknown) => {
        // Une permission affichée doit être celle que le moteur applique.
        setPerms((prev) => ({ ...prev, [role]: current }));
        setSaveError(toHumanMessage(err));
      })
      .finally(() => {
        setSavingRole((r) => (r === role ? null : r));
      });
  };

  return (
    <div className="mt-2 overflow-x-auto">
      {saveError !== null && (
        <p role="alert" className="mb-2 text-sm text-danger">
          {saveError}
        </p>
      )}
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-rule text-left text-xs text-neutral">
            <th scope="col" className="py-2 pr-4 font-medium">
              {t("perms.role")}
            </th>
            <th scope="col" className="py-2 pr-4 font-medium">
              {t("perms.files")}
            </th>
            <th scope="col" className="py-2 pr-4 font-medium">
              {t("perms.shell")}
            </th>
            <th scope="col" className="py-2 font-medium">
              {t("perms.network")}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ role, permissions }) => {
            const p = permsFor(role, permissions);
            const key = roleLabelKey(role);
            const label = key !== null ? t(key) : role;
            return (
              <tr key={role} className="border-b border-rule/70 last:border-0">
                <th
                  scope="row"
                  className="py-3 pr-4 text-left align-middle font-normal text-ink"
                >
                  <span className="flex items-center gap-2">
                    {label}
                    {savingRole === role && <Spinner className="size-3" />}
                  </span>
                </th>
                <td className="py-3 pr-4 align-middle">
                  <Segmented
                    label={`${t("perms.files")} — ${label}`}
                    options={fsOptions}
                    value={p.filesystem ?? "none"}
                    onChange={(value) => {
                      update(role, p, { filesystem: value });
                    }}
                  />
                </td>
                <td className="py-3 pr-4 align-middle">
                  <Toggle
                    label={`${t("perms.shell")} — ${label}`}
                    checked={p.shell === true}
                    onChange={(value) => {
                      update(role, p, { shell: value });
                    }}
                  />
                </td>
                <td className="py-3 align-middle">
                  <Toggle
                    label={`${t("perms.network")} — ${label}`}
                    checked={p.network === true}
                    onChange={(value) => {
                      update(role, p, { network: value });
                    }}
                  />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/* ————————————————————————————————————————————————
 * Indicateur « Enregistré ✓ » (autosave)
 * ———————————————————————————————————————————————— */

function SavedIndicator() {
  const t = useT();
  const savedAt = useSettingsStore((s) => s.savedAt);
  const syncError = useSettingsStore((s) => s.syncError);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (savedAt === null) return;
    setVisible(true);
    const id = setTimeout(() => {
      setVisible(false);
    }, 1600);
    return () => {
      clearTimeout(id);
    };
  }, [savedAt]);

  if (syncError !== null) {
    // Un réglage que le moteur n'a pas reçu ne doit jamais passer pour appliqué.
    return (
      <span role="alert" className="text-xs text-danger">
        {t("settings.syncFailed", { detail: syncError })}
      </span>
    );
  }

  return (
    <span
      role="status"
      aria-live="polite"
      className={cx(
        "flex items-center gap-1 text-xs text-ok",
        "transition-opacity duration-[var(--dur-base)] ease-[var(--ease-out)]",
        visible ? "opacity-100" : "opacity-0",
      )}
    >
      <IconCheck width={13} height={13} />
      {t("settings.saved")}
    </span>
  );
}

/* ————————————————————————————————————————————————
 * Panneaux
 * ———————————————————————————————————————————————— */

function GeneralPanel() {
  const t = useT();
  const s = useSettingsStore();
  const restartTour = useUiStore((st) => st.restartTour);
  return (
    <Panel title={t("settings.general.title")} intro={t("settings.general.intro")}>
      <Row
        label={t("settings.general.language")}
        hint={t("settings.general.language.hint")}
      >
        <Select
          aria-label={t("settings.general.language")}
          value={s.language}
          onChange={(e) => {
            s.set("language", e.target.value as typeof s.language);
          }}
          options={[
            { value: "fr", label: "Français" },
            { value: "en", label: "English" },
            { value: "es", label: "Español" },
          ]}
        />
      </Row>
      <Row label={t("settings.general.theme")} hint={t("settings.general.theme.hint")}>
        <Segmented
          label={t("settings.general.theme")}
          options={[
            { value: "light", label: t("settings.general.theme.light") },
            { value: "dark", label: t("settings.general.theme.dark") },
            { value: "auto", label: t("settings.general.theme.auto") },
          ]}
          value={s.theme}
          onChange={(value) => {
            s.set("theme", value);
          }}
        />
      </Row>
      <Row
        label={t("settings.general.density")}
        hint={t("settings.general.density.hint")}
      >
        <Segmented
          label={t("settings.general.density")}
          options={[
            {
              value: "comfortable",
              label: t("settings.general.density.comfortable"),
            },
            { value: "compact", label: t("settings.general.density.compact") },
          ]}
          value={s.density}
          onChange={(value) => {
            s.set("density", value);
          }}
        />
      </Row>
      <Row
        label={t("settings.general.fontSize")}
        hint={t("settings.general.fontSize.hint")}
      >
        <Segmented
          label={t("settings.general.fontSize")}
          options={[
            { value: "small", label: t("settings.general.fontSize.small") },
            { value: "normal", label: t("settings.general.fontSize.normal") },
            { value: "large", label: t("settings.general.fontSize.large") },
          ]}
          value={s.fontSize}
          onChange={(value) => {
            s.set("fontSize", value);
          }}
        />
      </Row>
      <Row
        label={t("settings.general.animations")}
        hint={t("settings.general.animations.hint")}
      >
        <Segmented
          label={t("settings.general.animations")}
          options={[
            { value: "auto", label: t("settings.general.animations.auto") },
            { value: "on", label: t("settings.general.animations.on") },
            { value: "reduced", label: t("settings.general.animations.reduced") },
          ]}
          value={s.motion}
          onChange={(value) => {
            s.set("motion", value);
          }}
        />
      </Row>
      <Row
        label={t("settings.general.resume")}
        hint={t("settings.general.resume.hint")}
      >
        <Toggle
          label={t("settings.general.resume")}
          checked={s.resumeLastConversation}
          onChange={(value) => {
            s.set("resumeLastConversation", value);
          }}
        />
      </Row>
      <Row
        label={t("settings.general.confirmDelete")}
        hint={t("settings.general.confirmDelete.hint")}
      >
        <Toggle
          label={t("settings.general.confirmDelete")}
          checked={s.confirmBeforeDelete}
          onChange={(value) => {
            s.set("confirmBeforeDelete", value);
          }}
        />
      </Row>
      <Row
        label={t("settings.general.aiLang")}
        hint={t("settings.general.aiLang.hint")}
      >
        <Select
          aria-label={t("settings.general.aiLang")}
          value={s.aiResponseLanguage}
          onChange={(e) => {
            s.set(
              "aiResponseLanguage",
              e.target.value as typeof s.aiResponseLanguage,
            );
          }}
          options={[
            { value: "auto", label: t("settings.general.aiLang.auto") },
            { value: "fr", label: "Français" },
            { value: "en", label: "English" },
            { value: "es", label: "Español" },
          ]}
        />
      </Row>
      <Row
        label={t("settings.general.tour")}
        hint={t("settings.general.tour.hint")}
      >
        <Button onClick={restartTour}>{t("settings.general.tour.button")}</Button>
      </Row>
    </Panel>
  );
}

function AiPanel() {
  const t = useT();
  const s = useSettingsStore();
  const providers = useModelsStore((st) => st.providers);
  const modelsStatus = useModelsStore((st) => st.status);
  const fetchModels = useModelsStore((st) => st.fetch);

  useEffect(() => {
    if (modelsStatus === "idle") void fetchModels();
  }, [modelsStatus, fetchModels]);

  // Seuls les fournisseurs réellement configurés peuvent être imposés.
  const modelOptions = useMemo(
    () => [
      { value: "", label: t("settings.ai.model.auto") },
      ...groupedModelOptions(providers, t, { onlyConfigured: true, providerInLabel: true }),
    ],
    [providers, t],
  );

  return (
    <Panel title={t("settings.ai.title")} intro={t("settings.ai.intro")}>
      <Row label={t("settings.ai.model")}>
        <Select
          aria-label={t("settings.ai.model")}
          value={s.defaultModel ?? ""}
          onChange={(e) => {
            s.set(
              "defaultModel",
              e.target.value.length === 0 ? null : e.target.value,
            );
          }}
          options={modelOptions}
        />
      </Row>
      <Row label={t("settings.ai.effort")} hint={t("settings.ai.effort.hint")}>
        <Segmented
          label={t("settings.ai.effort")}
          options={[
            { value: "low", label: t("chat.effort.low") },
            { value: "medium", label: t("chat.effort.medium") },
            { value: "high", label: t("chat.effort.high") },
          ]}
          value={s.defaultEffort}
          onChange={(value) => {
            s.set("defaultEffort", value);
          }}
        />
      </Row>
      <Row
        label={t("settings.ai.autoRouting")}
        hint={t("settings.ai.autoRouting.hint")}
      >
        <Toggle
          label={t("settings.ai.autoRouting")}
          checked={s.autoRouting}
          onChange={(value) => {
            s.set("autoRouting", value);
          }}
        />
      </Row>
      <Row
        label={t("settings.ai.streaming")}
        hint={t("settings.ai.streaming.hint")}
      >
        <Toggle
          label={t("settings.ai.streaming")}
          checked={s.streaming}
          onChange={(value) => {
            s.set("streaming", value);
          }}
        />
      </Row>
      <Row
        label={t("settings.ai.maxTokens")}
        hint={t("settings.ai.maxTokens.hint")}
      >
        <NumberInput
          value={s.maxResponseTokens}
          onChange={(value) => {
            s.set("maxResponseTokens", value ?? DEFAULT_SETTINGS.maxResponseTokens);
          }}
          placeholder={t("settings.ai.maxTokens.placeholder")}
          min={1}
          step={256}
          suffix="tokens"
        />
      </Row>
      <Row label={t("settings.ai.timeout")} hint={t("settings.ai.timeout.hint")}>
        <NumberInput
          value={s.requestTimeout}
          onChange={(value) => {
            s.set("requestTimeout", value ?? DEFAULT_SETTINGS.requestTimeout);
          }}
          min={5}
          step={5}
          suffix="s"
        />
      </Row>
      <Row label={t("settings.ai.retries")} hint={t("settings.ai.retries.hint")}>
        <NumberInput
          value={s.maxRetries}
          onChange={(value) => {
            s.set("maxRetries", value ?? 0);
          }}
          min={0}
          max={10}
          step={1}
        />
      </Row>
    </Panel>
  );
}

function CachingPanel() {
  const t = useT();
  const s = useSettingsStore();
  return (
    <Panel title={t("settings.caching.title")} intro={t("settings.caching.intro")}>
      <Row
        label={t("settings.caching.enabled")}
        hint={t("settings.caching.enabled.hint")}
      >
        <Toggle
          label={t("settings.caching.enabled")}
          checked={s.cacheEnabled}
          onChange={(value) => {
            s.set("cacheEnabled", value);
          }}
        />
      </Row>
      <Row label={t("settings.caching.ttl")} hint={t("settings.caching.ttl.hint")}>
        <Segmented
          label={t("settings.caching.ttl")}
          options={[
            { value: "5m", label: t("settings.caching.ttl.5m") },
            { value: "1h", label: t("settings.caching.ttl.1h") },
          ]}
          value={s.cacheTtl}
          onChange={(value) => {
            s.set("cacheTtl", value);
          }}
        />
      </Row>
      <Row
        label={t("settings.caching.minPrefix")}
        hint={t("settings.caching.minPrefix.hint")}
      >
        <NumberInput
          value={s.cacheMinPrefix}
          onChange={(value) => {
            s.set("cacheMinPrefix", value ?? 0);
          }}
          min={0}
          step={256}
          suffix="tokens"
        />
      </Row>
    </Panel>
  );
}

function AgentsSettingsPanel() {
  const t = useT();
  return (
    <Panel title={t("settings.agents.title")} intro={t("settings.agents.intro")}>
      <div className="mt-6 animate-rise-in">
        <h3 className="text-sm font-medium text-ink">
          {t("settings.agents.perms")}
        </h3>
        <p className="mt-0.5 max-w-xl text-xs text-neutral">
          {t("settings.agents.perms.hint")}
        </p>
        <PermissionMatrix />
      </div>
    </Panel>
  );
}

function DeveloperPanel() {
  const t = useT();
  const s = useSettingsStore();
  const mode = useUiStore((st) => st.mode);
  const setMode = useUiStore((st) => st.setMode);
  return (
    <Panel title={t("settings.dev.title")} intro={t("settings.dev.intro")}>
      <Row
        label={t("settings.dev.advanced")}
        hint={t("settings.dev.advanced.hint")}
      >
        <Toggle
          label={t("settings.dev.advanced")}
          checked={mode === "advanced"}
          onChange={(value) => {
            setMode(value ? "advanced" : "simple");
          }}
        />
      </Row>
      <Row label={t("settings.dev.logLevel")}>
        <Select
          aria-label={t("settings.dev.logLevel")}
          value={s.logLevel}
          onChange={(e) => {
            s.set("logLevel", e.target.value as typeof s.logLevel);
          }}
          options={[
            { value: "error", label: t("settings.dev.logLevel.error") },
            { value: "warn", label: t("settings.dev.logLevel.warn") },
            { value: "info", label: t("settings.dev.logLevel.info") },
            { value: "debug", label: t("settings.dev.logLevel.debug") },
          ]}
        />
      </Row>
    </Panel>
  );
}

function ResetSettings() {
  const t = useT();
  const syncFromEngine = useSettingsStore((s) => s.syncFromEngine);
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-6 border-t border-rule pt-4">
      <Button
        variant="ghost"
        onClick={() => {
          setOpen(true);
        }}
      >
        {t("settings.reset")}
      </Button>
      <ConfirmDialog
        open={open}
        title={t("settings.reset")}
        body={t("settings.reset.body")}
        confirmLabel={t("settings.reset")}
        cancelLabel={t("common.cancel")}
        onConfirm={() => {
          void engine.resetSettings().then(syncFromEngine);
          setOpen(false);
        }}
        onCancel={() => {
          setOpen(false);
        }}
      />
    </div>
  );
}

function PrivacyPanel() {
  const t = useT();
  const s = useSettingsStore();
  return (
    <Panel title={t("settings.privacy.title")} intro={t("settings.privacy.intro")}>
      <Row
        label={t("settings.privacy.redact")}
        hint={t("settings.privacy.redact.hint")}
      >
        <Toggle
          label={t("settings.privacy.redact")}
          checked={s.redactSecrets}
          onChange={(value) => {
            s.set("redactSecrets", value);
          }}
        />
      </Row>
      <Row
        label={t("settings.privacy.localOnly")}
        hint={t("settings.privacy.localOnly.hint")}
      >
        <Toggle
          label={t("settings.privacy.localOnly")}
          checked={s.localOnly}
          onChange={(value) => {
            s.set("localOnly", value);
          }}
        />
      </Row>
      <ResetSettings />
    </Panel>
  );
}

function ShortcutsPanel() {
  const t = useT();
  const shortcuts: Array<{ keys: string; action: string }> = [
    { keys: t("settings.shortcuts.enterKeys"), action: t("settings.shortcuts.enter") },
    {
      keys: t("settings.shortcuts.shiftEnterKeys"),
      action: t("settings.shortcuts.shiftEnter"),
    },
    {
      keys: t("settings.shortcuts.escapeKeys"),
      action: t("settings.shortcuts.escape"),
    },
    {
      keys: t("settings.shortcuts.arrowsKeys"),
      action: t("settings.shortcuts.arrows"),
    },
  ];
  return (
    <Panel
      title={t("settings.shortcuts.title")}
      intro={t("settings.shortcuts.intro")}
    >
      <dl className="mt-1 divide-y divide-rule">
        {shortcuts.map((shortcut, index) => (
          <div
            key={shortcut.keys}
            style={{ animationDelay: `${String(index * 30)}ms` }}
            className="flex animate-rise-in items-center justify-between gap-4 py-3"
          >
            <dt className="text-sm text-ink">{shortcut.action}</dt>
            <dd>
              <kbd className="rounded-md border border-rule bg-paper-2 px-2 py-1 font-mono text-xs text-muted">
                {shortcut.keys}
              </kbd>
            </dd>
          </div>
        ))}
      </dl>
    </Panel>
  );
}

function AboutPanel({
  health,
  healthError,
  advanced,
}: {
  health: HealthInfo | null;
  healthError: boolean;
  advanced: boolean;
}) {
  const t = useT();
  const engineStatus = healthError
    ? t("settings.about.engineDown")
    : health === null
      ? t("settings.about.engineChecking")
      : `${t("settings.about.engineOnline")}${
          advanced && health.version !== undefined
            ? ` · v${health.version}`
            : ""
        }`;

  return (
    <Panel title={t("settings.about.title")}>
      <div className="flex animate-rise-in items-center gap-3">
        <LogoChip className="size-10 rounded-lg p-1.5" />
        <div>
          <p className="text-sm font-medium text-ink">Elysium</p>
          <p className="text-xs text-neutral">{t("settings.about.tagline")}</p>
        </div>
      </div>
      <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
        <dt className="text-neutral">{t("settings.about.context")}</dt>
        <dd className="text-ink">
          {isTauri()
            ? t("settings.about.contextTauri")
            : t("settings.about.contextBrowser")}
        </dd>
        <dt className="text-neutral">{t("settings.about.engine")}</dt>
        <dd className="text-ink">{engineStatus}</dd>
      </dl>
      <div className="mt-4 flex flex-wrap gap-3 text-sm">
        <a
          href="https://github.com/Zafery-Cosmos/elysium#readme"
          target="_blank"
          rel="noreferrer"
          className="rounded-sm text-muted underline-offset-2 hover:text-ink hover:underline"
        >
          {t("settings.about.docs")}
        </a>
        <a
          href="https://github.com/Zafery-Cosmos/elysium"
          target="_blank"
          rel="noreferrer"
          className="rounded-sm text-muted underline-offset-2 hover:text-ink hover:underline"
        >
          {t("settings.about.source")}
        </a>
      </div>
    </Panel>
  );
}

/* ————————————————————————————————————————————————
 * Page
 * ———————————————————————————————————————————————— */

type SectionId =
  | "general"
  | "ai"
  | "caching"
  | "agents"
  | "developer"
  | "privacy"
  | "database"
  | "shortcuts"
  | "about";

const SECTION_TITLES: Record<SectionId, MessageKey> = {
  general: "settings.general.title",
  ai: "settings.ai.title",
  caching: "settings.caching.title",
  agents: "settings.agents.title",
  developer: "settings.dev.title",
  privacy: "settings.privacy.title",
  database: "database.title",
  shortcuts: "settings.shortcuts.title",
  about: "settings.about.title",
};

const SECTION_ORDER: SectionId[] = [
  "general",
  "ai",
  "caching",
  "agents",
  "developer",
  "privacy",
  "database",
  "shortcuts",
  "about",
];

export function Settings() {
  const t: TFunction = useT();
  const [section, setSection] = useState<SectionId>("general");
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [healthError, setHealthError] = useState(false);
  const mode = useUiStore((s) => s.mode);
  const syncFromEngine = useSettingsStore((s) => s.syncFromEngine);

  useEffect(() => {
    void syncFromEngine();
  }, [syncFromEngine]);

  useEffect(() => {
    let cancelled = false;
    engine
      .health()
      .then((info) => {
        if (!cancelled) setHealth(info);
      })
      .catch(() => {
        if (!cancelled) setHealthError(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      <PageHeader title={t("settings.title")} action={<SavedIndicator />} />
      <div className="flex flex-col gap-8 p-6 md:flex-row md:gap-10">
        <nav
          aria-label={t("settings.sectionsNav")}
          className="shrink-0 md:sticky md:top-0 md:w-56 md:self-start"
        >
          <ul className="flex gap-1 overflow-x-auto md:flex-col md:overflow-visible">
            {SECTION_ORDER.map((id) => {
              const active = section === id;
              return (
                <li key={id} className="shrink-0">
                  <button
                    type="button"
                    aria-current={active ? "page" : undefined}
                    onClick={() => {
                      setSection(id);
                    }}
                    className={cx(
                      "w-full rounded-md px-3 py-2 text-left text-sm whitespace-nowrap",
                      "transition-colors duration-[var(--dur-fast)] ease-[var(--ease-out)]",
                      active
                        ? "bg-paper-3 font-medium text-ink"
                        : "text-muted hover:bg-paper-2 hover:text-ink",
                    )}
                  >
                    {t(SECTION_TITLES[id])}
                  </button>
                </li>
              );
            })}
          </ul>
        </nav>

        <div className="min-w-0 flex-1 pb-10 md:max-w-2xl">
          {section === "general" && <GeneralPanel />}
          {section === "ai" && <AiPanel />}
          {section === "caching" && <CachingPanel />}
          {section === "agents" && <AgentsSettingsPanel />}
          {section === "developer" && <DeveloperPanel />}
          {section === "privacy" && <PrivacyPanel />}
          {section === "database" && <DatabasePanel />}
          {section === "shortcuts" && <ShortcutsPanel />}
          {section === "about" && (
            <AboutPanel
              health={health}
              healthError={healthError}
              advanced={mode === "advanced"}
            />
          )}
        </div>
      </div>
    </div>
  );
}
