import { CHAT_EXECUTIONS } from "../../lib/labels";
import { useT } from "../../i18n";
import { SelectPill } from "./SelectPill";
import type { Execution, ExpertSubmode } from "../../types/engine";

/**
 * Sélecteur du mode d'exécution (Simple / Expert), en pastille compacte
 * (cf. SelectPill). Les libellés sont traduits en direct.
 */
export function ExecutionSelector({
  value,
  submode = "analyse",
  onChange,
  disabled = false,
  placement = "top",
}: {
  value: Execution;
  submode?: ExpertSubmode;
  onChange: (execution: Execution, submode?: ExpertSubmode) => void;
  disabled?: boolean;
  placement?: "top" | "bottom";
}) {
  const t = useT();
  return (
    <SelectPill<Execution | "expert-complete">
      ariaLabel={t("chat.exec.label")}
      title={t("chat.exec.label")}
      value={value === "expert" && submode === "complet" ? "expert-complete" : value}
      options={[
        ...CHAT_EXECUTIONS.map((e) => ({
          value: e.value,
          label: e.value === "expert" ? t("chat.exec.expertAnalyse") : t(e.labelKey),
          hint: t(e.hintKey),
        })),
        // Les agents proposent les fichiers ; chacun est relu avant d'être écrit.
        {
          value: "expert-complete" as const,
          label: t("chat.exec.expertComplete"),
          hint: t("chat.exec.expertComplete.hint"),
        },
      ]}
      onChange={(next) => {
        if (next === "expert-complete") onChange("expert", "complet");
        else if (next === "expert") onChange("expert", "analyse");
        else onChange(next);
      }}
      disabled={disabled}
      placement={placement}
    />
  );
}
