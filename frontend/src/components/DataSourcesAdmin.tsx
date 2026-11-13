"use client";

import { useMemo, useRef, useState } from "react";
import { Card, ErrorNote, Skeleton, StatusBadge } from "@/components/ui";
import {
  api,
  TIMEFRAMES,
  type Coverage,
  type DataSource,
  type ImportReport,
  type SyncReport,
} from "@/lib/api";
import { CATEGORY_LABELS, REJECTION_LABELS, dateTime } from "@/lib/format";
import { useApi } from "@/lib/useApi";

const INPUT = "block w-full rounded-lg border border-line bg-canvas px-3 py-2 text-sm";
const BUTTON =
  "rounded-lg border border-line px-3 py-2 text-sm hover:bg-raised disabled:cursor-not-allowed disabled:opacity-50";
const TH = "pb-2 pr-4 font-medium";
const TD = "py-2.5 pr-4";

function describe(error: unknown): string {
  return error instanceof Error ? error.message : "Erro inesperado.";
}

/** `onChange` avisa a página quando algo foi alterado (ex.: para recarregar a auditoria). */
export function DataSourcesAdmin({ onChange }: { onChange?: () => void }) {
  const sources = useApi<DataSource[]>("/api/v1/data-sources", 15_000);
  const coverage = useApi<Coverage[]>("/api/v1/market/coverage");
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<ImportReport | null>(null);
  const form = useRef<HTMLFormElement>(null);

  const bySymbol = useMemo(() => {
    const groups = new Map<
      string,
      { symbol: string; source: string; candles: number; timeframes: number; first: string; last: string }
    >();
    for (const row of coverage.data ?? []) {
      const group = groups.get(row.symbol_id);
      if (!group) {
        groups.set(row.symbol_id, {
          symbol: row.symbol,
          source: row.source,
          candles: row.candles,
          timeframes: 1,
          first: row.first_ts,
          last: row.last_ts,
        });
      } else {
        group.candles += row.candles;
        group.timeframes += 1;
        if (row.first_ts < group.first) group.first = row.first_ts;
        if (row.last_ts > group.last) group.last = row.last_ts;
      }
    }
    return [...groups.values()].sort(
      (a, b) => a.source.localeCompare(b.source) || a.symbol.localeCompare(b.symbol),
    );
  }, [coverage.data]);

  function begin(action: string) {
    setBusy(action);
    setMessage(null);
    setError(null);
  }

  function refresh() {
    sources.reload();
    coverage.reload();
    onChange?.();
  }

  async function sync(source: DataSource) {
    begin(`sync-${source.id}`);
    try {
      const result = await api<SyncReport>(`/api/v1/admin/data-sources/${source.id}/sync`, {
        method: "POST",
      });
      setMessage(
        result.candles > 0
          ? `Sincronização concluída: ${result.candles.toLocaleString("pt-BR")} candle(s) novo(s) em ${result.series} série(s).`
          : "Sincronização concluída: as séries já estavam em dia.",
      );
    } catch (caught) {
      setError(describe(caught));
    }
    setBusy(null);
    refresh();
  }

  async function importFile(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    begin("import");
    setReport(null);
    const data = new FormData(event.currentTarget);
    if (!data.get("category")) data.delete("category");
    try {
      setReport(await api<ImportReport>("/api/v1/admin/market/import", { method: "POST", body: data }));
      form.current?.reset();
    } catch (caught) {
      setError(describe(caught));
    }
    setBusy(null);
    refresh();
  }

  return (
    <Card title="Fontes de dados">
      <div className="space-y-6">
        {error && <ErrorNote message={error} />}
        {message && (
          <p role="status" className="rounded-lg bg-accent/10 px-4 py-3 text-sm text-accent">
            {message}
          </p>
        )}

        {!sources.data ? (
          <Skeleton className="h-16" />
        ) : (
          <ul className="divide-y divide-line">
            {sources.data.map((source) => (
              <li key={source.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                <div className="min-w-0">
                  <div className="text-sm">{source.name}</div>
                  <div className="text-xs text-muted">
                    Tipo {source.kind} · somente leitura · última sincronização:{" "}
                    {dateTime(source.last_sync_at)}
                  </div>
                  {source.kind === "mt5" && source.status === "not_configured" && (
                    <div className="text-xs text-muted">
                      Alimentada pela ponte que roda junto ao terminal (ver README).
                    </div>
                  )}
                  {source.last_error && (
                    <div className="text-xs break-words text-danger">{source.last_error}</div>
                  )}
                </div>
                <div className="flex items-center gap-3">
                  <StatusBadge status={source.status} />
                  {source.kind === "synthetic" && (
                    <button className={BUTTON} disabled={busy !== null} onClick={() => sync(source)}>
                      {busy === `sync-${source.id}` ? "Sincronizando…" : "Sincronizar agora"}
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}

        <div>
          <h3 className="text-sm font-medium">Importar histórico (CSV ou Parquet)</h3>
          <p className="mt-1 text-xs text-muted">
            Colunas esperadas: data/hora, open, high, low, close e, opcionalmente, volume. A
            exportação de barras do MetaTrader 5 é aceita diretamente. Linhas inválidas são
            rejeitadas e listadas; reimportar não duplica candles.
          </p>
          <form
            ref={form}
            onSubmit={importFile}
            className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-6"
          >
            <label className="space-y-1 text-xs text-muted lg:col-span-2">
              Arquivo
              <input className={INPUT} type="file" name="file" accept=".csv,.txt,.parquet,.pq" required />
            </label>
            <label className="space-y-1 text-xs text-muted">
              Símbolo
              <input className={INPUT} name="symbol" placeholder="EURUSD" maxLength={40} required />
            </label>
            <label className="space-y-1 text-xs text-muted">
              Timeframe
              <select className={INPUT} name="timeframe" defaultValue="H1">
                {TIMEFRAMES.map((t) => (
                  <option key={t}>{t}</option>
                ))}
              </select>
            </label>
            <label className="space-y-1 text-xs text-muted">
              Fuso dos horários
              <input className={INPUT} name="source_timezone" defaultValue="UTC" list="timezones" required />
              <datalist id="timezones">
                {["UTC", "Europe/Athens", "Europe/London", "America/New_York", "America/Sao_Paulo"].map(
                  (zone) => (
                    <option key={zone} value={zone} />
                  ),
                )}
              </datalist>
            </label>
            <label className="space-y-1 text-xs text-muted">
              Categoria
              <select className={INPUT} name="category" defaultValue="">
                <option value="">Detectar</option>
                {Object.entries(CATEGORY_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <div className="sm:col-span-2 lg:col-span-6">
              <button
                type="submit"
                disabled={busy !== null}
                className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-accent-ink disabled:opacity-60"
              >
                {busy === "import" ? "Importando…" : "Importar"}
              </button>
            </div>
          </form>

          {report && (
            <div role="status" className="mt-4 rounded-lg border border-line bg-raised/40 p-4 text-sm">
              <p>
                <strong>
                  {report.symbol} {report.timeframe}
                </strong>
                : {report.rows_imported.toLocaleString("pt-BR")} de{" "}
                {report.rows_read.toLocaleString("pt-BR")} linha(s) importada(s)
                {report.first_ts && ` · ${dateTime(report.first_ts)} a ${dateTime(report.last_ts)}`} ·
                nota de qualidade {report.quality.score}/100
              </p>
              {report.rows_rejected > 0 && (
                <ul className="mt-2 text-warn">
                  {Object.entries(report.rejected_by_reason).map(([reason, count]) => (
                    <li key={reason}>
                      {count} rejeitada(s): {REJECTION_LABELS[reason] ?? reason}
                    </li>
                  ))}
                </ul>
              )}
              {report.quality.issues.map((issue) => (
                <p key={issue.code} className="mt-1 text-muted">
                  {issue.message}
                </p>
              ))}
            </div>
          )}
        </div>

        <div>
          <h3 className="text-sm font-medium">Candles armazenados</h3>
          {coverage.error ? (
            <div className="mt-2">
              <ErrorNote message={coverage.error} onRetry={coverage.reload} />
            </div>
          ) : !coverage.data ? (
            <Skeleton className="mt-2 h-24" />
          ) : bySymbol.length === 0 ? (
            <p className="mt-2 text-sm text-muted">
              Nenhum candle armazenado ainda. A fonte sintética carrega o histórico inicial em
              segundo plano logo após a API iniciar.
            </p>
          ) : (
            <div className="mt-2 max-h-80 overflow-auto">
              <table className="w-full min-w-[36rem] text-left text-sm">
                <thead className="sticky top-0 bg-panel text-xs text-muted">
                  <tr>
                    <th className={TH}>Símbolo</th>
                    <th className={TH}>Fonte</th>
                    <th className={`${TH} text-right`}>Candles</th>
                    <th className={`${TH} text-right`}>Timeframes</th>
                    <th className={TH}>De</th>
                    <th className={TH}>Até</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {bySymbol.map((row) => (
                    <tr key={`${row.source}-${row.symbol}`}>
                      <td className={`${TD} font-mono`}>{row.symbol}</td>
                      <td className={`${TD} text-muted`}>{row.source}</td>
                      <td className={`${TD} text-right font-mono tabular-nums`}>
                        {row.candles.toLocaleString("pt-BR")}
                      </td>
                      <td className={`${TD} text-right font-mono tabular-nums`}>{row.timeframes}</td>
                      <td className={`${TD} whitespace-nowrap`}>{dateTime(row.first)}</td>
                      <td className={`${TD} whitespace-nowrap`}>{dateTime(row.last)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}
