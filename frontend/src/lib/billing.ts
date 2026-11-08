import { isLocalProviderName } from "./labels";
import type { ProviderInfo } from "../types/engine";

/**
 * Comment on se connecte à un fournisseur, donc comment il est facturé :
 * - `subscription` : compte personnel via un CLI officiel (OAuth : Claude Code, Codex), sans clé ;
 * - `api` : clé API, facturée au token ;
 * - `local` : modèle qui tourne sur la machine (Ollama, LM Studio…).
 */
export type Billing = "subscription" | "api" | "local";

/** Ordre d'affichage : abonnement (OAuth), puis API, puis local. */
export const BILLING_ORDER: readonly Billing[] = ["subscription", "api", "local"];

export function providerBilling(provider: Pick<ProviderInfo, "name" | "kind" | "is_local">): Billing {
  if (provider.kind === "cli") return "subscription";
  if (provider.is_local === true || provider.kind === "local" || isLocalProviderName(provider.name)) {
    return "local";
  }
  return "api";
}

export interface BillingGroup<P> {
  billing: Billing;
  providers: P[];
}

/**
 * Range les fournisseurs par mode de connexion, dans l'ordre abonnement → API → local.
 * Dans un groupe, les fournisseurs configurés passent d'abord ; l'ordre d'origine est conservé ensuite.
 * Les groupes vides sont omis.
 */
export function groupByBilling<P extends Pick<ProviderInfo, "name" | "kind" | "is_local" | "configured">>(
  providers: readonly P[],
): BillingGroup<P>[] {
  return BILLING_ORDER.map((billing) => {
    const inGroup = providers.filter((p) => providerBilling(p) === billing);
    const configured = inGroup.filter((p) => p.configured === true);
    const others = inGroup.filter((p) => p.configured !== true);
    return { billing, providers: [...configured, ...others] };
  }).filter((g) => g.providers.length > 0);
}

/** Libellé lisible des connexions par abonnement (le moteur ne les nomme pas). */
export const CLI_PROVIDER_LABELS: Readonly<Record<string, string>> = {
  "claude-code": "Claude Code",
  codex: "Codex",
};
