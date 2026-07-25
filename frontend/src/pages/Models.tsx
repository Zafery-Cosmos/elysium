import { useEffect, useMemo, useState, type FormEvent } from "react";
import { PageHeader } from "../components/layout/PageHeader";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { TextField } from "../components/ui/Field";
import { ErrorState } from "../components/ui/ErrorState";
import { LoadingBlock } from "../components/ui/Spinner";
import { useModelsStore } from "../stores/models";
import { KNOWN_PROVIDERS, providerMeta, type ProviderMeta } from "../lib/labels";
import type { ProviderInfo } from "../types/engine";

interface ProviderView {
  meta: ProviderMeta;
  info: ProviderInfo | null;
}

function ProviderCard({ view }: { view: ProviderView }) {
  const configure = useModelsStore((s) => s.configure);
  const savingProvider = useModelsStore((s) => s.savingProvider);
  const saveError = useModelsStore((s) => s.saveError);

  const [open, setOpen] = useState(false);
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [saved, setSaved] = useState(false);

  const { meta, info } = view;
  const configured = info?.configured === true;
  const reachable = info?.reachable;
  const modelCount = info?.models?.length ?? 0;
  const saving = savingProvider === meta.name;

  const onSubmit = async (e: FormEvent): Promise<void> => {
    e.preventDefault();
    setSaved(false);
    const ok = await configure(meta.name, {
      ...(baseUrl.trim().length > 0 ? { base_url: baseUrl.trim() } : {}),
      ...(apiKey.trim().length > 0 ? { api_key: apiKey.trim() } : {}),
    });
    if (ok) {
      // La clé ne reste jamais en mémoire du formulaire après envoi.
      setApiKey("");
      setSaved(true);
      setOpen(false);
    }
  };

  return (
    <article className="flex flex-col gap-3 rounded-lg border border-rule bg-paper-2/50 px-5 py-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-sm font-medium text-ink">{meta.label}</h2>
          <p className="mt-0.5 text-xs text-neutral">{meta.description}</p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1.5">
          {configured ? (
            <Badge tone="ok">Configuré</Badge>
          ) : (
            <Badge tone="muted">Non configuré</Badge>
          )}
          {configured && reachable === true && (
            <Badge tone="ok">Joignable</Badge>
          )}
          {configured && reachable === false && (
            <Badge tone="danger">Injoignable</Badge>
          )}
        </div>
      </div>

      {modelCount > 0 && (
        <p className="text-xs text-neutral">
          {String(modelCount)} modèle{modelCount > 1 ? "s" : ""} disponible
          {modelCount > 1 ? "s" : ""}
        </p>
      )}

      {saved && !open && (
        <p className="text-xs text-ok" role="status">
          Configuration enregistrée.
        </p>
      )}

      {open ? (
        <form
          className="flex flex-col gap-3 border-t border-rule pt-3"
          onSubmit={(e) => {
            void onSubmit(e);
          }}
        >
          {meta.needsBaseUrl && (
            <TextField
              label="URL du serveur"
              type="url"
              value={baseUrl}
              onChange={(e) => {
                setBaseUrl(e.target.value);
              }}
              placeholder={
                meta.name === "ollama"
                  ? "http://127.0.0.1:11434"
                  : "https://mon-serveur.exemple/v1"
              }
            />
          )}
          <TextField
            label="Clé API"
            type="password"
            autoComplete="off"
            value={apiKey}
            onChange={(e) => {
              setApiKey(e.target.value);
            }}
            placeholder={
              configured ? "Une clé est déjà enregistrée" : "sk-…"
            }
            hint={
              configured
                ? "La clé enregistrée n'est jamais affichée. Saisissez-en une nouvelle pour la remplacer."
                : meta.needsApiKey
                  ? "Stockée dans le trousseau du système, jamais en clair."
                  : "Facultative pour ce fournisseur."
            }
          />
          {saveError !== null && saving === false && (
            <p role="alert" className="text-sm text-danger">
              {saveError}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <Button
              variant="ghost"
              onClick={() => {
                setOpen(false);
                setApiKey("");
              }}
            >
              Annuler
            </Button>
            <Button
              type="submit"
              variant="primary"
              loading={saving}
              disabled={baseUrl.trim().length === 0 && apiKey.trim().length === 0}
            >
              Enregistrer
            </Button>
          </div>
        </form>
      ) : (
        <div>
          <Button
            variant="ghost"
            onClick={() => {
              setOpen(true);
              setSaved(false);
            }}
          >
            {configured ? "Modifier la configuration" : "Configurer"}
          </Button>
        </div>
      )}
    </article>
  );
}

export function Models() {
  const { providers, status, error, fetch } = useModelsStore();

  useEffect(() => {
    void fetch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Les cinq fournisseurs connus sont toujours affichés ; ceux renvoyés
  // par le moteur en plus s'ajoutent à la suite.
  const views = useMemo<ProviderView[]>(() => {
    const byName = new Map(
      providers.map((p) => [p.name.toLowerCase(), p] as const),
    );
    const known = KNOWN_PROVIDERS.map((meta) => ({
      meta,
      info: byName.get(meta.name) ?? null,
    }));
    const extra = providers
      .filter(
        (p) => !KNOWN_PROVIDERS.some((m) => m.name === p.name.toLowerCase()),
      )
      .map((p) => ({ meta: providerMeta(p.name), info: p }));
    return [...known, ...extra];
  }, [providers]);

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      <PageHeader
        title="Modèles"
        subtitle="Fournisseurs d'IA — cloud ou 100 % local"
      />
      <div className="p-6">
        {status === "loading" && (
          <LoadingBlock label="Interrogation des fournisseurs…" />
        )}
        {status === "error" && error !== null && (
          <ErrorState message={error} onRetry={() => void fetch()} />
        )}
        {status === "ready" && (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            {views.map((view) => (
              <ProviderCard key={view.meta.name} view={view} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
