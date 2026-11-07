import type { TFunction } from "../i18n";
import type { CliAccount } from "../services/engine";

/** « moi@mail.com · max » — ce qui permet de vérifier qui est réellement connecté. */
export function describeAccount(account: CliAccount | null | undefined, t: TFunction): string {
  if (account == null) return t("admin.account.unknown");
  const parts = [account.email, account.plan ?? account.method].filter(
    (p): p is string => typeof p === "string" && p.length > 0,
  );
  return parts.length > 0 ? parts.join(" · ") : t("admin.account.unknown");
}
