import { CLI_PROVIDER_LABELS, groupByBilling, type Billing } from "./billing";
import { providerMeta } from "./labels";
import type { MessageKey, TFunction } from "../i18n";
import type { ProviderInfo } from "../types/engine";

const GROUP_LABEL: Record<Billing, MessageKey> = {
  subscription: "chat.model.group.subscription",
  api: "chat.model.group.api",
  local: "chat.model.group.local",
};

export interface GroupedModelOption {
  value: string;
  label: string;
  group: string;
}

/**
 * Options de liste déroulante pour choisir un modèle, rangées par mode de connexion
 * (abonnement OAuth, API, local). `providerInLabel` préfixe le libellé du nom du fournisseur.
 */
export function groupedModelOptions(
  providers: readonly ProviderInfo[],
  t: TFunction,
  { onlyConfigured = false, providerInLabel = false }: { onlyConfigured?: boolean; providerInLabel?: boolean } = {},
): GroupedModelOption[] {
  const usable = providers.filter((p) => (!onlyConfigured || p.configured === true) && (p.models?.length ?? 0) > 0);
  const out: GroupedModelOption[] = [];
  for (const section of groupByBilling(usable)) {
    for (const p of section.providers) {
      const providerName = p.label ?? CLI_PROVIDER_LABELS[p.name] ?? providerMeta(p.name).label;
      for (const m of p.models ?? []) {
        const id = m.id ?? m.name;
        if (id === undefined || id.length === 0) continue;
        const modelName = m.display_name ?? m.name ?? id;
        out.push({
          value: `${p.name}:${id}`,
          label: providerInLabel ? `${providerName} · ${modelName}` : modelName,
          group: t(GROUP_LABEL[section.billing]),
        });
      }
    }
  }
  return out;
}
