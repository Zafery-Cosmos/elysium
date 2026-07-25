import { useEffect, useMemo, useState, type FormEvent } from "react";
import { PageHeader } from "../components/layout/PageHeader";
import { IconCheck, IconPlus, IconSearch } from "../components/layout/icons";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";
import { TextField } from "../components/ui/Field";
import { ErrorState } from "../components/ui/ErrorState";
import { LoadingBlock, Spinner } from "../components/ui/Spinner";
import { Modal } from "../components/ui/Modal";
import { Toggle } from "../components/ui/Toggle";
import { useMcpStore } from "../stores/mcp";
import { useT, type TFunction } from "../i18n";
import { cx } from "../lib/cx";
import type { McpCatalogEntry, McpServer } from "../types/engine";

/** Catégorie brute (donnée du moteur), ou chaîne vide pour « Autres ». */
function categoryKey(entry: { category?: string }): string {
  const raw = entry.category?.trim();
  return raw !== undefined && raw.length > 0 ? raw : "";
}

function categoryLabel(key: string, t: TFunction): string {
  return key.length > 0 ? key : t("mcp.otherCategory");
}

function TransportTag({ transport }: { transport?: string }) {
  if (transport === undefined || transport.length === 0) return null;
  return (
    <span className="rounded-sm border border-rule px-1.5 py-0.5 font-mono text-[0.68rem] text-neutral">
      {transport}
    </span>
  );
}

/* ————— Carte du catalogue ————— */

function CatalogCard({
  entry,
  installed,
  delay,
}: {
  entry: McpCatalogEntry;
  installed: boolean;
  delay: number;
}) {
  const t = useT();
  const install = useMcpStore((s) => s.install);
  const installing = useMcpStore((s) => s.installing);
  const busy = installing === entry.id;

  return (
    <article
      style={{ animationDelay: `${delay}ms` }}
      className="card-lift flex animate-rise-in flex-col gap-3 rounded-lg border border-rule bg-paper-2/50 px-5 py-4 hover:border-rule-strong"
    >
      <div className="flex items-start justify-between gap-3">
        <h3 className="min-w-0 truncate text-sm font-medium text-ink">
          {entry.name ?? entry.id}
        </h3>
        <TransportTag transport={entry.transport} />
      </div>
      {entry.description !== undefined && entry.description.length > 0 && (
        <p className="line-clamp-3 text-xs text-muted">{entry.description}</p>
      )}
      <div className="mt-auto flex items-center justify-between gap-2 pt-1">
        <span className="rounded-full bg-paper-3 px-2 py-0.5 text-[0.68rem] text-neutral">
          {categoryLabel(categoryKey(entry), t)}
        </span>
        {installed ? (
          <span className="flex items-center gap-1 text-xs text-ok">
            <IconCheck width={13} height={13} />
            {t("mcp.installedTag")}
          </span>
        ) : (
          <Button
            variant="ghost"
            loading={busy}
            onClick={() => {
              void install(entry.id);
            }}
          >
            {t("mcp.install")}
          </Button>
        )}
      </div>
    </article>
  );
}

/* ————— Carte serveur installé ————— */

function InstalledCard({
  server,
  delay,
}: {
  server: McpServer;
  delay: number;
}) {
  const t = useT();
  const setEnabled = useMcpStore((s) => s.setEnabled);
  const remove = useMcpStore((s) => s.remove);
  const mutatingId = useMcpStore((s) => s.mutatingId);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const enabled = server.enabled !== false;
  const busy = mutatingId === server.id;

  return (
    <article
      style={{ animationDelay: `${delay}ms` }}
      className="card-lift flex animate-rise-in flex-col gap-3 rounded-lg border border-rule bg-paper-2/50 px-5 py-4 hover:border-rule-strong"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-medium text-ink">
            {server.name ?? server.catalog_id ?? server.id}
          </h3>
          {server.category !== undefined && server.category.length > 0 && (
            <p className="mt-0.5 text-xs text-neutral">{server.category}</p>
          )}
        </div>
        <Badge tone="muted">{t("mcp.soon")}</Badge>
      </div>
      {server.description !== undefined && server.description.length > 0 && (
        <p className="line-clamp-2 text-xs text-muted">{server.description}</p>
      )}
      <div className="mt-auto flex items-center justify-between gap-2 pt-1">
        <label className="flex items-center gap-2 text-xs text-muted">
          <Toggle
            checked={enabled}
            disabled={busy}
            onChange={(value) => {
              void setEnabled(server.id, value);
            }}
            label={enabled ? t("mcp.disable") : t("mcp.enable")}
          />
          {enabled ? t("mcp.enable") : t("mcp.disable")}
        </label>
        <div className="flex items-center gap-2">
          {busy && <Spinner className="size-3.5" />}
          <button
            type="button"
            onClick={() => {
              setConfirmOpen(true);
            }}
            className={cx(
              "rounded-sm text-xs text-neutral underline-offset-2",
              "transition-colors duration-[var(--dur-fast)] ease-[var(--ease-out)] hover:text-danger hover:underline",
            )}
          >
            {t("mcp.remove")}
          </button>
        </div>
      </div>
      <ConfirmDialog
        open={confirmOpen}
        title={t("mcp.removeTitle")}
        body={t("mcp.removeBody")}
        confirmLabel={t("mcp.remove")}
        cancelLabel={t("common.cancel")}
        onConfirm={() => {
          setConfirmOpen(false);
          void remove(server.id);
        }}
        onCancel={() => {
          setConfirmOpen(false);
        }}
      />
    </article>
  );
}

/* ————— Modal serveur personnalisé ————— */

function CustomServerModal({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const t = useT();
  const addCustom = useMcpStore((s) => s.addCustom);
  const installing = useMcpStore((s) => s.installing);
  const actionError = useMcpStore((s) => s.actionError);
  const busy = installing === "custom";
  const [name, setName] = useState("");
  const [transport, setTransport] = useState("stdio");
  const [command, setCommand] = useState("");
  const [url, setUrl] = useState("");

  const onSubmit = async (e: FormEvent): Promise<void> => {
    e.preventDefault();
    const ok = await addCustom({
      name: name.trim(),
      transport: transport.trim(),
      ...(command.trim().length > 0 ? { command: command.trim() } : {}),
      ...(url.trim().length > 0 ? { url: url.trim() } : {}),
    });
    if (ok) {
      setName("");
      setCommand("");
      setUrl("");
      onClose();
    }
  };

  return (
    <Modal open={open} title={t("mcp.addCustom")} onClose={onClose}>
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          void onSubmit(e);
        }}
      >
        <TextField
          label="Nom"
          value={name}
          onChange={(e) => {
            setName(e.target.value);
          }}
          placeholder="Mon serveur MCP"
          required
        />
        <TextField
          label="Transport"
          value={transport}
          onChange={(e) => {
            setTransport(e.target.value);
          }}
          placeholder="stdio · sse · http"
        />
        <TextField
          label="Commande (stdio)"
          value={command}
          onChange={(e) => {
            setCommand(e.target.value);
          }}
          placeholder="npx -y @acme/mcp-server"
        />
        <TextField
          label="URL (sse / http)"
          type="url"
          value={url}
          onChange={(e) => {
            setUrl(e.target.value);
          }}
          placeholder="https://mon-serveur.exemple/mcp"
        />
        {actionError !== null && !busy && (
          <p role="alert" className="text-sm text-danger">
            {actionError}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            type="submit"
            variant="primary"
            loading={busy}
            disabled={name.trim().length === 0}
          >
            {t("common.add")}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

/* ————— Page ————— */

export function Mcp() {
  const t = useT();
  const { catalog, servers, status, error, fetch } = useMcpStore();
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<string>("all");
  const [customOpen, setCustomOpen] = useState(false);

  useEffect(() => {
    void fetch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const installedIds = useMemo(
    () =>
      new Set(
        servers
          .map((s) => s.catalog_id)
          .filter((id): id is string => typeof id === "string"),
      ),
    [servers],
  );

  const categories = useMemo(() => {
    const set = new Set<string>();
    for (const entry of catalog) set.add(categoryKey(entry));
    return [...set].sort((a, b) => a.localeCompare(b, "fr"));
  }, [catalog]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return catalog.filter((entry) => {
      if (category !== "all" && categoryKey(entry) !== category) return false;
      if (q.length === 0) return true;
      const haystack = `${entry.name ?? ""} ${entry.description ?? ""} ${
        entry.id
      }`.toLowerCase();
      return haystack.includes(q);
    });
  }, [catalog, query, category]);

  const grouped = useMemo(() => {
    const map = new Map<string, McpCatalogEntry[]>();
    for (const entry of filtered) {
      const key = categoryKey(entry);
      const list = map.get(key) ?? [];
      list.push(entry);
      map.set(key, list);
    }
    return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0], "fr"));
  }, [filtered]);

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      <PageHeader title={t("mcp.title")} subtitle={t("mcp.subtitle")} />
      <div className="flex flex-col gap-8 p-6">
        <p className="max-w-2xl animate-rise-in text-sm text-muted">
          {t("mcp.intro")}
        </p>

        {status === "loading" && catalog.length === 0 && (
          <LoadingBlock label={t("nav.conversationsLoading")} />
        )}
        {status === "error" && error !== null && (
          <ErrorState message={error} onRetry={() => void fetch()} />
        )}

        {(status === "ready" || catalog.length > 0 || servers.length > 0) && (
          <>
            {servers.length > 0 && (
              <section
                aria-label={t("mcp.installed")}
                className="flex animate-rise-in flex-col gap-3"
              >
                <h2 className="text-sm font-medium text-muted">
                  {t("mcp.installed")}
                </h2>
                <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {servers.map((server, index) => (
                    <InstalledCard
                      key={server.id}
                      server={server}
                      delay={Math.min(index, 8) * 40}
                    />
                  ))}
                </div>
              </section>
            )}

            {/* Recherche + filtre catégorie */}
            <div className="flex animate-rise-in flex-col gap-3 [animation-delay:60ms]">
              <div className="relative max-w-md">
                <IconSearch
                  width={15}
                  height={15}
                  className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-neutral"
                />
                <input
                  type="search"
                  value={query}
                  onChange={(e) => {
                    setQuery(e.target.value);
                  }}
                  placeholder={t("mcp.searchPlaceholder")}
                  aria-label={t("common.search")}
                  className={cx(
                    "w-full rounded-md border border-rule bg-paper py-2 pr-3 pl-9 text-sm text-ink placeholder:text-neutral",
                    "transition-colors duration-[var(--dur-fast)] ease-[var(--ease-out)] hover:border-rule-strong",
                  )}
                />
              </div>
              {categories.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {["all", ...categories].map((cat) => {
                    const selected = category === cat;
                    return (
                      <button
                        key={cat}
                        type="button"
                        aria-pressed={selected}
                        onClick={() => {
                          setCategory(cat);
                        }}
                        className={cx(
                          "h-7 rounded-full border px-3 text-xs",
                          "transition-colors duration-[var(--dur-fast)] ease-[var(--ease-out)]",
                          selected
                            ? "border-ink bg-ink font-medium text-paper"
                            : "border-rule bg-paper text-muted hover:border-rule-strong hover:text-ink",
                        )}
                      >
                        {cat === "all" ? t("common.all") : cat}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Catalogue groupé par catégorie */}
            {grouped.length === 0 ? (
              <p className="text-sm text-neutral">{t("mcp.empty")}</p>
            ) : (
              grouped.map(([cat, entries], groupIndex) => (
                <section
                  key={cat}
                  aria-label={cat}
                  className="flex animate-rise-in flex-col gap-3"
                  style={{ animationDelay: `${Math.min(groupIndex, 6) * 40}ms` }}
                >
                  <h2 className="text-sm font-medium text-muted">{cat}</h2>
                  <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
                    {entries.map((entry, index) => (
                      <CatalogCard
                        key={entry.id}
                        entry={entry}
                        installed={installedIds.has(entry.id)}
                        delay={Math.min(index, 8) * 30}
                      />
                    ))}
                  </div>
                </section>
              ))
            )}

            <div className="animate-rise-in">
              <Button
                variant="ghost"
                onClick={() => {
                  setCustomOpen(true);
                }}
              >
                <IconPlus width={14} height={14} />
                {t("mcp.addCustom")}
              </Button>
              <p className="mt-2 max-w-2xl text-xs text-neutral">
                {t("mcp.permissionsNote")}
              </p>
            </div>
          </>
        )}
      </div>

      <CustomServerModal
        open={customOpen}
        onClose={() => {
          setCustomOpen(false);
        }}
      />
    </div>
  );
}
