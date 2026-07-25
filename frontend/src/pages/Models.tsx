import { useEffect, useMemo, useState, type FormEvent } from "react";
import { PageHeader } from "../components/layout/PageHeader";
import { IconChevronDown, IconPlus, IconRefresh } from "../components/layout/icons";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { TextField } from "../components/ui/Field";
import { ErrorState } from "../components/ui/ErrorState";
import { Modal } from "../components/ui/Modal";
import { LoadingBlock, Spinner } from "../components/ui/Spinner";
import { useModelsStore } from "../stores/models";
import { useT, type TFunction } from "../i18n";
import {
  KNOWN_PROVIDERS,
  canonicalProviderName,
  isLocalProviderName,
  providerMeta,
  type ProviderMeta,
} from "../lib/labels";
import {
  costTierLabel,
  formatContextWindow,
  releaseYear,
} from "../lib/format";
import { cx } from "../lib/cx";
import type { ModelInfo, ProviderInfo } from "../types/engine";

interface ProviderView {
  meta: ProviderMeta;
  info: ProviderInfo | null;
}

/* ————— Lignes de modèles ————— */

function ModelLine({ model, t }: { model: ModelInfo; t: TFunction }) {
  const label =
    model.display_name ?? model.name ?? model.id ?? t("chat.model.default");
  const year = releaseYear(model.release_date);
  const context = formatContextWindow(model.context_window);
  const cost = costTierLabel(model.cost_tier);
  return (
    <li className="flex items-center gap-3 py-1.5">
      <span className="min-w-0 flex-1 truncate text-sm text-ink">{label}</span>
      {year !== null && (
        <span className="shrink-0 font-mono text-xs text-neutral">{year}</span>
      )}
      {context !== null && (
        <span className="shrink-0 font-mono text-xs text-neutral">{context}</span>
      )}
      {cost !== null && (
        <span
          aria-label={t("chat.cost", { value: cost })}
          className="w-9 shrink-0 text-right font-mono text-xs text-neutral"
        >
          {cost}
        </span>
      )}
    </li>
  );
}

function ModelList({ models, t }: { models: ModelInfo[]; t: TFunction }) {
  const [open, setOpen] = useState(false);
  if (models.length === 0) return null;
  return (
    <div className="border-t border-rule pt-2">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => {
          setOpen((v) => !v);
        }}
        className={cx(
          "flex items-center gap-1.5 rounded-sm text-xs text-muted",
          "transition-colors duration-[var(--dur-fast)] ease-[var(--ease-out)] hover:text-ink",
        )}
      >
        <IconChevronDown
          width={12}
          height={12}
          className={cx(
            "transition-transform duration-[var(--dur-base)] ease-[var(--ease-out)]",
            open && "rotate-180",
          )}
        />
        {t("models.count", { count: models.length })}
      </button>
      {open && (
        <ul className="mt-1.5 animate-fade-in divide-y divide-rule/60">
          {models.map((model, index) => (
            <ModelLine
              key={model.id ?? model.name ?? String(index)}
              model={model}
              t={t}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

/* ————— Résultat du test de connexion ————— */

function TestResultLine({ name, t }: { name: string; t: TFunction }) {
  const result = useModelsStore((s) => s.testResults[name]);
  if (result === undefined) return null;
  return (
    <p
      role="status"
      className={cx(
        "flex items-center gap-2 text-xs",
        result.reachable ? "text-ok" : "text-danger",
      )}
    >
      <span
        aria-hidden="true"
        className={cx(
          "size-1.5 rounded-full",
          result.reachable ? "bg-ok" : "bg-danger",
        )}
      />
      {result.reachable ? t("models.testOk") : (result.detail ?? t("models.testFail"))}
    </p>
  );
}

/* ————— Formulaire de configuration (accordéon) ————— */

function ConfigForm({
  meta,
  configured,
  onDone,
}: {
  meta: ProviderMeta;
  configured: boolean;
  onDone: () => void;
}) {
  const t = useT();
  const configure = useModelsStore((s) => s.configure);
  const savingProvider = useModelsStore((s) => s.savingProvider);
  const saveError = useModelsStore((s) => s.saveError);
  const test = useModelsStore((s) => s.test);
  const testingProvider = useModelsStore((s) => s.testingProvider);

  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const saving = savingProvider === meta.name;
  const testing = testingProvider === meta.name;
  const dirty = baseUrl.trim().length > 0 || apiKey.trim().length > 0;

  const onSubmit = async (e: FormEvent): Promise<void> => {
    e.preventDefault();
    const ok = await configure(meta.name, {
      ...(baseUrl.trim().length > 0 ? { base_url: baseUrl.trim() } : {}),
      ...(apiKey.trim().length > 0 ? { api_key: apiKey.trim() } : {}),
    });
    if (ok) {
      setApiKey("");
      onDone();
    }
  };

  return (
    <form
      className="flex animate-fade-in flex-col gap-3 border-t border-rule pt-3"
      onSubmit={(e) => {
        void onSubmit(e);
      }}
    >
      {meta.needsBaseUrl && (
        <TextField
          label={t("models.serverUrl")}
          type="url"
          value={baseUrl}
          onChange={(e) => {
            setBaseUrl(e.target.value);
          }}
          placeholder={
            meta.name === "ollama"
              ? "http://127.0.0.1:11434"
              : meta.name === "lmstudio"
                ? "http://127.0.0.1:1234/v1"
                : "https://mon-serveur.exemple/v1"
          }
        />
      )}
      <TextField
        label={t("models.apiKey")}
        type="password"
        autoComplete="off"
        value={apiKey}
        onChange={(e) => {
          setApiKey(e.target.value);
        }}
        placeholder={configured ? t("models.apiKey.saved") : "sk-…"}
        hint={
          configured
            ? t("models.apiKey.hintConfigured")
            : meta.needsApiKey
              ? t("models.apiKey.hintNew")
              : t("models.apiKey.hintOptional")
        }
      />
      {saveError !== null && !saving && (
        <p role="alert" className="text-sm text-danger">
          {saveError}
        </p>
      )}
      <TestResultLine name={meta.name} t={t} />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Button
          variant="ghost"
          loading={testing}
          onClick={() => {
            void test(meta.name);
          }}
        >
          {t("models.test")}
        </Button>
        <div className="flex gap-2">
          <Button variant="ghost" onClick={onDone}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" variant="primary" loading={saving} disabled={!dirty}>
            {t("common.save")}
          </Button>
        </div>
      </div>
    </form>
  );
}

/* ————— Carte fournisseur cloud ————— */

function ProviderCard({ view, delay }: { view: ProviderView; delay: number }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [saved, setSaved] = useState(false);
  const { meta, info } = view;
  const configured = info?.configured === true;
  const models = info?.models ?? [];
  const defaultModel = info?.default_model;
  const testResult = useModelsStore((s) => s.testResults[meta.name]);

  return (
    <article
      style={{ animationDelay: `${delay}ms` }}
      className="card-lift flex animate-rise-in flex-col gap-3 rounded-lg border border-rule bg-paper-2/50 px-5 py-4 hover:border-rule-strong"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-medium text-ink">{meta.label}</h3>
          <p className="mt-0.5 text-xs text-neutral">{t(meta.descKey)}</p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1.5">
          {configured ? (
            <Badge tone="ok">{t("models.configured")}</Badge>
          ) : (
            <Badge tone="muted">{t("models.notConfigured")}</Badge>
          )}
          {testResult !== undefined && (
            <Badge tone={testResult.reachable ? "ok" : "danger"}>
              {testResult.reachable ? t("models.reachable") : t("models.unreachable")}
            </Badge>
          )}
        </div>
      </div>

      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-neutral">
        {defaultModel !== undefined &&
          defaultModel !== null &&
          defaultModel.length > 0 && (
            <span>
              {t("models.defaultModel")}{" "}
              <span className="font-mono text-muted">{defaultModel}</span>
            </span>
          )}
        {models.length > 0 && (
          <span>{t("models.available", { count: models.length })}</span>
        )}
      </div>

      {saved && !open && (
        <p className="text-xs text-ok" role="status">
          {t("models.savedConfig")}
        </p>
      )}

      {open ? (
        <ConfigForm
          meta={meta}
          configured={configured}
          onDone={() => {
            setOpen(false);
            setSaved(true);
          }}
        />
      ) : (
        <div>
          <Button
            variant="ghost"
            onClick={() => {
              setOpen(true);
              setSaved(false);
            }}
          >
            {configured ? t("models.modify") : t("models.configure")}
          </Button>
        </div>
      )}

      <ModelList models={models} t={t} />
    </article>
  );
}

/* ————— Carte fournisseur local (Ollama, LM Studio) ————— */

function LocalProviderCard({ view, delay }: { view: ProviderView; delay: number }) {
  const t = useT();
  const fetch = useModelsStore((s) => s.fetch);
  const status = useModelsStore((s) => s.status);
  const [open, setOpen] = useState(false);
  const { meta, info } = view;
  const models = info?.models ?? [];
  const detected = models.length > 0;
  const reachable = info?.reachable;

  return (
    <article
      style={{ animationDelay: `${delay}ms` }}
      className="card-lift flex animate-rise-in flex-col gap-3 rounded-lg border border-rule bg-paper-2/50 px-5 py-4 hover:border-rule-strong"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-medium text-ink">{meta.label}</h3>
          <p className="mt-0.5 text-xs text-neutral">{t(meta.descKey)}</p>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {detected || reachable === true ? (
            <Badge tone="ok">{t("models.detected")}</Badge>
          ) : (
            <Badge tone="muted">{t("models.notDetected")}</Badge>
          )}
          <button
            type="button"
            title={t("models.refresh")}
            aria-label={`${t("models.refresh")} — ${meta.label}`}
            onClick={() => {
              void fetch();
            }}
            className={cx(
              "grid size-7 place-items-center rounded-md text-muted",
              "transition-colors duration-[var(--dur-fast)] ease-[var(--ease-out)]",
              "hover:bg-paper-3 hover:text-ink",
            )}
          >
            {status === "loading" ? (
              <Spinner className="size-3.5" />
            ) : (
              <IconRefresh width={14} height={14} />
            )}
          </button>
        </div>
      </div>

      {detected ? (
        <div>
          <p className="text-xs text-neutral">
            {t("models.installedList", { count: models.length })}
          </p>
          <ul className="mt-1 divide-y divide-rule/60">
            {models.map((model, index) => (
              <ModelLine
                key={model.id ?? model.name ?? String(index)}
                model={model}
                t={t}
              />
            ))}
          </ul>
        </div>
      ) : (
        <p className="text-xs text-neutral">
          {t("models.noneDetected")}{" "}
          {meta.hintKey !== undefined ? t(meta.hintKey) : ""}
        </p>
      )}

      {open ? (
        <ConfigForm
          meta={meta}
          configured={info?.configured === true}
          onDone={() => {
            setOpen(false);
          }}
        />
      ) : (
        <div>
          <Button
            variant="ghost"
            onClick={() => {
              setOpen(true);
            }}
          >
            {t("models.configureAddress")}
          </Button>
        </div>
      )}
    </article>
  );
}

/* ————— Modal fournisseur personnalisé ————— */

function CustomProviderModal({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const t = useT();
  const addCustom = useModelsStore((s) => s.addCustom);
  const adding = useModelsStore((s) => s.addingCustom);
  const addError = useModelsStore((s) => s.addCustomError);
  const [name, setName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [defaultModel, setDefaultModel] = useState("");

  const onSubmit = async (e: FormEvent): Promise<void> => {
    e.preventDefault();
    const ok = await addCustom({
      name: name.trim(),
      base_url: baseUrl.trim(),
      ...(apiKey.trim().length > 0 ? { api_key: apiKey.trim() } : {}),
      ...(defaultModel.trim().length > 0
        ? { default_model: defaultModel.trim() }
        : {}),
    });
    if (ok) {
      setName("");
      setBaseUrl("");
      setApiKey("");
      setDefaultModel("");
      onClose();
    }
  };

  return (
    <Modal open={open} title={t("models.addCustom")} onClose={onClose}>
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          void onSubmit(e);
        }}
      >
        <TextField
          label={t("models.custom.name")}
          value={name}
          onChange={(e) => {
            setName(e.target.value);
          }}
          placeholder={t("models.custom.name.placeholder")}
          required
        />
        <TextField
          label={t("models.custom.baseUrl")}
          type="url"
          value={baseUrl}
          onChange={(e) => {
            setBaseUrl(e.target.value);
          }}
          placeholder="https://mon-serveur.exemple/v1"
          hint={t("models.custom.baseUrl.hint")}
          required
        />
        <TextField
          label={t("models.custom.apiKey")}
          type="password"
          autoComplete="off"
          value={apiKey}
          onChange={(e) => {
            setApiKey(e.target.value);
          }}
          placeholder="sk-…"
        />
        <TextField
          label={t("models.custom.defaultModel")}
          value={defaultModel}
          onChange={(e) => {
            setDefaultModel(e.target.value);
          }}
          placeholder="llama-3.3-70b"
        />
        {addError !== null && !adding && (
          <p role="alert" className="text-sm text-danger">
            {addError}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            type="submit"
            variant="primary"
            loading={adding}
            disabled={name.trim().length === 0 || baseUrl.trim().length === 0}
          >
            {t("common.add")}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

/* ————— Page ————— */

export function Models() {
  const t = useT();
  const { providers, status, error, fetch } = useModelsStore();
  const [customOpen, setCustomOpen] = useState(false);

  useEffect(() => {
    void fetch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const { cloud, local } = useMemo(() => {
    const byName = new Map(
      providers.map((p) => [canonicalProviderName(p.name), p] as const),
    );
    const isLocal = (p: ProviderInfo): boolean =>
      p.kind === "local" || isLocalProviderName(p.name);

    const cloudViews: ProviderView[] = KNOWN_PROVIDERS.filter(
      (m) => !m.local,
    ).map((meta) => ({ meta, info: byName.get(meta.name) ?? null }));
    for (const p of providers) {
      const canonical = canonicalProviderName(p.name);
      if (isLocal(p)) continue;
      if (KNOWN_PROVIDERS.some((m) => m.name === canonical)) continue;
      cloudViews.push({ meta: providerMeta(p.name), info: p });
    }

    const localViews: ProviderView[] = KNOWN_PROVIDERS.filter(
      (m) => m.local,
    ).map((meta) => ({ meta, info: byName.get(meta.name) ?? null }));
    for (const p of providers) {
      const canonical = canonicalProviderName(p.name);
      if (!isLocal(p)) continue;
      if (KNOWN_PROVIDERS.some((m) => m.name === canonical)) continue;
      localViews.push({ meta: providerMeta(p.name), info: p });
    }

    return { cloud: cloudViews, local: localViews };
  }, [providers]);

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      <PageHeader title={t("models.title")} subtitle={t("models.subtitle")} />
      <div className="flex flex-col gap-8 p-6">
        <p className="max-w-2xl animate-rise-in text-sm text-muted">
          {t("models.intro")}
        </p>

        {status === "loading" && providers.length === 0 && (
          <LoadingBlock label={t("models.loading")} />
        )}
        {status === "error" && error !== null && (
          <ErrorState message={error} onRetry={() => void fetch()} />
        )}

        {(status === "ready" || providers.length > 0) && (
          <>
            <section
              aria-label={t("models.cloud")}
              className="flex animate-rise-in flex-col gap-3 [animation-delay:60ms]"
            >
              <h2 className="text-sm font-medium text-muted">{t("models.cloud")}</h2>
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
                {cloud.map((view, index) => (
                  <ProviderCard
                    key={view.meta.name}
                    view={view}
                    delay={Math.min(index, 8) * 40}
                  />
                ))}
                <button
                  type="button"
                  onClick={() => {
                    setCustomOpen(true);
                  }}
                  style={{ animationDelay: `${Math.min(cloud.length, 8) * 40}ms` }}
                  className={cx(
                    "card-lift flex min-h-28 animate-rise-in flex-col items-center justify-center gap-2",
                    "rounded-lg border border-dashed border-rule px-5 py-4 text-muted",
                    "hover:border-rule-strong hover:text-ink",
                  )}
                >
                  <IconPlus width={16} height={16} />
                  <span className="text-sm">{t("models.addCustom")}</span>
                  <span className="text-xs text-neutral">
                    {t("models.addCustom.sub")}
                  </span>
                </button>
              </div>
            </section>

            <section
              aria-label={t("models.local")}
              className="flex animate-rise-in flex-col gap-3 [animation-delay:140ms]"
            >
              <h2 className="text-sm font-medium text-muted">{t("models.local")}</h2>
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                {local.map((view, index) => (
                  <LocalProviderCard
                    key={view.meta.name}
                    view={view}
                    delay={Math.min(index, 8) * 40}
                  />
                ))}
              </div>
            </section>
          </>
        )}
      </div>

      <CustomProviderModal
        open={customOpen}
        onClose={() => {
          setCustomOpen(false);
        }}
      />
    </div>
  );
}
