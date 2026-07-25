import { CHAT_MODES } from "../../lib/labels";
import { useT } from "../../i18n";
import { SelectPill } from "./SelectPill";
import type { ChatMode } from "../../types/engine";

/**
 * Sélecteur de mode de conversation, en pastille compacte (cf. SelectPill) :
 * montre le mode courant + un chevron, ouvre un petit panneau de choix.
 * Les libellés sont traduits en direct selon la langue de l'interface.
 */
export function ModeSelector({
  value,
  onChange,
  disabled = false,
  placement = "top",
}: {
  value: ChatMode;
  onChange: (mode: ChatMode) => void;
  disabled?: boolean;
  placement?: "top" | "bottom";
}) {
  const t = useT();
  return (
    <SelectPill
      ariaLabel={t("chat.mode.label")}
      title={t("chat.mode.label")}
      value={value}
      options={CHAT_MODES.map((m) => ({
        value: m.value,
        label: t(m.labelKey),
        hint: t(m.hintKey),
      }))}
      onChange={onChange}
      disabled={disabled}
      placement={placement}
    />
  );
}
