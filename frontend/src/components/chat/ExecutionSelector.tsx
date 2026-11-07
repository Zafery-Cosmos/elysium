import { CHAT_EXECUTIONS } from "../../lib/labels";
import { useT } from "../../i18n";
import { SelectPill } from "./SelectPill";
import type { Execution } from "../../types/engine";

/**
 * Sélecteur du mode d'exécution (Simple / Expert), en pastille compacte
 * (cf. SelectPill). Les libellés sont traduits en direct.
 */
export function ExecutionSelector({
  value,
  onChange,
  disabled = false,
  placement = "top",
}: {
  value: Execution;
  onChange: (execution: Execution) => void;
  disabled?: boolean;
  placement?: "top" | "bottom";
}) {
  const t = useT();
  return (
    <SelectPill<Execution | "expert-complete">
      ariaLabel={t("chat.exec.label")}
      title={t("chat.exec.label")}
      value={value}
      options={[
        ...CHAT_EXECUTIONS.map((e) => ({
          value: e.value,
          label: e.value === "expert" ? t("chat.exec.expertAnalyse") : t(e.labelKey),
          hint: t(e.hintKey),
        })),
        // « Complet » (les agents écrivent les fichiers sous validation) n'existe
        // pas encore : visible mais grisé, jamais sélectionnable.
        {
          value: "expert-complete" as const,
          label: t("chat.exec.expertComplete"),
          hint: t("chat.exec.expertComplete.hint"),
          disabled: true,
          badge: t("chat.exec.soon"),
        },
      ]}
      onChange={(next) => {
        if (next !== "expert-complete") onChange(next);
      }}
      disabled={disabled}
      placement={placement}
    />
  );
}
