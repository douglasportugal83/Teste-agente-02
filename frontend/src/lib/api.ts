/** Cliente tipado da API do TraderAI Pro. */

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(
  /\/$/,
  "",
);

const TOKEN_KEY = "traderai.token";

export function getToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    // armazenamento indisponível (modo privado): a sessão dura só até recarregar
  }
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

function describeError(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    return detail
      .map((d: { msg?: string }) => (d.msg ?? "").replace(/^Value error, /, ""))
      .filter(Boolean)
      .join(" ");
  }
  return `Erro inesperado (HTTP ${status}).`;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  // Para FormData (upload), o navegador define o Content-Type com o boundary correto.
  if (init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "Não foi possível conectar à API. Verifique se o backend está no ar.");
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, describeError(response.status, body));
  return body as T;
}

export type Role = { id: string; name: string; description: string | null; permissions: string[] };

export type User = {
  id: string;
  email: string;
  full_name: string | null;
  is_active: boolean;
  role: Role;
  created_at: string;
  last_login_at: string | null;
};

export type SystemInfo = {
  app_name: string;
  version: string;
  environment: string;
  trading_mode: string;
  real_orders_enabled: boolean;
  server_time: string;
  disclaimer: string;
};

export type Connection = { name: string; kind: string; status: string; detail: string | null };

export type AssetCategory = "metals" | "indices" | "crypto" | "forex" | "other";

export type CategorySummary = { category: AssetCategory; count: number; symbols: string[] };

export type SimulatorSummary = {
  account_id: string;
  name: string;
  status: "running" | "paused" | "blocked" | "stopped";
  status_reason: string | null;
  currency: string;
  initial_balance: number;
  balance: number;
  equity: number;
  pnl: number;
  pnl_pct: number;
  open_positions: number;
  closed_trades: number;
};

export type Alert = {
  id: string;
  severity: "info" | "warning" | "critical";
  category: string;
  title: string;
  message: string;
  is_read: boolean;
  created_at: string;
};

export type Overview = {
  system: SystemInfo;
  connections: Connection[];
  monitored_symbols: number;
  market_by_category: CategorySummary[];
  simulator: SimulatorSummary | null;
  recent_alerts: Alert[];
  unread_alerts: number;
  equity_curve: { ts: string; equity: number }[];
};

export type RiskRule = {
  id: string;
  account_id: string;
  rule_type: string;
  value: number;
  is_enabled: boolean;
  description: string | null;
};

export type DataSource = {
  id: string;
  name: string;
  kind: string;
  status: string;
  read_only: boolean;
  is_enabled: boolean;
  last_sync_at: string | null;
  last_error: string | null;
};

export type AuditLog = {
  id: string;
  user_id: string | null;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  details: Record<string, unknown>;
  ip_address: string | null;
  created_at: string;
};

export type Timeframe = "M1" | "M5" | "M15" | "M30" | "H1" | "H4" | "D1" | "W1";
export const TIMEFRAMES: Timeframe[] = ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1"];

export type MarketSymbol = {
  id: string;
  name: string;
  canonical_name: string;
  description: string | null;
  category: AssetCategory;
  digits: number;
  is_monitored: boolean;
  data_source_id: string;
};

export type Candle = { t: number; o: number; h: number; l: number; c: number; v: number };

export type CandleSeries = {
  symbol_id: string;
  symbol: string;
  canonical_name: string;
  timeframe: Timeframe;
  digits: number;
  source_kind: string;
  is_synthetic: boolean;
  notice: string | null;
  candles: Candle[];
};

export type Quote = {
  symbol_id: string;
  name: string;
  canonical_name: string;
  category: AssetCategory;
  digits: number;
  source_kind: string;
  is_synthetic: boolean;
  price: number | null;
  price_ts: string | null;
  change_pct: number | null;
  is_stale: boolean;
};

export type QualityIssue = {
  code: string;
  severity: "info" | "warning" | "critical";
  message: string;
  count: number;
  examples: string[];
};

export type QualityReport = {
  symbol: string;
  timeframe: Timeframe;
  candles: number;
  first_ts: string | null;
  last_ts: string | null;
  expected_candles: number;
  completeness_pct: number;
  is_stale: boolean;
  last_candle_age_seconds: number | null;
  score: number;
  issues: QualityIssue[];
};

export type Coverage = {
  symbol_id: string;
  symbol: string;
  source: string;
  timeframe: Timeframe;
  candles: number;
  first_ts: string;
  last_ts: string;
};

export type SyncReport = { series: number; candles: number; rejected: number; errors: string[] };

export type ImportReport = {
  symbol_id: string;
  symbol: string;
  timeframe: Timeframe;
  rows_read: number;
  rows_imported: number;
  rows_rejected: number;
  rejected_by_reason: Record<string, number>;
  first_ts: string | null;
  last_ts: string | null;
  quality: QualityReport;
};
