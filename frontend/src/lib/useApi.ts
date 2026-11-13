"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type State<T> = { data: T | null; error: string | null; loading: boolean };

/** GET com estados de carregamento/erro; encerra a sessão se a API responder 401. */
export function useApi<T>(path: string | null): State<T> & { reload: () => void } {
  const { logout } = useAuth();
  const [state, setState] = useState<State<T>>({ data: null, error: null, loading: true });
  const [version, setVersion] = useState(0);

  useEffect(() => {
    if (!path) return;
    let cancelled = false;
    api<T>(path)
      .then((data) => {
        if (!cancelled) setState({ data, error: null, loading: false });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        if (error instanceof ApiError && error.status === 401) logout();
        const message = error instanceof Error ? error.message : "Erro inesperado.";
        setState((previous) => ({ data: previous.data, error: message, loading: false }));
      });
    return () => {
      cancelled = true;
    };
  }, [path, version, logout]);

  const reload = useCallback(() => setVersion((v) => v + 1), []);
  return { ...state, reload };
}
