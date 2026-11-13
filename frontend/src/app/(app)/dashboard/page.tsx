"use client";

import { useState } from "react";
import { EquityChart } from "@/components/EquityChart";
import { Card, ErrorNote, PageHeader, Skeleton, StatusBadge } from "@/components/ui";
import { api, type Overview } from "@/lib/api";
import { CATEGORY_LABELS, dateTime, money, signedPercent } from "@/lib/format";
import { useApi } from "@/lib/useApi";

function Metric({ label, value, tone = "" }: { label: string; value: string; tone?: string }) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className={`mt-1 font-mono text-lg font-medium tabular-nums ${tone}`}>{value}</dd>
    </div>
  );
}

const SEVERITY_TONE = { info: "bg-info", warning: "bg-warn", critical: "bg-danger" };

export default function DashboardPage() {
  const { data, error, loading, reload } = useApi<Overview>("/api/v1/dashboard/overview");
  const [actionError, setActionError] = useState<string | null>(null);

  async function markRead(id: string) {
    setActionError(null);
    try {
      await api(`/api/v1/alerts/${id}/read`, { method: "POST" });
      reload();
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : "Erro inesperado.");
    }
  }

  if (loading && !data) {
    return (
      <>
        <PageHeader title="Visão Geral" />
        <div className="grid gap-4 lg:grid-cols-3">
          <Skeleton className="h-44 lg:col-span-2" />
          <Skeleton className="h-44" />
          <Skeleton className="h-56 lg:col-span-3" />
        </div>
      </>
    );
  }
  if (!data) {
    return (
      <>
        <PageHeader title="Visão Geral" />
        <ErrorNote message={error ?? "Sem dados."} onRetry={reload} />
      </>
    );
  }

  const sim = data.simulator;
  const pnlTone = !sim || sim.pnl === 0 ? "" : sim.pnl > 0 ? "text-accent" : "text-danger";

  return (
    <>
      <PageHeader
        title="Visão Geral"
        subtitle={`API v${data.system.version} · ambiente ${data.system.environment} · modo ${data.system.trading_mode}`}
      />
      {(error || actionError) && (
        <div className="mb-4">
          <ErrorNote message={(actionError ?? error) as string} onRetry={reload} />
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <Card
          title="Simulador"
          className="lg:col-span-2"
          action={sim && <StatusBadge status={sim.status} />}
        >
          {sim ? (
            <>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-5 sm:grid-cols-4">
                <Metric label="Patrimônio fictício" value={money(sim.equity, sim.currency)} />
                <Metric
                  label="Resultado simulado"
                  value={`${money(sim.pnl, sim.currency)} (${signedPercent(sim.pnl_pct)})`}
                  tone={pnlTone}
                />
                <Metric label="Posições abertas" value={String(sim.open_positions)} />
                <Metric label="Operações encerradas" value={String(sim.closed_trades)} />
              </dl>
              <p className="mt-4 text-sm text-muted">
                {sim.name} · capital inicial {money(sim.initial_balance, sim.currency)}
                {sim.status_reason ? ` · ${sim.status_reason}` : ""}
              </p>
            </>
          ) : (
            <p className="text-sm text-muted">Nenhuma conta de simulação encontrada.</p>
          )}
        </Card>

        <Card title="Conexões">
          <ul className="space-y-3">
            {data.connections.map((connection) => (
              <li key={connection.name} className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-sm">{connection.name}</div>
                  {connection.detail && (
                    <div className="text-xs text-muted">{connection.detail}</div>
                  )}
                </div>
                <StatusBadge status={connection.status} />
              </li>
            ))}
          </ul>
        </Card>

        <Card title="Performance acumulada (fictícia)" className="lg:col-span-2">
          <EquityChart points={data.equity_curve} currency={sim?.currency ?? "USD"} />
        </Card>

        <Card
          title="Alertas recentes"
          action={
            data.unread_alerts > 0 && (
              <span className="rounded-full bg-info/15 px-2.5 py-1 text-xs text-info">
                {data.unread_alerts} não lido{data.unread_alerts > 1 ? "s" : ""}
              </span>
            )
          }
        >
          {data.recent_alerts.length === 0 ? (
            <p className="text-sm text-muted">Nenhum alerta até o momento.</p>
          ) : (
            <ul className="space-y-4">
              {data.recent_alerts.map((alert) => (
                <li key={alert.id} className="flex gap-3">
                  <span
                    className={`mt-1.5 size-2 shrink-0 rounded-full ${SEVERITY_TONE[alert.severity]}`}
                    aria-hidden
                  />
                  <div className={`min-w-0 ${alert.is_read ? "opacity-60" : ""}`}>
                    <div className="text-sm font-medium">{alert.title}</div>
                    <p className="text-sm text-muted">{alert.message}</p>
                    <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-muted">
                      <time>{dateTime(alert.created_at)}</time>
                      {!alert.is_read && (
                        <button onClick={() => markRead(alert.id)} className="text-accent underline">
                          Marcar como lido
                        </button>
                      )}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card
          title="Mercado por categoria"
          className="lg:col-span-3"
          action={
            <span className="text-xs text-muted">{data.monitored_symbols} ativos monitorados</span>
          }
        >
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {data.market_by_category.map((group) => (
              <div key={group.category} className="rounded-lg bg-raised/50 p-4">
                <div className="flex items-baseline justify-between">
                  <h3 className="text-sm font-medium">{CATEGORY_LABELS[group.category]}</h3>
                  <span className="text-xs text-muted">{group.count}</span>
                </div>
                <ul className="mt-3 flex flex-wrap gap-1.5">
                  {group.symbols.map((symbol) => (
                    <li
                      key={symbol}
                      className="rounded-md border border-line px-2 py-1 font-mono text-xs"
                    >
                      {symbol}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
          <p className="mt-4 text-xs text-muted">
            Catálogo inicial. Cotações e descoberta dinâmica de símbolos chegam com as fontes de
            dados na Sprint 2.
          </p>
        </Card>
      </div>
    </>
  );
}
