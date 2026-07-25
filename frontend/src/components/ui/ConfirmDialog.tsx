import { Button } from "./Button";
import { Modal } from "./Modal";

/**
 * Confirmation modale accessible : Échap / clic sur le fond annulent,
 * le focus entre dans la boîte, l'action destructive utilise le ton danger.
 */
export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel,
  cancelLabel,
  danger = true,
  busy = false,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  body?: string;
  confirmLabel: string;
  cancelLabel: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <Modal open={open} title={title} onClose={onCancel}>
      {body !== undefined && (
        <p className="mb-5 text-sm text-muted">{body}</p>
      )}
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onCancel}>
          {cancelLabel}
        </Button>
        <Button
          variant={danger ? "danger" : "primary"}
          loading={busy}
          onClick={onConfirm}
        >
          {confirmLabel}
        </Button>
      </div>
    </Modal>
  );
}
