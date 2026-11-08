import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { PageHeader } from "../components/layout/PageHeader";
import { ForceGraph } from "../components/memory/ForceGraph";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";
import { TextField } from "../components/ui/Field";
import { Modal } from "../components/ui/Modal";
import { Segmented } from "../components/ui/Segmented";
import { Select } from "../components/ui/Select";
import { ErrorState } from "../components/ui/ErrorState";
import { LoadingBlock, Spinner } from "../components/ui/Spinner";
import { useT, type TFunction } from "../i18n";
import type { MessageKey } from "../i18n/dictionaries";
import { cx } from "../lib/cx";
import { pickDirectory } from "../services/endpoint";
import { engine, toHumanMessage } from "../services/engine";
import { useProjectsStore } from "../stores/projects";
import { useUiStore } from "../stores/ui";
import type {
  MemoryContext,
  MemoryFileDetail,
  MemoryFileRow,
  MemoryGraph,
  MemoryItem,
  MemoryKind,
  MemoryOverview,
  MemoryTier,
} from "../types/engine";

type View = "items" | "files" | "context";
type FilesMode = "graph" | "list";
const KINDS: MemoryKind[] = ["decision", "constraint", "fact", "preference", "note", "task_result"];

const fmtDate = (iso: string | null): string =>
  iso === null ? "—" : new Date(/Z|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`).toLocaleString();
const fmtTokens = (n: number): string => new Intl.NumberFormat().format(n);

/* ————— Bandeau de chiffres ————— */

function OverviewStrip({ o, t }: { o: MemoryOverview; t: TFunction }) {
  const cells: Array<[string, string, string?]> = [
    [t("memory.stat.long"), String(o.items.long)],
    [t("memory.stat.short"), String(o.items.short)],
    [t("memory.stat.files"), String(o.files.count), o.files.last_scan_at !== null ? t("memory.stat.scanned", { when: fmtDate(o.files.last_scan_at) }) : t("memory.stat.neverScanned")],
    [t("memory.stat.context"), `${fmtTokens(o.context.tokens)} tok`, t("memory.stat.contextHint")],
    [t("memory.stat.saved"), `≈ ${fmtTokens(o.context.reread_tokens_avoided)} tok`, t("memory.stat.savedHint")],
  ];
  return (
    <dl className="grid grid-cols-2 gap-3 lg:grid-cols-5">
      {cells.map(([label, value, hint]) => (
        <div key={label} className="rounded-lg border border-rule bg-paper p-3">
          <dt className="text-xs text-neutral">{label}</dt>
          <dd className="mt-1 text-lg text-ink">{value}</dd>
          {hint !== undefined && <p className="mt-0.5 text-xs text-neutral">{hint}</p>}
        </div>
      ))}
    </dl>
  );
}

/* ————— Souvenirs (court / long terme) ————— */

interface Draft {
  id: string | null;
  tier: MemoryTier;
  kind: MemoryKind;
  title: string;
  content: string;
  pinned: boolean;
}
const EMPTY: Draft = { id: null, tier: "long", kind: "decision", title: "", content: "", pinned: false };

function ItemsView({ projectId, onChanged, t }: { projectId: string; onChanged: () => void; t: TFunction }) {
  const [tier, setTier] = useState<MemoryTier | "all">("all");
  const [kind, setKind] = useState<MemoryKind | "all">("all");
  const [q, setQ] = useState("");
  const [items, setItems] = useState<MemoryItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);
  const [toDelete, setToDelete] = useState<MemoryItem | null>(null);

  const latestLoad = useRef(0);
  const load = useCallback(() => {
    latestLoad.current += 1;
    const ticket = latestLoad.current;
    engine
      .listMemory(projectId, {
        ...(tier !== "all" ? { tier } : {}),
        ...(kind !== "all" ? { kind } : {}),
        q,
      })
      .then((r) => {
        if (ticket !== latestLoad.current) return; // une recherche plus récente a pris le relais
        setItems(r.items);
        setError(null);
      })
      .catch((err: unknown) => setError(toHumanMessage(err)));
  }, [projectId, tier, kind, q]);
  useEffect(() => {
    const timer = window.setTimeout(load, q === "" ? 0 : 250);
    return () => window.clearTimeout(timer);
  }, [load, q]);

  const act = (job: Promise<unknown>) =>
    job
      .then(() => {
        load();
        onChanged();
        return true;
      })
      .catch((err: unknown) => {
        setError(toHumanMessage(err));
        return false;
      });

  const save = (event: FormEvent) => {
    event.preventDefault();
    if (draft === null || draft.title.trim() === "") return;
    setSaving(true);
    const job =
      draft.id === null
        ? engine.createMemory(projectId, { tier: draft.tier, kind: draft.kind, title: draft.title, content: draft.content, pinned: draft.pinned })
        : engine.updateMemory(projectId, draft.id, { kind: draft.kind, title: draft.title, content: draft.content, pinned: draft.pinned });
    void act(job).then((saved) => {
      setSaving(false);
      if (saved) setDraft(null); // en cas d'échec, ce qui a été saisi reste là
    });
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end gap-3">
        <Segmented<MemoryTier | "all">
          label={t("memory.tier.label")}
          value={tier}
          onChange={setTier}
          options={[
            { value: "all", label: t("memory.tier.all") },
            { value: "long", label: t("memory.tier.long"), hint: t("memory.tier.long.hint") },
            { value: "short", label: t("memory.tier.short"), hint: t("memory.tier.short.hint") },
          ]}
        />
        <div className="w-44">
          <Select
            label={t("memory.kind.label")}
            value={kind}
            onChange={(e) => setKind(e.target.value as MemoryKind | "all")}
            options={[
              { value: "all", label: t("memory.kind.all") },
              ...KINDS.map((k) => ({ value: k, label: t(`memory.kind.${k}` as MessageKey) })),
            ]}
          />
        </div>
        <div className="min-w-48 flex-1">
          <TextField label={t("memory.search")} value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("memory.search.placeholder")} />
        </div>
        <Button variant="primary" onClick={() => setDraft({ ...EMPTY })}>
          {t("memory.add")}
        </Button>
      </div>

      {error !== null && <ErrorState message={error} onRetry={load} />}
      {items === null && error === null && <LoadingBlock label={t("memory.loading")} />}
      {items !== null && items.length === 0 && (
        <p className="rounded-lg border border-dashed border-rule px-4 py-8 text-sm text-neutral">{t("memory.items.empty")}</p>
      )}
      {items !== null && items.length > 0 && (
        <ul className="grid gap-3 md:grid-cols-2">
          {items.map((item) => (
            <li key={item.id} className="flex flex-col gap-2 rounded-lg border border-rule bg-paper p-4">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={item.tier === "long" ? "ok" : "info"}>
                  {item.tier === "long" ? t("memory.tier.long") : t("memory.tier.short")}
                </Badge>
                <span className="text-xs text-neutral">{t(`memory.kind.${item.kind}` as MessageKey)}</span>
                {item.pinned && <span className="text-xs text-ink">📌</span>}
                {item.source === "system" && <span className="text-xs text-neutral">· {t("memory.auto")}</span>}
              </div>
              <h3 className="text-sm font-medium text-ink">{item.title}</h3>
              {item.content !== "" && <p className="whitespace-pre-wrap break-words text-sm text-muted">{item.content}</p>}
              {item.expires_at !== null && (
                <p className="text-xs text-neutral">{t("memory.forgets", { when: fmtDate(item.expires_at) })}</p>
              )}
              <div className="mt-auto flex flex-wrap gap-2 pt-1">
                {item.tier === "short" && (
                  <Button className="h-7 px-2 text-xs" onClick={() => void act(engine.promoteMemory(projectId, item.id))}>
                    {t("memory.promote")}
                  </Button>
                )}
                <Button
                  className="h-7 px-2 text-xs"
                  onClick={() => void act(engine.updateMemory(projectId, item.id, { pinned: !item.pinned }))}
                >
                  {item.pinned ? t("memory.unpin") : t("memory.pin")}
                </Button>
                <Button
                  className="h-7 px-2 text-xs"
                  onClick={() =>
                    setDraft({ id: item.id, tier: item.tier, kind: item.kind, title: item.title, content: item.content, pinned: item.pinned })
                  }
                >
                  {t("memory.edit")}
                </Button>
                <Button variant="danger" className="h-7 px-2 text-xs" onClick={() => setToDelete(item)}>
                  {t("memory.delete")}
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <Modal open={draft !== null} title={draft?.id === null ? t("memory.add") : t("memory.edit")} onClose={() => setDraft(null)}>
        {draft !== null && (
          <form onSubmit={save} className="flex flex-col gap-3">
            {draft.id === null && (
              <Segmented<MemoryTier>
                label={t("memory.tier.label")}
                value={draft.tier}
                onChange={(v) => setDraft({ ...draft, tier: v })}
                options={[
                  { value: "long", label: t("memory.tier.long"), hint: t("memory.tier.long.hint") },
                  { value: "short", label: t("memory.tier.short"), hint: t("memory.tier.short.hint") },
                ]}
              />
            )}
            <Select
              label={t("memory.kind.label")}
              value={draft.kind}
              onChange={(e) => setDraft({ ...draft, kind: e.target.value as MemoryKind })}
              options={KINDS.map((k) => ({ value: k, label: t(`memory.kind.${k}` as MessageKey) }))}
            />
            <TextField label={t("memory.field.title")} value={draft.title} maxLength={200} onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
            <label className="flex flex-col gap-1.5 text-sm font-medium text-muted">
              {t("memory.field.content")}
              <textarea
                value={draft.content}
                onChange={(e) => setDraft({ ...draft, content: e.target.value })}
                rows={5}
                maxLength={8000}
                className="rounded-md border border-rule bg-paper px-3 py-2 text-sm font-normal text-ink"
              />
            </label>
            <label className="flex items-center gap-2 text-sm text-muted">
              <input type="checkbox" checked={draft.pinned} onChange={(e) => setDraft({ ...draft, pinned: e.target.checked })} />
              {t("memory.field.pinned")}
            </label>
            <div className="flex justify-end gap-2">
              <Button onClick={() => setDraft(null)}>{t("common.cancel")}</Button>
              <Button type="submit" variant="primary" loading={saving} disabled={draft.title.trim() === ""}>
                {t("common.save")}
              </Button>
            </div>
          </form>
        )}
      </Modal>

      <ConfirmDialog
        open={toDelete !== null}
        title={t("memory.delete.title")}
        body={toDelete?.title}
        confirmLabel={t("memory.delete")}
        cancelLabel={t("common.cancel")}
        onConfirm={() => {
          if (toDelete !== null) void act(engine.deleteMemory(projectId, toDelete.id));
          setToDelete(null);
        }}
        onCancel={() => setToDelete(null)}
      />
    </div>
  );
}

/* ————— Fichiers : arbre + graphe de voisinage ————— */

function MiniGraph({ detail, onOpen, t }: { detail: MemoryFileDetail; onOpen: (path: string) => void; t: TFunction }) {
  const left = detail.imported_by.slice(0, 7);
  const right = detail.imports.slice(0, 7);
  const rows = Math.max(left.length, right.length, 1);
  const height = Math.max(120, rows * 30 + 20);
  const midY = height / 2;
  const y = (i: number, n: number) => (n === 1 ? midY : 18 + (i * (height - 36)) / (n - 1));
  const short = (p: string) => (p.length > 26 ? `…${p.slice(-25)}` : p);
  const Node = ({ x, y: py, path, anchor }: { x: number; y: number; path: string; anchor: "start" | "end" }) => (
    <g className="cursor-pointer" onClick={() => onOpen(path)} role="link" aria-label={path}>
      <title>{path}</title>
      <circle cx={x} cy={py} r={4} className="fill-ink" />
      <text x={anchor === "start" ? x + 9 : x - 9} y={py + 4} textAnchor={anchor} className="fill-ink text-[10px] hover:underline">
        {short(path)}
      </text>
    </g>
  );
  return (
    <figure>
      <svg viewBox={`0 0 560 ${String(height)}`} className="w-full rounded-lg border border-rule bg-paper-2" role="img" aria-label={t("memory.graph.label")}>
        {left.map((n, i) => (
          <line key={`l${n.path}`} x1={150} y1={y(i, left.length)} x2={280} y2={midY} className="stroke-rule-strong" />
        ))}
        {right.map((n, i) => (
          <line key={`r${n.path}`} x1={280} y1={midY} x2={410} y2={y(i, right.length)} className="stroke-rule-strong" />
        ))}
        {left.map((n, i) => (
          <Node key={`ln${n.path}`} x={150} y={y(i, left.length)} path={n.path} anchor="end" />
        ))}
        {right.map((n, i) => (
          <Node key={`rn${n.path}`} x={410} y={y(i, right.length)} path={n.path} anchor="start" />
        ))}
        <circle cx={280} cy={midY} r={7} className="fill-accent" />
        <text x={280} y={midY - 12} textAnchor="middle" className="fill-ink text-[10px] font-medium">
          {short(detail.path.split("/").pop() ?? detail.path)}
        </text>
      </svg>
      <figcaption className="mt-1 flex justify-between text-xs text-neutral">
        <span>← {t("memory.graph.importedBy")}</span>
        <span>{t("memory.graph.imports")} →</span>
      </figcaption>
    </figure>
  );
}

function FileLinks({ title, links, onOpen }: { title: string; links: Array<{ path: string; summary: string }>; onOpen: (p: string) => void }) {
  if (links.length === 0) return null;
  return (
    <section>
      <h4 className="text-xs font-medium text-neutral">{title}</h4>
      <ul className="mt-1 flex flex-col gap-1">
        {links.map((l) => (
          <li key={l.path}>
            <button type="button" onClick={() => onOpen(l.path)} className="block w-full cursor-pointer rounded-md px-2 py-1 text-left hover:bg-paper-2">
              <span className="block truncate font-mono text-xs text-ink">{l.path}</span>
              {l.summary !== "" && <span className="block truncate text-xs text-neutral">{l.summary}</span>}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function FilesView({ projectId, overview, onChanged, t }: { projectId: string; overview: MemoryOverview; onChanged: () => void; t: TFunction }) {
  const [files, setFiles] = useState<MemoryFileRow[] | null>(null);
  const [graph, setGraph] = useState<MemoryGraph | null>(null);
  const [mode, setMode] = useState<FilesMode>("graph");
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<MemoryFileDetail | null>(null);
  const [q, setQ] = useState("");
  const [path, setPath] = useState("");
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(() => {
    engine
      .memoryFiles(projectId)
      .then((r) => setFiles(r.files))
      .catch((err: unknown) => setError(toHumanMessage(err)));
    engine
      .memoryGraph(projectId)
      .then(setGraph)
      .catch((err: unknown) => setError(toHumanMessage(err)));
  }, [projectId]);
  useEffect(load, [load]);

  useEffect(() => {
    if (selected === null) {
      setDetail(null);
      return;
    }
    engine
      .memoryFile(projectId, selected)
      .then(setDetail)
      .catch((err: unknown) => setError(toHumanMessage(err)));
  }, [projectId, selected]);

  const scan = (root?: string) => {
    setScanning(true);
    setError(null);
    setMessage(null);
    engine
      .scanMemory(projectId, root)
      .then((stats) => {
        setMessage(t("memory.scan.done", { files: stats.files, read: stats.read, unchanged: stats.unchanged }));
        load();
        onChanged();
      })
      .catch((err: unknown) => setError(toHumanMessage(err)))
      .finally(() => setScanning(false));
  };
  const choose = async () => {
    const picked = await pickDirectory();
    if (picked !== null) scan(picked);
  };

  const grouped = useMemo(() => {
    const filter = q.trim().toLowerCase();
    const map = new Map<string, MemoryFileRow[]>();
    for (const f of files ?? []) {
      if (filter !== "" && !f.path.toLowerCase().includes(filter) && !f.summary.toLowerCase().includes(filter)) continue;
      const dir = f.path.includes("/") ? f.path.slice(0, f.path.lastIndexOf("/")) : ".";
      map.set(dir, [...(map.get(dir) ?? []), f]);
    }
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [files, q]);

  const hasFolder = overview.folder !== null;
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="primary" loading={scanning} disabled={!hasFolder} onClick={() => scan()}>
          {t("memory.scan")}
        </Button>
        <Button onClick={() => void choose()}>{hasFolder ? t("memory.folder.change") : t("memory.folder.choose")}</Button>
        {hasFolder && <span className="min-w-0 truncate font-mono text-xs text-neutral" title={overview.folder ?? ""}>{overview.folder}</span>}
        {scanning && <Spinner />}
      </div>
      {!hasFolder && (
        <div className="flex max-w-xl flex-wrap items-center gap-2">
          <input
            value={path}
            onChange={(e) => setPath(e.target.value)}
            placeholder={t("preview.path.placeholder")}
            aria-label={t("preview.path.placeholder")}
            className="min-w-0 flex-1 rounded-md border border-rule bg-paper px-3 py-1.5 text-sm text-ink"
          />
          <Button disabled={path.trim() === ""} onClick={() => scan(path.trim())}>{t("preview.path.use")}</Button>
          <p className="w-full text-xs text-neutral">{t("memory.folder.hint")}</p>
        </div>
      )}
      {message !== null && <p role="status" className="text-sm text-ok">{message}</p>}
      {error !== null && <p role="alert" className="text-sm text-danger">{error}</p>}

      {files !== null && files.length === 0 ? (
        <p className="rounded-lg border border-dashed border-rule px-4 py-8 text-sm text-neutral">{t("memory.files.empty")}</p>
      ) : (
        <div className={cx("grid gap-4", mode === "graph" ? "lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]" : "lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]")}>
          <div className="flex min-h-0 flex-col gap-2">
            <Segmented<FilesMode>
              label={t("memory.view.files")}
              value={mode}
              onChange={setMode}
              options={[
                { value: "graph", label: t("memory.filesview.graph") },
                { value: "list", label: t("memory.filesview.list") },
              ]}
            />
            <TextField label={t("memory.search")} value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("memory.files.search")} />
            {mode === "graph" ? (
              <>
                {graph === null ? (
                  <LoadingBlock label={t("memory.loading")} />
                ) : (
                  graph.nodes.length > 0 && <ForceGraph nodes={graph.nodes} edges={graph.edges} selected={selected} query={q} onSelect={setSelected} />
                )}
                {graph !== null && graph.truncated && (
                  <p className="text-xs text-neutral">{t("memory.graphmap.truncated", { shown: graph.nodes.length, total: graph.total })}</p>
                )}
                {graph !== null && graph.nodes.length > 0 && graph.edges.length === 0 && (
                  <p className="text-xs text-neutral">{t("memory.graphmap.noLinks")}</p>
                )}
              </>
            ) : (
            <div className="max-h-[60vh] overflow-auto rounded-lg border border-rule bg-paper p-2">
              {grouped.map(([dir, rows]) => (
                <details key={dir} open={grouped.length < 12 || q !== ""} className="mb-1">
                  <summary className="cursor-pointer rounded-md px-2 py-1 font-mono text-xs text-muted hover:bg-paper-2">
                    {dir}/ <span className="text-neutral">({rows.length})</span>
                  </summary>
                  <ul>
                    {rows.map((f) => (
                      <li key={f.path}>
                        <button
                          type="button"
                          onClick={() => setSelected(f.path)}
                          className={cx(
                            "block w-full cursor-pointer rounded-md px-3 py-1 text-left hover:bg-paper-2",
                            selected === f.path && "bg-paper-3",
                          )}
                        >
                          <span className="flex items-baseline justify-between gap-2">
                            <span className="truncate font-mono text-xs text-ink">{f.path.split("/").pop()}</span>
                            <span className="shrink-0 text-[10px] text-neutral">
                              {f.imported_by > 0 ? `← ${String(f.imported_by)} ` : ""}
                              {f.imports > 0 ? `→ ${String(f.imports)}` : ""}
                            </span>
                          </span>
                          {f.summary !== "" && <span className="block truncate text-xs text-neutral">{f.summary}</span>}
                        </button>
                      </li>
                    ))}
                  </ul>
                </details>
              ))}
              {files === null && <LoadingBlock label={t("memory.loading")} />}
            </div>
            )}
          </div>

          <div className="min-w-0">
            {detail === null ? (
              <p className="rounded-lg border border-dashed border-rule px-4 py-8 text-sm text-neutral">{t("memory.files.pick")}</p>
            ) : (
              <div className="flex flex-col gap-3 rounded-lg border border-rule bg-paper p-4">
                <div>
                  <h3 className="break-all font-mono text-sm text-ink">{detail.path}</h3>
                  <p className="mt-0.5 text-xs text-neutral">
                    {detail.language ?? "—"} · {fmtTokens(detail.size)} {t("memory.bytes")} · {t("memory.scannedAt", { when: fmtDate(detail.scanned_at) })}
                  </p>
                </div>
                {detail.summary !== "" && <p className="text-sm text-muted">{detail.summary}</p>}
                <MiniGraph detail={detail} onOpen={setSelected} t={t} />
                {detail.symbols.length > 0 && (
                  <p className="text-xs text-muted">
                    <span className="text-neutral">{t("memory.symbols")} : </span>
                    {detail.symbols.join(", ")}
                  </p>
                )}
                {detail.external.length > 0 && (
                  <p className="text-xs text-muted">
                    <span className="text-neutral">{t("memory.external")} : </span>
                    {detail.external.join(", ")}
                  </p>
                )}
                <FileLinks title={t("memory.graph.importedBy")} links={detail.imported_by} onOpen={setSelected} />
                <FileLinks title={t("memory.graph.imports")} links={detail.imports} onOpen={setSelected} />
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/* ————— Ce que reçoivent les agents ————— */

function ContextView({ projectId, t }: { projectId: string; t: TFunction }) {
  const [ctx, setCtx] = useState<MemoryContext | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    engine
      .memoryContext(projectId)
      .then(setCtx)
      .catch((err: unknown) => setError(toHumanMessage(err)));
  }, [projectId]);
  if (error !== null) return <ErrorState message={error} />;
  if (ctx === null) return <LoadingBlock label={t("memory.loading")} />;
  return (
    <div className="flex flex-col gap-3">
      <p className="max-w-3xl text-sm text-muted">{t("memory.context.intro")}</p>
      <p className="text-xs text-neutral">
        {t("memory.context.size", { tokens: ctx.tokens, budget: ctx.budget_tokens, items: ctx.items, files: ctx.files })}
      </p>
      {ctx.text === "" ? (
        <p className="rounded-lg border border-dashed border-rule px-4 py-8 text-sm text-neutral">{t("memory.context.empty")}</p>
      ) : (
        <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap rounded-lg border border-rule bg-paper p-4 font-mono text-xs text-ink">{ctx.text}</pre>
      )}
    </div>
  );
}

/* ————— Page ————— */

export function Memory() {
  const t = useT();
  const { projects, status, fetch } = useProjectsStore();
  const lastProjectId = useUiStore((s) => s.lastProjectId);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [view, setView] = useState<View>("items");
  const [overview, setOverview] = useState<MemoryOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    void fetch();
  }, [fetch]);
  const active = useMemo(() => projects.filter((p) => p.status !== "archived"), [projects]);
  useEffect(() => {
    if (projectId === null && active.length > 0) {
      setProjectId(active.find((p) => p.id === lastProjectId)?.id ?? active[0]?.id ?? null);
    }
  }, [active, projectId, lastProjectId]);

  // Un projet supprimé ailleurs ne doit pas rester affiché ici.
  useEffect(() => {
    if (projectId !== null && status === "ready" && !active.some((p) => p.id === projectId)) {
      setProjectId(null);
      setOverview(null);
    }
  }, [active, projectId, status]);

  useEffect(() => {
    setOverview(null); // seulement au changement de projet : un rafraîchissement garde la vue
  }, [projectId]);

  useEffect(() => {
    if (projectId === null) return;
    let current = true;
    engine
      .memoryOverview(projectId)
      .then((o) => {
        if (!current) return;
        setOverview(o);
        setError(null);
      })
      .catch((err: unknown) => {
        if (current) setError(toHumanMessage(err));
      });
    return () => {
      current = false;
    };
  }, [projectId, tick]);
  const refresh = useCallback(() => setTick((n) => n + 1), []);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <PageHeader
        title={t("memory.title")}
        subtitle={t("memory.subtitle")}
        action={
          active.length > 0 ? (
            <div className="w-56">
              <Select
                aria-label={t("memory.project")}
                value={projectId ?? ""}
                onChange={(e) => setProjectId(e.target.value)}
                options={active.map((p) => ({ value: p.id, label: p.name }))}
              />
            </div>
          ) : undefined
        }
      />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 p-6 pb-12">
          {status === "loading" && projects.length === 0 && <LoadingBlock label={t("memory.loading")} />}
          {status !== "loading" && active.length === 0 && (
            <p className="rounded-lg border border-dashed border-rule px-4 py-8 text-sm text-neutral">{t("memory.noProject")}</p>
          )}
          {projectId !== null && (
            <>
              {error !== null && <ErrorState message={error} onRetry={refresh} />}
              {overview !== null && <OverviewStrip o={overview} t={t} />}
              <Segmented<View>
                label={t("memory.title")}
                value={view}
                onChange={setView}
                options={[
                  { value: "items", label: t("memory.view.items") },
                  { value: "files", label: t("memory.view.files") },
                  { value: "context", label: t("memory.view.context") },
                ]}
              />
              {view === "items" && <ItemsView key={projectId} projectId={projectId} onChanged={refresh} t={t} />}
              {view === "files" && overview !== null && (
                <FilesView key={projectId} projectId={projectId} overview={overview} onChanged={refresh} t={t} />
              )}
              {view === "context" && <ContextView key={`${projectId}-${String(tick)}`} projectId={projectId} t={t} />}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
