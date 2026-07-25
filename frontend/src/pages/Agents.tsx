import { useEffect, useMemo, useState, type FormEvent } from "react";
import { PageHeader } from "../components/layout/PageHeader";
import { IconPlus } from "../components/layout/icons";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorState } from "../components/ui/ErrorState";
import { TextField, TextAreaField } from "../components/ui/Field";
import { LoadingBlock, Spinner } from "../components/ui/Spinner";
import { Modal } from "../components/ui/Modal";
import { Segmented } from "../components/ui/Segmented";
import { Select } from "../components/ui/Select";
import { Toggle } from "../components/ui/Toggle";
import { useAgentsStore, agentKey } from "../stores/agents";
import { useModelsStore } from "../stores/models";
import { useUiStore } from "../stores/ui";
import { roleLabelKey, DEFAULT_AGENT_ROLES } from "../lib/labels";
import { useT, type TFunction } from "../i18n";
import { cx } from "../lib/cx";
import type {
  Agent,
  AgentPermissions,
  FilesystemAccess,
} from "../types/engine";

const BUILTIN_ROLES = new Set(DEFAULT_AGENT_ROLES.map((r) => r.role));

/** Un agent est intégré si le moteur le déclare ainsi, ou si son rôle est connu. */
function isBuiltin(agent: Agent): boolean {
  if (agent.builtin === true) return true;
  if (agent.builtin === false) return false;
  const role = agent.role?.toLowerCase();
  return role !== undefined && BUILTIN_ROLES.has(role);
}

function fsOptions(t: TFunction): Array<{ value: FilesystemAccess; label: string }> {
  return [
    { value: "none", label: t("perms.fs.none") },
    { value: "read", label: t("perms.fs.read") },
    { value: "read_write", label: t("perms.fs.read_write") },
  ];
}

function useModelOptions(t: TFunction): Array<{ value: string; label: string }> {
  const providers = useModelsStore((s) => s.providers);
  return useMemo(() => {
    const out = [{ value: "", label: t("agents.field.model.auto") }];
    for (const p of providers) {
      for (const m of p.models ?? []) {
        const id = m.id ?? m.name;
        if (id === undefined || id.length === 0) continue;
        out.push({
          value: `${p.name}:${id}`,
          label: m.display_name ?? m.name ?? id,
        });
      }
    }
    return out;
  }, [providers, t]);
}

/* ————— Éditeur de permissions en ligne ————— */

function PermissionsEditor({
  agent,
  label,
  disabled,
}: {
  agent: Agent;
  label: string;
  disabled: boolean;
}) {
  const t = useT();
  const updatePermissions = useAgentsStore((s) => s.updatePermissions);
  const p: AgentPermissions = agent.permissions ?? {};
  const change = (patch: Partial<AgentPermissions>): void => {
    void updatePermissions(agent, { ...p, ...patch });
  };
  return (
    <div className="flex flex-col gap-2 border-t border-rule pt-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-neutral">
          {t("perms.files")}
        </span>
        <Segmented
          label={`${t("perms.files")} — ${label}`}
          disabled={disabled}
          options={fsOptions(t)}
          value={p.filesystem ?? "none"}
          onChange={(value) => {
            change({ filesystem: value });
          }}
        />
      </div>
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-neutral">
          {t("perms.shell")}
        </span>
        <Toggle
          label={`${t("perms.shell")} — ${label}`}
          disabled={disabled}
          checked={p.shell === true}
          onChange={(value) => {
            change({ shell: value });
          }}
        />
      </div>
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-neutral">
          {t("perms.network")}
        </span>
        <Toggle
          label={`${t("perms.network")} — ${label}`}
          disabled={disabled}
          checked={p.network === true}
          onChange={(value) => {
            change({ network: value });
          }}
        />
      </div>
    </div>
  );
}

/* ————— Carte agent ————— */

function AgentCard({
  agent,
  advanced,
  delay = 0,
}: {
  agent: Agent;
  advanced: boolean;
  delay?: number;
}) {
  const t = useT();
  const mutatingKey = useAgentsStore((s) => s.mutatingKey);
  const setEnabled = useAgentsStore((s) => s.setEnabled);
  const remove = useAgentsStore((s) => s.remove);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const key = agentKey(agent);
  const busy = mutatingKey === key;
  const enabled = agent.enabled !== false;
  const builtin = isBuiltin(agent);
  const roleKey = roleLabelKey(agent.role);
  const roleLabel = roleKey !== null ? t(roleKey) : (agent.role ?? null);

  return (
    <article
      style={{ animationDelay: `${String(delay)}ms` }}
      className={cx(
        "card-lift flex animate-rise-in flex-col gap-3 rounded-lg border border-rule bg-paper-2/50 px-5 py-4 hover:border-rule-strong",
        !enabled && "opacity-55",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="truncate text-sm font-medium text-ink">{agent.name}</h2>
          {roleLabel !== null && (
            <p className="mt-0.5 truncate text-xs text-neutral">{roleLabel}</p>
          )}
        </div>
        <Badge tone={enabled ? "ok" : "muted"}>
          {enabled ? t("agents.enabled") : t("agents.disabled")}
        </Badge>
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        <span className="rounded-full bg-paper-3 px-2 py-0.5 text-[0.68rem] text-neutral">
          {builtin ? t("agents.builtin") : t("agents.custom")}
        </span>
        {advanced &&
          agent.model !== undefined &&
          agent.model !== null &&
          agent.model.length > 0 && (
            <span className="truncate font-mono text-[0.68rem] text-neutral">
              {agent.model}
            </span>
          )}
      </div>

      <p className="text-sm text-neutral">{t("agents.noTask")}</p>

      <div className="flex items-center justify-between gap-2">
        <label className="flex items-center gap-2 text-xs text-muted">
          <Toggle
            checked={enabled}
            disabled={busy}
            onChange={(value) => {
              void setEnabled(agent, value);
            }}
            label={enabled ? t("agents.disable") : t("agents.enable")}
          />
          {enabled ? t("agents.enabled") : t("agents.disabled")}
        </label>
        <div className="flex items-center gap-2">
          {busy && <Spinner className="size-3.5" />}
          {builtin ? (
            <span
              className="text-[0.68rem] text-neutral"
              title={t("agents.deleteBuiltinNote")}
            >
              {t("agents.builtin")}
            </span>
          ) : (
            <button
              type="button"
              onClick={() => {
                setConfirmOpen(true);
              }}
              className={cx(
                "rounded-sm text-xs text-neutral underline-offset-2",
                "transition-colors duration-[var(--dur-fast)] ease-[var(--ease-out)] hover:text-danger hover:underline",
              )}
            >
              {t("agents.delete")}
            </button>
          )}
        </div>
      </div>

      <PermissionsEditor
        agent={agent}
        label={roleLabel ?? agent.name}
        disabled={busy}
      />

      <ConfirmDialog
        open={confirmOpen}
        title={t("agents.delete.title")}
        body={t("agents.delete.body")}
        confirmLabel={t("agents.delete")}
        cancelLabel={t("common.cancel")}
        onConfirm={() => {
          setConfirmOpen(false);
          void remove(agent);
        }}
        onCancel={() => {
          setConfirmOpen(false);
        }}
      />
    </article>
  );
}

/* ————— Modal de création ————— */

function CreateAgentModal({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const t = useT();
  const createAgent = useAgentsStore((s) => s.createAgent);
  const creating = useAgentsStore((s) => s.creating);
  const actionError = useAgentsStore((s) => s.actionError);
  const modelOptions = useModelOptions(t);

  const [name, setName] = useState("");
  const [role, setRole] = useState("");
  const [prompt, setPrompt] = useState("");
  const [model, setModel] = useState("");
  const [fs, setFs] = useState<FilesystemAccess>("read");
  const [shell, setShell] = useState(false);
  const [network, setNetwork] = useState(false);

  const reset = (): void => {
    setName("");
    setRole("");
    setPrompt("");
    setModel("");
    setFs("read");
    setShell(false);
    setNetwork(false);
  };

  const onSubmit = async (e: FormEvent): Promise<void> => {
    e.preventDefault();
    const normalizedRole = role
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "");
    const ok = await createAgent({
      name: name.trim(),
      role: normalizedRole,
      system_prompt: prompt.trim(),
      ...(model.length > 0 ? { model } : {}),
      permissions: { filesystem: fs, shell, network },
    });
    if (ok) {
      reset();
      onClose();
    }
  };

  return (
    <Modal open={open} title={t("agents.create.title")} onClose={onClose}>
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          void onSubmit(e);
        }}
      >
        <TextField
          label={t("agents.field.name")}
          value={name}
          onChange={(e) => {
            setName(e.target.value);
          }}
          placeholder={t("agents.field.name.placeholder")}
          required
        />
        <TextField
          label={t("agents.field.role")}
          value={role}
          onChange={(e) => {
            setRole(e.target.value);
          }}
          placeholder={t("agents.field.role.placeholder")}
          hint={t("agents.field.role.hint")}
          required
        />
        <TextAreaField
          label={t("agents.field.prompt")}
          value={prompt}
          onChange={(e) => {
            setPrompt(e.target.value);
          }}
          placeholder={t("agents.field.prompt.placeholder")}
          required
        />
        <Select
          label={t("agents.field.model")}
          value={model}
          onChange={(e) => {
            setModel(e.target.value);
          }}
          options={modelOptions}
        />
        <div className="flex flex-col gap-2">
          <span className="text-sm font-medium text-muted">
            {t("agents.field.perms")}
          </span>
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs text-neutral">{t("perms.files")}</span>
            <Segmented
              label={t("perms.files")}
              options={fsOptions(t)}
              value={fs}
              onChange={setFs}
            />
          </div>
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs text-neutral">{t("perms.shell")}</span>
            <Toggle label={t("perms.shell")} checked={shell} onChange={setShell} />
          </div>
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs text-neutral">{t("perms.network")}</span>
            <Toggle
              label={t("perms.network")}
              checked={network}
              onChange={setNetwork}
            />
          </div>
        </div>
        {actionError !== null && !creating && (
          <p role="alert" className="text-sm text-danger">
            {actionError}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            type="submit"
            variant="primary"
            loading={creating}
            disabled={
              name.trim().length === 0 ||
              role.trim().length === 0 ||
              prompt.trim().length === 0
            }
          >
            {t("common.create")}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

/* ————— Page ————— */

export function Agents() {
  const t = useT();
  const { agents, status, error, fetch } = useAgentsStore();
  const mode = useUiStore((s) => s.mode);
  const fetchModels = useModelsStore((s) => s.fetch);
  const modelsStatus = useModelsStore((s) => s.status);
  const [createOpen, setCreateOpen] = useState(false);

  useEffect(() => {
    void fetch();
    if (modelsStatus === "idle") void fetchModels();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      <PageHeader
        title={t("agents.title")}
        subtitle={t("agents.subtitle")}
        action={
          <Button
            variant="primary"
            onClick={() => {
              setCreateOpen(true);
            }}
          >
            <IconPlus width={14} height={14} />
            {t("agents.create")}
          </Button>
        }
      />
      <div className="p-6">
        {status === "loading" && agents.length === 0 && (
          <LoadingBlock label={t("agents.loading")} />
        )}
        {status === "error" && error !== null && (
          <ErrorState message={error} onRetry={() => void fetch()} />
        )}
        {status === "ready" && agents.length === 0 && (
          <EmptyState
            title={t("agents.empty.title")}
            description={t("agents.empty.desc")}
            action={
              <Button
                variant="primary"
                onClick={() => {
                  setCreateOpen(true);
                }}
              >
                <IconPlus width={14} height={14} />
                {t("agents.create")}
              </Button>
            }
          />
        )}
        {agents.length > 0 && (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            {agents.map((agent, index) => (
              <AgentCard
                key={agentKey(agent)}
                agent={agent}
                advanced={mode === "advanced"}
                delay={Math.min(index, 8) * 40}
              />
            ))}
          </div>
        )}
      </div>

      <CreateAgentModal
        open={createOpen}
        onClose={() => {
          setCreateOpen(false);
        }}
      />
    </div>
  );
}
