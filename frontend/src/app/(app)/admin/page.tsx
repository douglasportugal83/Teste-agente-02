"use client";

import { useState } from "react";
import { DataSourcesAdmin } from "@/components/DataSourcesAdmin";
import { Card, ErrorNote, PageHeader, Skeleton, StatusBadge } from "@/components/ui";
import { api, type AuditLog, type Role, type User } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { dateTime } from "@/lib/format";
import { useApi } from "@/lib/useApi";

const TH = "pb-2 pr-4 font-medium";
const TD = "py-3 pr-4 align-top";

export default function AdminPage() {
  const { user: me, can } = useAuth();
  const allowed = can("admin:users");
  const users = useApi<User[]>(allowed ? "/api/v1/admin/users" : null);
  const roles = useApi<Role[]>(allowed ? "/api/v1/admin/roles" : null);
  const logs = useApi<AuditLog[]>(allowed ? "/api/v1/admin/audit-logs?limit=30" : null);
  const [actionError, setActionError] = useState<string | null>(null);

  if (!allowed) {
    return (
      <>
        <PageHeader title="Administração" />
        <ErrorNote message="Seu papel não tem permissão para acessar a administração." />
      </>
    );
  }

  async function update(id: string, patch: { role?: string; is_active?: boolean }) {
    setActionError(null);
    try {
      await api(`/api/v1/admin/users/${id}`, { method: "PATCH", body: JSON.stringify(patch) });
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : "Erro inesperado.");
    }
    users.reload();
    logs.reload();
  }

  const loadError = users.error ?? roles.error ?? logs.error;

  return (
    <>
      <PageHeader
        title="Administração"
        subtitle="Usuários, permissões, fontes de dados e trilha de auditoria."
      />
      <div className="space-y-4">
        {(actionError || loadError) && <ErrorNote message={(actionError ?? loadError) as string} />}

        <Card title="Usuários e permissões">
          {!users.data ? (
            <Skeleton className="h-24" />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[40rem] text-left text-sm">
                <thead className="text-xs text-muted">
                  <tr>
                    <th className={TH}>Usuário</th>
                    <th className={TH}>Papel</th>
                    <th className={TH}>Último acesso</th>
                    <th className={TH}>Estado</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {users.data.map((user) => (
                    <tr key={user.id}>
                      <td className={TD}>
                        <div>{user.full_name ?? "—"}</div>
                        <div className="text-xs text-muted">{user.email}</div>
                      </td>
                      <td className={TD}>
                        <select
                          aria-label={`Papel de ${user.email}`}
                          className="rounded-md border border-line bg-canvas px-2 py-1.5"
                          value={user.role.name}
                          onChange={(e) => update(user.id, { role: e.target.value })}
                        >
                          {(roles.data ?? [user.role]).map((role) => (
                            <option key={role.name} value={role.name}>
                              {role.name}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className={TD}>{dateTime(user.last_login_at)}</td>
                      <td className={TD}>
                        <div className="flex flex-wrap items-center gap-2">
                          <StatusBadge
                            status={user.is_active ? "connected" : "error"}
                            label={user.is_active ? "Ativo" : "Inativo"}
                          />
                          {user.id !== me?.id && (
                            <button
                              className="text-xs text-accent underline"
                              onClick={() => update(user.id, { is_active: !user.is_active })}
                            >
                              {user.is_active ? "Desativar" : "Reativar"}
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <DataSourcesAdmin onChange={logs.reload} />

        <Card title="Auditoria (últimos 30 eventos)">
          {!logs.data ? (
            <Skeleton className="h-24" />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[40rem] text-left text-sm">
                <thead className="text-xs text-muted">
                  <tr>
                    <th className={TH}>Quando</th>
                    <th className={TH}>Ação</th>
                    <th className={TH}>Detalhes</th>
                    <th className={TH}>IP</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {logs.data.map((log) => (
                    <tr key={log.id}>
                      <td className={`${TD} whitespace-nowrap`}>{dateTime(log.created_at)}</td>
                      <td className={`${TD} font-mono text-xs`}>{log.action}</td>
                      <td className={`${TD} font-mono text-xs break-all text-muted`}>
                        {Object.keys(log.details).length ? JSON.stringify(log.details) : "—"}
                      </td>
                      <td className={`${TD} font-mono text-xs`}>{log.ip_address ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </>
  );
}
