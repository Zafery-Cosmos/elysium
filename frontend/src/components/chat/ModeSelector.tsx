import { CHAT_MODES } from "../../lib/labels";
import { SelectPill } from "./SelectPill";
import type { ChatMode } from "../../types/engine";

/**
 * Sélecteur de mode de conversation, en pastille compacte (cf. SelectPill) :
 * montre le mode courant + un chevron, ouvre un petit panneau de choix.
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
  return (
    <SelectPill
      ariaLabel="Mode de conversation"
      title="Mode de conversation"
      value={value}
      options={CHAT_MODES}
      onChange={onChange}
      disabled={disabled}
      placement={placement}
    />
  );
}
