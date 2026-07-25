import { ModeSelector } from "./ModeSelector";
import { ExecutionSelector } from "./ExecutionSelector";
import { ModelPicker } from "./ModelPicker";
import { useChatStore } from "../../stores/chat";

/**
 * Bande de contrôles compacte partagée par le fil de chat et l'accueil :
 * [Mode ▾] [Exécution ▾] [● Modèle ▾]. Câblée sur les préférences du store,
 * de sorte que le choix fait sur l'accueil est repris dans la conversation.
 */
export function ChatControls({
  disabled = false,
  placement = "top",
}: {
  disabled?: boolean;
  placement?: "top" | "bottom";
}) {
  const mode = useChatStore((s) => s.mode);
  const execution = useChatStore((s) => s.execution);
  const model = useChatStore((s) => s.model);
  const effort = useChatStore((s) => s.effort);

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <ModeSelector
        value={mode}
        onChange={(value) => {
          useChatStore.getState().setMode(value);
        }}
        disabled={disabled}
        placement={placement}
      />
      <ExecutionSelector
        value={execution}
        onChange={(value) => {
          useChatStore.getState().setExecution(value);
        }}
        disabled={disabled}
        placement={placement}
      />
      <ModelPicker
        model={model}
        effort={effort}
        onModelChange={(value) => {
          useChatStore.getState().setModel(value);
        }}
        onEffortChange={(value) => {
          useChatStore.getState().setEffort(value);
        }}
      />
    </div>
  );
}
