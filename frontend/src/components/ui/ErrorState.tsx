import { Button } from "./Button";
import { EngineDiagnostics } from "./EngineDiagnostics";

export function ErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div
      role="alert"
      className="flex flex-col items-start gap-3 rounded-lg border border-danger/40 bg-paper px-6 py-8"
    >
      <p className="text-sm text-danger">{message}</p>
      {onRetry !== undefined && (
        <Button variant="ghost" onClick={onRetry}>
          Réessayer
        </Button>
      )}
      <EngineDiagnostics />
    </div>
  );
}
