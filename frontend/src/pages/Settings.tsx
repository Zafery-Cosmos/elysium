import {
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { PageHeader } from "../components/layout/PageHeader";
import { LogoChip } from "../components/layout/LogoChip";
import { IconCheck } from "../components/layout/icons";
import { Toggle } from "../components/ui/Toggle";
import { Segmented } from "../components/ui/Segmented";
import { Select } from "../components/ui/Select";
import { Spinner } from "../components/ui/Spinner";
import { useSettingsStore } from "../stores/settings";
import { useUiStore } from "../stores/ui";
import { useModelsStore } from "../stores/models";
import { useAgentsStore } from "../stores/agents";
import { engine } from "../services/engine";
import { isTauri } from "../services/endpoint";
import { cx } from "../lib/cx";
import { roleLabel, DEFAULT_AGENT_ROLES } from "../lib/labels";
import type {
  AgentPermissions,
  FilesystemAccess,
  HealthInfo,
} from "../types/engine";

/* ————————————————————————————————————————————————
 * Primitives de présentation
 * ———————————————————————————————————————————————— */

/** Une ligne de réglage : intitulé + explication à gauche, contrôle à droite. */
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
        <label
          htmlFor={htmlFor}
          className="block text-sm font-medium text-ink"
        >
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

/** En-tête de panneau : titre + phrase d'intro. */
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

/** Champ nombre monochrome, avec support de la valeur nulle (vide). */
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

const FS_OPTIONS: Array<{ value: FilesystemAccess; label: string }> = [
  { value: "none", label: "Aucun" },
  { value: "read", label: "Lecture" },
  { value: "read_write", label: "Lecture/écriture" },
];

function canonicalRole(role: string): string {
  return role.toLowerCase();
}

function PermissionMatrix() {
  const agents = useAgentsStore((s) => s.agents);
  const status = useAgentsStore((s) => s.status);
  const fetch = useAgentsStore((s) => s.fetch);
  const [perms, setPerms] = useState<Record<string, AgentPermissions>>({});
  const [savingRole, setSavingRole] = useState<string | null>(null);

  useEffect(() => {
    if (status === "idle") void fetch();
  }, [status, fetch]);

  // Fusionne les rôles par défaut avec ceux (et permissions) renvoyés par
  // le moteur ; les rôles inconnus du moteur restent affichés.
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
    const next: AgentPermissions = { ...current, ...patch };
    setPerms((prev) => ({ ...prev, [role]: next }));
    setSavingRole(role);
    void engine
      .updateAgentPermissions(role, next)
      .catch(() => {
        // Lecture/écriture tolérante : en cas d'échec, on garde l'état local.
      })
      .finally(() => {
        setSavingRole((r) => (r === role ? null : r));
      });
  };

  return (
    <div className="mt-2 overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-rule text-left text-xs text-neutral">
            <th scope="col" className="py-2 pr-4 font-medium">
              Rôle
            </th>
            <th scope="col" className="py-2 pr-4 font-medium">
              Fichiers
            </th>
            <th scope="col" className="py-2 pr-4 font-medium">
              Terminal
            </th>
            <th scope="col" className="py-2 font-medium">
              Réseau
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ role, permissions }) => {
            const p = permsFor(role, permissions);
            const label = roleLabel(role) ?? role;
            return (
              <tr
                key={role}
                className="border-b border-rule/70 last:border-0"
              >
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
                    label={`Accès fichiers — ${label}`}
                    options={FS_OPTIONS}
                    value={p.filesystem ?? "none"}
                    onChange={(value) => {
                      update(role, p, { filesystem: value });
                    }}
                  />
                </td>
                <td className="py-3 pr-4 align-middle">
                  <Toggle
                    label={`Terminal — ${label}`}
                    checked={p.shell === true}
                    onChange={(value) => {
                      update(role, p, { shell: value });
                    }}
                  />
                </td>
                <td className="py-3 align-middle">
                  <Toggle
                    label={`Réseau — ${label}`}
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
 * Indicateur « Enregistré ✓ »
 * ———————————————————————————————————————————————— */

function SavedIndicator() {
  const savedAt = useSettingsStore((s) => s.savedAt);
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
      Enregistré
    </span>
  );
}

/* ————————————————————————————————————————————————
 * Panneaux
 * ———————————————————————————————————————————————— */

function GeneralPanel() {
  const s = useSettingsStore();
  return (
    <Panel title="Général" intro="Langue, apparence et confort d'utilisation.">
      <Row label="Langue de l'interface" hint="Langue des menus et libellés.">
        <Select
          aria-label="Langue de l'interface"
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
      <Row
        label="Thème"
        hint="Le thème clair est la référence d'Elysium ; le sombre arrive bientôt."
      >
        <Segmented
          label="Thème"
          options={[
            { value: "light", label: "Clair" },
            { value: "dark", label: "Sombre" },
            { value: "auto", label: "Auto" },
          ]}
          value={s.theme}
          onChange={(value) => {
            s.set("theme", value);
          }}
        />
      </Row>
      <Row label="Densité de l'interface" hint="Compact resserre les espacements.">
        <Segmented
          label="Densité"
          options={[
            { value: "comfortable", label: "Confortable" },
            { value: "compact", label: "Compact" },
          ]}
          value={s.density}
          onChange={(value) => {
            s.set("density", value);
          }}
        />
      </Row>
      <Row label="Taille de police" hint="S'applique à toute l'interface.">
        <Segmented
          label="Taille de police"
          options={[
            { value: "small", label: "Petite" },
            { value: "normal", label: "Normale" },
            { value: "large", label: "Grande" },
          ]}
          value={s.fontSize}
          onChange={(value) => {
            s.set("fontSize", value);
          }}
        />
      </Row>
      <Row
        label="Animations"
        hint="« Auto » suit le système ; « Activées » les force malgré tout."
      >
        <Segmented
          label="Animations"
          options={[
            { value: "auto", label: "Auto" },
            { value: "on", label: "Activées" },
            { value: "reduced", label: "Réduites" },
          ]}
          value={s.motion}
          onChange={(value) => {
            s.set("motion", value);
          }}
        />
      </Row>
      <Row
        label="Reprendre la dernière conversation"
        hint="Rouvre automatiquement le dernier fil au démarrage."
      >
        <Toggle
          label="Reprendre la dernière conversation"
          checked={s.resumeLastConversation}
          onChange={(value) => {
            s.set("resumeLastConversation", value);
          }}
        />
      </Row>
      <Row
        label="Confirmer avant suppression"
        hint="Demande une confirmation avant de supprimer un élément."
      >
        <Toggle
          label="Confirmer avant suppression"
          checked={s.confirmBeforeDelete}
          onChange={(value) => {
            s.set("confirmBeforeDelete", value);
          }}
        />
      </Row>
      <Row
        label="Langue de réponse de l'IA"
        hint="« Auto » : l'IA répond dans la langue de votre message."
      >
        <Select
          aria-label="Langue de réponse de l'IA"
          value={s.aiResponseLanguage}
          onChange={(e) => {
            s.set(
              "aiResponseLanguage",
              e.target.value as typeof s.aiResponseLanguage,
            );
          }}
          options={[
            { value: "auto", label: "Automatique" },
            { value: "fr", label: "Français" },
            { value: "en", label: "English" },
            { value: "es", label: "Español" },
          ]}
        />
      </Row>
    </Panel>
  );
}

function AiPanel() {
  const s = useSettingsStore();
  const providers = useModelsStore((st) => st.providers);
  const modelsStatus = useModelsStore((st) => st.status);
  const fetchModels = useModelsStore((st) => st.fetch);

  useEffect(() => {
    if (modelsStatus === "idle") void fetchModels();
  }, [modelsStatus, fetchModels]);

  const providerOptions = useMemo(
    () => [
      { value: "", label: "Automatique" },
      ...providers.map((p) => ({ value: p.name, label: p.label ?? p.name })),
    ],
    [providers],
  );

  const modelOptions = useMemo(() => {
    const out = [{ value: "", label: "Automatique" }];
    for (const p of providers) {
      for (const m of p.models ?? []) {
        const id = m.id ?? m.name;
        if (id === undefined || id.length === 0) continue;
        out.push({
          value: `${p.name}:${id}`,
          label: `${m.display_name ?? m.name ?? id}`,
        });
      }
    }
    return out;
  }, [providers]);

  return (
    <Panel
      title="Intelligence artificielle"
      intro="Réglages par défaut du raisonnement, du routage et des coûts."
    >
      <Row label="Fournisseur par défaut">
        <Select
          aria-label="Fournisseur par défaut"
          value={s.defaultProvider ?? ""}
          onChange={(e) => {
            s.set(
              "defaultProvider",
              e.target.value.length === 0 ? null : e.target.value,
            );
          }}
          options={providerOptions}
        />
      </Row>
      <Row label="Modèle par défaut">
        <Select
          aria-label="Modèle par défaut"
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
      <Row label="Effort par défaut" hint="Profondeur de raisonnement du modèle.">
        <Segmented
          label="Effort par défaut"
          options={[
            { value: "low", label: "Faible" },
            { value: "medium", label: "Moyen" },
            { value: "high", label: "Élevé" },
          ]}
          value={s.defaultEffort}
          onChange={(value) => {
            s.set("defaultEffort", value);
          }}
        />
      </Row>
      <Row label="Exécution par défaut" hint="Un modèle solo, ou l'équipe d'agents.">
        <Segmented
          label="Exécution par défaut"
          options={[
            { value: "simple", label: "Simple" },
            { value: "expert", label: "Expert" },
          ]}
          value={s.defaultExecution}
          onChange={(value) => {
            s.set("defaultExecution", value);
          }}
        />
      </Row>
      <Row label="Mode par défaut" hint="Comportement au premier message.">
        <Segmented
          label="Mode par défaut"
          options={[
            { value: "discuss", label: "Discuter" },
            { value: "plan", label: "Plan" },
            { value: "edit", label: "Éditer" },
          ]}
          value={s.defaultMode}
          onChange={(value) => {
            s.set("defaultMode", value);
          }}
        />
      </Row>
      <Row
        label="Routage automatique"
        hint="Choisit le meilleur modèle selon la tâche, le contexte et le coût."
      >
        <Toggle
          label="Routage automatique"
          checked={s.autoRouting}
          onChange={(value) => {
            s.set("autoRouting", value);
          }}
        />
      </Row>
      <Row
        label="Bascule de secours automatique"
        hint="En cas d'échec d'un modèle, réessaie avec un autre."
      >
        <Toggle
          label="Bascule de secours automatique"
          checked={s.autoFallback}
          onChange={(value) => {
            s.set("autoFallback", value);
          }}
        />
      </Row>
      <Row
        label="Comparaison multi-modèles"
        hint="Interroge plusieurs modèles et compare leurs réponses."
      >
        <Toggle
          label="Comparaison multi-modèles"
          checked={s.multiModelCompare}
          onChange={(value) => {
            s.set("multiModelCompare", value);
          }}
        />
      </Row>
      <Row
        label="Réponse en flux (streaming)"
        hint="Affiche la réponse au fil de sa génération."
      >
        <Toggle
          label="Réponse en flux"
          checked={s.streaming}
          onChange={(value) => {
            s.set("streaming", value);
          }}
        />
      </Row>
      <Row
        label="Garde-fou de coût"
        hint="Dépense maximale par session, en euros. Vide = illimité."
      >
        <NumberInput
          value={s.costGuard}
          onChange={(value) => {
            s.set("costGuard", value);
          }}
          placeholder="Illimité"
          min={0}
          step={1}
          suffix="€"
        />
      </Row>
      <Row
        label="Tokens maximum en réponse"
        hint="Plafond de longueur des réponses. Vide = automatique."
      >
        <NumberInput
          value={s.maxResponseTokens}
          onChange={(value) => {
            s.set("maxResponseTokens", value);
          }}
          placeholder="Auto"
          min={1}
          step={256}
          suffix="tokens"
        />
      </Row>
      <Row label="Délai d'expiration" hint="Abandon d'une requête trop longue.">
        <NumberInput
          value={s.requestTimeout}
          onChange={(value) => {
            s.set("requestTimeout", value ?? 0);
          }}
          min={5}
          step={5}
          suffix="s"
        />
      </Row>
      <Row label="Tentatives" hint="Nombre de reprises en cas d'erreur réseau.">
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
  const s = useSettingsStore();
  return (
    <Panel
      title="Prompt caching"
      intro="Réutilise les préfixes de prompt identiques d'une requête à l'autre : jusqu'à ~90 % de coût et de latence en moins sur la partie mise en cache."
    >
      <Row label="Activé" hint="Met en cache les préfixes stables des prompts.">
        <Toggle
          label="Cache de prompt activé"
          checked={s.cacheEnabled}
          onChange={(value) => {
            s.set("cacheEnabled", value);
          }}
        />
      </Row>
      <Row label="Durée de conservation" hint="Fenêtre pendant laquelle un préfixe reste en cache.">
        <Segmented
          label="Durée de conservation"
          options={[
            { value: "5m", label: "5 min" },
            { value: "1h", label: "1 heure" },
            { value: "24h", label: "24 h" },
          ]}
          value={s.cacheTtl}
          onChange={(value) => {
            s.set("cacheTtl", value);
          }}
        />
      </Row>
      <Row
        label="Taille minimale de préfixe"
        hint="En dessous, la mise en cache n'est pas rentable."
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
      <Row
        label="Pré-chauffage du cache"
        hint="Amorce le cache avec le contexte du projet à l'ouverture."
      >
        <Toggle
          label="Pré-chauffage du cache"
          checked={s.cacheWarmup}
          onChange={(value) => {
            s.set("cacheWarmup", value);
          }}
        />
      </Row>
      <Row
        label="Afficher les statistiques"
        hint="Montre les taux de réussite du cache et les économies réalisées."
      >
        <Toggle
          label="Afficher les statistiques de cache"
          checked={s.cacheStatsVisible}
          onChange={(value) => {
            s.set("cacheStatsVisible", value);
          }}
        />
      </Row>
    </Panel>
  );
}

function AgentsPanel() {
  const s = useSettingsStore();
  return (
    <Panel
      title="Agents & permissions"
      intro="Comment l'équipe d'agents collabore, et ce que chaque rôle est autorisé à faire."
    >
      <Row
        label="Autoriser les débats"
        hint="Les agents peuvent confronter leurs choix avant de trancher."
      >
        <Toggle
          label="Autoriser les débats"
          checked={s.allowDebates}
          onChange={(value) => {
            s.set("allowDebates", value);
          }}
        />
      </Row>
      <Row
        label="Agents en parallèle (max.)"
        hint="Nombre d'agents pouvant travailler simultanément."
      >
        <NumberInput
          value={s.maxParallelAgents}
          onChange={(value) => {
            s.set("maxParallelAgents", value ?? 1);
          }}
          min={1}
          max={12}
          step={1}
        />
      </Row>
      <Row
        label="Validation humaine requise pour…"
        hint="Quelles actions exigent votre accord explicite."
      >
        <Segmented
          label="Validation humaine requise"
          options={[
            { value: "none", label: "Jamais" },
            { value: "privileged", label: "Actions sensibles" },
            { value: "all", label: "Toujours" },
          ]}
          value={s.humanApproval}
          onChange={(value) => {
            s.set("humanApproval", value);
          }}
        />
      </Row>
      <Row
        label="Snapshot automatique"
        hint="Prend une capture du projet avant tout changement important."
      >
        <Toggle
          label="Snapshot automatique avant changements"
          checked={s.autoSnapshot}
          onChange={(value) => {
            s.set("autoSnapshot", value);
          }}
        />
      </Row>
      <div className="mt-6 animate-rise-in">
        <h3 className="text-sm font-medium text-ink">Permissions par rôle</h3>
        <p className="mt-0.5 max-w-xl text-xs text-neutral">
          Par défaut, chaque action privilégiée demande votre accord. Le broker
          applique ces règles quel que soit le mode.
        </p>
        <PermissionMatrix />
      </div>
    </Panel>
  );
}

function MemoryPanel() {
  const s = useSettingsStore();
  return (
    <Panel
      title="Contexte & mémoire"
      intro="Ce que l'équipe garde en tête d'une session à l'autre."
    >
      <Row
        label="Mémoire vectorielle"
        hint="Retrouve les informations pertinentes du projet par similarité."
      >
        <Toggle
          label="Mémoire vectorielle"
          checked={s.vectorMemory}
          onChange={(value) => {
            s.set("vectorMemory", value);
          }}
        />
      </Row>
      <Row
        label="Taille de contexte"
        hint="Quantité d'historique et de code fournie au modèle."
      >
        <Segmented
          label="Taille de contexte"
          options={[
            { value: "small", label: "Réduite" },
            { value: "balanced", label: "Équilibrée" },
            { value: "large", label: "Large" },
            { value: "max", label: "Maximum" },
          ]}
          value={s.contextSize}
          onChange={(value) => {
            s.set("contextSize", value);
          }}
        />
      </Row>
      <Row
        label="Compaction automatique"
        hint="Condense l'historique ancien pour rester sous la limite de contexte."
      >
        <Toggle
          label="Compaction automatique"
          checked={s.autoCompaction}
          onChange={(value) => {
            s.set("autoCompaction", value);
          }}
        />
      </Row>
      <Row
        label="Résumé automatique"
        hint="Résume les longues conversations pour garder l'essentiel."
      >
        <Toggle
          label="Résumé automatique"
          checked={s.autoSummary}
          onChange={(value) => {
            s.set("autoSummary", value);
          }}
        />
      </Row>
    </Panel>
  );
}

function DeveloperPanel() {
  const s = useSettingsStore();
  const mode = useUiStore((st) => st.mode);
  const setMode = useUiStore((st) => st.setMode);
  return (
    <Panel
      title="Développeur"
      intro="Outils avancés, journalisation et diagnostics."
    >
      <Row
        label="Mode avancé"
        hint="Affiche l'activité de l'équipe, les modèles et les détails techniques."
      >
        <Toggle
          label="Mode avancé"
          checked={mode === "advanced"}
          onChange={(value) => {
            setMode(value ? "advanced" : "simple");
          }}
        />
      </Row>
      <Row label="Niveau de journalisation">
        <Select
          aria-label="Niveau de journalisation"
          value={s.logLevel}
          onChange={(e) => {
            s.set("logLevel", e.target.value as typeof s.logLevel);
          }}
          options={[
            { value: "error", label: "Erreurs" },
            { value: "warn", label: "Avertissements" },
            { value: "info", label: "Informations" },
            { value: "debug", label: "Débogage" },
          ]}
        />
      </Row>
      <Row
        label="Exposer les événements bruts"
        hint="Affiche le flux d'événements du moteur, sans filtrage."
      >
        <Toggle
          label="Exposer les événements bruts"
          checked={s.exposeRawEvents}
          onChange={(value) => {
            s.set("exposeRawEvents", value);
          }}
        />
      </Row>
      <Row
        label="Coûts et tokens en direct"
        hint="Montre la consommation au fil des échanges."
      >
        <Toggle
          label="Coûts et tokens en direct"
          checked={s.showLiveCost}
          onChange={(value) => {
            s.set("showLiveCost", value);
          }}
        />
      </Row>
      <Row
        label="Port du moteur"
        hint={
          isTauri()
            ? "Géré par l'application."
            : "Port local du moteur IA. Vide = valeur par défaut."
        }
      >
        {isTauri() ? (
          <span className="text-sm text-neutral">Géré par l'application</span>
        ) : (
          <NumberInput
            value={s.enginePort}
            onChange={(value) => {
              s.set("enginePort", value);
            }}
            placeholder="Auto"
            min={1}
            max={65535}
            step={1}
          />
        )}
      </Row>
      <Row
        label="Outils de développement"
        hint="Active la console de développement de la webview."
      >
        <Toggle
          label="Outils de développement"
          checked={s.devtools}
          onChange={(value) => {
            s.set("devtools", value);
          }}
        />
      </Row>
    </Panel>
  );
}

function PrivacyPanel() {
  const s = useSettingsStore();
  return (
    <Panel
      title="Confidentialité"
      intro="Rien ne quitte votre machine sans votre accord."
    >
      <Row
        label="Caviarder les secrets"
        hint="Masque clés et jetons détectés avant tout envoi au cloud."
      >
        <Toggle
          label="Caviarder les secrets"
          checked={s.redactSecrets}
          onChange={(value) => {
            s.set("redactSecrets", value);
          }}
        />
      </Row>
      <Row
        label="Mode 100 % local"
        hint="N'utilise que des modèles exécutés sur votre machine."
      >
        <Toggle
          label="Mode 100 % local"
          checked={s.localOnly}
          onChange={(value) => {
            s.set("localOnly", value);
          }}
        />
      </Row>
      <Row
        label="Télémétrie"
        hint="Partage de statistiques d'usage anonymes. Désactivée par défaut."
      >
        <Toggle
          label="Télémétrie"
          checked={s.telemetry}
          onChange={(value) => {
            s.set("telemetry", value);
          }}
        />
      </Row>
      <Row
        label="Effacer à la fermeture"
        hint="Supprime caches et données temporaires en quittant."
      >
        <Toggle
          label="Effacer à la fermeture"
          checked={s.clearOnQuit}
          onChange={(value) => {
            s.set("clearOnQuit", value);
          }}
        />
      </Row>
      <Row
        label="Chiffrement au repos"
        hint="Chiffre la base de données locale et les secrets stockés."
      >
        <Toggle
          label="Chiffrement au repos"
          checked={s.encryption}
          onChange={(value) => {
            s.set("encryption", value);
          }}
        />
      </Row>
    </Panel>
  );
}

const SHORTCUTS: Array<{ keys: string; action: string }> = [
  { keys: "Entrée", action: "Envoyer le message" },
  { keys: "Maj + Entrée", action: "Nouvelle ligne dans la saisie" },
  { keys: "Échap", action: "Fermer un menu ou une fenêtre" },
  { keys: "↑ / ↓", action: "Naviguer dans les listes déroulantes" },
];

function ShortcutsPanel() {
  return (
    <Panel
      title="Raccourcis clavier"
      intro="Les gestes clavier disponibles dans Elysium."
    >
      <dl className="mt-1 divide-y divide-rule">
        {SHORTCUTS.map((shortcut, index) => (
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
  const engineStatus = healthError
    ? "Injoignable — vérifiez qu'Elysium est bien démarré."
    : health === null
      ? "Vérification…"
      : `En ligne${
          advanced && health.version !== undefined
            ? ` · v${health.version}`
            : ""
        }`;

  return (
    <Panel title="À propos">
      <div className="flex animate-rise-in items-center gap-3">
        <LogoChip className="size-10 rounded-lg p-1.5" />
        <div>
          <p className="text-sm font-medium text-ink">Elysium</p>
          <p className="text-xs text-neutral">
            Environnement de développement IA open source
          </p>
        </div>
      </div>
      <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
        <dt className="text-neutral">Contexte</dt>
        <dd className="text-ink">
          {isTauri() ? "Application de bureau (Tauri)" : "Navigateur (dev)"}
        </dd>
        <dt className="text-neutral">Moteur IA</dt>
        <dd className="text-ink">{engineStatus}</dd>
      </dl>
      <div className="mt-4 flex flex-wrap gap-3 text-sm">
        <a
          href="https://github.com/"
          target="_blank"
          rel="noreferrer"
          className="rounded-sm text-muted underline-offset-2 hover:text-ink hover:underline"
        >
          Documentation ↗
        </a>
        <a
          href="https://github.com/"
          target="_blank"
          rel="noreferrer"
          className="rounded-sm text-muted underline-offset-2 hover:text-ink hover:underline"
        >
          Code source ↗
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
  | "memory"
  | "developer"
  | "privacy"
  | "shortcuts"
  | "about";

const SECTIONS: Array<{ id: SectionId; label: string }> = [
  { id: "general", label: "Général" },
  { id: "ai", label: "Intelligence artificielle" },
  { id: "caching", label: "Prompt caching" },
  { id: "agents", label: "Agents & permissions" },
  { id: "memory", label: "Contexte & mémoire" },
  { id: "developer", label: "Développeur" },
  { id: "privacy", label: "Confidentialité" },
  { id: "shortcuts", label: "Raccourcis clavier" },
  { id: "about", label: "À propos" },
];

export function Settings() {
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
      <PageHeader title="Réglages" action={<SavedIndicator />} />
      <div className="flex flex-col gap-8 p-6 md:flex-row md:gap-10">
        {/* Navigation des sections */}
        <nav
          aria-label="Sections des réglages"
          className="shrink-0 md:sticky md:top-0 md:w-56 md:self-start"
        >
          <ul className="flex gap-1 overflow-x-auto md:flex-col md:overflow-visible">
            {SECTIONS.map((item) => {
              const active = section === item.id;
              return (
                <li key={item.id} className="shrink-0">
                  <button
                    type="button"
                    aria-current={active ? "page" : undefined}
                    onClick={() => {
                      setSection(item.id);
                    }}
                    className={cx(
                      "w-full rounded-md px-3 py-2 text-left text-sm whitespace-nowrap",
                      "transition-colors duration-[var(--dur-fast)] ease-[var(--ease-out)]",
                      active
                        ? "bg-paper-3 font-medium text-ink"
                        : "text-muted hover:bg-paper-2 hover:text-ink",
                    )}
                  >
                    {item.label}
                  </button>
                </li>
              );
            })}
          </ul>
        </nav>

        {/* Panneau actif */}
        <div className="min-w-0 flex-1 pb-10 md:max-w-2xl">
          {section === "general" && <GeneralPanel />}
          {section === "ai" && <AiPanel />}
          {section === "caching" && <CachingPanel />}
          {section === "agents" && <AgentsPanel />}
          {section === "memory" && <MemoryPanel />}
          {section === "developer" && <DeveloperPanel />}
          {section === "privacy" && <PrivacyPanel />}
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
