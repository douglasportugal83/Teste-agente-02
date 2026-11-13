"use client";

import { useMemo, useState } from "react";
import { CandleChart } from "@/components/CandleChart";
import { Card, ErrorNote, PageHeader, Skeleton, StatusBadge } from "@/components/ui";
import {
  TIMEFRAMES,
  type CandleSeries,
  type DataSource,
  type MarketSymbol,
  type QualityReport,
  type Timeframe,
} from "@/lib/api";
import {
  CATEGORY_LABELS,
  SOURCE_KIND_LABELS,
  dateTime,
  price,
  signedPercent,
} from "@/lib/format";
import { useApi } from "@/lib/useApi";

const SEVERITY_TONE = { info: "text-info", warning: "text-warn", critical: "text-danger" };
const CATEGORY_ORDER = ["metals", "indices", "crypto", "forex", "other"];

function Stat({ label, value, tone = "" }: { label: string; value: string; tone?: string }) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className={`mt-0.5 font-mono text-sm tabular-nums ${tone}`}>{value}</dd>
    </div>
  );
}

export default function ChartsPage() {
  const symbols = useApi<MarketSymbol[]>("/api/v1/symbols");
  const sources = useApi<DataSource[]>("/api/v1/data-sources");
  const [selected, setSelected] = useState<string | null>(null);
  const [timeframe, setTimeframe] = useState<Timeframe>("H1");

  const options = useMemo(() => {
    const kinds = new Map((sources.data ?? []).map((s) => [s.id, s.kind]));
    return (symbols.data ?? [])
      .filter((s) => s.is_monitored)
      .map((s) => ({ ...s, kind: kinds.get(s.data_source_id) ?? "" }))
      .sort(
        (a, b) =>
          CATEGORY_ORDER.indexOf(a.category) - CATEGORY_ORDER.indexOf(b.category) ||
          a.name.localeCompare(b.name),
      );
  }, [symbols.data, sources.data]);

  const symbolId = selected ?? options[0]?.id ?? null;
  const query = symbolId ? `symbol_id=${symbolId}&timeframe=${timeframe}` : null;
  const series = useApi<CandleSeries>(
    query && `/api/v1/market/candles?${query}&limit=1500`,
    30_000,
  );
  const quality = useApi<QualityReport>(query && `/api/v1/market/quality?${query}`, 60_000);

  const candles = series.data?.candles ?? [];
  const last = candles.at(-1);
  const first = candles[0];
  const change = last && first ? (last.c / first.o - 1) * 100 : null;
  const digits = series.data?.digits ?? 2;

  return (
    <>
      <PageHeader
        title="Gráficos"
        subtitle="Candles e volume das séries armazenadas. Indicadores e marcações de estrutura chegam com as estratégias."
      />

      <div className="space-y-4">
        {(symbols.error || series.error) && (
          <ErrorNote message={(symbols.error ?? series.error) as string} onRetry={series.reload} />
        )}

        <Card>
          <div className="flex flex-wrap items-end gap-4">
            <label className="block space-y-1.5 text-sm">
              <span className="text-xs text-muted">Ativo</span>
              <select
                className="block rounded-lg border border-line bg-canvas px-3 py-2"
                value={symbolId ?? ""}
                onChange={(e) => setSelected(e.target.value)}
                disabled={options.length === 0}
              >
                {CATEGORY_ORDER.filter((c) => options.some((o) => o.category === c)).map((c) => (
                  <optgroup key={c} label={CATEGORY_LABELS[c]}>
                    {options
                      .filter((o) => o.category === c)
                      .map((o) => (
                        <option key={o.id} value={o.id}>
                          {o.name} · {SOURCE_KIND_LABELS[o.kind] ?? o.kind}
                        </option>
                      ))}
                  </optgroup>
                ))}
              </select>
            </label>

            <div className="space-y-1.5">
              <span className="block text-xs text-muted">Timeframe</span>
              <div className="flex flex-wrap gap-1" role="group" aria-label="Timeframe">
                {TIMEFRAMES.map((t) => (
                  <button
                    key={t}
                    onClick={() => setTimeframe(t)}
                    aria-pressed={t === timeframe}
                    className={`rounded-md px-2.5 py-1.5 font-mono text-xs ${
                      t === timeframe
                        ? "bg-accent font-semibold text-accent-ink"
                        : "border border-line text-muted hover:text-ink"
                    }`}
                  >
                    {t}
                  </button>
                ))}
              </div>
            </div>

            {last && (
              <dl className="ml-auto flex flex-wrap gap-x-6 gap-y-2">
                <Stat label="Último fechamento" value={price(last.c, digits)} />
                <Stat
                  label={`Variação (${candles.length} candles)`}
                  value={change === null ? "—" : signedPercent(change)}
                  tone={change === null || change === 0 ? "" : change > 0 ? "text-accent" : "text-danger"}
                />
                <Stat
                  label="Último candle (abertura)"
                  value={dateTime(new Date(last.t * 1000).toISOString())}
                />
              </dl>
            )}
          </div>

          {series.data?.notice && (
            <p className="mt-4 rounded-lg border border-warn/40 bg-warn/10 px-3 py-2 text-sm text-warn">
              {series.data.notice}
            </p>
          )}

          <div className="mt-4">
            {series.loading && !series.data ? (
              <Skeleton className="h-[26rem]" />
            ) : candles.length === 0 ? (
              <div className="flex h-[26rem] items-center justify-center rounded-lg border border-dashed border-line px-4 text-center text-sm text-muted">
                Não há candles armazenados para este ativo e timeframe.
              </div>
            ) : (
              <CandleChart
                seriesKey={`${series.data?.symbol_id}-${series.data?.timeframe}`}
                candles={candles}
                digits={digits}
              />
            )}
          </div>
          <p className="mt-2 text-xs text-muted">
            Eixo de tempo em UTC. Somente candles fechados; atualização automática a cada 30 s.
          </p>
        </Card>

        <Card
          title="Qualidade dos dados"
          action={
            quality.data && (
              <StatusBadge
                status={
                  quality.data.score >= 90 ? "connected" : quality.data.score >= 60 ? "paused" : "error"
                }
                label={`Nota ${quality.data.score}/100`}
              />
            )
          }
        >
          {quality.error ? (
            <ErrorNote message={quality.error} onRetry={quality.reload} />
          ) : !quality.data ? (
            <Skeleton className="h-20" />
          ) : (
            <>
              <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                <Stat label="Candles armazenados" value={quality.data.candles.toLocaleString("pt-BR")} />
                <Stat label="Completude" value={`${quality.data.completeness_pct.toLocaleString("pt-BR")}%`} />
                <Stat label="Primeiro candle" value={dateTime(quality.data.first_ts)} />
                <Stat
                  label="Atualização"
                  value={quality.data.is_stale ? "Atrasada" : "Em dia"}
                  tone={quality.data.is_stale ? "text-danger" : "text-accent"}
                />
              </dl>
              {quality.data.issues.length === 0 ? (
                <p className="mt-4 text-sm text-muted">Nenhum problema detectado nesta série.</p>
              ) : (
                <ul className="mt-4 space-y-2 text-sm">
                  {quality.data.issues.map((issue) => (
                    <li key={issue.code}>
                      <span className={`font-medium ${SEVERITY_TONE[issue.severity]}`}>
                        {issue.severity === "critical" ? "Crítico" : issue.severity === "warning" ? "Atenção" : "Informação"}
                        :
                      </span>{" "}
                      {issue.message}
                      {issue.examples.length > 0 && (
                        <span className="text-muted"> Ex.: {issue.examples.slice(0, 3).map(dateTime).join("; ")}</span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </Card>
      </div>
    </>
  );
}
