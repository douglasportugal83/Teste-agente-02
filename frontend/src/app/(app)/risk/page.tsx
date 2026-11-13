"use client";

import { Card, ErrorNote, PageHeader, Skeleton, StatusBadge } from "@/components/ui";
import type { RiskRule } from "@/lib/api";
import { RISK_RULE_LABELS } from "@/lib/format";
import { useApi } from "@/lib/useApi";

export default function RiskPage() {
  const { data, error, loading, reload } = useApi<RiskRule[]>("/api/v1/risk/rules");

  return (
    <>
      <PageHeader
        title="Gestão de Risco"
        subtitle="Limites padrão da sua conta de simulação. Edição, monitor de exposição e bloqueios automáticos chegam na Sprint 5."
      />
      {error && <ErrorNote message={error} onRetry={reload} />}
      {loading && !data && <Skeleton className="h-64" />}
      {data && (
        <Card title="Limites configurados (somente leitura)">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[32rem] text-left text-sm">
              <thead className="text-xs text-muted">
                <tr>
                  <th className="pb-2 font-medium">Regra</th>
                  <th className="pb-2 font-medium">Valor</th>
                  <th className="pb-2 font-medium">Estado</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {data.map((rule) => (
                  <tr key={rule.id}>
                    <td className="py-3 pr-4">
                      <div>{RISK_RULE_LABELS[rule.rule_type] ?? rule.rule_type}</div>
                      <div className="text-xs text-muted">{rule.description}</div>
                    </td>
                    <td className="py-3 pr-4 font-mono tabular-nums">
                      {rule.value.toLocaleString("pt-BR")}
                    </td>
                    <td className="py-3">
                      <StatusBadge
                        status={rule.is_enabled ? "connected" : "not_configured"}
                        label={rule.is_enabled ? "Ativa" : "Inativa"}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-4 text-xs text-muted">
            As regras estão armazenadas, mas ainda não são aplicadas: o motor do simulador que as
            consome é entregue na Sprint 5.
          </p>
        </Card>
      )}
    </>
  );
}
