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
    <SelectPill
      ariaLabel={t("chat.exec.label")}
      title={t("chat.exec.label")}
      value={value}
      options={CHAT_EXECUTIONS.map((e) => ({
        value: e.value,
        label: t(e.labelKey),
        hint: t(e.hintKey),
      }))}
      onChange={onChange}
      disabled={disabled}
      placement={placement}
    />
  );
}
