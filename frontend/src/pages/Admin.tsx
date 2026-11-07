import { useEffect, useMemo, type ReactNode } from "react";
import { PageHeader } from "../components/layout/PageHeader";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { CliAccountActions } from "../components/ui/CliAccountActions";
import { ErrorState } from "../components/ui/ErrorState";
import { Segmented } from "../components/ui/Segmented";
import { Spinner } from "../components/ui/Spinner";
import { useT, type TFunction } from "../i18n";
import { describeAccount } from "../lib/account";
import { useAdminStore, type AdminPeriod } from "../stores/admin";
import { useSettingsStore } from "../stores/settings";
import type { CliProvider } from "../stores/ui";
import type {
  AdminDay,
  AdminGroup,
  AdminOverview,
  AdminProviderStatus,
  AdminQuota,
} from "../types/engine";

const REFRESH_MS = 30_000;

const PROVIDER_LABELS: Record<string, string> = {
  "claude-code": "Claude Code",
  codex: "Codex",
  anthropic: "Anthropic",
  openai: "OpenAI",
  google: "Google",
  xai: "xAI",
  ollama: "Ollama",
  lmstudio: "LM Studio",
  openrouter: "OpenRouter",
  deepseek: "DeepSeek",
  mistral: "Mistral",
};
const providerLabel = (name: string): string => PROVIDER_LABELS[name] ?? name;

/** Nuances de gris (thème monochrome) : la légende et les valeurs lèvent toute ambiguïté. */
const SHADES = ["bg-ink", "bg-muted", "bg-neutral", "bg-rule-strong"] as const;

/* ————— Formatage ————— */

interface Formatters {
  count: (n: number) => string;
  compact: (n: number) => string;
  usd: (n: number) => string;
  duration: (ms: number) => string;
  when: (iso: string | null) => string;
  resetIn: (epochSeconds: number) => string;
  uptime: (seconds: number) => string;
}

function makeFormatters(lang: string): Formatters {
  const count = new Intl.NumberFormat(lang);
  const compact = new Intl.NumberFormat(lang, { notation: "compact", maximumFractionDigits: 1 });
  const usd = new Intl.NumberFormat(lang, { style: "currency", currency: "USD" });
  const relative = new Intl.RelativeTimeFormat(lang, { numeric: "auto" });
  const dateTime = new Intl.DateTimeFormat(lang, { dateStyle: "short", timeStyle: "short" });
  return {
    count: (n) => count.format(n),
    compact: (n) => compact.format(n),
    usd: (n) => usd.format(n),
    duration: (ms) => (ms < 1000 ? `${String(ms)} ms` : `${(ms / 1000).toFixed(1)} s`),
    // L'horodatage du moteur est en UTC sans fuseau : on le lit comme tel.
    when: (iso) =>
      iso === null ? "—" : dateTime.format(new Date(/Z|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`)),
    resetIn: (epochSeconds) => {
      const seconds = epochSeconds - Date.now() / 1000;
      const minutes = Math.round(seconds / 60);
      if (Math.abs(minutes) < 60) return relative.format(minutes, "minute");
      const hours = Math.round(minutes / 60);
      if (Math.abs(hours) < 48) return relative.format(hours, "hour");
      return relative.format(Math.round(hours / 24), "day");
    },
    uptime: (seconds) => {
      const d = Math.floor(seconds / 86400);
      const h = Math.floor((seconds % 86400) / 3600);
      const m = Math.floor((seconds % 3600) / 60);
      return d > 0 ? `${String(d)} d ${String(h)} h` : h > 0 ? `${String(h)} h ${String(m)} min` : `${String(m)} min`;
    },
  };
}

/* ————— Primitives ————— */

function Section({
  id,
  title,
  hint,
  children,
}: {
  id: string;
  title: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <section aria-labelledby={id} className="animate-rise-in">
      <h2 id={id} className="text-md text-ink">
        {title}
      </h2>
      {hint !== undefined && <p className="mt-1 max-w-2xl text-xs text-neutral">{hint}</p>}
      <div className="mt-3">{children}</div>
    </section>
  );
}

function Empty({ children }: { children: string }) {
  return (
    <p className="rounded-lg border border-dashed border-rule px-4 py-6 text-sm text-neutral">
      {children}
    </p>
  );
}

/* ————— Connexions ————— */

function ConnectionCard({
  provider,
  stats,
  fmt,
  t,
  actions,
}: {
  provider: AdminProviderStatus;
  stats: AdminGroup | undefined;
  fmt: Formatters;
  t: TFunction;
  actions?: ReactNode;
}) {
  const isCli = provider.kind === "cli";
  const status =
    provider.signed_in === true
      ? { tone: "ok" as const, label: t("admin.signedIn") }
      : provider.signed_in === false
        ? { tone: "danger" as const, label: t("admin.signedOut") }
        : { tone: "muted" as const, label: t("admin.keyStored") };
  return (
    <li className="flex flex-col gap-2 rounded-lg border border-rule bg-paper p-4">
      <div className="flex items-center justify-between gap-2">
        <h3 className="truncate text-sm font-medium text-ink">{providerLabel(provider.name)}</h3>
        <Badge tone={status.tone} live={provider.signed_in === true}>
          {status.label}
        </Badge>
      </div>
      <p className="text-xs text-neutral">{isCli ? t("admin.kind.cli") : t("admin.kind.api")}</p>
      {provider.signed_in === true && (
        // Qui est réellement connecté : permet de vérifier le « Connecté ».
        <p className="break-words text-xs text-ink">{describeAccount(provider.account, t)}</p>
      )}
      {provider.signed_in === false && provider.detail !== null && (
        <p className="text-xs text-danger">{provider.detail}</p>
      )}
      <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
        <dt className="text-neutral">{t("admin.defaultModel")}</dt>
        <dd className="truncate text-right text-ink">{provider.default_model}</dd>
        <dt className="text-neutral">{t("admin.kpi.calls")}</dt>
        <dd className="text-right text-ink">{fmt.count(stats?.calls ?? 0)}</dd>
      </dl>
      {actions}
    </li>
  );
}

/* ————— Quotas ————— */

function QuotaCard({ quota, fmt, t }: { quota: AdminQuota; fmt: Formatters; t: TFunction }) {
  const windowLabel = (name: string): string =>
    name === "five_hour"
      ? t("admin.quota.five_hour")
      : name === "seven_day"
        ? t("admin.quota.seven_day")
        : t("admin.quota.other", { name });
  return (
    <li className="rounded-lg border border-rule bg-paper p-4">
      <h3 className="text-sm font-medium text-ink">{providerLabel(quota.provider)}</h3>
      <div className="mt-3 flex flex-col gap-4">
        {quota.windows.map((w) => {
          const pct = Math.min(100, Math.max(0, Math.round(w.utilization * 100)));
          const label = windowLabel(w.name);
          return (
            <div key={w.name}>
              <div className="flex items-baseline justify-between gap-2 text-xs">
                <span className="text-ink">{label}</span>
                <span className={pct >= 85 ? "text-danger" : "text-muted"}>
                  {t("admin.quota.used", { pct })}
                </span>
              </div>
              <div
                role="progressbar"
                aria-label={label}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={pct}
                className="mt-1.5 h-2 overflow-hidden rounded-full bg-paper-3"
              >
                <div
                  className={`h-full rounded-full ${pct >= 85 ? "bg-danger" : "bg-ink"}`}
                  style={{ width: `${String(pct)}%` }}
                />
              </div>
              {w.resets_at !== null && (
                <p className="mt-1 text-xs text-neutral">
                  {t("admin.quota.resets", { when: fmt.resetIn(w.resets_at) })}
                </p>
              )}
            </div>
          );
        })}
      </div>
    </li>
  );
}

/* ————— Consommation ————— */

function Kpi({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-rule bg-paper p-4" title={hint}>
      <dt className="text-xs text-neutral">{label}</dt>
      <dd className="mt-1 text-xl font-semibold tracking-tight text-ink">{value}</dd>
    </div>
  );
}

function DayChart({
  days,
  fmt,
  t,
}: {
  days: AdminDay[];
  fmt: Formatters;
  t: TFunction;
}) {
  const model = useMemo(() => {
    const providers = [...new Set(days.map((d) => d.provider))].sort();
    const byDay = new Map<string, Map<string, number>>();
    for (const d of days) {
      const row = byDay.get(d.day) ?? new Map<string, number>();
      row.set(d.provider, (row.get(d.provider) ?? 0) + d.input_tokens + d.output_tokens);
      byDay.set(d.day, row);
    }
    const columns = [...byDay.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([day, row]) => ({
        day,
        row,
        total: [...row.values()].reduce((sum, v) => sum + v, 0),
      }));
    const max = Math.max(1, ...columns.map((c) => c.total));
    return { providers, columns, max };
  }, [days]);

  if (model.columns.length === 0) return <Empty>{t("admin.chart.empty")}</Empty>;

  return (
    <div className="rounded-lg border border-rule bg-paper p-4">
      <ul className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted" aria-label={t("admin.chart.title")}>
        {model.providers.map((p, i) => (
          <li key={p} className="flex items-center gap-1.5">
            <span aria-hidden="true" className={`size-2.5 rounded-sm ${SHADES[i % SHADES.length] ?? "bg-ink"}`} />
            {providerLabel(p)}
          </li>
        ))}
      </ul>
      <div className="overflow-x-auto">
        <div className="flex h-40 min-w-full items-end gap-1" role="list">
          {model.columns.map((c) => (
            <div
              key={c.day}
              role="listitem"
              title={`${t("admin.chart.day", { day: c.day, tokens: fmt.count(c.total) })}${model.providers
                .filter((p) => c.row.has(p))
                .map((p) => `\n${providerLabel(p)} · ${fmt.count(c.row.get(p) ?? 0)}`)
                .join("")}`}
              className="flex h-full min-w-2 flex-1 flex-col justify-end"
            >
              <div
                className="flex w-full flex-col-reverse overflow-hidden rounded-t-sm"
                style={{ height: `${String(Math.max(2, (c.total / model.max) * 100))}%` }}
              >
                {model.providers.map((p, i) => {
                  const v = c.row.get(p) ?? 0;
                  return v === 0 ? null : (
                    <div
                      key={p}
                      className={SHADES[i % SHADES.length] ?? "bg-ink"}
                      style={{ height: `${String((v / c.total) * 100)}%` }}
                    />
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </div>
      <p className="mt-2 flex justify-between text-xs text-neutral">
        <span>{model.columns[0]?.day}</span>
        <span>{model.columns[model.columns.length - 1]?.day}</span>
      </p>
    </div>
  );
}

function UsageTable({
  caption,
  keyLabel,
  rows,
  fmt,
  t,
}: {
  caption: string;
  keyLabel: string;
  rows: AdminGroup[];
  fmt: Formatters;
  t: TFunction;
}) {
  if (rows.length === 0) return null;
  const th = "px-3 py-2 text-right text-xs font-medium text-neutral";
  return (
    <div className="overflow-x-auto rounded-lg border border-rule bg-paper">
      <table className="w-full min-w-[640px] text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="border-b border-rule">
          <tr>
            <th scope="col" className="px-3 py-2 text-left text-xs font-medium text-neutral">
              {keyLabel}
            </th>
            <th scope="col" className={th}>{t("admin.table.calls")}</th>
            <th scope="col" className={th}>{t("admin.table.in")}</th>
            <th scope="col" className={th}>{t("admin.table.out")}</th>
            <th scope="col" className={th}>{t("admin.table.errors")}</th>
            <th scope="col" className={th}>{t("admin.table.latency")}</th>
            <th scope="col" className={th}>{t("admin.table.last")}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-rule">
          {rows.map((r) => (
            <tr key={r.key}>
              <th scope="row" className="max-w-56 truncate px-3 py-2 text-left font-normal text-ink">
                {r.key}
              </th>
              <td className="px-3 py-2 text-right text-ink">{fmt.count(r.calls)}</td>
              <td className="px-3 py-2 text-right text-muted">{fmt.compact(r.input_tokens)}</td>
              <td className="px-3 py-2 text-right text-muted">{fmt.compact(r.output_tokens)}</td>
              <td className={`px-3 py-2 text-right ${r.errors > 0 ? "text-danger" : "text-muted"}`}>
                {r.errors > 0
                  ? `${fmt.count(r.errors)} (${String(Math.round((r.errors / r.calls) * 100))} %)`
                  : "0"}
              </td>
              <td className="px-3 py-2 text-right text-muted">{fmt.duration(r.avg_duration_ms)}</td>
              <td className="px-3 py-2 text-right text-muted">{fmt.when(r.last_used)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ————— Page ————— */

const isCliId = (name: string): name is CliProvider =>
  name === "claude-code" || name === "codex";

function Content({
  data,
  fmt,
  t,
  onChanged,
}: {
  data: AdminOverview;
  fmt: Formatters;
  t: TFunction;
  onChanged: () => void;
}) {
  const stats = new Map(data.by_provider.map((g) => [g.key, g]));
  const hasCli = data.providers.some((p) => p.kind === "cli");
  const actionsFor = (p: AdminProviderStatus): ReactNode => {
    if (p.kind !== "cli" || !isCliId(p.name)) return undefined;
    return (
      <CliAccountActions
        id={p.name}
        signedIn={p.signed_in}
        installed={p.installed !== false}
        onChanged={onChanged}
      />
    );
  };
  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-10 p-6 pb-12">
      <Section
        id="adm-conn"
        title={t("admin.connections")}
        hint={hasCli ? t("admin.connections.hint") : undefined}
      >
        {data.providers.length === 0 ? (
          <Empty>{t("admin.connections.empty")}</Empty>
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {data.providers.map((p) => (
              <ConnectionCard
                key={p.name}
                provider={p}
                stats={stats.get(p.name)}
                fmt={fmt}
                t={t}
                actions={actionsFor(p)}
              />
            ))}
          </ul>
        )}
      </Section>

      <Section id="adm-quota" title={t("admin.quota.title")}>
        {data.quotas.length === 0 ? (
          <Empty>{t("admin.quota.empty")}</Empty>
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2">
            {data.quotas.map((q) => (
              <QuotaCard key={q.provider} quota={q} fmt={fmt} t={t} />
            ))}
          </ul>
        )}
      </Section>

      <Section
        id="adm-usage"
        title={t("admin.usage.title")}
        hint={hasCli ? t("admin.usage.cliNote") : undefined}
      >
        <dl className="grid grid-cols-2 gap-3 lg:grid-cols-5">
          <Kpi label={t("admin.kpi.calls")} value={fmt.count(data.totals.calls)} />
          <Kpi label={t("admin.kpi.in")} value={fmt.compact(data.totals.input_tokens)} />
          <Kpi label={t("admin.kpi.out")} value={fmt.compact(data.totals.output_tokens)} />
          <Kpi label={t("admin.kpi.errors")} value={fmt.count(data.totals.errors)} />
          <Kpi
            label={t("admin.kpi.cost")}
            value={fmt.usd(data.totals.cost_usd)}
            hint={t("admin.kpi.cost.hint")}
          />
        </dl>
        <h3 className="mt-6 mb-2 text-sm font-medium text-ink">{t("admin.chart.title")}</h3>
        <DayChart days={data.by_day} fmt={fmt} t={t} />
        <div className="mt-6 flex flex-col gap-4">
          <UsageTable
            caption={t("admin.reliability.title")}
            keyLabel={t("admin.table.provider")}
            rows={data.by_provider.map((g) => ({ ...g, key: providerLabel(g.key) }))}
            fmt={fmt}
            t={t}
          />
          <UsageTable
            caption={t("admin.byModel.title")}
            keyLabel={t("admin.table.model")}
            rows={data.by_model}
            fmt={fmt}
            t={t}
          />
          <UsageTable
            caption={t("admin.byAgent.title")}
            keyLabel={t("admin.table.agent")}
            rows={data.by_agent}
            fmt={fmt}
            t={t}
          />
        </div>
      </Section>

      <Section id="adm-errors" title={t("admin.errors.title")}>
        {data.recent_errors.length === 0 ? (
          <Empty>{t("admin.errors.none")}</Empty>
        ) : (
          <ul className="divide-y divide-rule rounded-lg border border-rule bg-paper">
            {data.recent_errors.map((e) => (
              <li key={`${e.at}-${e.provider}-${e.message ?? ""}`} className="px-4 py-3 text-sm">
                <p className="flex flex-wrap items-baseline gap-x-2 text-ink">
                  <span className="font-medium">{providerLabel(e.provider)}</span>
                  <span className="text-xs text-neutral">
                    {e.model} · {fmt.when(e.at)}
                  </span>
                </p>
                {e.message !== null && <p className="mt-0.5 break-words text-xs text-danger">{e.message}</p>}
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section id="adm-actions" title={t("admin.actions.title")} hint={t("admin.actions.hint")}>
        {data.recent_actions.length === 0 ? (
          <Empty>{t("admin.actions.none")}</Empty>
        ) : (
          <ul className="divide-y divide-rule rounded-lg border border-rule bg-paper">
            {data.recent_actions.map((a) => (
              <li
                key={`${a.at}-${a.agent ?? ""}-${a.tool ?? ""}`}
                className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5 text-sm"
              >
                <span className="text-ink">
                  {a.agent ?? "—"} <span className="text-neutral">→</span>{" "}
                  <span className="font-mono text-xs">{a.tool ?? "?"}</span>
                </span>
                <span className="text-xs text-neutral">
                  {a.status ?? ""} · {fmt.when(a.at)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section id="adm-engine" title={t("admin.engine.title")}>
        <dl className="grid max-w-sm grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-sm">
          <dt className="text-neutral">{t("admin.engine.version")}</dt>
          <dd className="text-right text-ink">v{data.engine.version}</dd>
          <dt className="text-neutral">{t("admin.engine.uptime")}</dt>
          <dd className="text-right text-ink">{fmt.uptime(data.engine.uptime_s)}</dd>
        </dl>
      </Section>
    </div>
  );
}

export function Admin() {
  const t = useT();
  const lang = useSettingsStore((s) => s.language);
  const { overview, status, error, days, setDays, fetch } = useAdminStore();
  const fmt = useMemo(() => makeFormatters(lang), [lang]);
  useEffect(() => {
    void fetch();
    const id = setInterval(() => {
      void fetch(true);
    }, REFRESH_MS);
    return () => {
      clearInterval(id);
    };
  }, [fetch]);

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      <PageHeader
        title={t("admin.title")}
        subtitle={t("admin.subtitle")}
        action={
          <div className="flex items-center gap-2">
            <Segmented<`${AdminPeriod}`>
              label={t("admin.period")}
              options={[
                { value: "7", label: t("admin.period.7") },
                { value: "30", label: t("admin.period.30") },
                { value: "90", label: t("admin.period.90") },
              ]}
              value={String(days) as `${AdminPeriod}`}
              onChange={(value) => {
                setDays(Number(value) as AdminPeriod);
              }}
            />
            <Button variant="ghost" onClick={() => void fetch()} loading={status === "loading" && overview !== null}>
              {t("admin.refresh")}
            </Button>
          </div>
        }
      />
      {overview === null && status !== "error" && (
        <div className="flex flex-1 items-center justify-center text-neutral" role="status">
          <Spinner />
        </div>
      )}
      {status === "error" && overview === null && (
        <div className="mx-auto w-full max-w-5xl p-6">
          <ErrorState message={error ?? ""} onRetry={() => void fetch()} />
        </div>
      )}
      {overview !== null && (
        <Content
          data={overview}
          fmt={fmt}
          t={t}
          onChanged={() => void fetch(true)}
        />
      )}
    </div>
  );
}
