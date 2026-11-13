"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type Loaded<T> = { path: string | null; data: T | null; error: string | null };
type State<T> = { data: T | null; error: string | null; loading: boolean };

/**
 * GET com estados de carregamento/erro; encerra a sessão se a API responder 401.
 * Ao mudar de `path`, o dado anterior deixa de ser devolvido (nunca mostra dado de outra
 * consulta); em recargas do mesmo `path`, o dado atual permanece visível até o novo chegar.
 */
export function useApi<T>(
  path: string | null,
  refreshMs?: number,
): State<T> & { reload: () => void } {
  const { logout } = useAuth();
  const [loaded, setLoaded] = useState<Loaded<T>>({ path: null, data: null, error: null });
  const [version, setVersion] = useState(0);

  useEffect(() => {
    if (!path) return;
    let cancelled = false;
    api<T>(path)
      .then((data) => {
        if (!cancelled) setLoaded({ path, data, error: null });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        if (error instanceof ApiError && error.status === 401) logout();
        const message = error instanceof Error ? error.message : "Erro inesperado.";
        setLoaded((previous) => ({
          path,
          data: previous.path === path ? previous.data : null,
          error: message,
        }));
      });
    return () => {
      cancelled = true;
    };
  }, [path, version, logout]);

  const reload = useCallback(() => setVersion((v) => v + 1), []);

  // Atualização periódica opcional (pausada enquanto a aba está oculta).
  useEffect(() => {
    if (!refreshMs || !path) return;
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") setVersion((v) => v + 1);
    }, refreshMs);
    return () => clearInterval(timer);
  }, [refreshMs, path]);

  const current = loaded.path === path;
  return {
    data: current ? loaded.data : null,
    error: current ? loaded.error : null,
    loading: !current,
    reload,
  };
}
